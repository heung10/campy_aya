"""Evaluate a campy session folder against its GPIO timestamp log."""

from __future__ import print_function

import argparse
import csv
import os
from collections import Counter


def read_csv_dicts(path):
	with open(path, newline="", encoding="utf-8") as f:
		return list(csv.DictReader(f))


def find_camera_folders(session_folder):
	camera_folders = []
	for name in sorted(os.listdir(session_folder)):
		path = os.path.join(session_folder, name)
		if not os.path.isdir(path):
			continue
		if os.path.exists(os.path.join(path, "frame_metadata.csv")):
			camera_folders.append(path)
	return camera_folders


def filter_gpio_duplicates(gpio_rows, min_interval_ms):
	accepted = []
	rejected = []
	threshold = float(min_interval_ms) / 1000.0
	for raw_idx, row in enumerate(gpio_rows):
		t = float(row["hostTimestampEpochSec"])
		if not accepted or t - accepted[-1][1] >= threshold:
			accepted.append((raw_idx, t, row))
		else:
			rejected.append((raw_idx, t, (t - accepted[-1][1]) * 1000.0, row))
	return accepted, rejected


def nearest_camera_matches(frame_rows, filtered_gpio):
	if not frame_rows or not filtered_gpio:
		return [], []

	frame_times = [float(row["hostDateTimeEpochSec"]) for row in frame_rows]
	frame_numbers = [int(row["savedFrameNumber"]) for row in frame_rows]
	matches = []
	frame_idx = 0
	for gpio_idx, (raw_idx, gpio_time, _) in enumerate(filtered_gpio, 1):
		while (
			frame_idx + 1 < len(frame_times)
			and abs(frame_times[frame_idx + 1] - gpio_time) <= abs(frame_times[frame_idx] - gpio_time)
		):
			frame_idx += 1
		matches.append((
			gpio_idx,
			raw_idx,
			frame_numbers[frame_idx],
			(gpio_time - frame_times[frame_idx]) * 1000.0,
		))

	matched_frames = set(match[2] for match in matches)
	missing_frames = [number for number in frame_numbers if number not in matched_frames]
	return matches, missing_frames


def summarize_camera(camera_folder, gpio_rows, filtered_gpio, rejected):
	frame_path = os.path.join(camera_folder, "frame_metadata.csv")
	writer_path = os.path.join(camera_folder, "writer_stats.csv")
	camera_name = os.path.basename(camera_folder)
	frame_rows = read_csv_dicts(frame_path)

	print("\nCamera: {}".format(camera_name))
	print("  frame_metadata rows: {}".format(len(frame_rows)))
	if os.path.exists(writer_path):
		writer_rows = read_csv_dicts(writer_path)
		if writer_rows:
			print("  writer frames: {}".format(writer_rows[0].get("framesWritten", "unknown")))

	print("  raw GPIO events: {}".format(len(gpio_rows)))
	print("  duplicate GPIO events removed: {}".format(len(rejected)))
	print("  filtered GPIO events: {}".format(len(filtered_gpio)))
	print("  filtered GPIO - camera frames: {}".format(len(filtered_gpio) - len(frame_rows)))

	if not frame_rows or not filtered_gpio:
		return

	if "hostDateTimeEpochSec" not in frame_rows[0]:
		print("  camera datetime columns missing; rerun with newer campy metadata.")
		return

	camera_first = float(frame_rows[0]["hostDateTimeEpochSec"])
	camera_last = float(frame_rows[-1]["hostDateTimeEpochSec"])
	gpio_first = filtered_gpio[0][1]
	gpio_last = filtered_gpio[-1][1]

	print("  camera first: {}".format(frame_rows[0].get("hostDateTimeIso", camera_first)))
	print("  GPIO first:   {}".format(filtered_gpio[0][2].get("hostTimestampIso", gpio_first)))
	print("  first offset GPIO-camera: {:.3f} ms".format((gpio_first - camera_first) * 1000.0))
	print("  camera last:  {}".format(frame_rows[-1].get("hostDateTimeIso", camera_last)))
	print("  GPIO last:    {}".format(filtered_gpio[-1][2].get("hostTimestampIso", gpio_last)))
	print("  last offset GPIO-camera: {:.3f} ms".format((gpio_last - camera_last) * 1000.0))

	matches, missing_frames = nearest_camera_matches(frame_rows, filtered_gpio)
	print("  camera frames without nearest GPIO assignment: {}".format(len(missing_frames)))
	if missing_frames:
		print("  missing frame numbers, first: {}".format(missing_frames[:20]))
		print("  missing frame numbers, last:  {}".format(missing_frames[-20:]))

	matched_counts = Counter(match[2] for match in matches)
	multiple = [(frame, count) for frame, count in sorted(matched_counts.items()) if count > 1]
	print("  camera frames with multiple filtered GPIO assignments: {}".format(len(multiple)))
	if multiple:
		print("  multiple-assigned frames, first: {}".format(multiple[:20]))


def main(argv=None):
	parser = argparse.ArgumentParser(description="Evaluate a campy session folder.")
	parser.add_argument("session_folder", help="Folder containing gpio_log.csv and camera subfolders.")
	parser.add_argument(
		"--duplicate-threshold-ms",
		type=float,
		default=1.0,
		help="Minimum interval for keeping GPIO events. Events closer than this are counted as duplicates.",
	)
	args = parser.parse_args(argv)

	session_folder = os.path.abspath(args.session_folder)
	gpio_path = os.path.join(session_folder, "gpio_log.csv")
	if not os.path.exists(gpio_path):
		raise FileNotFoundError("Missing gpio_log.csv: {}".format(gpio_path))

	gpio_rows = read_csv_dicts(gpio_path)
	filtered_gpio, rejected = filter_gpio_duplicates(gpio_rows, args.duplicate_threshold_ms)
	camera_folders = find_camera_folders(session_folder)

	print("Session: {}".format(session_folder))
	print("GPIO values: {}".format(dict(Counter(row.get("gpioValue", "") for row in gpio_rows))))
	print("Duplicate threshold: {} ms".format(args.duplicate_threshold_ms))

	if not camera_folders:
		print("No camera folders with frame_metadata.csv were found.")
		return 1

	for camera_folder in camera_folders:
		summarize_camera(camera_folder, gpio_rows, filtered_gpio, rejected)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
