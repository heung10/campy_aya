"""
Headless GPIO event logging for Neurologger interface boards.
"""

import csv
import logging
import os
import threading
import time
from datetime import datetime

import serial


PACKET_START = b"\x3c"
PACKET_END = 0x3E
EVENT_MARKER = 0x83


def _gpio_enabled(params):
	return params.get("enableGPIOTimestampLogging", False)


def _log_path(params):
	return os.path.join(params["saveFolder"], params["gpioLogFilename"])


def _ensure_parent_dir(path):
	parent_dir = os.path.dirname(path)
	if parent_dir and not os.path.isdir(parent_dir):
		os.makedirs(parent_dir)
		print("Made directory {}.".format(parent_dir), flush=True)


def _write_header_if_needed(log_path):
	if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
		return

	with open(log_path, "w", newline="", encoding="utf-8") as f:
		w = csv.writer(f)
		w.writerow(["hostTimestampIso", "hostTimestampEpochSec", "gpioValue"])


def _listen_loop(serial_conn, stop_event, log_path):
	with open(log_path, "a", newline="", encoding="utf-8") as f:
		w = csv.writer(f)
		while not stop_event.is_set():
			try:
				serial_conn.read_until(PACKET_START)
				if stop_event.is_set():
					break

				while serial_conn.in_waiting < 4 and not stop_event.is_set():
					time.sleep(0.01)

				if stop_event.is_set():
					break

				data = serial_conn.read(4)
				if len(data) < 4:
					continue

				if data[3] != PACKET_END or data[1] != EVENT_MARKER:
					continue

				now = datetime.now()
				w.writerow([now.isoformat(timespec="microseconds"), "{:.6f}".format(now.timestamp()), data[2]])
				f.flush()

				print(
					"Received GPIO signal {} at {}.".format(
						data[2],
						now.strftime("%Y-%m-%d %H:%M:%S.%f"),
					),
					flush=True,
				)
			except serial.SerialException as e:
				if not stop_event.is_set():
					logging.error("GPIO logger serial error: {}".format(e))
				break
			except Exception as e:
				if not stop_event.is_set():
					logging.error("GPIO logger error: {}".format(e))
				time.sleep(0.01)


def StartLogging(systems, params):
	if not _gpio_enabled(params):
		return systems

	log_path = _log_path(params)
	_ensure_parent_dir(log_path)
	_write_header_if_needed(log_path)

	serial_conn = serial.Serial(
		port=params["gpioSerialPort"],
		baudrate=params["gpioBaudRate"],
		timeout=params["gpioSerialTimeoutSec"],
	)
	stop_event = threading.Event()
	thread = threading.Thread(
		target=_listen_loop,
		args=(serial_conn, stop_event, log_path),
		daemon=True,
	)
	thread.start()

	systems["gpio_logger"] = {
		"serial": serial_conn,
		"stop_event": stop_event,
		"thread": thread,
		"log_path": log_path,
	}

	print(
		"GPIO logger started on {} and writing to {}.".format(
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
	logger_state["stop_event"].set()

	try:
		logger_state["serial"].close()
	except Exception:
		pass

	try:
		logger_state["thread"].join(timeout=2.0)
	except Exception:
		pass

	print("GPIO log saved to {}.".format(logger_state["log_path"]), flush=True)
	systems["gpio_logger"] = None
