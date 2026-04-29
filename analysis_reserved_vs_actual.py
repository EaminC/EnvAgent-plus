#!/usr/bin/env python3
"""Summarize reserved-vs-actual hardware details from inspect outputs.

Scans results/*_actual_reserved_info.json, extracts the key actual hardware
fields, prints a pandas DataFrame, and writes results/reserved_vs_actual.csv.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


UNKNOWN = "unknown"


def _as_unknown(value):
    if value in (None, "", [], {}, ()):
        return UNKNOWN
    return value


def _extract_run_id(data: dict, source_path: Path) -> str:
    input_info = data.get("input_info_file")
    if isinstance(input_info, str) and input_info:
        return Path(input_info).name
    return source_path.stem.replace("_actual_reserved_info", "")


def _extract_repo_name(run_id: str, source_path: Path) -> str:
    log_dir = source_path.parent.parent / "logs_tacc_15"
    server_name = run_id.replace("_info.json", "")
    for log_path in sorted(log_dir.glob("*.log")):
        try:
            with log_path.open("r", encoding="utf-8") as handle:
                contents = handle.read()
                if server_name not in contents:
                    continue
                for line in contents.splitlines():
                    if "--repo" not in line:
                        continue
                    match = re.search(r'--repo\s+"?([^"\s]+)"?', line)
                    if match:
                        return match.group(1)
        except Exception:
            continue
    return UNKNOWN


def _discover_runs_from_logs(workspace_root: Path) -> dict[str, str]:
    log_dir = workspace_root / "logs_tacc_15"
    runs: dict[str, str] = {}
    for log_path in sorted(log_dir.glob("20260428_*.log")):
        run_id = UNKNOWN
        repo = UNKNOWN
        try:
            with log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if run_id == UNKNOWN:
                        match = re.search(r"Info saved to:\s+(auto-server-[^\s]+_info\.json)", line)
                        if match:
                            run_id = match.group(1)
                    if repo == UNKNOWN and "--repo" in line:
                        match = re.search(r'--repo\s+"?([^"\s]+)"?', line)
                        if match:
                            repo = match.group(1)
                    if run_id != UNKNOWN and repo != UNKNOWN:
                        break
        except Exception:
            continue

        if run_id != UNKNOWN:
            runs[run_id] = repo

    return runs


def _load_rows(results_dir: Path, workspace_root: Path) -> list[dict]:
    rows_by_run_id: dict[str, dict] = {}
    log_runs = _discover_runs_from_logs(workspace_root)

    for run_id, repo in log_runs.items():
        rows_by_run_id[run_id] = {
            "run_id": run_id,
            "repo": repo,
            "node_type": UNKNOWN,
            "cpus": UNKNOWN,
            "memory_mb": UNKNOWN,
            "disk_gb": UNKNOWN,
            "gpu_type": UNKNOWN,
            "gpu_count": UNKNOWN,
            "using_placeholder": False,
        }

    for json_path in sorted(results_dir.glob("*_actual_reserved_info.json")):
        try:
            with json_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            data = {}

        run_id = _extract_run_id(data, json_path)
        if run_id not in log_runs:
            continue

        # Use new hardware fields if available, fall back to old ones
        actual_cpus = _as_unknown(data.get("actual_cpus", data.get("actual_vcpus")))
        actual_memory_mb = _as_unknown(data.get("actual_memory_mb", data.get("actual_ram_mb")))
        actual_disk_gb = _as_unknown(data.get("actual_disk_gb"))
        actual_gpu_type = _as_unknown(data.get("actual_gpu_type"))
        actual_gpu_count = _as_unknown(data.get("actual_gpu_count"))
        using_placeholder = data.get("using_placeholder_baremetal", False)

        # Add warning if using placeholder baremetal
        warning = ""
        if using_placeholder and actual_cpus == "1" and actual_memory_mb == "1":
            warning = " [WARNING: Using placeholder baremetal flavor values!]"

        rows_by_run_id[run_id] = {
            "run_id": run_id,
            "repo": _extract_repo_name(run_id, json_path),
            "node_type": _as_unknown(data.get("selected_node_type")),
            "cpus": actual_cpus + warning,
            "memory_mb": actual_memory_mb,
            "disk_gb": actual_disk_gb,
            "gpu_type": actual_gpu_type,
            "gpu_count": actual_gpu_count,
            "using_placeholder": using_placeholder,
        }

    return [rows_by_run_id[key] for key in sorted(rows_by_run_id)]


def main() -> int:
    workspace_root = Path(__file__).resolve().parent
    results_dir = workspace_root / "results"
    rows = _load_rows(results_dir, workspace_root)

    if not rows:
        print(f"No files matched: {results_dir / '*_actual_reserved_info.json'}")
        return 1

    dataframe = pd.DataFrame(rows, columns=["run_id", "repo", "node_type", "cpus", "memory_mb", "disk_gb", "gpu_type", "gpu_count", "using_placeholder"])
    print(dataframe.to_string(index=False))

    out_path = results_dir / "reserved_vs_actual.csv"
    dataframe.to_csv(out_path, index=False)
    print(f"\nWrote CSV to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())