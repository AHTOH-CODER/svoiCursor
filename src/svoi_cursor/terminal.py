from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPlainTextEdit, QVBoxLayout

try:
    from winpty import PtyProcess
except ImportError:  # pragma: no cover - runtime fallback message in UI.
    PtyProcess = None  # type: ignore[assignment,misc]

CSI_PATTERN = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")
PROMPT_PATTERN = re.compile(r"PS [^>\n]*>|>>")


class VtStreamParser:
    """Fixed-size screen buffer + scrollback for PowerShell / PSReadLine."""

    def __init__(self, rows: int = 24, cols: int = 80) -> None:
        self.rows = max(1, rows)
        self.cols = max(1, cols)
        self._scrollback: list[list[str]] = []
        self._screen: list[list[str]] = [[] for _ in range(self.rows)]
        self._cursor_row = 0
        self._cursor_col = 0
        self._pending = ""

    def set_size(self, rows: int, cols: int) -> None:
        rows = max(1, rows)
        cols = max(1, cols)
        self.cols = cols
        if rows == self.rows:
            return
        if rows > self.rows:
            self._screen.extend([[] for _ in range(rows - self.rows)])
        else:
            self._scrollback.extend(self._screen[: self.rows - rows])
            self._screen = self._screen[self.rows - rows :]
            self._cursor_row = min(self._cursor_row, rows - 1)
        self.rows = rows

    def reset(self) -> None:
        self._scrollback = []
        self._screen = [[] for _ in range(self.rows)]
        self._cursor_row = 0
        self._cursor_col = 0
        self._pending = ""

    def feed(self, text: str) -> None:
        data = self._pending + text
        self._pending = ""
        index = 0
        while index < len(data):
            char = data[index]
            if char == "\x1b":
                next_index, held = self._consume_escape(data, index)
                if held:
                    self._pending = data[index:]
                    return
                index = next_index
                continue
            index = self._consume_char(data, index)

    def render(self) -> str:
        lines = ["".join(line).rstrip() for line in self._scrollback]
        screen_lines: list[str] = []
        last_screen = len(self._screen) - 1
        for index, line in enumerate(self._screen):
            text = "".join(line)
            if index < last_screen:
                text = text.rstrip()
            screen_lines.append(text)
        all_lines = lines + screen_lines
        while all_lines and all_lines[-1] == "":
            all_lines.pop()
        return "\n".join(all_lines)

    def _consume_escape(self, data: str, index: int) -> tuple[int, bool]:
        if index + 1 >= len(data):
            return index, True

        second = data[index + 1]
        if second == "[":
            match = CSI_PATTERN.match(data, index)
            if match is None:
                return index + 1, True
            params, command = match.groups()
            self._apply_csi(params, command)
            return match.end(), False

        if second == "]":
            end = self._find_osc_end(data, index + 2)
            if end is None:
                return index, True
            return end, False

        return index + 2, False

    def _find_osc_end(self, data: str, start: int) -> int | None:
        for pos in range(start, len(data)):
            if data[pos] == "\x07":
                return pos + 1
            if data[pos] == "\x1b" and pos + 1 < len(data) and data[pos + 1] == "\\":
                return pos + 2
        return None

    def _apply_csi(self, params: str, command: str) -> None:
        if command == "m":
            if params and "93" in params.split(";"):
                line = self._screen[self._cursor_row]
                del line[self._cursor_col :]
            return

        numbers: list[int] = []
        if params and not params.startswith("?"):
            for part in params.split(";"):
                if part.isdigit():
                    numbers.append(int(part))

        if command in {"H", "f"}:
            row = numbers[0] if len(numbers) >= 1 else 1
            col = numbers[1] if len(numbers) >= 2 else 1
            target_row = max(0, min(self.rows - 1, row - 1))
            target_col = max(0, col - 1)
            prompt_row = self._find_prompt_row()
            if prompt_row is not None and target_col >= 20:
                self._cursor_row = prompt_row
                self._cursor_col = target_col
            else:
                self._cursor_row = target_row
                self._cursor_col = target_col
            return

        if command in {"A", "B", "C", "D"}:
            step = numbers[0] if numbers else 1
            if command == "A":
                self._cursor_row = max(0, self._cursor_row - step)
            elif command == "B":
                self._cursor_row = min(self.rows - 1, self._cursor_row + step)
            elif command == "C":
                self._cursor_col += step
            elif command == "D":
                self._cursor_col = max(0, self._cursor_col - step)
            return

        if command == "K":
            mode = numbers[0] if numbers else 0
            line = self._screen[self._cursor_row]
            if mode in {0, 2}:
                del line[self._cursor_col :]
            if mode in {1, 2}:
                del line[: self._cursor_col]
            return

        if command == "J":
            mode = numbers[0] if numbers else 0
            if mode == 2:
                self._screen = [[] for _ in range(self.rows)]
                self._cursor_row = 0
                self._cursor_col = 0
            elif mode == 0:
                del self._screen[self._cursor_row][self._cursor_col :]
                for row in range(self._cursor_row + 1, self.rows):
                    self._screen[row] = []
            elif mode == 1:
                for row in range(0, self._cursor_row):
                    self._screen[row] = []
                del self._screen[self._cursor_row][: self._cursor_col]
            return

    def _consume_char(self, data: str, index: int) -> int:
        char = data[index]
        if char == "\r":
            if index + 1 < len(data) and data[index + 1] == "\n":
                if self._should_skip_crlf(data, index):
                    return index + 2
            self._cursor_col = 0
            return index + 1
        if char == "\n":
            self._linefeed()
            return index + 1
        if char in {"\x08", "\x7f"}:
            if self._cursor_col > 0:
                self._cursor_col -= 1
                line = self._screen[self._cursor_row]
                if self._cursor_col < len(line):
                    del line[self._cursor_col]
            return index + 1
        if char == "\x07":
            return index + 1
        if char.isprintable() or char == "\t":
            self._write_char(char)
        return index + 1

    def _write_char(self, char: str) -> None:
        line = self._screen[self._cursor_row]
        if char == " " and self._cursor_col < len(line):
            text = "".join(line)
            gt = text.find("> ")
            if gt >= 0 and self._cursor_col > gt + 1:
                del line[self._cursor_col]
                return
        if self._cursor_col == len(line):
            line.append(char)
        elif self._cursor_col < len(line):
            line[self._cursor_col] = char
        else:
            line.extend(" " * (self._cursor_col - len(line)))
            line.append(char)
        self._cursor_col += 1

    def _find_prompt_row(self) -> int | None:
        for row in range(self.rows - 1, -1, -1):
            text = "".join(self._screen[row])
            if PROMPT_PATTERN.search(text):
                return row
        return None

    def _linefeed(self) -> None:
        if self._cursor_row >= self.rows - 1:
            self._scroll_up(1)
            self._cursor_row = self.rows - 1
        else:
            self._cursor_row += 1
        self._cursor_col = 0

    def _scroll_up(self, count: int = 1) -> None:
        for _ in range(count):
            self._scrollback.append(self._screen[0])
            self._screen = self._screen[1:] + [[]]

    def _should_skip_crlf(self, data: str, index: int) -> bool:
        tail = data[index + 2 : index + 80]
        match = re.search(r"\x1b\[(\d+);(\d+)H", tail)
        if match is None:
            return False
        target_row = int(match.group(1)) - 1
        return target_row <= self._cursor_row


class PtyReaderWorker(QObject):
    output = Signal(str)
    finished = Signal()

    def __init__(self, pty) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.pty = pty
        self._running = True

    @Slot()
    def run(self) -> None:
        while self._running and self.pty is not None and self.pty.isalive():
            try:
                data = self.pty.read(4096)
            except EOFError:
                break
            except Exception as error:  # noqa: BLE001 - surface PTY read errors once.
                self.output.emit(f"\n[PowerShell read error: {error}]")
                break

            if not data:
                time.sleep(0.01)
                continue
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
            self.output.emit(text)

        self.finished.emit()

    def stop(self) -> None:
        self._running = False


class TerminalView(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TerminalOutput")
        self.setFont(QFont("Cascadia Code", 10))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setReadOnly(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pty = None
        self._vt = VtStreamParser()

    def set_terminal_size(self, rows: int, cols: int) -> None:
        self._vt.set_size(rows, cols)

    def bind_pty(self, pty) -> None:  # type: ignore[no-untyped-def]
        self._pty = pty

    def pty_alive(self) -> bool:
        return self._pty is not None and self._pty.isalive()

    def append_shell_output(self, text: str) -> None:
        self._vt.feed(text)
        self._render_from_vt()

    def append_external(self, text: str) -> None:
        if not text.endswith("\n"):
            text = f"{text}\n"
        self._append_text(text)

    def clear_screen(self) -> None:
        self._vt.reset()
        self.clear()

    def apply_edit_command(self, command: str) -> None:
        if command == "copy":
            if self.textCursor().hasSelection():
                self.copy()
            return

        if command == "cut":
            if self.textCursor().hasSelection():
                self.copy()
                cursor = self.textCursor()
                cursor.clearSelection()
                self.setTextCursor(cursor)
            return

        if command == "paste":
            if self.pty_alive():
                clipboard = QApplication.clipboard().text()
                if clipboard:
                    self._write_pty(clipboard)
            return

        if command == "selectAll":
            self.selectAll()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        modifiers = event.modifiers()
        ctrl = modifiers & Qt.KeyboardModifier.ControlModifier

        if ctrl and key == Qt.Key.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            elif self.pty_alive():
                self._write_pty("\x03")
            event.accept()
            return

        if ctrl and key == Qt.Key.Key_X:
            if self.textCursor().hasSelection():
                self.copy()
                cursor = self.textCursor()
                cursor.clearSelection()
                self.setTextCursor(cursor)
            event.accept()
            return

        if ctrl and key == Qt.Key.Key_V:
            if self.pty_alive():
                clipboard = QApplication.clipboard().text()
                if clipboard:
                    self._write_pty(clipboard)
            event.accept()
            return

        if ctrl and key == Qt.Key.Key_A:
            self.selectAll()
            event.accept()
            return

        if not self.pty_alive():
            panel = self.parent()
            if isinstance(panel, TerminalPanel):
                panel.ensure_ready()
            if not self.pty_alive():
                if ctrl and key == Qt.Key.Key_C and self.textCursor().hasSelection():
                    self.copy()
                elif key in {Qt.Key.Key_PageUp, Qt.Key.Key_PageDown}:
                    super().keyPressEvent(event)
                event.accept()
                return

        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._write_pty("\r")
            event.accept()
            return

        if key == Qt.Key.Key_Backspace:
            self._write_pty("\x7f")
            event.accept()
            return

        if key == Qt.Key.Key_Space:
            self._write_pty(" ")
            event.accept()
            return

        if key == Qt.Key.Key_Delete:
            self._write_pty("\x1b[3~")
            event.accept()
            return

        if key == Qt.Key.Key_Tab:
            self._write_pty("\t")
            event.accept()
            return

        if key == Qt.Key.Key_Up:
            self._write_pty("\x1b[A")
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self._write_pty("\x1b[B")
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self._write_pty("\x1b[D")
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self._write_pty("\x1b[C")
            event.accept()
            return
        if key == Qt.Key.Key_Home:
            self._write_pty("\x1b[H")
            event.accept()
            return
        if key == Qt.Key.Key_End:
            self._write_pty("\x1b[F")
            event.accept()
            return

        if key in {Qt.Key.Key_PageUp, Qt.Key.Key_PageDown}:
            super().keyPressEvent(event)
            event.accept()
            return

        if event.text() and not ctrl:
            self._write_pty(event.text())
            event.accept()
            return

        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().mousePressEvent(event)
        self.setFocus()

    def focusInEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().focusInEvent(event)
        panel = self.parent()
        if isinstance(panel, TerminalPanel):
            panel.ensure_ready()

    def _write_pty(self, text: str) -> None:
        try:
            self._pty.write(text)
        except Exception as error:  # noqa: BLE001 - show write errors to user.
            self.append_external(f"[PowerShell write error: {error}]")

    def _render_from_vt(self) -> None:
        rendered = self._vt.render()
        if rendered == self.toPlainText():
            return
        was_at_end = self.verticalScrollBar().value() >= self.verticalScrollBar().maximum() - 2
        self.setPlainText(rendered)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        if was_at_end:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def _append_text(self, text: str) -> None:
        self._vt.feed(text)
        self._render_from_vt()


class TerminalPanel(QFrame):
    def __init__(self, cwd: Path) -> None:
        super().__init__()
        self.setObjectName("TerminalPanel")
        self.cwd = cwd.resolve()
        self._pty = None
        self._reader_thread: QThread | None = None
        self._reader_worker: PtyReaderWorker | None = None
        self._external_busy = False
        self._shell_started = False
        self._last_rows = 0
        self._last_cols = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("POWERSHELL")
        header.setObjectName("PanelTitle")
        layout.addWidget(header)

        self.view = TerminalView()
        layout.addWidget(self.view, stretch=1)

    def is_usable(self) -> bool:
        return self.isVisible() and self.view.viewport().height() >= 40

    def ensure_ready(self) -> None:
        if not self.is_usable():
            return

        rows, cols = self._terminal_size()
        size_changed = (
            self._shell_started
            and (abs(rows - self._last_rows) > 1 or abs(cols - self._last_cols) > 2)
        )

        if not self._shell_started or size_changed:
            self._start_shell()
            return

        if self._pty is None or not self._pty.isalive():
            self._start_shell()
            return

        rows, cols = self._terminal_size()
        self.view.set_terminal_size(rows, cols)
        try:
            self._pty.setwinsize(rows, cols)
            self._last_rows = rows
            self._last_cols = cols
        except Exception:
            pass

        if self._reader_thread is None or not self._reader_thread.isRunning():
            self._start_reader()

    def _start_shell(self) -> None:
        self._stop_reader()
        self.view.clear_screen()

        if PtyProcess is None:
            self.view.append_external(
                "PowerShell PTY недоступен.\n"
                "Установите зависимость: python -m pip install pywinpty"
            )
            return

        try:
            rows, cols = self._terminal_size()
            self.view.set_terminal_size(rows, cols)
            self._pty = PtyProcess.spawn(
                ["powershell.exe", "-NoLogo", "-NoProfile"],
                dimensions=(rows, cols),
                cwd=str(self.cwd),
            )
            self.view.bind_pty(self._pty)
            self._last_rows = rows
            self._last_cols = cols
            self._shell_started = True
            self._start_reader()
            self.view.setFocus()
        except Exception as error:  # noqa: BLE001 - show startup errors in panel.
            self._pty = None
            self._shell_started = False
            self.view.bind_pty(None)
            self.view.append_external(f"Failed to start PowerShell: {error}")

    def _terminal_size(self) -> tuple[int, int]:
        metrics = self.view.fontMetrics()
        cols = max(80, self.view.viewport().width() // max(1, metrics.horizontalAdvance("M")))
        rows = max(8, self.view.viewport().height() // max(1, metrics.height()))
        return rows, cols

    def _start_reader(self) -> None:
        if self._pty is None:
            return

        self._reader_thread = QThread(self)
        self._reader_worker = PtyReaderWorker(self._pty)
        self._reader_worker.moveToThread(self._reader_thread)
        self._reader_thread.started.connect(self._reader_worker.run)
        self._reader_worker.output.connect(self.view.append_shell_output)
        self._reader_worker.finished.connect(self._on_reader_finished)
        self._reader_worker.finished.connect(self._reader_thread.quit)
        self._reader_thread.finished.connect(self._reader_worker.deleteLater)
        self._reader_thread.finished.connect(self._reader_thread.deleteLater)
        self._reader_thread.finished.connect(self._clear_reader)
        self._reader_thread.start()

    def _on_reader_finished(self) -> None:
        if self._pty is not None and self._pty.isalive() and self.is_usable():
            QTimer.singleShot(100, self._restart_reader_if_needed)

    def _restart_reader_if_needed(self) -> None:
        if self._pty is None or not self._pty.isalive():
            return
        if self._reader_thread is not None and self._reader_thread.isRunning():
            return
        self._reader_worker = None
        self._reader_thread = None
        self._start_reader()

    def _stop_reader(self) -> None:
        if self._reader_worker is not None:
            self._reader_worker.stop()
        if self._pty is not None:
            try:
                if self._pty.isalive():
                    self._pty.close(force=True)
            except Exception:
                pass
            self._pty = None
            self.view.bind_pty(None)
        self._shell_started = False
        if self._reader_thread is not None:
            self._reader_thread.quit()
            self._reader_thread.wait(3000)
        self._clear_reader()

    def _clear_reader(self) -> None:
        self._reader_thread = None
        self._reader_worker = None

    def _close_shell(self) -> None:
        self._stop_reader()

    def set_cwd(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        if not self._shell_started:
            return
        if self._pty is None or not self._pty.isalive():
            self.ensure_ready()
            return

        path = str(self.cwd).replace("'", "''")
        try:
            self._pty.write(f"Set-Location -LiteralPath '{path}'\r")
        except Exception as error:  # noqa: BLE001 - restart shell if cd fails.
            self.view.append_external(f"[cd error: {error}]")
            self.restart()

    def write(self, text: str) -> None:
        self.ensure_ready()
        self.view.append_external(text)

    def clear_output(self) -> None:
        self.view.clear_screen()

    def clear(self) -> None:
        self.clear_output()
        if self._pty is not None and self._pty.isalive():
            try:
                self._pty.write("Clear-Host\r\n")
            except Exception:
                pass

    def run_command(self, command: str) -> bool:
        self.ensure_ready()
        if self._pty is None or not self._pty.isalive():
            self.write("[Terminal is not available]\n")
            return False
        try:
            self._pty.write(f"{command}\r")
            return True
        except Exception as error:  # noqa: BLE001 - show run errors in panel.
            self.write(f"[Run error: {error}]\n")
            return False

    def restart(self) -> None:
        self._shell_started = False
        self._start_shell()

    def set_external_busy(self, busy: bool) -> None:
        self._external_busy = busy

    @property
    def is_busy(self) -> bool:
        return self._external_busy

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        if not self.is_usable():
            return
        rows, cols = self._terminal_size()
        self.view.set_terminal_size(rows, cols)
        if self._pty is None or not self._pty.isalive():
            self.ensure_ready()
            return
        try:
            self._pty.setwinsize(rows, cols)
            self._last_rows = rows
            self._last_cols = cols
        except Exception:
            pass

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        self.ensure_ready()
        if self.view.pty_alive():
            self.view.setFocus()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._close_shell()
        super().closeEvent(event)
