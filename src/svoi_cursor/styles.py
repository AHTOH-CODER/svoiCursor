APP_STYLE = """
QMainWindow, QWidget {
    background: #1e1e1e;
    color: #cccccc;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

QWidget#TitleBar {
    background: #181818;
    border: none;
    min-height: 28px;
    max-height: 28px;
}

QFrame#TopBarDivider {
    background: #3c3c3c;
    border: none;
    min-height: 1px;
    max-height: 1px;
}

QWidget#TitleBar QToolButton {
    background: transparent;
    color: #cccccc;
    border: none;
    border-radius: 2px;
    padding: 2px 8px;
    min-height: 24px;
    max-height: 24px;
    font-size: 12px;
}

QWidget#TitleBar QToolButton:hover {
    background: #2a2d2e;
}

QWidget#TitleBar QToolButton:pressed {
    background: #37373d;
}

QWidget#TitleBar QToolButton::menu-indicator {
    image: none;
    width: 0;
    height: 0;
}

QPushButton#TitleRunButton {
    background: transparent;
    color: #cccccc;
    border: none;
    border-radius: 2px;
    padding: 2px 10px;
    min-height: 24px;
    max-height: 24px;
    font-size: 12px;
}

QPushButton#TitleRunButton:hover {
    background: #2a2d2e;
}

QPushButton#WindowButton {
    background: transparent;
    color: #cccccc;
    border: none;
    border-radius: 0;
    padding: 0;
    font-size: 12px;
}

QPushButton#WindowButton:hover {
    background: #3c3c3c;
}

QPushButton#WindowCloseButton {
    background: transparent;
    color: #cccccc;
    border: none;
    border-radius: 0;
    padding: 0;
    font-size: 12px;
}

QPushButton#WindowCloseButton:hover {
    background: #e81123;
    color: #ffffff;
}

QFrame#SideBar, QFrame#AgentPanel, QFrame#TerminalPanel {
    background: #252526;
    border-right: 1px solid #1b1b1b;
}

QFrame#AgentPanel {
    border-left: 1px solid #1b1b1b;
    border-right: none;
}

QLabel#PanelTitle {
    color: #bbbbbb;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 10px 12px 4px 12px;
    text-transform: uppercase;
}

QPushButton {
    background: transparent;
    color: #cccccc;
    border: none;
    border-radius: 4px;
    padding: 8px;
}

QPushButton:hover {
    background: #3c3c3c;
}

QPushButton#AgentSendButton {
    background: #3c3c3c;
    color: #e6e6e6;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 8px 12px;
}

QPushButton#AgentSendButton:hover {
    background: #4a4a4a;
}

QPushButton#AgentSendButton:pressed {
    background: #333333;
}

QPushButton#AgentSendButton:disabled {
    background: #2d2d2d;
    color: #858585;
    border-color: #3a3a3a;
}

QLabel#ExplorerTitle {
    color: #bbbbbb;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 2px 4px 0 4px;
    text-transform: uppercase;
}

QPushButton#ExplorerAction {
    background: #2d2d2d;
    color: #cccccc;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 0 5px;
    font-size: 10px;
    min-width: 20px;
}

QPushButton#ExplorerAction:hover {
    background: #3c3c3c;
}

QMenu {
    background: #252526;
    color: #cccccc;
    border: 1px solid #454545;
}

QMenu::item:selected {
    background: #094771;
}

QTreeView {
    background: #252526;
    color: #cccccc;
    border: none;
    outline: 0;
}

QTreeView::item {
    min-height: 22px;
}

QTreeView::item:selected {
    background: #37373d;
}

QTabWidget::pane {
    border: none;
}

QTabBar::tab {
    background: #2d2d2d;
    color: #cccccc;
    padding: 9px 16px;
    border-right: 1px solid #1e1e1e;
}

QTabBar::tab:selected {
    background: #1e1e1e;
    color: #ffffff;
}

QPlainTextEdit, QTextEdit {
    background: #1e1e1e;
    color: #d4d4d4;
    border: none;
    selection-background-color: #264f78;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 14px;
}

QTextEdit#ChatHistory {
    background: #252526;
    font-family: "Segoe UI", Arial, sans-serif;
}

QPlainTextEdit#TerminalOutput {
    background: #181818;
    color: #cccccc;
    border-top: 1px solid #2b2b2b;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 13px;
    padding: 4px;
}

QPlainTextEdit#PromptInput {
    background: #1e1e1e;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    padding: 8px;
    font-family: "Segoe UI", Arial, sans-serif;
}

QStatusBar {
    background: #181818;
    color: #cccccc;
    border-top: 1px solid #2b2b2b;
}

QStatusBar::item {
    border: none;
}

QSplitter::handle {
    background: #1b1b1b;
}
"""
