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
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal
import yaml

from .config_model import PROJECT_ROOT, auto_camera_video_filenames
from campy.gpio import logger as gpio_logger
from campy.trigger import pulsepal as pulsepal_trigger


class AcquisitionRunner(QObject):
    outputLine = pyqtSignal(str)
    stateChanged = pyqtSignal(str)
    finished = pyqtSignal(int)
    preflightChecked = pyqtSignal(dict)
    preparationSucceeded = pyqtSignal(str)
    preparationFailed = pyqtSignal(str)

    def __init__(self, parent=None):
        super(AcquisitionRunner, self).__init__(parent)
        self._process = None
        self._reader_thread = None
        self._wait_thread = None
        self._prepare_thread = None
        self._runtime_config_path = None
        self.preview_folder = None
        self._stop_file_path = None
        self._camera_control_file_path = None
        self._suppressed_gpio_lines = 0
        self._total_gpio_lines = 0
        self._last_gpio_summary = 0.0
        self.last_command = []
        self.state = "idle"

    def is_running(self):
        return self._process is not None and self._process.poll() is None

    def is_preparing(self):
        return self._prepare_thread is not None and self._prepare_thread.is_alive()

    def prepare(self, config_path, prepared_at=None):
        if self.is_running():
            raise RuntimeError("Acquisition is already running.")

        config_data = self._load_config_data(config_path)
        preflight = self._run_preflight_checks(config_data)
        self.preflightChecked.emit(preflight)
        failures = [result for result in preflight.values() if not result.get("ok", False)]
        if failures:
            raise RuntimeError("; ".join(result["message"] for result in failures))

        config_path = self._make_runtime_config(config_path, prepared_at=prepared_at)
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

    def prepare_async(self, config_path, prepared_at=None):
        if self.is_running():
            raise RuntimeError("Acquisition is already running.")
        if self.is_preparing():
            raise RuntimeError("Acquisition preparation is already running.")

        self._set_state("preparing")
        self._prepare_thread = threading.Thread(
            target=self._prepare_worker,
            args=(config_path, prepared_at),
            daemon=True,
        )
        self._prepare_thread.start()

    def _prepare_worker(self, config_path, prepared_at):
        try:
            self.prepare(config_path, prepared_at=prepared_at)
            self.preparationSucceeded.emit(str(self.preview_folder or ""))
        except Exception as exc:
            if not self.is_running():
                self._set_state("idle")
            self.preparationFailed.emit(str(exc))
        finally:
            self._prepare_thread = None

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

    def apply_exposure_time(self, camera_name, exposure_time_us):
        if not self.is_running() or not self._camera_control_file_path:
            raise RuntimeError("Acquisition is not running.")

        payload = {}
        control_path = Path(self._camera_control_file_path)
        if control_path.exists():
            try:
                with control_path.open("r", encoding="utf-8") as handle:
                    payload = yaml.safe_load(handle) or {}
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}

        cameras = payload.get("cameras")
        if not isinstance(cameras, dict):
            cameras = {}
        cameras[str(camera_name)] = {
            "cameraExposureTimeInUs": float(exposure_time_us),
        }
        payload["cameras"] = cameras
        payload["updatedAtEpochSec"] = time.time()

        with open(self._camera_control_file_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, default_flow_style=False)
        self.outputLine.emit(
            "[GUI] Requested {} exposure time {:.1f} us.".format(str(camera_name), float(exposure_time_us))
        )

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

    def _load_config_data(self, config_path):
        source_path = Path(config_path).expanduser().resolve()
        with source_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError("Config file must contain a YAML mapping.")
        return data

    def _run_preflight_checks(self, data):
        results = {}

        trigger_enabled = bool(data.get("startTriggerController", False))
        trigger_controller = str(data.get("triggerController", "")).lower()
        if trigger_enabled and trigger_controller == "pulsepal":
            try:
                self.outputLine.emit("[GUI] Checking PulsePal connection...")
                ok, message = pulsepal_trigger.CheckConnection(data)
                results["Trigger"] = {"ok": bool(ok), "state": "Ready" if ok else "Disconnected", "message": message}
                self.outputLine.emit("[GUI] PulsePal preflight: {}.".format(message))
            except Exception as exc:
                message = "PulsePal port {} unavailable: {}".format(data.get("pulsePalPort", "-"), exc)
                results["Trigger"] = {"ok": False, "state": "Disconnected", "message": message}
                self.outputLine.emit("[GUI] PulsePal preflight failed: {}".format(message))
        elif trigger_enabled:
            message = "trigger controller {} not preflight-checked".format(data.get("triggerController", "-"))
            results["Trigger"] = {"ok": True, "state": "Ready", "message": message}
            self.outputLine.emit("[GUI] Trigger preflight skipped: {}.".format(message))
        else:
            results["Trigger"] = {"ok": True, "state": "Disabled", "message": "trigger disabled"}

        if bool(data.get("enableGPIOTimestampLogging", False)):
            try:
                self.outputLine.emit("[GUI] Checking GPIO connection...")
                ok, message = gpio_logger.CheckConnection(data)
                results["GPIO"] = {"ok": bool(ok), "state": "Ready" if ok else "Disconnected", "message": message}
                self.outputLine.emit("[GUI] GPIO preflight: {}.".format(message))
            except Exception as exc:
                message = "GPIO port {} unavailable: {}".format(data.get("gpioSerialPort", "-"), exc)
                results["GPIO"] = {"ok": False, "state": "Disconnected", "message": message}
                self.outputLine.emit("[GUI] GPIO preflight failed: {}".format(message))
        else:
            results["GPIO"] = {"ok": True, "state": "Disabled", "message": "GPIO logging disabled"}

        return results

    def _make_runtime_config(self, config_path, prepared_at=None):
        data = self._load_config_data(config_path)
        prepared_at = prepared_at or datetime.now()
        data["videoFilename"] = auto_camera_video_filenames(data, now=prepared_at)
        self.outputLine.emit(
            "[GUI] Prepared output filenames: {}.".format(", ".join(data["videoFilename"]))
        )

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
        control_handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            prefix="campy_gui_camera_control_",
            delete=False,
            encoding="utf-8",
        )
        with control_handle:
            control_handle.write("")
        self._camera_control_file_path = control_handle.name
        data["guiCameraControlFile"] = self._camera_control_file_path

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
        if self._camera_control_file_path:
            try:
                Path(self._camera_control_file_path).unlink()
            except Exception:
                pass
        self._camera_control_file_path = None

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
