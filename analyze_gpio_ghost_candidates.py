"""Read-only diagnostic for GPIO ghost candidates versus missed camera acquisitions."""

import csv
from bisect import bisect_right
from pathlib import Path
from statistics import median


ROOT = Path(r"D:\logger_test3")
GPIO_PATH = ROOT / "gpio_log.csv"
CAMERA_PATH = ROOT / "1c" / "frame_metadata.csv"


def read_rows(path):
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


gpio_rows = read_rows(GPIO_PATH)
camera_rows = read_rows(CAMERA_PATH)

camera_hw = [float(row["cameraTimeStampSec"]) for row in camera_rows]
camera_host = [float(row["hostDateTimeEpochSec"]) for row in camera_rows]

print("Frames: {}".format(len(camera_rows)))

for channel in ("0", "1"):
    channel_rows = [row for row in gpio_rows if row["gpioValue"] == channel]
    times = [float(row["hostTimestampEpochSec"]) for row in channel_rows]
    intervals_ms = [(b - a) * 1000.0 for a, b in zip(times, times[1:])]
    print("\nChannel {}: {} events ({:+d} versus frames)".format(
        channel, len(times), len(times) - len(camera_rows)
    ))
    print("  interval median: {:.6f} ms".format(median(intervals_ms)))
    for threshold in (1.0, 5.0, 10.0, 12.5, 15.0, 18.75):
        print("  intervals < {:5.2f} ms: {}".format(
            threshold, sum(value < threshold for value in intervals_ms)
        ))

# A camera interval >37.5 ms contains at least one absent nominal 25 ms frame.
long_gaps = []
for index in range(1, len(camera_rows)):
    hardware_diff_ms = (camera_hw[index] - camera_hw[index - 1]) * 1000.0
    if hardware_diff_ms > 37.5:
        long_gaps.append((index, hardware_diff_ms))

print("\nCamera hardware intervals >37.5 ms: {}".format(len(long_gaps)))
print("  min/median/max: {:.6f} / {:.6f} / {:.6f} ms".format(
    min(item[1] for item in long_gaps),
    median(item[1] for item in long_gaps),
    max(item[1] for item in long_gaps),
))

# Count channel-1 trigger records whose host timestamps lie between the host
# observations of the frames bracketing each hardware gap. Host jitter makes
# this diagnostic approximate, but it tests whether the extra direct pulse is
# present at the correct gap locations.
channel1_times = [
    float(row["hostTimestampEpochSec"])
    for row in gpio_rows
    if row["gpioValue"] == "1"
]
counts = []
for index, _ in long_gaps:
    left = camera_host[index - 1]
    right = camera_host[index]
    counts.append(bisect_right(channel1_times, right) - bisect_right(channel1_times, left))

distribution = {}
for count in counts:
    distribution[count] = distribution.get(count, 0) + 1
print("\nChannel-1 events between host timestamps bracketing each camera gap:")
print("  {}".format(dict(sorted(distribution.items()))))

# Adjacent channel rows with an identical timestamp reveal logger-level pairing.
ch0 = [float(row["hostTimestampEpochSec"]) for row in gpio_rows if row["gpioValue"] == "0"]
ch1 = channel1_times
identical_shifted = sum(a == b for a, b in zip(ch0, ch1[1:]))
print("\nShifted channel pairs with identical timestamp: {}/{}".format(
    identical_shifted, min(len(ch0), max(0, len(ch1) - 1))
))

print("\nInterpretation check:")
print("  Events removable using a conventional <1 ms duplicate rule: {}".format(
    sum((b - a) * 1000.0 < 1.0 for a, b in zip(ch1, ch1[1:]))
))
print("  Events that must be removed to force channel 1 to frame count: {}".format(
    len(ch1) - len(camera_rows)
))
