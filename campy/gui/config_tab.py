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
    camera_names,
    get_value,
    load_config,
    messages_to_text,
    save_config,
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

        path_row = QHBoxLayout()
        self.config_path = QLineEdit()
        self.config_path.setPlaceholderText("Select a campy .yaml config")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_config)
        load = QPushButton("Load")
        load.clicked.connect(self._load_clicked)
        path_row.addWidget(QLabel("Config"))
        path_row.addWidget(self.config_path, 1)
        path_row.addWidget(browse)
        path_row.addWidget(load)
        layout.addLayout(path_row)

        content = QHBoxLayout()
        content.addWidget(self._recording_group(), 1)
        content.addWidget(self._hardware_group(), 1)
        layout.addLayout(content)

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
        self.frame_rate = self._double_spin(0.001, 10000, 3, " Hz")
        self.num_cams = QSpinBox()
        self.num_cams.setRange(1, 6)
        self.camera_names = QLineEdit()
        self.display_rate = self._double_spin(0, 120, 2, " Hz")

        form.addRow("saveFolder", folder_row)
        form.addRow("videoFilename", self.video_filename)
        form.addRow("recording time", self.rec_time)
        form.addRow("frame rate", self.frame_rate)
        form.addRow("num cameras", self.num_cams)
        form.addRow("camera names", self.camera_names)
        form.addRow("preview rate", self.display_rate)
        self._connect_dirty_signals([
            self.save_folder,
            self.video_filename,
            self.rec_time,
            self.frame_rate,
            self.num_cams,
            self.camera_names,
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

    def _browse_save_folder(self):
        start = self.save_folder.text() or ""
        path = QFileDialog.getExistingDirectory(self, "Select save folder", start)
        if path:
            self.save_folder.setText(path)

    def _load_clicked(self):
        if not self.config_path.text().strip():
            self.validation_text.setPlainText("Choose a config file first.")
            return
        try:
            self.config = load_config(self.config_path.text().strip())
            self.config_path.setText(str(self.config.path))
            self._populate_fields()
            self._set_dirty(False)
            self._validate_fields()
            self.configLoaded.emit(self.config.data, str(self.config.path))
        except Exception as exc:
            self.validation_text.setPlainText("Could not load config:\n{}".format(exc))

    def _save_clicked(self):
        if not self.config.loaded:
            self.validation_text.setPlainText("Load a config before saving.")
            return
        self._collect_fields()
        try:
            path = save_config(self.config)
            self._set_dirty(False)
            self._validate_fields()
            self.configSaved.emit(self.config.data, str(path))
        except Exception as exc:
            self.validation_text.setPlainText("Could not save config:\n{}".format(exc))

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
        self.save_folder.setText(str(get_value(data, "saveFolder", get_value(data, "videoFolder", ""))))
        self.video_filename.setText(str(get_value(data, "videoFilename", "0.mp4")))
        self.rec_time.setValue(float(get_value(data, "recTimeInSec", 10)))
        self.frame_rate.setValue(float(get_value(data, "frameRate", 40)))
        self.num_cams.setValue(int(get_value(data, "numCams", 1)))
        self.camera_names.setText(", ".join(camera_names(data)))
        self.display_rate.setValue(float(get_value(data, "displayFrameRate", 0)))
        self.start_trigger.setChecked(bool(get_value(data, "startTriggerController", False)))
        self.wait_for_trigger.setChecked(bool(get_value(data, "waitForTriggerStart", False)))
        self.pulse_hz.setValue(float(get_value(data, "pulseFrequencyHz", get_value(data, "frameRate", 40))))
        self.pulse_port.setText(str(get_value(data, "pulsePalPort", "")))
        self.gpio_enabled.setChecked(bool(get_value(data, "enableGPIOTimestampLogging", False)))
        self.gpio_port.setText(str(get_value(data, "gpioSerialPort", "")))
        self.gpio_log_name.setText(str(get_value(data, "gpioLogFilename", "gpio_log.csv")))
        self._loading = False

    def _collect_fields(self):
        data = self.config.data
        set_if_present(data, "saveFolder", self.save_folder.text().strip())
        set_if_present(data, "videoFilename", self.video_filename.text().strip())
        set_if_present(data, "recTimeInSec", self._clean_number(self.rec_time.value()))
        set_if_present(data, "frameRate", self._clean_number(self.frame_rate.value()))
        set_if_present(data, "numCams", int(self.num_cams.value()))
        set_camera_names(data, self.camera_names.text())
        set_if_present(data, "displayFrameRate", self._clean_number(self.display_rate.value()))
        set_if_present(data, "startTriggerController", bool(self.start_trigger.isChecked()))
        set_if_present(data, "waitForTriggerStart", bool(self.wait_for_trigger.isChecked()))
        set_if_present(data, "pulseFrequencyHz", self._clean_number(self.pulse_hz.value()))
        set_if_present(data, "pulsePalPort", self.pulse_port.text().strip())
        set_if_present(data, "enableGPIOTimestampLogging", bool(self.gpio_enabled.isChecked()))
        set_if_present(data, "gpioSerialPort", self.gpio_port.text().strip())
        set_if_present(data, "gpioLogFilename", self.gpio_log_name.text().strip() or "gpio_log.csv")

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

    def _set_dirty(self, dirty):
        self._dirty = bool(dirty)
        if self.config.path:
            label = "Unsaved changes" if dirty else "Saved"
        else:
            label = "No config loaded"
        self.dirty_label.setText(label)
        self.dirtyChanged.emit(self._dirty)
