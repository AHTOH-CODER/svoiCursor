from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from svoi_cursor.explorer import ExplorerPanel
from svoi_cursor.model_provider import ChatMessage, ModelClient
from svoi_cursor.runner import CodeRunner, RunResult
from svoi_cursor.styles import APP_STYLE
from svoi_cursor.syntax import CodeHighlighter, language_for_path
from svoi_cursor.terminal import TerminalPanel, TerminalView
from svoi_cursor.window_chrome import (
    TitleBar,
    apply_frameless_window,
    handle_frameless_native_event,
)


def _quote_powershell_path(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


class AgentWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, client: ModelClient, messages: list[ChatMessage]) -> None:
        super().__init__()
        self.client = client
        self.messages = messages

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.client.complete(self.messages))
        except Exception as error:  # noqa: BLE001 - surface model errors in the chat panel.
            self.failed.emit(str(error))


class AgentPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("AgentPanel")
        self.client = ModelClient()
        self.messages: list[ChatMessage] = [
            ChatMessage(
                role="system",
                content=(
                    "You are an AI coding agent inside a Python IDE inspired by Cursor. "
                    "Help the user edit, explain, and reason about code."
                ),
            )
        ]
        self._thread: QThread | None = None
        self._worker: AgentWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("AI AGENT")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self.history = QTextEdit()
        self.history.setObjectName("ChatHistory")
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("Диалог с вашей моделью")
        layout.addWidget(self.history, stretch=1)

        input_shell = QWidget()
        input_layout = QVBoxLayout(input_shell)
        input_layout.setContentsMargins(12, 8, 12, 12)
        input_layout.setSpacing(8)

        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("PromptInput")
        self.prompt.setPlaceholderText("Спросите агента или попросите изменить код...")
        self.prompt.setFixedHeight(92)
        input_layout.addWidget(self.prompt)

        self.send_button = QPushButton("Отправить")
        self.send_button.setObjectName("AgentSendButton")
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_button)

        layout.addWidget(input_shell)
        self._append_assistant(
            "Готов к работе. Подключите SVOI_MODEL_ENDPOINT, чтобы использовать вашу модель."
        )

    def send_message(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if not prompt or self._thread is not None:
            return

        self.prompt.clear()
        self.messages.append(ChatMessage(role="user", content=prompt))
        self._append_user(prompt)
        self.send_button.setEnabled(False)
        self.send_button.setText("Думаю...")

        self._thread = QThread(self)
        self._worker = AgentWorker(self.client, self.messages.copy())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._handle_answer)
        self._worker.failed.connect(self._handle_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._reset_worker)
        self._thread.start()

    def _append_user(self, text: str) -> None:
        self.history.append(f"<p><b style='color:#9cdcfe'>Вы</b><br>{self._escape(text)}</p>")

    def _append_assistant(self, text: str) -> None:
        self.history.append(
            f"<p><b style='color:#4ec9b0'>Agent</b><br>{self._escape(text).replace(chr(10), '<br>')}</p>"
        )

    @Slot(str)
    def _handle_answer(self, answer: str) -> None:
        self.messages.append(ChatMessage(role="assistant", content=answer))
        self._append_assistant(answer)

    @Slot(str)
    def _handle_error(self, error: str) -> None:
        self._append_assistant(f"Ошибка модели: {error}")

    @Slot()
    def _reset_worker(self) -> None:
        self._thread = None
        self._worker = None
        self.send_button.setEnabled(True)
        self.send_button.setText("Отправить")

    def _escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API name.
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.path = path
        self.highlighter: CodeHighlighter | None = None
        self.line_number_area = LineNumberArea(self)
        self.setFont(QFont("Cascadia Code", 11))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width()
        self.highlight_current_line()
        if path is not None:
            self.highlighter = CodeHighlighter(self.document(), language_for_path(path))

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, *_args: object) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name.
        super().resizeEvent(event)
        contents_rect = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(
                contents_rect.left(),
                contents_rect.top(),
                self.line_number_area_width(),
                contents_rect.height(),
            )
        )

    def line_number_area_paint_event(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#1e1e1e"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#858585"))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    @Slot()
    def highlight_current_line(self) -> None:
        if self.isReadOnly():
            return

        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#2a2d2e"))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


class EditorTabs(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.removeTab)
        self._open_paths: dict[Path, CodeEditor] = {}
        self._untitled_counter = 1
        self._create_welcome_tab()

    def new_file(self) -> CodeEditor:
        self._remove_welcome_tab_if_needed()
        editor = CodeEditor()
        name = f"Untitled-{self._untitled_counter}"
        self._untitled_counter += 1
        editor.setProperty("untitledName", name)
        editor.document().modificationChanged.connect(
            lambda changed, current_editor=editor: self._mark_modified(current_editor, changed)
        )
        index = self.addTab(editor, name)
        self.setCurrentIndex(index)
        return editor

    def open_file(self, path: Path) -> None:
        self._remove_welcome_tab_if_needed()
        existing = self._open_paths.get(path)
        if existing is not None:
            self.setCurrentWidget(existing)
            return

        editor = CodeEditor(path)
        editor.setPlainText(self._read_text(path))
        editor.setProperty("filePath", str(path))
        editor.document().modificationChanged.connect(
            lambda changed, current_editor=editor: self._mark_modified(current_editor, changed)
        )

        index = self.addTab(editor, path.name)
        self.setTabToolTip(index, str(path))
        self.setCurrentIndex(index)
        self._open_paths[path] = editor

    def removeTab(self, index: int) -> None:  # noqa: N802 - Qt API name.
        widget = self.widget(index)
        if widget is not None:
            file_path = widget.property("filePath")
            if file_path:
                self._open_paths.pop(Path(file_path), None)
        super().removeTab(index)
        if self.count() == 0:
            self._create_welcome_tab()

    def current_editor(self) -> CodeEditor | None:
        widget = self.currentWidget()
        if isinstance(widget, CodeEditor) and not widget.property("welcome"):
            return widget
        return None

    def current_file(self) -> Path | None:
        editor = self.current_editor()
        return editor.path if editor else None

    def close_file(self, path: Path) -> None:
        editor = self._open_paths.get(path)
        if editor is None:
            return
        index = self.indexOf(editor)
        if index >= 0:
            self.removeTab(index)

    def rename_file(self, old_path: Path, new_path: Path) -> None:
        editor = self._open_paths.pop(old_path, None)
        if editor is None:
            return
        self._assign_path(editor, new_path)

    def save_current_file(self, target_path: Path | None = None) -> Path | None:
        editor = self.current_editor()
        if editor is None:
            return None

        if target_path is not None:
            self._assign_path(editor, target_path)

        if editor.path is None:
            return None

        editor.path.write_text(editor.toPlainText(), encoding="utf-8")
        editor.document().setModified(False)
        self._mark_modified(editor, False)
        return editor.path

    def _assign_path(self, editor: CodeEditor, path: Path) -> None:
        if editor.path is not None:
            self._open_paths.pop(editor.path, None)
        editor.path = path
        editor.setProperty("filePath", str(path))
        editor.highlighter = CodeHighlighter(editor.document(), language_for_path(path))
        self._open_paths[path] = editor

        index = self.indexOf(editor)
        if index >= 0:
            self.setTabText(index, path.name)
            self.setTabToolTip(index, str(path))

    def _mark_modified(self, editor: CodeEditor, changed: bool) -> None:
        index = self.indexOf(editor)
        if index < 0:
            return
        name = editor.path.name if editor.path is not None else editor.property("untitledName")
        prefix = "● " if changed else ""
        self.setTabText(index, f"{prefix}{name}")

    def _remove_welcome_tab_if_needed(self) -> None:
        for index in range(self.count()):
            widget = self.widget(index)
            if widget is not None and widget.property("welcome"):
                self.removeTab(index)
                break

    def _create_welcome_tab(self) -> None:
        editor = CodeEditor()
        editor.setReadOnly(True)
        editor.setProperty("welcome", True)
        editor.setPlainText(
            "svoiCursor\n\n"
            "Выберите файл в Explorer слева\n"
            "или откройте его через File → Open File."
        )
        self.addTab(editor, "Выберите файл")

    def _read_text(self, path: Path) -> str:
        for encoding in ("utf-8", "cp1251"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(errors="replace")


class MainWindow(QMainWindow):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.setWindowTitle("svoiCursor")
        self.setWindowIcon(QIcon())
        self.resize(1440, 900)
        self.setMinimumSize(640, 420)
        apply_frameless_window(self)
        self._run_thread: QThread | None = None
        self._runner: CodeRunner | None = None

        self.editor_tabs = EditorTabs()
        self.terminal = TerminalPanel(root)
        self.explorer = ExplorerPanel(root)
        self.explorer.file_selected.connect(self.editor_tabs.open_file)
        self.explorer.file_deleted.connect(self.editor_tabs.close_file)
        self.explorer.file_renamed.connect(self.editor_tabs.rename_file)
        self.explorer.folder_changed.connect(self._on_folder_changed)
        self.agent_panel = AgentPanel()

        editor_terminal_splitter = QSplitter(Qt.Vertical)
        editor_terminal_splitter.addWidget(self.editor_tabs)
        editor_terminal_splitter.addWidget(self.terminal)
        editor_terminal_splitter.setSizes([650, 220])
        editor_terminal_splitter.setCollapsible(0, False)
        self.editor_terminal_splitter = editor_terminal_splitter

        horizontal_splitter = QSplitter(Qt.Horizontal)
        horizontal_splitter.addWidget(self.explorer)
        horizontal_splitter.addWidget(editor_terminal_splitter)
        horizontal_splitter.addWidget(self.agent_panel)
        horizontal_splitter.setSizes([260, 820, 360])
        horizontal_splitter.setCollapsible(1, False)
        self.horizontal_splitter = horizontal_splitter

        self.explorer.setMinimumWidth(48)
        self.agent_panel.setMinimumWidth(180)
        self._panel_defaults = {
            "Explorer": 260,
            "Terminal": 220,
            "AI Agent": 360,
        }

        self.title_bar = TitleBar(self)
        self._create_actions(self.title_bar.layout())
        self.title_bar.add_window_controls()

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.title_bar)

        top_divider = QFrame()
        top_divider.setObjectName("TopBarDivider")
        top_divider.setFixedHeight(1)
        shell_layout.addWidget(top_divider)

        shell_layout.addWidget(horizontal_splitter)
        self.setCentralWidget(shell)

        status = QStatusBar()
        status.showMessage(f"Workspace: {root}")
        self.setStatusBar(status)
        self._update_window_title()

        QTimer.singleShot(0, lambda: self._toggle_bottom_panel("Terminal", False))

    def _create_actions(self, title_layout) -> None:  # type: ignore[no-untyped-def]
        new_action = QAction("New File", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_file)
        self.addAction(new_action)

        open_action = QAction("Open File...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_file)
        self.addAction(open_action)

        open_folder_action = QAction("Open Folder...", self)
        open_folder_action.setShortcut("Ctrl+K Ctrl+O")
        open_folder_action.triggered.connect(self._open_folder)
        self.addAction(open_folder_action)

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_current_file)
        self.addAction(save_action)

        save_as_action = QAction("Save As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self._save_current_file_as)
        self.addAction(save_as_action)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

        undo_action = QAction("Undo", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(lambda: self._editor_command("undo"))
        self.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(lambda: self._editor_command("redo"))
        self.addAction(redo_action)

        cut_action = QAction("Cut", self)
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(lambda: self._editor_command("cut"))
        self.addAction(cut_action)

        copy_action = QAction("Copy", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(lambda: self._editor_command("copy"))
        self.addAction(copy_action)

        paste_action = QAction("Paste", self)
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(lambda: self._editor_command("paste"))
        self.addAction(paste_action)

        select_all_action = QAction("Select All", self)
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(lambda: self._editor_command("selectAll"))
        self.addAction(select_all_action)

        duplicate_line_action = QAction("Duplicate Line", self)
        duplicate_line_action.setShortcut("Shift+Alt+Down")
        duplicate_line_action.triggered.connect(self._duplicate_current_line)
        self.addAction(duplicate_line_action)

        toggle_explorer_action = QAction("Explorer", self)
        toggle_explorer_action.setCheckable(True)
        toggle_explorer_action.setChecked(True)
        toggle_explorer_action.triggered.connect(
            lambda visible: self._toggle_side_panel(0, "Explorer", visible)
        )

        toggle_terminal_action = QAction("Terminal", self)
        toggle_terminal_action.setCheckable(True)
        toggle_terminal_action.setChecked(False)
        toggle_terminal_action.triggered.connect(
            lambda visible: self._toggle_bottom_panel("Terminal", visible)
        )

        toggle_agent_action = QAction("AI Agent", self)
        toggle_agent_action.setCheckable(True)
        toggle_agent_action.setChecked(True)
        toggle_agent_action.triggered.connect(
            lambda visible: self._toggle_side_panel(2, "AI Agent", visible)
        )

        self._view_actions = {
            "Explorer": toggle_explorer_action,
            "Terminal": toggle_terminal_action,
            "AI Agent": toggle_agent_action,
        }

        restart_terminal_action = QAction("Restart PowerShell", self)
        restart_terminal_action.triggered.connect(self.terminal.restart)

        run_action = QAction("Run", self)
        run_action.setShortcut("F5")
        run_action.triggered.connect(self._run_current_file)
        self.addAction(run_action)

        clear_terminal_action = QAction("Clear Terminal", self)
        clear_terminal_action.setShortcut("Ctrl+L")
        clear_terminal_action.triggered.connect(self.terminal.clear)
        self.addAction(clear_terminal_action)

        about_action = QAction("About svoiCursor", self)
        about_action.triggered.connect(self._show_about)

        self._add_menu_button(title_layout, "File", [
            new_action,
            open_action,
            open_folder_action,
            save_action,
            save_as_action,
            None,
            quit_action,
        ])
        self._add_menu_button(title_layout, "Edit", [
            undo_action,
            redo_action,
            None,
            cut_action,
            copy_action,
            paste_action,
        ])
        self._add_menu_button(title_layout, "Selection", [
            select_all_action,
            duplicate_line_action,
        ])
        self._add_menu_button(title_layout, "View", [
            toggle_explorer_action,
            toggle_terminal_action,
            toggle_agent_action,
        ])
        self._add_menu_button(title_layout, "Terminal", [
            clear_terminal_action,
            restart_terminal_action,
        ])
        self._add_menu_button(title_layout, "Help", [
            about_action,
        ])

        run_button = QPushButton("Run")
        run_button.setObjectName("TitleRunButton")
        run_button.clicked.connect(self._run_current_file)
        title_layout.addWidget(run_button)

    def _add_menu_button(
        self,
        title_layout,
        title: str,
        actions: list[QAction | None],
    ) -> None:  # type: ignore[no-untyped-def]
        button = QToolButton()
        button.setText(title)
        button.setPopupMode(QToolButton.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setArrowType(Qt.ArrowType.NoArrow)
        menu = button.menu()
        if menu is None:
            from PySide6.QtWidgets import QMenu

            menu = QMenu(button)
            button.setMenu(menu)
        for action in actions:
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        title_layout.addWidget(button)

    def _toggle_side_panel(self, index: int, name: str, visible: bool) -> None:
        widget = self.horizontal_splitter.widget(index)
        if widget is None:
            return

        widget.setVisible(True)
        sizes = self.horizontal_splitter.sizes()
        default_size = self._panel_defaults[name]

        if visible:
            if sizes[index] < 50:
                delta = default_size - sizes[index]
                sizes[index] = default_size
                sizes[1] = max(300, sizes[1] - delta)
                self.horizontal_splitter.setSizes(sizes)
        else:
            if sizes[index] > 0:
                sizes[1] += sizes[index]
                sizes[index] = 0
                self.horizontal_splitter.setSizes(sizes)

        state = "показана" if visible else "скрыта"
        self.statusBar().showMessage(f"Панель {name} {state}", 3000)

    def _toggle_bottom_panel(self, name: str, visible: bool) -> None:
        widget = self.editor_terminal_splitter.widget(1)
        if widget is None:
            return

        widget.setVisible(True)
        sizes = self.editor_terminal_splitter.sizes()
        default_size = self._panel_defaults[name]

        if visible:
            if sizes[1] < 50:
                delta = default_size - sizes[1]
                sizes[1] = default_size
                sizes[0] = max(200, sizes[0] - delta)
                self.editor_terminal_splitter.setSizes(sizes)
            self.terminal.ensure_ready()
        else:
            if sizes[1] > 0:
                sizes[0] += sizes[1]
                sizes[1] = 0
                self.editor_terminal_splitter.setSizes(sizes)

        state = "показана" if visible else "скрыта"
        self.statusBar().showMessage(f"Панель {name} {state}", 3000)

    def _new_file(self) -> None:
        self.editor_tabs.new_file()
        self.statusBar().showMessage("New file created", 3000)

    def _open_file(self) -> None:
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Open File",
            str(self.root),
            "Code Files (*.py *.c *.h *.cpp *.cc *.cxx *.hpp *.go);;All Files (*)",
        )
        if file_name:
            self.editor_tabs.open_file(Path(file_name))
            self.statusBar().showMessage(f"Opened {file_name}", 3000)

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", str(self.root))
        if not folder:
            return
        self.root = Path(folder).resolve()
        self.explorer.set_root(self.root)
        self.terminal.set_cwd(self.root)
        self.statusBar().showMessage(f"Workspace: {self.root}", 5000)

    def _on_folder_changed(self, root: Path) -> None:
        self.root = root
        self.terminal.set_cwd(self.root)
        self._update_window_title()
        self.statusBar().showMessage(f"Workspace: {self.root}", 5000)

    def _update_window_title(self) -> None:
        self.setWindowTitle(f"svoiCursor - {self.root.name}")

    def _save_current_file(self) -> None:
        editor = self.editor_tabs.current_editor()
        if editor is not None and editor.path is None:
            self._save_current_file_as()
            return

        path = self.editor_tabs.save_current_file()
        if path is None:
            self.statusBar().showMessage("No editable file is open", 3000)
            return
        self.statusBar().showMessage(f"Saved {path}", 3000)

    def _save_current_file_as(self) -> Path | None:
        editor = self.editor_tabs.current_editor()
        if editor is None:
            self.statusBar().showMessage("No editable file is open", 3000)
            return None

        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save File As",
            str(editor.path or self.root / "untitled.py"),
            "Code Files (*.py *.c *.h *.cpp *.cc *.cxx *.hpp *.go);;All Files (*)",
        )
        if not file_name:
            return None

        path = self.editor_tabs.save_current_file(Path(file_name))
        if path is not None:
            self.statusBar().showMessage(f"Saved {path}", 3000)
        return path

    def _editor_command(self, command: str) -> None:
        focused = QApplication.focusWidget()
        if isinstance(focused, TerminalView):
            focused.apply_edit_command(command)
            return

        editor = self.editor_tabs.current_editor()
        if editor is None:
            self.statusBar().showMessage("No editable file is open", 3000)
            return
        editor.setFocus()
        getattr(editor, command)()

    def _duplicate_current_line(self) -> None:
        editor = self.editor_tabs.current_editor()
        if editor is None:
            self.statusBar().showMessage("No editable file is open", 3000)
            return

        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        line = cursor.selectedText().replace("\u2029", "")
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        cursor.insertText(f"\n{line}")
        editor.setTextCursor(cursor)

    def _run_current_file(self) -> None:
        if self._run_thread is not None:
            self.terminal.write("\nA process is already running.")
            return

        if not self._view_actions["Terminal"].isChecked():
            self._view_actions["Terminal"].setChecked(True)
            self._toggle_bottom_panel("Terminal", True)

        editor = self.editor_tabs.current_editor()
        if editor is not None and editor.path is None:
            path = self._save_current_file_as()
            if path is None:
                self.terminal.write("\nSave the file before running it.")
                self.terminal.set_external_busy(False)
                return
        else:
            path = self.editor_tabs.save_current_file()
        if path is None:
            self.terminal.write("\nOpen a Python, C, C++, or Go file before running.")
            self.terminal.set_external_busy(False)
            return

        if path.suffix.lower() == ".py":
            self.terminal.run_command(f"python {_quote_powershell_path(path)}")
            return

        self.terminal.set_external_busy(True)
        self.terminal.clear_output()
        self.terminal.write(f"> Running {path}\n")
        self._run_thread = QThread(self)
        self._runner = CodeRunner(path, self.terminal.cwd)
        self._runner.moveToThread(self._run_thread)
        self._run_thread.started.connect(self._runner.run)
        self._runner.finished.connect(self._handle_run_result)
        self._runner.finished.connect(self._run_thread.quit)
        self._run_thread.finished.connect(self._runner.deleteLater)
        self._run_thread.finished.connect(self._run_thread.deleteLater)
        self._run_thread.finished.connect(self._reset_runner)
        self._run_thread.start()

    @Slot(object)
    def _handle_run_result(self, result: RunResult) -> None:
        self.terminal.write(f"$ {result.command}\n")
        if result.output:
            self.terminal.write(f"{result.output}\n")
        self.terminal.write(f"Process exited with code {result.exit_code}.")
        self.statusBar().showMessage(f"Run finished with code {result.exit_code}", 3000)

    @Slot()
    def _reset_runner(self) -> None:
        self._run_thread = None
        self._runner = None
        self.terminal.set_external_busy(False)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About svoiCursor",
            "svoiCursor\n\nPython IDE prototype with VS Code-like UI and a right AI agent panel.",
        )

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.terminal._close_shell()
        super().closeEvent(event)

    def nativeEvent(self, event_type, message):  # type: ignore[no-untyped-def]  # noqa: N802
        handled, result = handle_frameless_native_event(self, event_type, message)
        if handled:
            return True, result
        return super().nativeEvent(event_type, message)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    workspace = Path(os.getenv("SVOI_WORKSPACE", Path.cwd())).resolve()
    window = MainWindow(workspace)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
