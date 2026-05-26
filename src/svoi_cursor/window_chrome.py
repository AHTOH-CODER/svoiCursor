from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
RESIZE_BORDER = 6


class TitleBar(QWidget):
    def __init__(self, window: QWidget) -> None:
        super().__init__()
        self._window = window
        self._drag_pos: QPoint | None = None
        self.setObjectName("TitleBar")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setFixedHeight(28)

    def layout(self) -> QHBoxLayout:
        return self._layout

    def add_window_controls(self) -> None:
        self._layout.addStretch(1)

        minimize = QPushButton("─")
        minimize.setObjectName("WindowButton")
        minimize.setToolTip("Minimize")
        minimize.clicked.connect(self._window.showMinimized)

        self._maximize = QPushButton("□")
        self._maximize.setObjectName("WindowButton")
        self._maximize.setToolTip("Maximize")
        self._maximize.clicked.connect(self._toggle_maximize)

        close = QPushButton("✕")
        close.setObjectName("WindowCloseButton")
        close.setToolTip("Close")
        close.clicked.connect(self._window.close)

        for button in (minimize, self._maximize, close):
            button.setFixedSize(40, 28)
            self._layout.addWidget(button)

    def _toggle_maximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
            self._maximize.setText("□")
        else:
            self._window.showMaximized()
            self._maximize.setText("❐")

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
                self._maximize.setText("□")
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)


def apply_frameless_window(window: QWidget) -> None:
    window.setWindowFlags(
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
    )


def handle_frameless_native_event(window: QWidget, event_type: bytes, message: int) -> tuple[bool, int]:
    if sys.platform != "win32" or event_type != b"windows_generic_MSG":
        return False, 0
    if window.isMaximized():
        return False, 0

    try:
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != WM_NCHITTEST:
            return False, 0

        x = ctypes.c_int16(msg.lParam & 0xFFFF).value
        y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
        pos = window.mapFromGlobal(QPoint(x, y))
    except Exception:
        return False, 0

    width = window.width()
    height = window.height()
    border = RESIZE_BORDER

    left = pos.x() <= border
    right = pos.x() >= width - border
    top = pos.y() <= border
    bottom = pos.y() >= height - border

    if top and left:
        return True, HTTOPLEFT
    if top and right:
        return True, HTTOPRIGHT
    if bottom and left:
        return True, HTBOTTOMLEFT
    if bottom and right:
        return True, HTBOTTOMRIGHT
    if left:
        return True, HTLEFT
    if right:
        return True, HTRIGHT
    if top:
        return True, HTTOP
    if bottom:
        return True, HTBOTTOM
    return False, 0
