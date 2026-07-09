"""
Main window for the campy GUI.
"""

from __future__ import print_function

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from campy.gpio import logger as gpio_logger

from .config_tab import ConfigTab
from .live_tab import LiveTab
from .preview_tab import PreviewTab
from .process_runner import AcquisitionRunner
from .config_model import auto_camera_video_filenames, camera_names, get_value, resolved_save_folder
from .style import APP_STYLE


class MainWindow(QMainWindow):
    LAST_CONFIG_KEY = "gui/last_config_path"

    def __init__(self, initial_config=None, parent=None):
        super(MainWindow, self).__init__(parent)
        self.setWindowTitle("campy GUI")
        self.resize(1440, 940)
        self.setStyleSheet(APP_STYLE)

        self.runner = AcquisitionRunner(self)
        self.config_tab = ConfigTab()
        self.live_tab = LiveTab()
        self.preview_tab = PreviewTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.config_tab, "Config")
        self.tabs.addTab(self.live_tab, "Recording")
        self.tabs.addTab(self.preview_tab, "Preview")
        self.setCentralWidget(self.tabs)
        self._last_tab_index = 0
        self._session_complete = False

        self.config_tab.configLoaded.connect(self._config_loaded)
        self.config_tab.configSaved.connect(self._config_saved)
        self.live_tab.readyRequested.connect(self._ready_requested)
        self.live_tab.startRequested.connect(self._start_recording_requested)
        self.live_tab.stopRequested.connect(self.runner.request_stop)
        self.live_tab.exposureRequested.connect(self._exposure_requested)
        self.preview_tab.readyRequested.connect(self._ready_requested)
        self.preview_tab.startRequested.connect(self._start_recording_requested)
        self.preview_tab.stopRequested.connect(self.runner.request_stop)
        self.runner.outputLine.connect(self._process_output)
        self.runner.preflightChecked.connect(self.live_tab.set_preflight_results)
        self.runner.stateChanged.connect(self.live_tab.set_process_state)
        self.runner.stateChanged.connect(self.preview_tab.set_process_state)
        self.runner.preparationSucceeded.connect(self._preparation_succeeded)
        self.runner.preparationFailed.connect(self._preparation_failed)
        self.runner.finished.connect(self._process_finished)
        self.tabs.currentChanged.connect(self._tab_changed)

        self.statusBar().showMessage("Load a campy YAML config to begin.")
        if initial_config:
            self.config_tab.config_path.setText(str(initial_config))
            self.config_tab.load_current_config()
        else:
            self._load_last_config_if_available()

    def _config_loaded(self, data, path):
        self.live_tab.set_config(data, path)
        self.preview_tab.set_config(data, path)
        self._save_last_config_path(path)
        self.statusBar().showMessage("Loaded config: {}".format(path), 5000)

    def _config_saved(self, data, path):
        self.live_tab.set_config(data, path)
        self.preview_tab.set_config(data, path)
        self._save_last_config_path(path)
        self.statusBar().showMessage("Saved config: {}".format(path), 5000)

    def _ready_requested(self):
        if self._session_complete:
            self.statusBar().showMessage("This GUI session is finished. Close and reopen campy-gui for the next recording.", 8000)
            return
        config_path = self.config_tab.current_path()
        if not config_path:
            self.statusBar().showMessage("Load and save a config before preparing acquisition.", 6000)
            self.tabs.setCurrentWidget(self.config_tab)
            return
        if self.config_tab.is_dirty():
            self.statusBar().showMessage("Save YAML before preparing so acquisition uses the edited values.", 8000)
            self.tabs.setCurrentWidget(self.config_tab)
            return
        prepared_at = datetime.now()
        existing_outputs = self._existing_output_paths(prepared_at=prepared_at)
        if existing_outputs and not self._confirm_overwrite(existing_outputs):
            self.statusBar().showMessage("Recording preparation canceled after overwrite warning.", 6000)
            return
        try:
            self.live_tab.log.clear()
            self.live_tab.append_log("[GUI] Preparing acquisition with {}".format(config_path))
            self.statusBar().showMessage("Preparing acquisition. The window will stay responsive during hardware checks.", 8000)
            self.runner.prepare_async(config_path, prepared_at=prepared_at)
        except Exception as exc:
            self.statusBar().showMessage("Could not prepare acquisition: {}".format(exc), 8000)
            self.live_tab.append_log("[GUI] Could not prepare acquisition: {}".format(exc))

    def _preparation_succeeded(self, preview_folder):
        self.preview_tab.set_preview_folder(preview_folder)
        self.tabs.setCurrentWidget(self.live_tab)
        self.statusBar().showMessage("Preparing cameras. Wait for the ready message, then click Start Recording.", 8000)

    def _preparation_failed(self, message):
        self.statusBar().showMessage("Could not prepare acquisition: {}".format(message), 8000)
        self.live_tab.append_log("[GUI] Could not prepare acquisition: {}".format(message))

    def _start_recording_requested(self):
        self.runner.start_recording()
        self.live_tab.set_recording_started()
        self.preview_tab.set_recording_started()
        self.statusBar().showMessage("Recording start command sent.", 5000)

    def _exposure_requested(self, camera_name, exposure_time_us):
        try:
            self._validate_exposure_request(exposure_time_us)
            self.runner.apply_exposure_time(camera_name, exposure_time_us)
            self.statusBar().showMessage(
                "Requested {} exposure {:.1f} us.".format(camera_name, exposure_time_us),
                5000,
            )
        except Exception as exc:
            self.statusBar().showMessage("Could not apply exposure: {}".format(exc), 8000)
            self.live_tab.append_log("[GUI] Could not apply exposure: {}".format(exc))

    def _process_output(self, line):
        self.live_tab.append_log(line)
        self.preview_tab.update_runtime_from_line(line)
        if "Press Enter to start" in line or "All cameras are ready" in line:
            self.live_tab.set_ready_to_start(True)
            self.preview_tab.set_ready_to_start(True)
            self.statusBar().showMessage("Cameras ready. Click 'Start Recording' in the Live tab.", 10000)

    def _process_finished(self, return_code):
        self._postprocess_gpio_log()
        self._session_complete = True
        self.live_tab.set_session_complete()
        self.preview_tab.set_session_complete()
        self.tabs.setTabEnabled(0, False)
        self.tabs.setTabEnabled(2, False)
        self.tabs.setCurrentWidget(self.live_tab)
        self.live_tab.refresh_status()
        self.statusBar().showMessage(
            "Acquisition finished with code {}. Close and reopen campy-gui before the next recording.".format(return_code),
            12000,
        )
        self.live_tab.append_log("[GUI] Acquisition finished with code {}.".format(return_code))
        self.live_tab.append_log("[GUI] This GUI session is now locked. Close and reopen campy-gui for the next recording.")

    def _tab_changed(self, index):
        if self._last_tab_index == 0 and index == 1 and self.config_tab.is_dirty():
            action = self._prompt_save_config_changes()
            if action == QMessageBox.Cancel:
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(self._last_tab_index)
                self.tabs.blockSignals(False)
                return
            if action == QMessageBox.Save:
                if not self.config_tab.save_current_config():
                    self.tabs.blockSignals(True)
                    self.tabs.setCurrentIndex(self._last_tab_index)
                    self.tabs.blockSignals(False)
                    return
        self._last_tab_index = index

    def _prompt_save_config_changes(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Unsaved YAML Changes")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText("The config YAML has unsaved changes.")
        dialog.setInformativeText("Save changes before moving to the Recording tab?")
        dialog.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        dialog.setDefaultButton(QMessageBox.Save)
        return dialog.exec_()

    def _postprocess_gpio_log(self):
        config_data = self.live_tab.config_data or {}
        if not get_value(config_data, "enableGPIOTimestampLogging", False):
            return

        threshold_ms = float(get_value(config_data, "gpioDuplicateThresholdMs", 1.0))
        try:
            result = gpio_logger.CleanLoggedFile(config_data, min_interval_ms=threshold_ms)
        except Exception as exc:
            self.live_tab.append_log("[GUI] GPIO cleanup failed: {}".format(exc))
            return

        if not result.get("cleaned"):
            return

        self.live_tab.append_log(
            "[GUI] GPIO cleanup complete: kept {} events, removed {} ghost/duplicate events at {} ms threshold.".format(
                result.get("kept", 0),
                result.get("removed", 0),
                result.get("threshold_ms", threshold_ms),
            )
        )

    def _settings(self):
        return QSettings()

    def _save_last_config_path(self, path):
        if not path:
            return
        self._settings().setValue(self.LAST_CONFIG_KEY, str(path))

    def _load_last_config_if_available(self):
        raw_path = self._settings().value(self.LAST_CONFIG_KEY, "", type=str)
        if not raw_path:
            return

        config_path = Path(raw_path).expanduser()
        if not config_path.exists():
            self.statusBar().showMessage("Last config file was not found: {}".format(raw_path), 6000)
            return

        self.config_tab.config_path.setText(str(config_path))
        if self.config_tab.load_current_config():
            self.statusBar().showMessage("Restored last config: {}".format(config_path), 5000)

    def _existing_output_paths(self, prepared_at=None):
        config_data = self.config_tab.config.data or {}
        if not config_data:
            return []

        save_folder = resolved_save_folder(config_data)
        video_names = auto_camera_video_filenames(config_data, now=prepared_at or datetime.now())
        existing = []
        for camera_name, video_name in zip(camera_names(config_data), video_names):
            video_path = save_folder / camera_name / video_name
            if video_path.exists():
                existing.append(video_path)

        if get_value(config_data, "enableGPIOTimestampLogging", False):
            gpio_path = save_folder / str(get_value(config_data, "gpioLogFilename", "gpio_log.csv"))
            if gpio_path.exists():
                existing.append(gpio_path)

        return existing

    def _confirm_overwrite(self, existing_paths):
        preview_lines = [str(path) for path in existing_paths[:8]]
        if len(existing_paths) > 8:
            preview_lines.append("... and {} more".format(len(existing_paths) - 8))

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Overwrite Existing Files")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText("Existing video or log files were found in the save folder.")
        dialog.setInformativeText("Do you want to overwrite them?\n\n{}".format("\n".join(preview_lines)))
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec_() == QMessageBox.Yes

    def _validate_exposure_request(self, exposure_time_us):
        frame_rate = float(get_value(self.live_tab.config_data or {}, "frameRate", 0) or 0)
        if frame_rate <= 0:
            return
        frame_period_us = 1e6 / frame_rate
        if float(exposure_time_us) >= frame_period_us:
            raise RuntimeError(
                "Exposure time {:.1f} us must be shorter than one frame period at {:.3f} Hz ({:.1f} us).".format(
                    float(exposure_time_us),
                    frame_rate,
                    frame_period_us,
                )
            )
