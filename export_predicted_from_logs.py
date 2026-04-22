#!/usr/bin/env python3
"""Export predicted hardware requirements from provisioning logs to CSV.

Parses log files (for example in logs_tacc) and extracts:
- repo URL/name
- predicted CPU/RAM/disk/GPU/GPU memory/OS/CUDA
- optional timing metadata from Start/End lines

Default behavior keeps only the latest log per repo URL, which is usually what you
want when there are retries or duplicate runs.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


CSV_COLUMNS = [
    "repo",
    "cpu",
    "ram",
    "disk",
    "gpu",
    "gpu_memory",
    "os",
    "cuda",
    "start_time",
    "end_time",
    "duration_seconds",
    "log_file",
]


def _extract_repo_url(text: str) -> Optional[str]:
    m = re.search(r'Command:\s+python\s+2\.0/src/provision_v2\.py\s+--repo\s+"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    return None


def _extract_field(text: str, label: str) -> Optional[str]:
    m = re.search(rf"^\s*{re.escape(label)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _extract_requirements_block(text: str) -> Optional[str]:
    marker = "Repository requirements analysis complete:"
    idx = text.find(marker)
    if idx < 0:
        return None

    # Take text after marker until next step header or separator.
    tail = text[idx + len(marker) :]
    end_candidates = []
    for pat in [r"\n={10,}\n", r"\nStep\s+\d+:", r"\nDiscovering Available Resources"]:
        m = re.search(pat, tail)
        if m:
            end_candidates.append(m.start())
    end = min(end_candidates) if end_candidates else len(tail)
    return tail[:end]


def _to_int_or_none(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    m = re.search(r"-?\d+", value)
    if not m:
        return None
    return int(m.group(0))


def _to_bool_or_none(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"required", "true", "yes"}:
        return True
    if v in {"not required", "false", "no"}:
        return False
    return None


def parse_log(log_path: Path) -> Optional[Dict[str, object]]:
    text = log_path.read_text(encoding="utf-8", errors="replace")

    repo = _extract_repo_url(text)
    block = _extract_requirements_block(text)
    if not repo or not block:
        return None

    cpu_raw = _extract_field(block, "CPU")
    ram_raw = _extract_field(block, "RAM")
    disk_raw = _extract_field(block, "Disk")
    gpu_raw = _extract_field(block, "GPU")
    gpu_mem_raw = _extract_field(block, "GPU Memory")
    os_raw = _extract_field(block, "OS")
    cuda_raw = _extract_field(block, "CUDA")

    start_time = _extract_field(text, "Start")
    end_line = re.search(
        r"^\s*End:\s+([^\(]+?)\s*\(exit=.*?duration=(\d+)s\)",
        text,
        re.MULTILINE,
    )
    end_time = end_line.group(1).strip() if end_line else None
    duration_seconds = int(end_line.group(2)) if end_line else None

    return {
        "repo": repo,
        "cpu": _to_int_or_none(cpu_raw),
        "ram": _to_int_or_none(ram_raw),
        "disk": _to_int_or_none(disk_raw),
        "gpu": _to_bool_or_none(gpu_raw),
        "gpu_memory": _to_int_or_none(gpu_mem_raw),
        "os": os_raw,
        "cuda": cuda_raw,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "log_file": str(log_path),
    }


def _sort_key_from_name(path: Path) -> Tuple[int, str]:
    stem = path.stem
    m = re.match(r"(\d{8}_\d{6})", stem)
    if m:
        return (int(m.group(1).replace("_", "")), stem)
    # Put non-standard names (e.g., kvm_*) first so standard timestamp files win.
    return (0, stem)


def collect_rows(log_dir: Path, latest_per_repo: bool) -> List[Dict[str, object]]:
    parsed: List[Dict[str, object]] = []
    for log_path in sorted(log_dir.glob("*.log"), key=_sort_key_from_name):
        row = parse_log(log_path)
        if row is not None:
            parsed.append(row)

    if not latest_per_repo:
        return parsed

    latest: Dict[str, Dict[str, object]] = {}
    for row in parsed:
        latest[str(row["repo"])] = row
    return sorted(latest.values(), key=lambda r: str(r["repo"]).lower())


def write_csv(out_csv: Path, rows: List[Dict[str, object]]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_repo_filter(repos_file: Path) -> Set[str]:
    repos: Set[str] = set()
    for raw in repos_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        repos.add(line)
    return repos


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse provisioning logs and export predicted requirements to CSV"
    )
    parser.add_argument(
        "--log-dir",
        default="logs_tacc",
        help="Directory containing .log files (default: logs_tacc)",
    )
    parser.add_argument(
        "--out-csv",
        default="predicted_requirements_tacc.csv",
        help="Output CSV path (default: predicted_requirements_tacc.csv)",
    )
    parser.add_argument(
        "--include-all-runs",
        action="store_true",
        help="Include every log file row; default keeps only latest row per repo.",
    )
    parser.add_argument(
        "--repos-file",
        default=None,
        help="Optional repo list file (one URL per line) to filter output rows.",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir).expanduser()
    out_csv = Path(args.out_csv).expanduser()

    rows = collect_rows(log_dir=log_dir, latest_per_repo=not args.include_all_runs)

    if args.repos_file:
        wanted = load_repo_filter(Path(args.repos_file).expanduser())
        rows = [r for r in rows if str(r.get("repo", "")) in wanted]

    write_csv(out_csv, rows)

    print(f"Wrote: {out_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
