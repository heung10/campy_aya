"""
Read saved campy output files into compact GUI status rows.
"""

from __future__ import print_function

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from .config_model import camera_names, get_value, resolved_save_folder


@dataclass
class StatusRow:
    device: str
    state: str
    count: str
    rate: str
    last_update: str
    notes: str


def collect_status(config_data, process_state):
    rows = []
    tiles = {}
    save_folder = resolved_save_folder(config_data)
    names = camera_names(config_data)
    frame_rate = float(get_value(config_data, "frameRate", 0) or 0)

    for index, name in enumerate(names[:6]):
        row, tile = _camera_status(name, save_folder, frame_rate, process_state)
        rows.append(row)
        tiles[index] = tile

    if get_value(config_data, "enableGPIOTimestampLogging", False):
        rows.append(_gpio_status(config_data, save_folder, process_state))

    rows.append(_pulsepal_status(config_data, process_state))
    return rows, tiles


def _camera_status(name, save_folder, expected_rate, process_state):
    camera_dir = save_folder / name
    frame_csv = camera_dir / "frame_metadata.csv"
    writer_csv = camera_dir / "writer_stats.csv"
    metadata_csv = camera_dir / "metadata.csv"
    live_csv = camera_dir / "live_status.csv"
    video_files = sorted(camera_dir.glob("*.mp4")) if camera_dir.exists() else []

    frame_count = _csv_data_rows(frame_csv)
    writer_count = _writer_count(writer_csv)
    metadata = _metadata(metadata_csv)
    live_status = _live_status(live_csv)
    total_frames = metadata.get("totalFrames")
    frame_gap_count = metadata.get("frameIdGapCount")
    frames_queued = metadata.get("framesQueued")

    count_text = "-"
    if frame_count:
        count_text = "{} frame rows".format(frame_count)
    if writer_count is not None:
        count_text = "{} / {} written".format(frame_count or "-", writer_count)
    if process_state in ["recording", "stopping"] and live_status:
        count_text = "{} frames".format(live_status.get("framesCollected", "-"))

    rate_text = "-"
    host_total = _as_float(metadata.get("hostTotalTime"))
    if total_frames and host_total and host_total > 0:
        rate_text = "{:.2f} Hz".format(float(total_frames) / host_total)
    elif frame_count and expected_rate:
        rate_text = "~{} Hz target".format(expected_rate)
    if process_state in ["recording", "stopping"] and live_status:
        rate_text = "{} Hz".format(live_status.get("fps", "-"))

    if process_state in ["recording", "stopping"] and live_status:
        state = "Recording" if process_state == "recording" else "Stopping"
    elif frame_count or writer_count is not None or total_frames:
        state = "Saved"
    elif process_state == "recording":
        state = "Recording"
    elif process_state == "ready":
        state = "Ready"
    elif process_state == "preparing":
        state = "Preparing"
    elif process_state == "running":
        state = "Waiting"
    elif process_state == "stopping":
        state = "Stopping"
    else:
        state = "Idle"

    notes = []
    if not camera_dir.exists():
        notes.append("folder not found")
    elif video_files and not frame_count and writer_count is None and not total_frames:
        notes.append("video exists, metadata missing")
    if frame_gap_count not in [None, "", "0", 0]:
        notes.append("frame ID gaps: {}".format(frame_gap_count))
    if frames_queued not in [None, ""]:
        notes.append("queued {}".format(frames_queued))
    if process_state in ["recording", "stopping"] and live_status:
        notes = ["elapsed {} sec".format(live_status.get("elapsedSec", "-"))]

    last_update = _last_update([live_csv, frame_csv, writer_csv, metadata_csv])
    tile = {
        "title": name,
        "state": state,
        "frames": count_text,
        "rate": rate_text,
        "notes": ", ".join(notes) if notes else "ready",
    }
    row = StatusRow(name, state, count_text, rate_text, last_update, tile["notes"])
    return row, tile


def _gpio_status(config_data, save_folder, process_state):
    log_name = get_value(config_data, "gpioLogFilename", "gpio_log.csv")
    log_path = save_folder / str(log_name)
    count = _csv_data_rows(log_path)
    rate = _gpio_rate(log_path)
    if count:
        state = "Saved"
    elif process_state == "recording":
        state = "Recording"
    elif process_state == "ready":
        state = "Ready"
    elif process_state == "preparing":
        state = "Preparing"
    elif process_state == "stopping":
        state = "Stopping"
    else:
        state = "Idle"
    notes = "port {}".format(get_value(config_data, "gpioSerialPort", "-"))
    if not log_path.exists():
        notes += ", log not found"
    return StatusRow("GPIO", state, str(count or "-"), rate, _last_update([log_path]), notes)


def _pulsepal_status(config_data, process_state):
    enabled = get_value(config_data, "startTriggerController", False)
    controller = get_value(config_data, "triggerController", "-")
    if not enabled:
        state = "Disabled"
    elif process_state == "recording":
        state = "Recording"
    elif process_state == "ready":
        state = "Ready"
    elif process_state == "preparing":
        state = "Preparing"
    elif process_state == "stopping":
        state = "Stopping"
    else:
        state = "Idle"
    notes = "{} {} Hz on {}".format(
        controller,
        get_value(config_data, "pulseFrequencyHz", "-"),
        get_value(config_data, "pulsePalPort", "-"),
    )
    return StatusRow("Trigger", state, "-", "-", "-", notes)


def _csv_data_rows(path):
    if not Path(path).exists():
        return 0
    try:
        with Path(path).open("r", newline="", encoding="utf-8") as handle:
            rows = sum(1 for _ in handle)
        return max(0, rows - 1)
    except Exception:
        return 0


def _writer_count(path):
    if not Path(path).exists():
        return None
    try:
        with Path(path).open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
            if not rows:
                return None
            if len(rows[0]) >= 2 and rows[0][0] == "framesWritten":
                return int(rows[0][1])
            if len(rows) >= 2 and rows[1]:
                return int(rows[1][0])
    except Exception:
        return None


def _metadata(path):
    data = {}
    if not Path(path).exists():
        return data
    try:
        with Path(path).open("r", newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2:
                    data[row[0]] = row[1]
    except Exception:
        pass
    return data


def _live_status(path):
    if not Path(path).exists():
        return {}
    try:
        with Path(path).open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            row = next(reader, None)
            return dict(row) if row else {}
    except Exception:
        return {}


def _gpio_rate(path):
    if not Path(path).exists():
        return "-"
    first = None
    last = None
    count = 0
    try:
        with Path(path).open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                timestamp = _as_float(row.get("hostTimestampEpochSec"))
                if timestamp is None:
                    continue
                first = timestamp if first is None else first
                last = timestamp
                count += 1
    except Exception:
        return "-"
    if first is None or last is None or last <= first or count < 2:
        return "-"
    return "{:.2f} Hz".format((count - 1) / (last - first))


def _last_update(paths):
    existing = [Path(path) for path in paths if Path(path).exists()]
    if not existing:
        return "-"
    newest = max(path.stat().st_mtime for path in existing)
    return datetime.fromtimestamp(newest).strftime("%H:%M:%S")


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None
