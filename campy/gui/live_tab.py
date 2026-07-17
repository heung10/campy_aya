"""
Recording control and status tab for the campy GUI.
"""

from __future__ import print_function

import re
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config_model import camera_names
from .status import collect_status


CAMERA_PROGRESS_RE = re.compile(
    r"^(?P<device>.+?) collected (?P<count>\d+) frames at (?P<rate>[0-9.]+) fps for (?P<elapsed>[0-9.]+) sec\."
)
GPIO_PROGRESS_RE = re.compile(
    r"^\[GUI\] GPIO events received: (?:(?P<total>\d+) total, )?(?P<count>\d+) recent lines hidden"
)
CAMERA_EXPOSURE_RE = re.compile(
    r"^(?P<device>.+?) applied exposure time (?P<exposure>[0-9.]+) us\.$"
)


class LiveTab(QWidget):
    readyRequested = pyqtSignal()
    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    exposureRequested = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super(LiveTab, self).__init__(parent)
        self.config_data = {}
        self.config_path = ""
        self.process_state = "idle"
        self.recording_phase = "idle"
        self.ready_to_start = False
        self.session_complete = False
        self.runtime_rows = {}
        self.preflight_rows = {}
        self.gpio_runtime_count = 0
        self.elapsed_seconds = 0.0
        self.exposure_rows = []
        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.refresh_timer.start(1000)

    def set_config(self, data, path):
        self.config_data = data or {}
        self.config_path = path or ""
        self.preflight_rows = {}
        self.elapsed_seconds = 0.0
        self._rebuild_exposure_controls()
        self._update_duration_label()
        self.refresh_status()

    def set_preflight_results(self, results):
        self.preflight_rows = {}
        for device, result in (results or {}).items():
            self.preflight_rows[device] = {
                "state": result.get("state", "Idle"),
                "count": "-",
                "rate": "-",
                "last_update": datetime.now().strftime("%H:%M:%S"),
                "notes": result.get("message", ""),
            }

        self.ready_to_start = bool(
            self.preflight_rows
            and all(row["state"] in ["Ready", "Disabled"] for row in self.preflight_rows.values())
        )
        self.refresh_status()

    def set_process_state(self, state):
        self.process_state = state or "idle"
        if self.process_state == "idle":
            if not self.session_complete:
                self.ready_to_start = False
                self.recording_phase = "idle"
                self.runtime_rows = {}
                self.preflight_rows = {}
                self.gpio_runtime_count = 0
                self.elapsed_seconds = 0.0
        elif self.process_state == "stopping":
            self.recording_phase = "stopping"
        elif self.process_state == "running" and self.recording_phase == "idle":
            self.recording_phase = "preparing"
        self.process_state_label.setText("Process: {}".format(self.process_state))
        self.ready_button.setEnabled(self.process_state == "idle" and not self.session_complete)
        self.start_button.setEnabled(self.process_state == "running" and self.ready_to_start)
        self.stop_button.setEnabled(self.process_state in ["running", "stopping"])
        self._update_exposure_buttons()
        self._update_duration_label()
        self.refresh_status()

    def set_ready_to_start(self, ready):
        self.ready_to_start = bool(ready)
        if ready:
            self.recording_phase = "ready"
        self.start_button.setEnabled(self.process_state == "running" and self.ready_to_start)
        self._update_exposure_buttons()
        if ready:
            self.process_state_label.setText("Process: ready")
        self._update_duration_label()
        self.refresh_status()

    def set_recording_started(self):
        self.recording_phase = "recording"
        self.session_complete = False
        self.runtime_rows = {}
        self.gpio_runtime_count = 0
        self.elapsed_seconds = 0.0
        self.ready_to_start = False
        self.start_button.setEnabled(False)
        self._update_exposure_buttons()
        self.process_state_label.setText("Process: recording")
        self._update_duration_label()
        self.refresh_status()

    def set_session_complete(self):
        self.session_complete = True
        self.ready_to_start = False
        self.recording_phase = "finished"
        self.ready_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._update_exposure_buttons()
        self.process_state_label.setText("Process: finished")
        self._update_duration_label()

    def append_log(self, line):
        if not line:
            return
        self.update_runtime_from_line(line)
        self.log.appendPlainText(line)
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.End)
        self.log.setTextCursor(cursor)

    def refresh_status(self):
        if not self.config_data:
            self._set_empty_status()
            return
        rows, _ = collect_status(self.config_data, self.recording_phase)
        rows = self._apply_runtime_rows(rows)
        self._populate_table(rows)

    def update_runtime_from_line(self, line):
        exposure_match = CAMERA_EXPOSURE_RE.match(line)
        if exposure_match:
            self.set_camera_exposure_value(
                exposure_match.group("device").strip(),
                float(exposure_match.group("exposure")),
            )
            return

        camera_match = CAMERA_PROGRESS_RE.match(line)
        if camera_match:
            device = camera_match.group("device").strip()
            count = camera_match.group("count")
            rate = camera_match.group("rate")
            elapsed = camera_match.group("elapsed")
            self.runtime_rows[device] = {
                "state": "Recording",
                "count": "{} frames".format(count),
                "rate": "{} Hz".format(rate),
                "last_update": datetime.now().strftime("%H:%M:%S"),
                "notes": "elapsed {} sec".format(elapsed),
            }
            self.elapsed_seconds = max(self.elapsed_seconds, float(elapsed))
            self._update_duration_label()
            self.refresh_status()
            return

        gpio_match = GPIO_PROGRESS_RE.match(line)
        if gpio_match:
            if gpio_match.group("total") is not None:
                self.gpio_runtime_count = int(gpio_match.group("total"))
            else:
                self.gpio_runtime_count += int(gpio_match.group("count"))
            self.runtime_rows["GPIO"] = {
                "state": "Recording",
                "count": "{} events".format(self.gpio_runtime_count),
                "rate": "live",
                "last_update": datetime.now().strftime("%H:%M:%S"),
                "notes": "live GPIO events from logger output",
            }
            self.refresh_status()

    def _apply_runtime_rows(self, rows):
        if self.recording_phase not in ["recording", "stopping"]:
            for row in rows:
                preflight = self.preflight_rows.get(row.device)
                if preflight is None:
                    continue
                row.state = preflight["state"]
                row.count = preflight["count"]
                row.rate = preflight["rate"]
                row.last_update = preflight["last_update"]
                row.notes = preflight["notes"]
            return rows

        if self.recording_phase not in ["recording", "stopping"]:
            return rows
        for row in rows:
            runtime = self.runtime_rows.get(row.device)
            if runtime is None:
                continue
            row.state = runtime["state"]
            row.count = runtime["count"]
            row.rate = runtime["rate"]
            row.last_update = runtime["last_update"]
            row.notes = runtime["notes"]
        return rows

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        self.ready_button = QPushButton("Ready to Record")
        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop Recording")
        self.refresh_button = QPushButton("Refresh Status")
        self.process_state_label = QLabel("Process: idle")
        self.process_state_label.setStyleSheet("font-weight: 600;")
        self.ready_button.clicked.connect(self.readyRequested.emit)
        self.start_button.clicked.connect(self.startRequested.emit)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        self.refresh_button.clicked.connect(self.refresh_status)
        controls.addWidget(self.ready_button)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        self.duration_label = QLabel("Duration: target - | elapsed 00:00:00")
        self.duration_label.setProperty("muted", True)
        controls.addWidget(self.duration_label)
        controls.addWidget(self.process_state_label)
        layout.addLayout(controls)

        exposure_group = QGroupBox("Exposure")
        self.exposure_layout = QGridLayout(exposure_group)
        self.exposure_layout.setContentsMargins(8, 8, 8, 8)
        self.exposure_layout.setHorizontalSpacing(8)
        self.exposure_layout.setVerticalSpacing(6)
        layout.addWidget(exposure_group, 0)

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Device", "State", "Count", "Rate", "Last update", "Notes"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setMinimumHeight(155)
        status_layout.addWidget(self.table)
        layout.addWidget(status_group, 4)

        log_group = QGroupBox("Acquisition Log")
        log_layout = QVBoxLayout(log_group)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setMaximumHeight(120)
        self.log.setPlainText("Start a recording to see campy output here.")
        log_layout.addWidget(self.log)
        layout.addWidget(log_group, 2)
        self.set_process_state("idle")

    def _set_empty_status(self):
        self._populate_table([])

    def _populate_table(self, rows):
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [row.device, row.state, row.count, row.rate, row.last_update, row.notes]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setTextAlignment(Qt.AlignCenter)
                    self._style_state_item(item, str(value).lower())
                self.table.setItem(row_index, column, item)

    def _style_state_item(self, item, state):
        if "recording" in state or "saved" in state:
            item.setBackground(Qt.darkGreen)
        elif "ready" in state or "preparing" in state or "waiting" in state or "stopping" in state:
            item.setBackground(Qt.darkYellow)
            item.setForeground(Qt.black)
        elif "disabled" in state:
            item.setBackground(Qt.darkGray)
        else:
            item.setBackground(Qt.darkRed)

    def _rebuild_exposure_controls(self):
        while self.exposure_layout.count():
            item = self.exposure_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.exposure_rows = []
        if not self.config_data:
            self.exposure_layout.addWidget(QLabel("Load a config to enable per-camera exposure control."), 0, 0)
            return

        default_exposure_ms = float(self.config_data.get("cameraExposureTimeInUs", 1500) or 1500) / 1000.0
        names = camera_names(self.config_data)
        for index, camera_name in enumerate(names[:6]):
            label = QLabel(camera_name)
            spin = QDoubleSpinBox()
            spin.setRange(0.01, 1000.0)
            spin.setDecimals(3)
            spin.setSuffix(" ms")
            spin.setSingleStep(0.1)
            spin.setValue(default_exposure_ms)
            button = QPushButton("Apply")
            button.setEnabled(False)
            button.clicked.connect(
                lambda _checked=False, name=camera_name, field=spin: self._request_exposure_change(name, field)
            )
            grid_row = index // 2
            col_offset = (index % 2) * 3
            self.exposure_layout.addWidget(label, grid_row, col_offset)
            self.exposure_layout.addWidget(spin, grid_row, col_offset + 1)
            self.exposure_layout.addWidget(button, grid_row, col_offset + 2)
            self.exposure_rows.append({
                "camera_name": camera_name,
                "spin": spin,
                "button": button,
            })

        self.exposure_layout.setColumnStretch(1, 1)
        self.exposure_layout.setColumnStretch(4, 1)
        self._update_exposure_buttons()

    def _update_exposure_buttons(self):
        enabled = self.process_state == "running" and self.recording_phase == "recording"
        for row in self.exposure_rows:
            row["button"].setEnabled(enabled)

    def set_camera_exposure_value(self, camera_name, exposure_time_us):
        for row in self.exposure_rows:
            if row["camera_name"] != camera_name:
                continue
            row["spin"].blockSignals(True)
            row["spin"].setValue(float(exposure_time_us) / 1000.0)
            row["spin"].blockSignals(False)
            break

    def _request_exposure_change(self, camera_name, field):
        self.exposureRequested.emit(str(camera_name), float(field.value()))

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
