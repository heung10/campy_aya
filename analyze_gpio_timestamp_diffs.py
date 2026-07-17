"""Analyze consecutive timestamps in a GPIO CSV without modifying the input."""

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt


DEFAULT_INPUT = Path(r"D:\random_foraging\WT2WT4_outdoorsmall_0710\gpio_log.csv")
DEFAULT_OUTPUT = Path(__file__).with_name("gpio_timestamp_differences.png")


def read_first_column(csv_path: Path) -> Tuple[str, List[datetime]]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader)
        if not header:
            raise ValueError("The CSV header is empty.")

        timestamps = []
        for row_number, row in enumerate(reader, start=2):
            if not row or not row[0].strip():
                continue
            try:
                timestamps.append(datetime.fromisoformat(row[0].strip()))
            except ValueError as error:
                raise ValueError(
                    f"Invalid timestamp in first column at CSV row {row_number}: {row[0]!r}"
                ) from error

    return header[0], timestamps


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot differences between consecutive timestamps in a CSV's first column."
    )
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--tolerance-ms",
        type=float,
        default=1e-6,
        help="Maximum range in milliseconds considered constant (default: 1e-6).",
    )
    args = parser.parse_args()

    column_name, timestamps = read_first_column(args.csv_path)
    if len(timestamps) < 2:
        raise ValueError("At least two valid timestamps are required.")

    differences_ms = [
        (current - previous).total_seconds() * 1000.0
        for previous, current in zip(timestamps, timestamps[1:])
    ]
    minimum = min(differences_ms)
    maximum = max(differences_ms)
    mean = sum(differences_ms) / len(differences_ms)
    constant = maximum - minimum <= args.tolerance_ms

    fig, axis = plt.subplots(figsize=(12, 5))
    axis.plot(range(1, len(differences_ms) + 1), differences_ms, linewidth=0.8)
    axis.axhline(mean, color="tab:red", linestyle="--", linewidth=1, label=f"Mean: {mean:.6f} ms")
    axis.set(
        title=f"Consecutive differences in {column_name}",
        xlabel="Consecutive timestamp pair index",
        ylabel="Difference (ms)",
    )
    axis.grid(True, alpha=0.3)
    axis.legend()
    fig.tight_layout()
    fig.savefig(args.output, dpi=160)
    plt.close(fig)

    print(f"Timestamps: {len(timestamps)}")
    print(f"Consecutive differences: {len(differences_ms)}")
    print(f"Minimum: {minimum:.9f} ms")
    print(f"Maximum: {maximum:.9f} ms")
    print(f"Mean: {mean:.9f} ms")
    print(f"Range: {maximum - minimum:.9f} ms")
    print(f"Constant within {args.tolerance_ms:g} ms tolerance: {constant}")
    print(f"Plot saved to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
