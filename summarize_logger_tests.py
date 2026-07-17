import csv
import json
import math
import os
import subprocess
import sys


RUNS = [
    r"D:\logger_test1",
    r"D:\logger_test2",
    r"D:\logger_test3",
]

FFPROBE = r"C:\Users\Cornell\anaconda3\envs\campy\Library\bin\ffprobe.exe"


def pct(sorted_values, q):
    if not sorted_values:
        return None
    idx = int(round((len(sorted_values) - 1) * q))
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]


def diffs(values):
    return [(values[i] - values[i - 1]) * 1000.0 for i in range(1, len(values))]


def summary_ms(values):
    if not values:
        return {}
    s = sorted(values)
    return {
        "min": s[0],
        "p1": pct(s, 0.01),
        "median": pct(s, 0.5),
        "p99": pct(s, 0.99),
        "max": s[-1],
        "short_lt_12p5": sum(1 for v in values if v < 12.5),
        "long_gt_37p5": sum(1 for v in values if v > 37.5),
    }


def read_metadata(path):
    rows = 0
    first = None
    last = None
    saved_ids = []
    camera_ids = []
    cam_ts = []
    host_epoch = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        for row in reader:
            rows += 1
            if first is None:
                first = dict(row)
            last = dict(row)
            if "savedFrameNumber" in row and row["savedFrameNumber"] != "":
                saved_ids.append(int(row["savedFrameNumber"]))
            if "cameraFrameID" in row and row["cameraFrameID"] != "":
                camera_ids.append(int(row["cameraFrameID"]))
            if "cameraTimeStampSec" in row and row["cameraTimeStampSec"] != "":
                cam_ts.append(float(row["cameraTimeStampSec"]))
            if "hostDateTimeEpochSec" in row and row["hostDateTimeEpochSec"] != "":
                host_epoch.append(float(row["hostDateTimeEpochSec"]))
    return {
        "rows": rows,
        "fields": fields,
        "saved_range": [saved_ids[0], saved_ids[-1]] if saved_ids else None,
        "saved_missing": (saved_ids[-1] - saved_ids[0] + 1 - len(saved_ids)) if saved_ids else None,
        "camera_id_range": [camera_ids[0], camera_ids[-1]] if camera_ids else None,
        "camera_id_missing": (camera_ids[-1] - camera_ids[0] + 1 - len(camera_ids)) if camera_ids else None,
        "camera_diff": summary_ms(diffs(cam_ts)),
        "host_epoch_span": (host_epoch[-1] - host_epoch[0]) if len(host_epoch) > 1 else None,
        "camera_span": (cam_ts[-1] - cam_ts[0]) if len(cam_ts) > 1 else None,
        "host_start": host_epoch[0] if host_epoch else None,
        "host_end": host_epoch[-1] if host_epoch else None,
    }


def read_gpio(path):
    channels = {}
    total = 0
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        time_col = "hostTimestampEpochSec" if "hostTimestampEpochSec" in fields else fields[0]
        value_col = "gpioValue" if "gpioValue" in fields else fields[1]
        for row in reader:
            total += 1
            ch = row[value_col]
            channels.setdefault(ch, []).append(float(row[time_col]))
    out = {"total": total, "fields": fields, "channels": {}}
    for ch, values in sorted(channels.items(), key=lambda kv: kv[0]):
        out["channels"][ch] = {
            "count": len(values),
            "span": (values[-1] - values[0]) if len(values) > 1 else None,
            "first": values[0] if values else None,
            "last": values[-1] if values else None,
            "diff": summary_ms(diffs(values)),
        }
    if "0" in channels and "1" in channels:
        ch0 = channels["0"]
        ch1 = channels["1"]
        same_index = [(ch1[i] - ch0[i]) * 1000.0 for i in range(min(len(ch0), len(ch1)))]
        shifted = [(ch1[i + 1] - ch0[i]) * 1000.0 for i in range(min(len(ch0), len(ch1) - 1))]
        out["ch1_minus_ch0_same_index"] = summary_ms(same_index)
        out["ch1_minus_ch0_same_index"]["exact_zero"] = sum(1 for v in same_index if v == 0.0)
        out["ch1_next_minus_ch0"] = summary_ms(shifted)
        out["ch1_next_minus_ch0"]["exact_zero"] = sum(1 for v in shifted if v == 0.0)
    return out


def ffprobe_frames(path):
    if not os.path.exists(FFPROBE):
        return None
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_frames,duration,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode:
        return {"error": proc.stderr.strip()}
    data = json.loads(proc.stdout)
    stream = (data.get("streams") or [{}])[0]
    return stream


def find_one(root, name):
    for cur, _, files in os.walk(root):
        if name in files:
            return os.path.join(cur, name)
    return None


def find_mp4(root):
    for cur, _, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(".mp4"):
                return os.path.join(cur, fn)
    return None


def main():
    results = []
    for root in RUNS:
        gpio = os.path.join(root, "gpio_log.csv")
        meta = find_one(root, "frame_metadata.csv")
        mp4 = find_mp4(root)
        item = {"run": os.path.basename(root), "root": root, "gpio": gpio, "metadata": meta, "mp4": mp4}
        item["metadata_summary"] = read_metadata(meta) if meta else None
        item["gpio_summary"] = read_gpio(gpio) if os.path.exists(gpio) else None
        item["video_summary"] = ffprobe_frames(mp4) if mp4 else None
        results.append(item)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
