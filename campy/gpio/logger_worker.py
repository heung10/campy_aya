"""
Standalone Neurologger-compatible GPIO logging worker.
"""

import argparse
import csv
import os
import time
from datetime import datetime

import serial


PACKET_START = b"\x3c"
PACKET_START_INT = PACKET_START[0]
PACKET_END = 0x3E
EVENT_MARKER = 0x83


def parse_args():
	parser = argparse.ArgumentParser(description="GPIO logger worker")
	parser.add_argument("--port", required=True)
	parser.add_argument("--baud", required=True, type=int)
	parser.add_argument("--log", required=True)
	parser.add_argument("--stop", required=True)
	return parser.parse_args()


def ensure_parent_dir(path):
	parent_dir = os.path.dirname(path)
	if parent_dir and not os.path.isdir(parent_dir):
		os.makedirs(parent_dir)


def write_header_if_needed(log_path):
	if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
		return

	with open(log_path, "w", newline="", encoding="utf-8") as f:
		w = csv.writer(f)
		w.writerow(["hostTimestampIso", "hostTimestampEpochSec", "gpioValue"])

def should_stop(stop_path):
	return os.path.exists(stop_path)


def main():
	args = parse_args()
	ensure_parent_dir(args.log)
	write_header_if_needed(args.log)
	ser = serial.Serial(args.port, args.baud, timeout=0)

	try:
		with open(args.log, "a", newline="", encoding="utf-8") as f:
			w = csv.writer(f)
			pending_start = False

			while not should_stop(args.stop):
				if not pending_start:
					start_bytes = ser.read_until(PACKET_START)
					if should_stop(args.stop):
						break

					if not start_bytes or start_bytes[-1:] != PACKET_START:
						time.sleep(0.01)
						continue

				while ser.in_waiting < 4 and not should_stop(args.stop):
					time.sleep(0.01)

				if should_stop(args.stop):
					break

				data = ser.read(4)
				pending_start = False
				if len(data) < 4:
					continue

				current_time = datetime.now()
				gpio_value = None

				# Original Neurologger-style expectation:
				#   <start> ? 0x83 <value> 0x3e
				if data[3] == PACKET_END and data[1] == EVENT_MARKER:
					gpio_value = data[2]
				# Observed on the integrated run:
				#   after consuming 0x3c, the next 4 bytes arrive as
				#   0x83 <value> 0x3e 0x3c
				elif data[0] == EVENT_MARKER and data[2] == PACKET_END:
					gpio_value = data[1]
					if data[3] == PACKET_START_INT:
						# Preserve the next packet's start marker so we do not
						# skip every other event on the next loop iteration.
						pending_start = True
				else:
					continue

				w.writerow([
					current_time.isoformat(timespec="microseconds"),
					"{:.6f}".format(current_time.timestamp()),
					gpio_value,
				])
				f.flush()

				print(
					"Received GPIO signal {} at {}.".format(
						gpio_value,
						current_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
					),
					flush=True,
				)
	finally:
		try:
			ser.close()
		except Exception:
			pass


if __name__ == "__main__":
	main()
