"""
Config editing tab for the campy GUI.
"""

from __future__ import print_function

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config_model import (
    CampyConfig,
    camera_gpu_ids,
    camera_names,
    camera_serials,
    camera_settings_paths,
    get_value,
    load_config,
    messages_to_text,
    save_config,
    set_camera_list,
    set_camera_names,
    set_if_present,
    validate_config,
)


class ConfigTab(QWidget):
    configLoaded = pyqtSignal(dict, str)
    configSaved = pyqtSignal(dict, str)
    dirtyChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super(ConfigTab, self).__init__(parent)
        self.config = CampyConfig()
        self._dirty = False
        self._loading = False
        self._build_ui()
        self._set_dirty(False)

    def is_dirty(self):
        return self._dirty

    def current_path(self):
        return str(self.config.path) if self.config.path else ""

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.camera_rows = []

        path_row = QHBoxLayout()
        self.config_path = QLineEdit()
        self.config_path.setPlaceholderText("Select a campy .yaml config")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_config)
        path_row.addWidget(QLabel("Config"))
        path_row.addWidget(self.config_path, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        content = QHBoxLayout()
        content.addWidget(self._recording_group(), 1)
        content.addWidget(self._hardware_group(), 1)
        layout.addLayout(content)

        self.camera_group = QGroupBox("Cameras")
        self.camera_layout = QGridLayout(self.camera_group)
        self.camera_layout.setContentsMargins(8, 8, 8, 8)
        self.camera_layout.setHorizontalSpacing(8)
        self.camera_layout.setVerticalSpacing(6)
        layout.addWidget(self.camera_group)

        save_row = QHBoxLayout()
        self.save_button = QPushButton("Save YAML")
        self.save_button.clicked.connect(self._save_clicked)
        self.save_as_button = QPushButton("Save YAML As...")
        self.save_as_button.clicked.connect(self._save_as_clicked)
        self.validation_button = QPushButton("Validate")
        self.validation_button.clicked.connect(self._validate_fields)
        self.dirty_label = QLabel("No config loaded")
        self.dirty_label.setProperty("muted", True)
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.save_as_button)
        save_row.addWidget(self.validation_button)
        save_row.addStretch(1)
        save_row.addWidget(self.dirty_label)
        layout.addLayout(save_row)

        self.validation_text = QPlainTextEdit()
        self.validation_text.setReadOnly(True)
        self.validation_text.setMaximumHeight(115)
        self.validation_text.setPlainText(
            "Load a YAML config, edit the major fields, then save before starting acquisition."
        )
        layout.addWidget(self.validation_text)
        layout.addStretch(1)

    def _recording_group(self):
        group = QGroupBox("Recording")
        form = QFormLayout(group)

        self.save_folder = QLineEdit()
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.save_folder, 1)
        browse_folder = QPushButton("...")
        browse_folder.setFixedWidth(34)
        browse_folder.clicked.connect(self._browse_save_folder)
        folder_row.addWidget(browse_folder)

        self.video_filename = QLineEdit()
        self.rec_time = self._double_spin(0.001, 10**7, 3, " s")
        self.infinite_recording = QCheckBox("record until stopped")
        self.frame_rate = self._double_spin(0.001, 10000, 3, " Hz")
        self.num_cams = QSpinBox()
        self.num_cams.setRange(1, 6)
        self.display_rate = self._double_spin(0, 120, 2, " Hz")
        self.infinite_recording.stateChanged.connect(self._infinite_recording_changed)
        self.num_cams.valueChanged.connect(self._num_cams_changed)

        form.addRow("saveFolder", folder_row)
        form.addRow("videoFilename", self.video_filename)
        form.addRow("infinite recording", self.infinite_recording)
        form.addRow("recording time", self.rec_time)
        form.addRow("frame rate", self.frame_rate)
        form.addRow("num cameras", self.num_cams)
        form.addRow("preview rate", self.display_rate)
        self._connect_dirty_signals([
            self.save_folder,
            self.video_filename,
            self.rec_time,
            self.infinite_recording,
            self.frame_rate,
            self.num_cams,
            self.display_rate,
        ])
        return group

    def _hardware_group(self):
        group = QGroupBox("Trigger / GPIO")
        form = QFormLayout(group)

        self.start_trigger = QCheckBox("start trigger controller")
        self.wait_for_trigger = QCheckBox("wait for camera-ready start")
        self.pulse_hz = self._double_spin(0.001, 10000, 3, " Hz")
        self.pulse_port = QLineEdit()
        self.gpio_enabled = QCheckBox("enable GPIO timestamp logging")
        self.gpio_port = QLineEdit()
        self.gpio_log_name = QLineEdit()

        form.addRow("trigger enabled", self.start_trigger)
        form.addRow("manual start", self.wait_for_trigger)
        form.addRow("pulse frequency", self.pulse_hz)
        form.addRow("PulsePal port", self.pulse_port)
        form.addRow("GPIO enabled", self.gpio_enabled)
        form.addRow("GPIO port", self.gpio_port)
        form.addRow("GPIO log file", self.gpio_log_name)
        self._connect_dirty_signals([
            self.start_trigger,
            self.wait_for_trigger,
            self.pulse_hz,
            self.pulse_port,
            self.gpio_enabled,
            self.gpio_port,
            self.gpio_log_name,
        ])
        return group

    def _double_spin(self, minimum, maximum, decimals, suffix):
        widget = QDoubleSpinBox()
        widget.setRange(float(minimum), float(maximum))
        widget.setDecimals(decimals)
        widget.setSuffix(suffix)
        widget.setSingleStep(1.0)
        return widget

    def _connect_dirty_signals(self, widgets):
        for widget in widgets:
            if isinstance(widget, (QLineEdit,)):
                widget.textChanged.connect(self._field_changed)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(self._field_changed)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._field_changed)

    def _browse_config(self):
        start = str(Path(self.config_path.text()).parent) if self.config_path.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select campy config", start, "YAML files (*.yaml *.yml)")
        if path:
            self.config_path.setText(path)
            self.load_current_config()

    def _browse_save_folder(self):
        start = self.save_folder.text() or ""
        path = QFileDialog.getExistingDirectory(self, "Select save folder", start)
        if path:
            self.save_folder.setText(path)

    def _load_clicked(self):
        self.load_current_config()

    def load_current_config(self):
        if not self.config_path.text().strip():
            self.validation_text.setPlainText("Choose a config file first.")
            return False
        try:
            self.config = load_config(self.config_path.text().strip())
            self.config_path.setText(str(self.config.path))
            self._populate_fields()
            self._set_dirty(False)
            self._validate_fields()
            self.configLoaded.emit(self.config.data, str(self.config.path))
            return True
        except Exception as exc:
            self.validation_text.setPlainText("Could not load config:\n{}".format(exc))
            return False

    def _save_clicked(self):
        self.save_current_config()

    def save_current_config(self):
        if not self.config.loaded:
            self.validation_text.setPlainText("Load a config before saving.")
            return False
        self._collect_fields()
        try:
            path = save_config(self.config)
            self._set_dirty(False)
            self._validate_fields()
            self.configSaved.emit(self.config.data, str(path))
            return True
        except Exception as exc:
            self.validation_text.setPlainText("Could not save config:\n{}".format(exc))
            return False

    def _save_as_clicked(self):
        if not self.config.data:
            self.validation_text.setPlainText("Load a config before saving.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save campy config", self.current_path(), "YAML files (*.yaml *.yml)")
        if not path:
            return
        self._collect_fields()
        try:
            saved_path = save_config(self.config, path)
            self.config_path.setText(str(saved_path))
            self._set_dirty(False)
            self._validate_fields()
            self.configSaved.emit(self.config.data, str(saved_path))
        except Exception as exc:
            self.validation_text.setPlainText("Could not save config:\n{}".format(exc))

    def _populate_fields(self):
        self._loading = True
        data = self.config.data
        num_cams = int(get_value(data, "numCams", 1))
        self.save_folder.setText(str(get_value(data, "saveFolder", get_value(data, "videoFolder", ""))))
        self.video_filename.setText(str(get_value(data, "videoFilename", "0.mp4")))
        self.rec_time.setValue(float(get_value(data, "recTimeInSec", 10)))
        self.infinite_recording.setChecked(bool(get_value(data, "infiniteRecording", False)))
        self.frame_rate.setValue(float(get_value(data, "frameRate", 40)))
        self.num_cams.setValue(num_cams)
        self.display_rate.setValue(float(get_value(data, "displayFrameRate", 0)))
        self.start_trigger.setChecked(bool(get_value(data, "startTriggerController", False)))
        self.wait_for_trigger.setChecked(bool(get_value(data, "waitForTriggerStart", False)))
        self.pulse_hz.setValue(float(get_value(data, "pulseFrequencyHz", get_value(data, "frameRate", 40))))
        self.pulse_port.setText(str(get_value(data, "pulsePalPort", "")))
        self.gpio_enabled.setChecked(bool(get_value(data, "enableGPIOTimestampLogging", False)))
        self.gpio_port.setText(str(get_value(data, "gpioSerialPort", "")))
        self.gpio_log_name.setText(str(get_value(data, "gpioLogFilename", "gpio_log.csv")))
        self._rebuild_camera_rows(num_cams)
        self._populate_camera_rows(data)
        self._update_recording_time_enabled()
        self._loading = False

    def _collect_fields(self):
        data = self.config.data
        set_if_present(data, "saveFolder", self.save_folder.text().strip())
        set_if_present(data, "videoFilename", self.video_filename.text().strip())
        set_if_present(data, "recTimeInSec", self._clean_number(self.rec_time.value()))
        set_if_present(data, "infiniteRecording", bool(self.infinite_recording.isChecked()))
        set_if_present(data, "frameRate", self._clean_number(self.frame_rate.value()))
        set_if_present(data, "numCams", int(self.num_cams.value()))
        set_camera_names(data, [row["name"].text().strip() for row in self.camera_rows])
        set_camera_list(data, "cameraSerialNo", [row["serial"].text().strip() for row in self.camera_rows])
        set_camera_list(data, "cameraSettings", [row["settings"].text().strip() for row in self.camera_rows])
        set_camera_list(data, "gpuID", [int(row["gpu"].value()) for row in self.camera_rows], coerce=int)
        set_if_present(data, "displayFrameRate", self._clean_number(self.display_rate.value()))
        set_if_present(data, "startTriggerController", bool(self.start_trigger.isChecked()))
        set_if_present(data, "waitForTriggerStart", bool(self.wait_for_trigger.isChecked()))
        set_if_present(data, "pulseFrequencyHz", self._clean_number(self.pulse_hz.value()))
        set_if_present(data, "pulsePalPort", self.pulse_port.text().strip())
        set_if_present(data, "enableGPIOTimestampLogging", bool(self.gpio_enabled.isChecked()))
        set_if_present(data, "gpioSerialPort", self.gpio_port.text().strip())
        set_if_present(data, "gpioLogFilename", self.gpio_log_name.text().strip() or "gpio_log.csv")
        set_if_present(data, "pulseTrainDurationSec", self._clean_number(self.rec_time.value()))

    def _clean_number(self, value):
        value = float(value)
        return int(value) if value.is_integer() else value

    def _validate_fields(self):
        if not self.config.data:
            self.validation_text.setPlainText("Load a config to validate it.")
            return
        self._collect_fields()
        messages = validate_config(self.config.data)
        self.validation_text.setPlainText(
            messages_to_text(messages)
            + "\n\nNote: this first draft uses PyYAML, so comments are not preserved when saving."
        )

    def _field_changed(self):
        if self._loading:
            return
        self._set_dirty(True)

    def _infinite_recording_changed(self):
        self._update_recording_time_enabled()
        self._field_changed()

    def _update_recording_time_enabled(self):
        self.rec_time.setEnabled(not self.infinite_recording.isChecked())

    def _num_cams_changed(self, value):
        self._rebuild_camera_rows(int(value))
        self._field_changed()

    def _rebuild_camera_rows(self, count):
        snapshot = self._camera_row_values()
        while self.camera_layout.count():
            item = self.camera_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.camera_rows = []
        for index in range(int(count)):
            row = self._create_camera_row(index)
            self.camera_rows.append(row)
            grid_row = index // 2
            grid_col = index % 2
            self.camera_layout.addWidget(row["group"], grid_row, grid_col)
        self.camera_layout.setColumnStretch(0, 1)
        self.camera_layout.setColumnStretch(1, 1)
        self._apply_camera_row_values(snapshot)

    def _create_camera_row(self, index):
        group = QGroupBox("Camera {}".format(index + 1))
        layout = QGridLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)

        name = QLineEdit()
        serial = QLineEdit()
        settings = QLineEdit()
        browse = QPushButton("...")
        browse.setFixedWidth(34)
        browse.clicked.connect(lambda _checked=False, field=settings: self._browse_camera_settings(field))
        gpu = QSpinBox()
        gpu.setRange(-1, 8)
        gpu.setToolTip("-1 uses CPU encoding. 0 or higher selects a GPU index.")

        layout.addWidget(QLabel("Name"), 0, 0)
        layout.addWidget(name, 0, 1)
        layout.addWidget(QLabel("GPU"), 0, 2)
        layout.addWidget(gpu, 0, 3)
        layout.addWidget(QLabel("Serial"), 1, 0)
        layout.addWidget(serial, 1, 1, 1, 3)
        layout.addWidget(QLabel("PFS"), 2, 0)
        layout.addWidget(settings, 2, 1, 1, 2)
        layout.addWidget(browse, 2, 3)

        self._connect_dirty_signals([name, serial, settings, gpu])
        return {
            "group": group,
            "name": name,
            "serial": serial,
            "settings": settings,
            "gpu": gpu,
        }

    def _camera_row_values(self):
        return [
            {
                "name": row["name"].text().strip(),
                "serial": row["serial"].text().strip(),
                "settings": row["settings"].text().strip(),
                "gpu": int(row["gpu"].value()),
            }
            for row in self.camera_rows
        ]

    def _apply_camera_row_values(self, rows):
        for index, row in enumerate(self.camera_rows):
            row_data = rows[index] if index < len(rows) else {}
            row["name"].setText(row_data.get("name", ""))
            row["serial"].setText(row_data.get("serial", ""))
            row["settings"].setText(row_data.get("settings", ""))
            row["gpu"].setValue(int(row_data.get("gpu", 0)))

    def _populate_camera_rows(self, data):
        names = camera_names(data)
        serials = camera_serials(data)
        settings_paths = camera_settings_paths(data)
        gpu_ids = camera_gpu_ids(data)
        for index, row in enumerate(self.camera_rows):
            row["name"].setText(names[index] if index < len(names) else "Camera{}".format(index + 1))
            row["serial"].setText(serials[index] if index < len(serials) else "")
            row["settings"].setText(settings_paths[index] if index < len(settings_paths) else "")
            row["gpu"].setValue(gpu_ids[index] if index < len(gpu_ids) else 0)

    def _browse_camera_settings(self, field):
        start = str(Path(field.text()).expanduser().parent) if field.text().strip() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select camera .pfs file", start, "PFS files (*.pfs);;All files (*)")
        if path:
            field.setText(path)

    def _set_dirty(self, dirty):
        self._dirty = bool(dirty)
        if self.config.path:
            label = "Unsaved changes" if dirty else "Saved"
        else:
            label = "No config loaded"
        self.dirty_label.setText(label)
        self.dirtyChanged.emit(self._dirty)
