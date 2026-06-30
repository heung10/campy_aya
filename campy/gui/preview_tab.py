"""
Camera preview tab for the campy GUI.
"""

from __future__ import print_function

from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from .config_model import camera_names
from .style import CAMERA_TILE_STYLE


class CameraTile(QFrame):
    def __init__(self, index, parent=None):
        super(CameraTile, self).__init__(parent)
        self.index = index
        self.setStyleSheet(CAMERA_TILE_STYLE)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 6)
        layout.setSpacing(4)

        self.title = QLabel("Camera {}".format(index + 1))
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-weight: 600; color: #f4f7fb;")

        self.preview = QLabel("No preview yet")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(210)
        self.preview.setStyleSheet("background: #050607; color: #8a9099; border: 1px solid #2d333d;")

        self._preview_path = None
        self._preview_mtime = None
        self._preview_pixmap = None

        layout.addWidget(self.title)
        layout.addWidget(self.preview, 1)

    def set_title(self, title):
        self.title.setText(title)

    def set_preview_path(self, path):
        self._preview_path = Path(path) if path else None
        self._preview_mtime = None
        self._preview_pixmap = None
        self.preview.clear()
        self.preview.setText("Waiting for preview" if path else "Unused")

    def refresh_preview(self):
        if self._preview_path is None or not self._preview_path.exists():
            return
        try:
            mtime = self._preview_path.stat().st_mtime
        except Exception:
            return
        if self._preview_pixmap is None or self._preview_mtime != mtime:
            try:
                image_bytes = self._preview_path.read_bytes()
            except Exception:
                return
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes)
            if pixmap.isNull():
                return
            self._preview_pixmap = pixmap
            self._preview_mtime = mtime
        self._draw_preview()

    def resizeEvent(self, event):  # noqa: N802
        super(CameraTile, self).resizeEvent(event)
        self._draw_preview()

    def _draw_preview(self):
        if self._preview_pixmap is None:
            return
        scaled = self._preview_pixmap.scaled(
            self.preview.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)


class PreviewTab(QWidget):
    def __init__(self, parent=None):
        super(PreviewTab, self).__init__(parent)
        self.config_data = {}
        self.preview_folder = None
        self.tiles = []
        self._build_ui()

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.refresh_previews)
        self.preview_timer.start(200)

    def set_config(self, data, path=""):
        self.config_data = data or {}
        self._refresh_tile_paths()

    def set_preview_folder(self, folder):
        self.preview_folder = Path(folder) if folder else None
        self._refresh_tile_paths()

    def refresh_previews(self):
        for tile in self.tiles:
            tile.refresh_preview()

    def _build_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        for index in range(6):
            tile = CameraTile(index)
            self.tiles.append(tile)
            layout.addWidget(tile, index // 3, index % 3)
        for column in range(3):
            layout.setColumnStretch(column, 1)
        for row in range(2):
            layout.setRowStretch(row, 1)

    def _refresh_tile_paths(self):
        names = camera_names(self.config_data)[:6] if self.config_data else []
        for index, tile in enumerate(self.tiles):
            title = names[index] if index < len(names) else "Camera {}".format(index + 1)
            tile.set_title(title)
            if self.preview_folder and index < len(names):
                tile.set_preview_path(self.preview_folder / "{}.png".format(names[index]))
            else:
                tile.set_preview_path(None)
