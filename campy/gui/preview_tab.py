"""
Camera preview tab for the campy GUI.
"""

from __future__ import print_function

import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .config_model import camera_names
from .style import CAMERA_TILE_STYLE

CAMERA_PROGRESS_RE = re.compile(
    r"^(?P<device>.+?) collected (?P<count>\d+) frames at (?P<rate>[0-9.]+) fps for (?P<elapsed>[0-9.]+) sec\."
)


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
    readyRequested = pyqtSignal()
    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()

    def __init__(self, parent=None):
        super(PreviewTab, self).__init__(parent)
        self.config_data = {}
        self.config_path = ""
        self.preview_folder = None
        self.process_state = "idle"
        self.recording_phase = "idle"
        self.ready_to_start = False
        self.session_complete = False
        self.elapsed_seconds = 0.0
        self.tiles = []
        self._build_ui()

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.refresh_previews)
        self.preview_timer.start(200)

    def set_config(self, data, path=""):
        self.config_data = data or {}
        self.config_path = path or ""
        self.elapsed_seconds = 0.0
        self._update_duration_label()
        self._refresh_tile_paths()

    def set_preview_folder(self, folder):
        self.preview_folder = Path(folder) if folder else None
        self._refresh_tile_paths()

    def refresh_previews(self):
        for tile in self.tiles:
            tile.refresh_preview()

    def set_process_state(self, state):
        self.process_state = state or "idle"
        if self.process_state == "idle":
            if not self.session_complete:
                self.ready_to_start = False
                self.recording_phase = "idle"
                self.elapsed_seconds = 0.0
        elif self.process_state == "stopping":
            self.recording_phase = "stopping"
        elif self.process_state == "running" and self.recording_phase == "idle":
            self.recording_phase = "preparing"
        self.process_state_label.setText("Process: {}".format(self.process_state))
        self.ready_button.setEnabled(self.process_state == "idle" and not self.session_complete)
        self.start_button.setEnabled(self.process_state == "running" and self.ready_to_start)
        self.stop_button.setEnabled(self.process_state in ["running", "stopping"])
        self._update_duration_label()

    def set_ready_to_start(self, ready):
        self.ready_to_start = bool(ready)
        if ready:
            self.recording_phase = "ready"
            self.process_state_label.setText("Process: ready")
        self.start_button.setEnabled(self.process_state == "running" and self.ready_to_start)
        self._update_duration_label()

    def set_recording_started(self):
        self.recording_phase = "recording"
        self.session_complete = False
        self.ready_to_start = False
        self.elapsed_seconds = 0.0
        self.start_button.setEnabled(False)
        self.process_state_label.setText("Process: recording")
        self._update_duration_label()

    def set_session_complete(self):
        self.session_complete = True
        self.ready_to_start = False
        self.recording_phase = "finished"
        self.ready_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.process_state_label.setText("Process: finished")
        self._update_duration_label()

    def update_runtime_from_line(self, line):
        match = CAMERA_PROGRESS_RE.match(line or "")
        if not match:
            return
        self.elapsed_seconds = max(self.elapsed_seconds, float(match.group("elapsed")))
        self._update_duration_label()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        self.ready_button = QPushButton("Ready to Record")
        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop Recording")
        self.process_state_label = QLabel("Process: idle")
        self.process_state_label.setStyleSheet("font-weight: 600;")
        self.duration_label = QLabel("Duration: target - | elapsed 00:00:00")
        self.duration_label.setProperty("muted", True)
        self.ready_button.clicked.connect(self.readyRequested.emit)
        self.start_button.clicked.connect(self.startRequested.emit)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        controls.addWidget(self.ready_button)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addStretch(1)
        controls.addWidget(self.duration_label)
        controls.addWidget(self.process_state_label)
        layout.addLayout(controls)

        preview_grid = QGridLayout()
        preview_grid.setContentsMargins(0, 0, 0, 0)
        preview_grid.setSpacing(8)
        for index in range(6):
            tile = CameraTile(index)
            self.tiles.append(tile)
            preview_grid.addWidget(tile, index // 3, index % 3)
        for column in range(3):
            preview_grid.setColumnStretch(column, 1)
        for row in range(2):
            preview_grid.setRowStretch(row, 1)
        layout.addLayout(preview_grid, 1)
        self.set_process_state("idle")

    def _refresh_tile_paths(self):
        names = camera_names(self.config_data)[:6] if self.config_data else []
        for index, tile in enumerate(self.tiles):
            title = names[index] if index < len(names) else "Camera {}".format(index + 1)
            tile.set_title(title)
            if self.preview_folder and index < len(names):
                tile.set_preview_path(self.preview_folder / "{}.png".format(names[index]))
            else:
                tile.set_preview_path(None)

    def _update_duration_label(self):
        target = "Infinite" if self.config_data.get("infiniteRecording", False) else self._format_hms(
            float(self.config_data.get("recTimeInSec", 0) or 0)
        )
        elapsed = self._format_hms(self.elapsed_seconds)
        self.duration_label.setText("Duration: target {} | elapsed {}".format(target, elapsed))

    def _format_hms(self, seconds):
        total_seconds = max(0, int(seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return "{:02d}:{:02d}:{:02d}".format(hours, minutes, secs)
