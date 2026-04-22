#!/usr/bin/env python3
"""Export monitor summary JSON files to CSV.

Supports multiple inputs so you can combine runs (for example: non-hardware + hardware)
into a single Excel-friendly CSV while preserving a run label.

Input format:
  --input <label>=<summary_json_path>

Example:
  python3 export_monitor_results_csv.py \
    --input non_hardware=monitor_results_repos/summary.json \
    --input hardware_14=monitor_results_hardware_14/summary.json \
    --out-csv monitor_results_all.csv \
    --split-by-label
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


CSV_COLUMNS = [
    "run_label",
    "repo_name",
    "repo_path",
    "status",
    "exit_code",
    "timed_out",
    "runtime",
    "peak_cpu_percent",
    "peak_ram_mb",
    "peak_disk_mb",
    "peak_gpu_util_percent",
    "peak_gpu_memory_mb",
]


def parse_input_spec(spec: str) -> Tuple[str, Path]:
    if "=" not in spec:
        raise ValueError(
            f"Invalid --input '{spec}'. Expected format: <label>=<summary_json_path>"
        )
    label, path_str = spec.split("=", 1)
    label = label.strip()
    path = Path(path_str.strip()).expanduser()
    if not label:
        raise ValueError(f"Invalid --input '{spec}'. Label cannot be empty.")
    if not path.exists():
        raise FileNotFoundError(f"Summary file not found: {path}")
    return label, path


def load_rows(label: str, summary_path: Path) -> List[Dict[str, Any]]:
    with summary_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    results = payload.get("results", [])
    if not isinstance(results, list):
        raise ValueError(f"Invalid summary format in {summary_path}: 'results' must be a list")

    rows: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        row = {
            "run_label": label,
            "repo_name": item.get("repo_name", ""),
            "repo_path": item.get("repo_path", ""),
            "status": item.get("status", ""),
            "exit_code": item.get("exit_code", ""),
            "timed_out": item.get("timed_out", ""),
            "runtime": item.get("runtime", ""),
            "peak_cpu_percent": item.get("peak_cpu_percent", ""),
            "peak_ram_mb": item.get("peak_ram_mb", ""),
            "peak_disk_mb": item.get("peak_disk_mb", ""),
            "peak_gpu_util_percent": item.get("peak_gpu_util_percent", ""),
            "peak_gpu_memory_mb": item.get("peak_gpu_memory_mb", ""),
        }
        rows.append(row)
    return rows


def write_csv(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert monitor summary JSON to CSV")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Input spec as <label>=<summary_json_path>. Can be provided multiple times.",
    )
    parser.add_argument(
        "--out-csv",
        required=True,
        help="Path to combined output CSV file.",
    )
    parser.add_argument(
        "--split-by-label",
        action="store_true",
        help="Also write one CSV per input label next to --out-csv.",
    )

    args = parser.parse_args()

    input_specs = [parse_input_spec(spec) for spec in args.input]

    combined_rows: List[Dict[str, Any]] = []
    rows_by_label: Dict[str, List[Dict[str, Any]]] = {}

    for label, summary_path in input_specs:
        rows = load_rows(label, summary_path)
        rows_by_label[label] = rows
        combined_rows.extend(rows)

    out_csv = Path(args.out_csv).expanduser()
    write_csv(out_csv, combined_rows)

    if args.split_by_label:
        for label, rows in rows_by_label.items():
            label_csv = out_csv.with_name(f"{out_csv.stem}_{label}{out_csv.suffix}")
            write_csv(label_csv, rows)

    print(f"Wrote combined CSV: {out_csv} ({len(combined_rows)} rows)")
    if args.split_by_label:
        for label, rows in rows_by_label.items():
            label_csv = out_csv.with_name(f"{out_csv.stem}_{label}{out_csv.suffix}")
            print(f"Wrote label CSV:    {label_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
