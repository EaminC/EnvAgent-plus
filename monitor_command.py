#!/usr/bin/env python3
"""Run a shell command while monitoring peak system resource usage.

Outputs a JSON object with:
  - runtime
  - peak_cpu_percent
  - peak_ram_mb
  - peak_disk_mb
  - peak_gpu_util_percent
  - peak_gpu_memory_mb
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import threading
import time
from typing import Any, Dict, Optional, Tuple

import psutil


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value.strip())
    except (TypeError, ValueError, AttributeError):
        return None


def query_gpu_metrics() -> Tuple[Optional[float], Optional[float]]:
    """Return (gpu_util_percent, gpu_memory_mb) for GPU 0 using nvidia-smi.

    If nvidia-smi is unavailable or fails, returns (None, None).
    """
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

    gpu_util = _safe_float(parts[0])
    gpu_mem = _safe_float(parts[1])
    return gpu_util, gpu_mem


def _kill_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Try to terminate the full process group, then force kill if needed."""
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


def run_command_with_monitoring(
    command: str,
    timeout_seconds: Optional[float] = None,
    sample_interval: float = 0.5,
) -> Dict[str, Any]:
    """Run command and return runtime + peak metrics as a dictionary.

    Args:
        command: Shell command to execute.
        timeout_seconds: Optional timeout. If exceeded, process is killed.
        sample_interval: Polling interval in seconds for resource sampling.
    """
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
            ram_mb = vm.used / (1024 * 1024)
            peaks["peak_ram_mb"] = max(peaks["peak_ram_mb"], ram_mb)

            du = psutil.disk_usage("/")
            disk_mb = du.used / (1024 * 1024)
            peaks["peak_disk_mb"] = max(peaks["peak_disk_mb"], disk_mb)

            gpu_util, gpu_mem = query_gpu_metrics()
            if gpu_util is not None:
                peaks["peak_gpu_util_percent"] = max(
                    peaks["peak_gpu_util_percent"], gpu_util
                )
            if gpu_mem is not None:
                peaks["peak_gpu_memory_mb"] = max(
                    peaks["peak_gpu_memory_mb"], gpu_mem
                )

            stop_event.wait(sample_interval)

    start = time.perf_counter()
    proc = subprocess.Popen(
        command,
        shell=True,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    try:
        proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        proc.communicate()
    finally:
        stop_event.set()
        monitor_thread.join(timeout=max(1.0, sample_interval * 3))

    runtime = time.perf_counter() - start

    result: Dict[str, Any] = {
        "runtime": round(runtime, 3),
        "peak_cpu_percent": round(peaks["peak_cpu_percent"], 2),
        "peak_ram_mb": round(peaks["peak_ram_mb"], 2),
        "peak_disk_mb": round(peaks["peak_disk_mb"], 2),
        "peak_gpu_util_percent": round(peaks["peak_gpu_util_percent"], 2),
        "peak_gpu_memory_mb": round(peaks["peak_gpu_memory_mb"], 2),
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a command with resource monitoring and JSON output."
    )
    parser.add_argument(
        "command",
        help="Shell command to run (quote it if it has spaces or shell operators).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds. If exceeded, process is killed.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Sampling interval in seconds (default: 0.5).",
    )

    args = parser.parse_args()
    result = run_command_with_monitoring(
        command=args.command,
        timeout_seconds=args.timeout,
        sample_interval=args.interval,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()