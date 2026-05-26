from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QTreeView,
    QVBoxLayout,
    QFileSystemModel,
    QWidget,
)


@dataclass
class FileClipboard:
    paths: list[Path]
    operation: str  # "copy" or "cut"


class ExplorerPanel(QFrame):
    file_selected = Signal(Path)
    file_deleted = Signal(Path)
    file_renamed = Signal(Path, Path)
    folder_changed = Signal(Path)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.setObjectName("SideBar")
        self.root = root.resolve()
        self._clipboard: FileClipboard | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(6, 4, 6, 2)
        header_layout.setSpacing(4)

        self.title = QLabel(f"EXPLORER: {self.root.name}")
        self.title.setObjectName("ExplorerTitle")
        header_layout.addWidget(self.title)
        layout.addWidget(header)

        self.model = QFileSystemModel(self)
        self.model.setRootPath(str(self.root))
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(str(self.root)))
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.doubleClicked.connect(self._open_index)
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)
        layout.addWidget(self.tree)

    def set_root(self, root: Path) -> None:
        self.root = root.resolve()
        self.title.setText(f"EXPLORER: {self.root.name}")
        self.model.setRootPath(str(self.root))
        self.tree.setRootIndex(self.model.index(str(self.root)))
        self.folder_changed.emit(self.root)

    def _refresh(self) -> None:
        current_root = self.root
        self.model.setRootPath("")
        self.model.setRootPath(str(current_root))
        self.tree.setRootIndex(self.model.index(str(current_root)))

    def _open_index(self, index) -> None:  # type: ignore[no-untyped-def]
        path = Path(self.model.filePath(index))
        if path.is_file():
            self.file_selected.emit(path)

    def _selected_path(self) -> Path | None:
        indexes = self.tree.selectedIndexes()
        if not indexes:
            return None
        path = Path(self.model.filePath(indexes[0]))
        return path if path.exists() else None

    def _target_directory(self) -> Path:
        selected = self._selected_path()
        if selected is None:
            return self.root
        return selected if selected.is_dir() else selected.parent

    def _create_file(self) -> None:
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if not ok or not name.strip():
            return

        path = self._target_directory() / name.strip()
        if path.exists():
            QMessageBox.warning(self, "New File", f"'{path.name}' already exists.")
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        self._refresh()
        self.file_selected.emit(path)

    def _create_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return

        path = self._target_directory() / name.strip()
        if path.exists():
            QMessageBox.warning(self, "New Folder", f"'{path.name}' already exists.")
            return

        path.mkdir(parents=True, exist_ok=True)
        self._refresh()

    def _rename_item(self) -> None:
        selected = self._selected_path()
        if selected is None or selected == self.root:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename",
            "New name:",
            text=selected.name,
        )
        if not ok or not new_name.strip() or new_name.strip() == selected.name:
            return

        target = selected.parent / new_name.strip()
        if target.exists():
            QMessageBox.warning(self, "Rename", f"'{target.name}' already exists.")
            return

        old_path = selected
        old_path.rename(target)
        self.file_renamed.emit(old_path, target)
        self._refresh()

    def _copy_items(self) -> None:
        selected = self._selected_path()
        if selected is None or selected == self.root:
            return
        self._clipboard = FileClipboard(paths=[selected], operation="copy")

    def _cut_items(self) -> None:
        selected = self._selected_path()
        if selected is None or selected == self.root:
            return
        self._clipboard = FileClipboard(paths=[selected], operation="cut")

    def _paste_items(self) -> None:
        if self._clipboard is None:
            return

        destination = self._target_directory()
        for source in self._clipboard.paths:
            if not source.exists():
                continue

            target = destination / source.name
            if target.exists():
                QMessageBox.warning(self, "Paste", f"'{target.name}' already exists.")
                continue

            if self._clipboard.operation == "copy":
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
            else:
                shutil.move(str(source), str(target))
                self.file_deleted.emit(source)

        if self._clipboard.operation == "cut":
            self._clipboard = None
        self._refresh()

    def _delete_item(self) -> None:
        selected = self._selected_path()
        if selected is None or selected == self.root:
            return

        item_type = "folder" if selected.is_dir() else "file"
        answer = QMessageBox.question(
            self,
            "Delete",
            f"Delete {item_type} '{selected.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if selected.is_dir():
            shutil.rmtree(selected)
        else:
            selected.unlink()
            self.file_deleted.emit(selected)
        self._refresh()

    def _show_context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        index = self.tree.indexAt(position)
        if index.isValid():
            self.tree.setCurrentIndex(index)

        menu = QMenu(self)
        actions = [
            ("New File", self._create_file),
            ("New Folder", self._create_folder),
            None,
            ("Cut", self._cut_items),
            ("Copy", self._copy_items),
            ("Paste", self._paste_items),
            None,
            ("Rename", self._rename_item),
            ("Delete", self._delete_item),
            None,
            ("Refresh", self._refresh),
        ]

        for item in actions:
            if item is None:
                menu.addSeparator()
                continue
            label, handler = item
            action = QAction(label, self)
            action.triggered.connect(handler)
            if label in {"Cut", "Copy", "Rename", "Delete"} and self._selected_path() is None:
                action.setEnabled(False)
            if label == "Paste" and self._clipboard is None:
                action.setEnabled(False)
            menu.addAction(action)

        menu.exec(self.tree.viewport().mapToGlobal(position))
