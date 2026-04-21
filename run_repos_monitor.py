#!/usr/bin/env python3
"""Run one command per repository with resource monitoring.

Features:
- Sequential execution (one repo at a time)
- System-wide resource sampling on a background thread
- Peak CPU / RAM / disk / GPU util / GPU memory tracking
- Timeout support with process-group kill
- Per-repo JSON result files + summary JSON
- Continue to next repo even when one fails

Command template variables:
- {repo_name}
- {repo_path}

Example:
  python3 run_repos_monitor.py \
    --repos-file repos_test.txt \
    --repos-root . \
    --command-template "bash envbench/run.sh {repo_path}" \
    --output-dir monitor_results \
    --timeout 1800
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value.strip())
    except (TypeError, ValueError, AttributeError):
        return None


def query_gpu_metrics() -> Tuple[Optional[float], Optional[float]]:
    """Return (gpu_util_percent, gpu_memory_mb) for GPU 0 via nvidia-smi."""
    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None

    if res.returncode != 0 or not res.stdout.strip():
        return None, None

    first_line = res.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in first_line.split(",")]
    if len(parts) < 2:
        return None, None

    return _safe_float(parts[0]), _safe_float(parts[1])


def _kill_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Terminate process group first, then force kill if needed."""
    if proc.poll() is not None:
        return

    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None

    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except OSError:
            pass

        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
            return

    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return slug.strip("_") or "repo"


def _repo_name_from_entry(entry: str) -> str:
    e = entry.strip()
    if e.endswith(".git"):
        e = e[:-4]
    if "/" in e:
        return e.rstrip("/").split("/")[-1]
    return e


def load_repo_entries(repos_file: Path) -> List[str]:
    entries: List[str] = []
    with repos_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entries.append(line)
    return entries


def resolve_repo_path(entry: str, repos_root: Path) -> Tuple[str, Path]:
    name = _repo_name_from_entry(entry)

    if entry.startswith("http://") or entry.startswith("https://"):
        return name, repos_root / name

    p = Path(entry).expanduser()
    if p.is_absolute():
        return name, p

    return name, repos_root / p


def clone_if_needed(entry: str, repo_path: Path, clone_missing: bool) -> Optional[str]:
    if repo_path.exists():
        return None

    if not (entry.startswith("http://") or entry.startswith("https://")):
        return f"Repository path does not exist: {repo_path}"

    if not clone_missing:
        return f"Repository not found locally: {repo_path} (use --clone-missing)"

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", entry, str(repo_path)]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        err = (res.stderr or "").strip() or "git clone failed"
        return f"Clone failed: {err}"

    return None


def run_monitored_command(
    command: str,
    cwd: Path,
    timeout_seconds: Optional[float],
    sample_interval: float,
) -> Dict[str, Any]:
    if sample_interval <= 0:
        raise ValueError("sample_interval must be > 0")

    peaks: Dict[str, float] = {
        "peak_cpu_percent": 0.0,
        "peak_ram_mb": 0.0,
        "peak_disk_mb": 0.0,
        "peak_gpu_util_percent": 0.0,
        "peak_gpu_memory_mb": 0.0,
    }
    stop_event = threading.Event()

    def monitor_loop() -> None:
        psutil.cpu_percent(interval=None)
        while not stop_event.is_set():
            cpu = psutil.cpu_percent(interval=None)
            peaks["peak_cpu_percent"] = max(peaks["peak_cpu_percent"], cpu)

            vm = psutil.virtual_memory()
            peaks["peak_ram_mb"] = max(peaks["peak_ram_mb"], vm.used / (1024 * 1024))

            du = psutil.disk_usage("/")
            peaks["peak_disk_mb"] = max(peaks["peak_disk_mb"], du.used / (1024 * 1024))

            gpu_util, gpu_mem = query_gpu_metrics()
            if gpu_util is not None:
                peaks["peak_gpu_util_percent"] = max(peaks["peak_gpu_util_percent"], gpu_util)
            if gpu_mem is not None:
                peaks["peak_gpu_memory_mb"] = max(peaks["peak_gpu_memory_mb"], gpu_mem)

            stop_event.wait(sample_interval)

    start = time.perf_counter()
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        shell=True,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
    finally:
        stop_event.set()
        monitor_thread.join(timeout=max(1.0, sample_interval * 3))

    runtime = time.perf_counter() - start

    return {
        "runtime": round(runtime, 3),
        "peak_cpu_percent": round(peaks["peak_cpu_percent"], 2),
        "peak_ram_mb": round(peaks["peak_ram_mb"], 2),
        "peak_disk_mb": round(peaks["peak_disk_mb"], 2),
        "peak_gpu_util_percent": round(peaks["peak_gpu_util_percent"], 2),
        "peak_gpu_memory_mb": round(peaks["peak_gpu_memory_mb"], 2),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a command sequentially over repos with resource monitoring."
    )
    parser.add_argument("--repos-file", required=True, help="Path to repo list file.")
    parser.add_argument(
        "--command-template",
        required=True,
        help="Command to run per repo. Supports {repo_name} and {repo_path} placeholders.",
    )
    parser.add_argument(
        "--repos-root",
        default=".",
        help="Base directory used to resolve relative repo paths/URLs (default: .)",
    )
    parser.add_argument(
        "--output-dir",
        default="monitor_results",
        help="Directory to write per-repo JSON and summary.json",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Per-repo timeout in seconds (optional).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Sampling interval in seconds (default: 0.5).",
    )
    parser.add_argument(
        "--clone-missing",
        action="store_true",
        help="Clone URL entries if missing locally.",
    )
    parser.add_argument(
        "--no-stdout-stderr",
        action="store_true",
        help="Do not store stdout/stderr in result JSON files.",
    )

    args = parser.parse_args()

    repos_file = Path(args.repos_file).expanduser().resolve()
    repos_root = Path(args.repos_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = load_repo_entries(repos_file)
    all_results: List[Dict[str, Any]] = []

    for idx, entry in enumerate(entries, start=1):
        repo_name, repo_path = resolve_repo_path(entry, repos_root)
        print(f"[{idx}/{len(entries)}] {repo_name}")

        clone_error = clone_if_needed(entry, repo_path, args.clone_missing)
        if clone_error:
            result = {
                "repo_name": repo_name,
                "repo_path": str(repo_path),
                "runtime": 0.0,
                "peak_cpu_percent": 0.0,
                "peak_ram_mb": 0.0,
                "peak_disk_mb": 0.0,
                "peak_gpu_util_percent": 0.0,
                "peak_gpu_memory_mb": 0.0,
                "exit_code": None,
                "timed_out": False,
                "status": "error",
                "error": clone_error,
            }
            all_results.append(result)
        else:
            command = args.command_template.format(
                repo_name=repo_name,
                repo_path=shlex.quote(str(repo_path)),
            )
            metrics = run_monitored_command(
                command=command,
                cwd=repo_path,
                timeout_seconds=args.timeout,
                sample_interval=args.interval,
            )

            status = "ok"
            if metrics["timed_out"]:
                status = "timeout"
            elif metrics["exit_code"] != 0:
                status = "error"

            result = {
                "repo_name": repo_name,
                "repo_path": str(repo_path),
                "runtime": metrics["runtime"],
                "peak_cpu_percent": metrics["peak_cpu_percent"],
                "peak_ram_mb": metrics["peak_ram_mb"],
                "peak_disk_mb": metrics["peak_disk_mb"],
                "peak_gpu_util_percent": metrics["peak_gpu_util_percent"],
                "peak_gpu_memory_mb": metrics["peak_gpu_memory_mb"],
                "exit_code": metrics["exit_code"],
                "timed_out": metrics["timed_out"],
                "status": status,
            }

            if not args.no_stdout_stderr:
                result["stdout"] = metrics["stdout"]
                result["stderr"] = metrics["stderr"]

            all_results.append(result)

        out_name = f"{idx:03d}_{_slugify(repo_name)}.json"
        out_path = output_dir / out_name
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(all_results[-1], f, indent=2, sort_keys=True)

    summary = {
        "total": len(all_results),
        "ok": sum(1 for r in all_results if r["status"] == "ok"),
        "error": sum(1 for r in all_results if r["status"] == "error"),
        "timeout": sum(1 for r in all_results if r["status"] == "timeout"),
        "results": all_results,
    }

    with (output_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    print(f"Wrote {len(all_results)} repo result files to {output_dir}")
    print(f"Summary: {summary['ok']} ok, {summary['error']} error, {summary['timeout']} timeout")


if __name__ == "__main__":
    main()
