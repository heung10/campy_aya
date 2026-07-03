"""
Launch and manage a standalone GPIO logging helper process.
"""

import csv
import os
import subprocess
import sys
import time
from pathlib import Path

import serial


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


def _read_gpio_rows(log_path):
	with open(log_path, "r", newline="", encoding="utf-8") as handle:
		reader = csv.DictReader(handle)
		rows = list(reader)
		fieldnames = list(reader.fieldnames or ["hostTimestampIso", "hostTimestampEpochSec", "gpioValue"])
	return fieldnames, rows


def _filter_duplicate_rows(rows, min_interval_ms):
	accepted = []
	rejected = []
	threshold = float(min_interval_ms) / 1000.0
	last_time = None
	for row in rows:
		try:
			timestamp = float(row["hostTimestampEpochSec"])
		except Exception:
			accepted.append(row)
			continue
		if last_time is None or timestamp - last_time >= threshold:
			accepted.append(row)
			last_time = timestamp
		else:
			rejected.append(row)
	return accepted, rejected


def CleanLoggedFile(params, min_interval_ms=1.0):
	if not _gpio_enabled(params):
		return {"cleaned": False, "removed": 0, "kept": 0, "log_path": None}

	log_path = Path(_log_path(params))
	if not log_path.exists():
		return {"cleaned": False, "removed": 0, "kept": 0, "log_path": str(log_path)}

	fieldnames, rows = _read_gpio_rows(str(log_path))
	filtered_rows, rejected_rows = _filter_duplicate_rows(rows, min_interval_ms)

	with log_path.open("w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(filtered_rows)

	return {
		"cleaned": True,
		"removed": len(rejected_rows),
		"kept": len(filtered_rows),
		"log_path": str(log_path),
		"threshold_ms": float(min_interval_ms),
	}


def CheckConnection(params):
	if not _gpio_enabled(params):
		return True, "disabled"

	port = str(params["gpioSerialPort"])
	baud = int(params["gpioBaudRate"])
	ser = serial.Serial(port, baud, timeout=0)
	try:
		return True, "connected to {} at {} baud".format(port, baud)
	finally:
		try:
			ser.close()
		except Exception:
			pass


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
