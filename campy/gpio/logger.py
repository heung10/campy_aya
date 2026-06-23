"""
Launch and manage a standalone GPIO logging helper process.
"""

import os
import subprocess
import sys
import time


def _gpio_enabled(params):
	return params.get("enableGPIOTimestampLogging", False)


def _log_path(params):
	return os.path.join(params["saveFolder"], params["gpioLogFilename"])

def _stop_path(log_path):
	return os.path.splitext(log_path)[0] + "_stop.flag"


def _ensure_parent_dir(path):
	parent_dir = os.path.dirname(path)
	if parent_dir and not os.path.isdir(parent_dir):
		os.makedirs(parent_dir)
		print("Made directory {}.".format(parent_dir), flush=True)


def StartLogging(systems, params):
	if not _gpio_enabled(params):
		return systems

	log_path = _log_path(params)
	stop_path = _stop_path(log_path)
	_ensure_parent_dir(log_path)

	if os.path.exists(stop_path):
		os.remove(stop_path)

	cmd = [
		sys.executable,
		"-m",
		"campy.gpio.logger_worker",
		"--port",
		str(params["gpioSerialPort"]),
		"--baud",
		str(params["gpioBaudRate"]),
		"--log",
		log_path,
		"--stop",
		stop_path,
	]

	creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	proc = subprocess.Popen(cmd, creationflags=creationflags)

	systems["gpio_logger"] = {
		"process": proc,
		"log_path": log_path,
		"stop_path": stop_path,
	}

	print(
		"GPIO logger helper started on {} and writing to {}.".format(
			params["gpioSerialPort"],
			log_path,
		),
		flush=True,
	)

	return systems


def StopLogging(systems):
	logger_state = systems.get("gpio_logger")
	if not logger_state:
		return

	print("Stopping GPIO logger...", flush=True)
	with open(logger_state["stop_path"], "w", encoding="utf-8") as f:
		f.write("stop\n")

	proc = logger_state["process"]
	try:
		proc.wait(timeout=5.0)
	except Exception:
		try:
			proc.terminate()
		except Exception:
			pass

	if os.path.exists(logger_state["stop_path"]):
		try:
			os.remove(logger_state["stop_path"])
		except Exception:
			pass

	print("GPIO log saved to {}.".format(logger_state["log_path"]), flush=True)
	systems["gpio_logger"] = None
