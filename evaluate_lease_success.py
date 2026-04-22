#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate reservation lease success rate from resource prediction JSON files."
    )
    parser.add_argument(
        "--predictions-dir",
        default="./predictions",
        help="Directory containing prediction JSON files (default: ./predictions)",
    )
    parser.add_argument(
        "--output-csv",
        default="lease_eval_results.csv",
        help="Output CSV path (default: lease_eval_results.csv)",
    )
    parser.add_argument(
        "--log-file",
        default="lease_logs.txt",
        help="Log file path (default: lease_logs.txt)",
    )
    parser.add_argument(
        "--cpu-node-type",
        default="compute",
        help='Node type for non-GPU requests (default: "compute")',
    )
    parser.add_argument(
        "--gpu-node-type",
        default="gpu_a100",
        help='Node type for GPU requests (default: "gpu_a100")',
    )
    parser.add_argument(
        "--nodes",
        type=int,
        default=1,
        help="Nodes per lease request (default: 1)",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=60,
        help="Lease duration in minutes (default: 60)",
    )
    parser.add_argument(
        "--start-offset-minutes",
        type=int,
        default=2,
        help="Lease start offset from now in minutes (default: 2)",
    )
    parser.add_argument(
        "--lease-timeout-seconds",
        type=int,
        default=90,
        help="Timeout for each lease create command (default: 90)",
    )
    parser.add_argument(
        "--lease-prefix",
        default="lease-eval",
        help="Prefix for generated lease names (default: lease-eval)",
    )
    parser.add_argument(
        "--cleanup-success",
        action="store_true",
        help="Delete lease immediately after successful creation",
    )
    return parser.parse_args()


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )


def load_predictions(predictions_dir: Path) -> List[Dict]:
    if not predictions_dir.exists():
        raise FileNotFoundError(f"Predictions directory not found: {predictions_dir}")

    prediction_files = sorted(predictions_dir.glob("*.json"))
    if not prediction_files:
        raise FileNotFoundError(f"No JSON files found in: {predictions_dir}")

    predictions: List[Dict] = []
    for path in prediction_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.warning("Skipping unreadable JSON file %s: %s", path, e)
            continue

        if isinstance(data, dict):
            predictions.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    predictions.append(item)
                else:
                    logging.warning("Skipping non-object item in %s", path)
        else:
            logging.warning("Skipping unsupported JSON structure in %s", path)

    return predictions


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def map_node_type(pred: Dict, cpu_node_type: str, gpu_node_type: str) -> str:
    return gpu_node_type if to_bool(pred.get("gpu", False)) else cpu_node_type


def classify_failure(error_text: str) -> str:
    text = (error_text or "").lower()

    capacity_patterns = [
        "not enough resources",
        "no available",
        "insufficient",
        "allocation",
        "capacity",
        "exhausted",
    ]
    invalid_patterns = [
        "invalid",
        "bad request",
        "unknown argument",
        "resource_properties",
        "validation",
        "malformed",
        "not found",
    ]

    if any(p in text for p in capacity_patterns):
        return "capacity_shortage"
    if any(p in text for p in invalid_patterns):
        return "invalid_request"
    return "other_error"


def make_time_window(start_offset_minutes: int, duration_minutes: int) -> (str, str):
    now = dt.datetime.utcnow().replace(second=0, microsecond=0)
    start = now + dt.timedelta(minutes=start_offset_minutes)
    end = start + dt.timedelta(minutes=duration_minutes)
    # Chameleon examples commonly use "YYYY-MM-DD HH:MM"
    return start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M")


def lease_name(prefix: str, repo: str) -> str:
    slug = repo.rstrip("/").split("/")[-1]
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", slug).strip("-").lower() or "repo"
    stamp = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{slug}-{stamp}"


def create_lease(
    repo: str,
    node_type: str,
    nodes: int,
    start_date: str,
    end_date: str,
    timeout_seconds: int,
    prefix: str,
) -> Dict:
    lname = lease_name(prefix, repo)
    reservation_spec = (
        f"min={nodes},max={nodes},resource_type=physical:host,"
        f"resource_properties=[\"=\", \"$node_type\", \"{node_type}\"]"
    )

    cmd = [
        "openstack",
        "reservation",
        "lease",
        "create",
        "--reservation",
        reservation_spec,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        lname,
        "-f",
        "json",
    ]

    logging.info("Creating lease for repo=%s node_type=%s lease=%s", repo, node_type, lname)
    logging.debug("Command: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        message = stderr or stdout or f"openstack exited with code {result.returncode}"
        raise RuntimeError(message)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}

    return {
        "lease_name": lname,
        "lease_id": payload.get("id", ""),
        "raw_stdout": result.stdout,
    }


def delete_lease(lease_id: str, timeout_seconds: int = 60) -> None:
    if not lease_id:
        return
    cmd = ["openstack", "reservation", "lease", "delete", lease_id]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
    if result.returncode == 0:
        logging.info("Deleted successful test lease: %s", lease_id)
    else:
        logging.warning(
            "Could not delete lease %s: %s",
            lease_id,
            (result.stderr or result.stdout or "unknown error").strip(),
        )


def write_csv(output_csv: Path, rows: Iterable[Dict]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["repo", "cpu", "ram", "gpu", "success", "failure_type"]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()
    setup_logging(Path(args.log_file))

    logging.info("Loading predictions from %s", args.predictions_dir)
    predictions = load_predictions(Path(args.predictions_dir))
    logging.info("Loaded %d prediction objects", len(predictions))

    rows = []
    start_date, end_date = make_time_window(args.start_offset_minutes, args.duration_minutes)

    for pred in predictions:
        repo = str(pred.get("repo", "")).strip()
        cpu = pred.get("cpu")
        ram = pred.get("ram")
        gpu = to_bool(pred.get("gpu", False))

        row = {
            "repo": repo,
            "cpu": cpu,
            "ram": ram,
            "gpu": gpu,
            "success": False,
            "failure_type": "other_error",
        }

        try:
            if not repo:
                raise ValueError("Missing repo field")

            node_type = map_node_type(pred, args.cpu_node_type, args.gpu_node_type)
            lease_info = create_lease(
                repo=repo,
                node_type=node_type,
                nodes=args.nodes,
                start_date=start_date,
                end_date=end_date,
                timeout_seconds=args.lease_timeout_seconds,
                prefix=args.lease_prefix,
            )

            row["success"] = True
            row["failure_type"] = ""
            logging.info(
                "Lease SUCCESS repo=%s lease_id=%s",
                repo,
                lease_info.get("lease_id", ""),
            )

            if args.cleanup_success:
                delete_lease(lease_info.get("lease_id", ""))

        except subprocess.TimeoutExpired:
            row["failure_type"] = "other_error"
            logging.exception("Lease TIMEOUT repo=%s", repo)
        except Exception as e:
            error_text = str(e)
            row["failure_type"] = classify_failure(error_text)
            logging.exception("Lease FAILED repo=%s failure_type=%s", repo, row["failure_type"])

        rows.append(row)

    write_csv(Path(args.output_csv), rows)
    logging.info("Wrote results CSV: %s", args.output_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
