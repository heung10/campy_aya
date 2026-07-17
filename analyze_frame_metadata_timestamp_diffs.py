"""Plot consecutive differences for the last four columns of frame_metadata.csv."""

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Callable, List

import matplotlib.pyplot as plt


DEFAULT_INPUT = Path(r"D:\random_foraging\WT2WT4_outdoorsmall_0710\1c\frame_metadata.csv")
DEFAULT_OUTPUT = Path(__file__).with_name("frame_metadata_timestamp_differences.png")


def iso_to_seconds(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def read_last_four_columns(csv_path: Path) -> tuple:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader)
        if len(header) < 4:
            raise ValueError("The CSV must contain at least four columns.")

        names = header[-4:]
        values = [[] for _ in names]  # type: List[List[float]]
        parsers = [float, float, iso_to_seconds, float]  # type: List[Callable[[str], float]]

        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise ValueError(
                    "CSV row {} contains {} columns; expected {}.".format(
                        row_number, len(row), len(header)
                    )
                )
            for index, (raw_value, parser) in enumerate(zip(row[-4:], parsers)):
                try:
                    values[index].append(parser(raw_value.strip()))
                except ValueError as error:
                    raise ValueError(
                        "Invalid value in column {!r} at CSV row {}: {!r}".format(
                            names[index], row_number, raw_value
                        )
                    ) from error

    return names, values


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot consecutive differences for the final four timestamp columns."
    )
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tolerance-ms", type=float, default=1e-6)
    args = parser.parse_args()

    names, columns = read_last_four_columns(args.csv_path)
    if any(len(column) < 2 for column in columns):
        raise ValueError("At least two data rows are required.")

    differences = [
        [(current - previous) * 1000.0 for previous, current in zip(column, column[1:])]
        for column in columns
    ]

    fig, axes = plt.subplots(4, 1, figsize=(13, 12), sharex=True)
    for axis, name, diffs in zip(axes, names, differences):
        mean = sum(diffs) / len(diffs)
        minimum = min(diffs)
        maximum = max(diffs)
        value_range = maximum - minimum
        is_constant = value_range <= args.tolerance_ms

        axis.plot(range(1, len(diffs) + 1), diffs, linewidth=0.7)
        axis.axhline(
            mean,
            color="tab:red",
            linestyle="--",
            linewidth=1,
            label="Mean: {:.6f} ms".format(mean),
        )
        axis.set_title(name)
        axis.set_ylabel("Difference (ms)")
        axis.grid(True, alpha=0.3)
        axis.legend(loc="upper right")

        print(name)
        print("  Differences: {}".format(len(diffs)))
        print("  Minimum: {:.9f} ms".format(minimum))
        print("  Maximum: {:.9f} ms".format(maximum))
        print("  Mean: {:.9f} ms".format(mean))
        print("  Range: {:.9f} ms".format(value_range))
        print("  Constant within {:g} ms tolerance: {}".format(args.tolerance_ms, is_constant))

    axes[-1].set_xlabel("Consecutive frame pair index")
    fig.suptitle("Consecutive differences for the last four timestamp columns", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(args.output, dpi=160)
    plt.close(fig)
    print("Plot saved to: {}".format(args.output.resolve()))


if __name__ == "__main__":
    main()
