#!/usr/bin/env python3
"""Analyze KVM batch provisioning results from per-run JSON outputs.

Reads logs_kvm/run_*_info.json files written by batch_provision.py and
builds a predicted-vs-actual CSV from the nested hardware_validation schema.
"""

from __future__ import annotations

import json
import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


WORKSPACE_ROOT = Path(__file__).resolve().parent
DEFAULT_LOGS_DIR = WORKSPACE_ROOT / "logs_kvm"


def _as_bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _load_run_json(path: Path) -> Dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _extract_rows(logs_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for json_path in sorted(logs_dir.glob("run_*_info.json")):
        try:
            data = _load_run_json(json_path)
        except Exception as exc:
            rows.append({
                "repo": data.get("repo", "unknown") if "data" in locals() and isinstance(data, dict) else "unknown",
                "provisioning_success": False,
                "predicted_cpu": None,
                "actual_cpu": None,
                "predicted_ram_gb": None,
                "actual_ram_gb": None,
                "predicted_disk_gb": None,
                "actual_disk_gb": None,
                "predicted_gpu_required": None,
                "actual_gpu_count": None,
                "selected_flavor": None,
                "hardware_match": None,
                "undersized_reasons": [f"Failed to read JSON: {exc}"],
            })
            continue

        hw = data.get("hardware_validation") or {}
        if not isinstance(hw, dict):
            hw = {}

        provisioning_success = data.get("provisioning_success")
        if provisioning_success is None:
            provisioning_success = data.get("provisioning_type") not in (None, "unknown")

        rows.append({
            "repo": data.get("repo", "unknown"),
            "provisioning_success": _as_bool(provisioning_success),
            "predicted_cpu": hw.get("predicted_cpu"),
            "actual_cpu": hw.get("actual_cpu"),
            "predicted_ram_gb": hw.get("predicted_ram_gb"),
            "actual_ram_gb": hw.get("actual_ram_gb"),
            "predicted_disk_gb": hw.get("predicted_disk_gb"),
            "actual_disk_gb": hw.get("actual_disk_gb"),
            "predicted_gpu_required": _as_bool(hw.get("predicted_gpu_required")),
            "actual_gpu_count": hw.get("actual_gpu_count", 0),
            "selected_flavor": hw.get("selected_flavor") or data.get("selected_flavor"),
            "hardware_match": hw.get("hardware_match"),
            "undersized_reasons": _as_list(hw.get("undersized_reasons")),
            "hardware_validation": hw,
            "source_json": str(json_path),
        })

    return rows


def _format_rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0/0 = 0.0%"
    return f"{numerator}/{denominator} = {(numerator / denominator):.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze KVM batch provisioning results")
    parser.add_argument("--logs-dir", type=str, default=str(DEFAULT_LOGS_DIR), help="Directory containing run_*_info.json files")
    args = parser.parse_args()

    logs_dir = Path(args.logs_dir)
    csv_path = logs_dir / "predicted_vs_actual.csv"

    if not logs_dir.exists():
        print(f"Logs directory not found: {logs_dir}")
        return 1

    rows = _extract_rows(logs_dir)
    if not rows:
        print(f"No run_*_info.json files found in: {logs_dir}")
        return 1

    df = pd.DataFrame(rows)

    # Keep the CSV schema focused on the requested fields.
    csv_df = df[[
        "repo",
        "provisioning_success",
        "predicted_cpu",
        "actual_cpu",
        "predicted_ram_gb",
        "actual_ram_gb",
        "predicted_disk_gb",
        "actual_disk_gb",
        "predicted_gpu_required",
        "actual_gpu_count",
        "selected_flavor",
        "hardware_match",
        "undersized_reasons",
    ]].copy()
    csv_df.to_csv(csv_path, index=False)

    provisioning_success_count = int(csv_df["provisioning_success"].sum())
    provisioning_total = len(csv_df)

    hardware_match_series = csv_df["hardware_match"].dropna()
    hardware_match_count = int(sum(bool(x) for x in hardware_match_series))
    hardware_match_total = int(len(hardware_match_series))

    gpu_required_count = int(csv_df["predicted_gpu_required"].sum())
    gpu_mismatch_count = int(
        sum(
            bool(pred) and int(actual_gpu or 0) == 0
            for pred, actual_gpu in zip(csv_df["predicted_gpu_required"], csv_df["actual_gpu_count"])
        )
    )
    undersized_count = int(
        sum(
            hw is False
            for hw in csv_df["hardware_match"].tolist()
        )
    )

    reason_counts = Counter()
    for reasons in csv_df["undersized_reasons"]:
        for reason in _as_list(reasons):
            reason_counts[reason] += 1

    print("\n" + "=" * 120)
    print("KVM BATCH HARDWARE ANALYSIS")
    print("=" * 120)
    print(csv_df.to_string(index=False))

    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"provisioning_success_rate: {_format_rate(provisioning_success_count, provisioning_total)}")
    print(
        f"hardware_match_rate: {_format_rate(hardware_match_count, hardware_match_total)}"
        if hardware_match_total
        else "hardware_match_rate: 0/0 = 0.0%"
    )
    print(f"GPU-required count: {gpu_required_count}")
    print(f"GPU-mismatch count: {gpu_mismatch_count}")
    print(f"Undersized count: {undersized_count}")
    print("Top undersized reasons:")
    if reason_counts:
        for reason, count in reason_counts.most_common():
            print(f"  - {reason}: {count}")
    else:
        print("  - none")

    print(f"\n✓ CSV saved to: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
