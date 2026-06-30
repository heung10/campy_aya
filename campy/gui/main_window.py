"""
Main window for the campy GUI.
"""

from __future__ import print_function

from PyQt5.QtWidgets import QMainWindow, QTabWidget

from .config_tab import ConfigTab
from .live_tab import LiveTab
from .preview_tab import PreviewTab
from .process_runner import AcquisitionRunner
from .style import APP_STYLE


class MainWindow(QMainWindow):
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

        self.config_tab.configLoaded.connect(self._config_loaded)
        self.config_tab.configSaved.connect(self._config_saved)
        self.live_tab.readyRequested.connect(self._ready_requested)
        self.live_tab.startRequested.connect(self._start_recording_requested)
        self.live_tab.stopRequested.connect(self.runner.request_stop)
        self.runner.outputLine.connect(self._process_output)
        self.runner.stateChanged.connect(self.live_tab.set_process_state)
        self.runner.finished.connect(self._process_finished)

        self.statusBar().showMessage("Load a campy YAML config to begin.")
        if initial_config:
            self.config_tab.config_path.setText(str(initial_config))
            self.config_tab._load_clicked()

    def _config_loaded(self, data, path):
        self.live_tab.set_config(data, path)
        self.preview_tab.set_config(data, path)
        self.statusBar().showMessage("Loaded config: {}".format(path), 5000)

    def _config_saved(self, data, path):
        self.live_tab.set_config(data, path)
        self.preview_tab.set_config(data, path)
        self.statusBar().showMessage("Saved config: {}".format(path), 5000)

    def _ready_requested(self):
        config_path = self.config_tab.current_path()
        if not config_path:
            self.statusBar().showMessage("Load and save a config before preparing acquisition.", 6000)
            self.tabs.setCurrentWidget(self.config_tab)
            return
        if self.config_tab.is_dirty():
            self.statusBar().showMessage("Save YAML before preparing so acquisition uses the edited values.", 8000)
            self.tabs.setCurrentWidget(self.config_tab)
            return
        try:
            self.live_tab.log.clear()
            self.runner.prepare(config_path)
            self.preview_tab.set_preview_folder(self.runner.preview_folder)
            self.tabs.setCurrentWidget(self.live_tab)
            self.statusBar().showMessage("Preparing cameras. Wait for the ready message, then click Start Recording.", 8000)
            self.live_tab.append_log("[GUI] Preparing acquisition with {}".format(config_path))
        except Exception as exc:
            self.statusBar().showMessage("Could not prepare acquisition: {}".format(exc), 8000)
            self.live_tab.append_log("[GUI] Could not prepare acquisition: {}".format(exc))

    def _start_recording_requested(self):
        self.runner.start_recording()
        self.live_tab.set_recording_started()
        self.statusBar().showMessage("Recording start command sent.", 5000)

    def _process_output(self, line):
        self.live_tab.append_log(line)
        if "Press Enter to start" in line or "All cameras are ready" in line:
            self.live_tab.set_ready_to_start(True)
            self.statusBar().showMessage("Cameras ready. Click 'Start Recording' in the Live tab.", 10000)

    def _process_finished(self, return_code):
        self.live_tab.refresh_status()
        self.statusBar().showMessage("Acquisition finished with code {}.".format(return_code), 8000)
        self.live_tab.append_log("[GUI] Acquisition finished with code {}.".format(return_code))
