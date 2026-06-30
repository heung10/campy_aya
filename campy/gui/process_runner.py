"""
Launch and control the existing campy acquisition command from the GUI.
"""

from __future__ import print_function

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal
import yaml

from .config_model import PROJECT_ROOT


class AcquisitionRunner(QObject):
    outputLine = pyqtSignal(str)
    stateChanged = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, parent=None):
        super(AcquisitionRunner, self).__init__(parent)
        self._process = None
        self._reader_thread = None
        self._wait_thread = None
        self._runtime_config_path = None
        self.preview_folder = None
        self._stop_file_path = None
        self._suppressed_gpio_lines = 0
        self._total_gpio_lines = 0
        self._last_gpio_summary = 0.0
        self.last_command = []
        self.state = "idle"

    def is_running(self):
        return self._process is not None and self._process.poll() is None

    def prepare(self, config_path):
        if self.is_running():
            raise RuntimeError("Acquisition is already running.")

        config_path = self._make_runtime_config(config_path)
        if getattr(sys, "frozen", False):
            self.last_command = [sys.executable, "--acquire", config_path]
        else:
            code = "from campy.campy import Main; Main()"
            self.last_command = [sys.executable, "-c", code, config_path]

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        self._process = subprocess.Popen(
            self.last_command,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self._set_state("running")
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()
        self._wait_thread = threading.Thread(target=self._wait_for_exit, daemon=True)
        self._wait_thread.start()

    def start_recording(self):
        if not self.is_running() or self._process.stdin is None:
            return
        try:
            self._process.stdin.write("\n")
            self._process.stdin.flush()
            self.outputLine.emit("[GUI] Sent start command to acquisition process.")
        except Exception as exc:
            self.outputLine.emit("[GUI] Could not send start command: {}".format(exc))

    def request_stop(self):
        if not self.is_running():
            return
        self._set_state("stopping")
        self.outputLine.emit("[GUI] Requesting graceful stop...")
        if self._stop_file_path:
            try:
                Path(self._stop_file_path).write_text("stop\n", encoding="utf-8")
                self.outputLine.emit("[GUI] Wrote graceful stop request file.")
            except Exception as exc:
                self.outputLine.emit("[GUI] Could not write stop request file: {}".format(exc))

        timer = threading.Timer(20.0, self._interrupt_if_running)
        timer.daemon = True
        timer.start()

    def _interrupt_if_running(self):
        if not self.is_running():
            return
        self.outputLine.emit("[GUI] Graceful stop is still pending; sending interrupt.")
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                os.kill(self._process.pid, signal.CTRL_BREAK_EVENT)
            else:
                self._process.send_signal(signal.SIGINT)
        except Exception as exc:
            self.outputLine.emit("[GUI] Graceful stop failed, terminating: {}".format(exc))
            self._terminate()
            return

        timer = threading.Timer(12.0, self._terminate_if_running)
        timer.daemon = True
        timer.start()

    def _read_output(self):
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                line = line.rstrip()
                if self._is_noisy_gpio_line(line):
                    self._summarize_gpio_line()
                    continue
                self.outputLine.emit(line)
        except Exception as exc:
            self.outputLine.emit("[GUI] Output reader stopped: {}".format(exc))

    def _wait_for_exit(self):
        process = self._process
        if process is None:
            return
        code = process.wait()
        self._process = None
        self._emit_gpio_summary(force=True)
        self._cleanup_runtime_config()
        self._set_state("idle")
        self.finished.emit(int(code) if code is not None else -1)

    def _terminate_if_running(self):
        if self.is_running():
            self.outputLine.emit("[GUI] Acquisition did not exit after stop request; terminating process.")
            self._terminate()

    def _terminate(self):
        if not self.is_running():
            return
        try:
            self._process.terminate()
        except Exception:
            pass

    def _set_state(self, state):
        self.state = state
        self.stateChanged.emit(state)

    def _make_runtime_config(self, config_path):
        source_path = Path(config_path).expanduser().resolve()
        with source_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        if not isinstance(data, dict):
            raise ValueError("Config file must contain a YAML mapping.")

        # GUI owns display inside the main window. Disable legacy matplotlib
        # preview windows for GUI-launched acquisitions.
        original_preview_rate = float(data.get("displayFrameRate", 0) or 0)
        preview_rate = original_preview_rate if original_preview_rate > 0 else 5
        data["displayFrameRate"] = 0
        data["waitForTriggerStart"] = True
        data["guiPreviewEnabled"] = True
        data["guiPreviewFrameRate"] = min(max(preview_rate, 1), 10)
        self.preview_folder = tempfile.mkdtemp(prefix="campy_gui_preview_")
        data["guiPreviewFolder"] = self.preview_folder
        stop_handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".flag",
            prefix="campy_gui_stop_",
            delete=True,
        )
        self._stop_file_path = stop_handle.name
        stop_handle.close()
        try:
            Path(self._stop_file_path).unlink()
        except Exception:
            pass
        data["guiStopFile"] = self._stop_file_path

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            prefix="campy_gui_runtime_",
            delete=False,
            encoding="utf-8",
        )
        with handle:
            yaml.safe_dump(data, handle, sort_keys=False, default_flow_style=False)
        self._runtime_config_path = handle.name
        self.outputLine.emit(
            "[GUI] Runtime config created with matplotlib preview off and Qt preview on."
        )
        return self._runtime_config_path

    def _cleanup_runtime_config(self):
        if not self._runtime_config_path:
            return
        try:
            Path(self._runtime_config_path).unlink()
        except Exception:
            pass
        self._runtime_config_path = None
        if self._stop_file_path:
            try:
                Path(self._stop_file_path).unlink()
            except Exception:
                pass
        self._stop_file_path = None

    def _is_noisy_gpio_line(self, line):
        return line.startswith("Received GPIO signal") or line.startswith("Received Signal:")

    def _summarize_gpio_line(self):
        self._suppressed_gpio_lines += 1
        self._total_gpio_lines += 1
        now = time.time()
        if now - self._last_gpio_summary >= 2.0:
            self._emit_gpio_summary()

    def _emit_gpio_summary(self, force=False):
        if self._suppressed_gpio_lines <= 0:
            return
        now = time.time()
        if not force and now - self._last_gpio_summary < 2.0:
            return
        self.outputLine.emit(
            "[GUI] GPIO events received: {} total, {} recent lines hidden to keep GUI responsive.".format(
                self._total_gpio_lines,
                self._suppressed_gpio_lines,
            )
        )
        self._suppressed_gpio_lines = 0
        self._last_gpio_summary = now
