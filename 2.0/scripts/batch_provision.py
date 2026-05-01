#!/usr/bin/env python3
import os
import sys
import json
import argparse
import subprocess
import time
import re
import shutil
from collections import Counter
from pathlib import Path

# Ensure repository root is on sys.path so envboot can be imported
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

OPENRC = Path('/tmp/kvm_test_openrc.sh')
REPOS_FILE = Path('/home/cc/EnvAgent-plus/repos_test.txt')


class OutputLogger:
    """Log to both file and stdout."""
    def __init__(self, log_file):
        self.log_file = log_file
        self.file = open(log_file, 'w')
    
    def write(self, msg):
        self.file.write(msg)
        self.file.flush()
        sys.__stdout__.write(msg)
        sys.__stdout__.flush()
    
    def flush(self):
        self.file.flush()
        sys.__stdout__.flush()
    
    def close(self):
        self.file.close()
    
    def __del__(self):
        if hasattr(self, 'file'):
            try:
                self.file.close()
            except:
                pass

# Load openrc into env dict
def load_openrc(env):
    if not OPENRC.exists():
        print('OpenRC not found:', OPENRC)
        return env
    for line in OPENRC.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#') or not line.startswith('export '):
            continue
        key, val = line[len('export '):].split('=',1)
        val=val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val=val[1:-1]
        env[key]=val
    return env

def detect_failure_reason(out: str, provisioning_success: bool):
    if provisioning_success:
        return None
    if 'No fixed IP addresses available' in out:
        return 'No fixed IP addresses available'
    if 'No capacity available' in out or 'Not enough resources available' in out:
        return 'No capacity available'
    m = re.search(r'✗ ERROR:\s*(.+)', out)
    if m:
        return m.group(1).strip()
    m = re.search(r'Exception:\s*(.+)', out)
    if m:
        return m.group(1).strip()
    return 'Other exception'


def extract_info_json_path(out: str):
    m = re.search(r'Info saved to:\s*(\S+_info\.json)', out)
    if m:
        return Path(m.group(1)).expanduser()
    return None


def load_hardware_validation(info_json_path: Path):
    if not info_json_path or not info_json_path.exists():
        return None, None

    try:
        with open(info_json_path) as f:
            data = json.load(f)
    except Exception:
        return None, None

    hardware_validation = data.get('hardware_validation') or {}
    return data, hardware_validation


def parse_single_log(out: str):
    lease_success = ('✓ SUCCESS: Lease created with' in out) or ('✓ Lease is ACTIVE' in out)
    provisioning_success = ('✓ Provisioning Complete!' in out) or ('✓ KVM instance is ACTIVE' in out)

    server_id = None
    flavor = None
    fip = None

    m_server = re.search(r'Server ID:\s*([0-9a-fA-F-]+)', out)
    if m_server:
        server_id = m_server.group(1)
    else:
        m_final = re.search(r'Final server_id:\s*([0-9a-fA-F-]+)', out)
        if m_final:
            server_id = m_final.group(1)

    m_node = re.search(r'Node Type:\s*(\S+)', out)
    if m_node:
        flavor = m_node.group(1)
    m_fip = re.search(r'Floating IP:\s*([^\s]+)', out)
    if m_fip:
        fip = m_fip.group(1)

    failure_reason = detect_failure_reason(out, provisioning_success)

    return {
        'lease_success': bool(lease_success),
        'provisioning_success': bool(provisioning_success),
        'failure_reason': failure_reason,
        'server_id': server_id,
        'flavor': flavor,
        'fip': fip,
    }


def run_batch(repos, log_dir, logger):
    # Import only when actually provisioning/deleting
    from envboot.osutil import conn

    results = []
    for idx, repo in enumerate(repos, 1):
        logger.write(f'\n=== RUN {idx}/{len(repos)}: {repo} ===\n')
        log_path = log_dir / f'run_{idx}.log'
        env = load_openrc(os.environ.copy())
        cmd = [
            env.get('PYTHON', '/home/cc/EnvAgent-plus/venv/bin/python'),
            '2.0/src/provision_v2.py',
            '--repo', repo,
            '--site', 'KVM@TACC',
            '--lease-duration', '2'
        ]
        logger.write(f'CMD: {" ".join(cmd)}\n')

        with open(log_path, 'wb') as lf:
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
                outb = b''
                for line in p.stdout:
                    lf.write(line)
                    lf.flush()
                    outb += line
                    logger.write(line.decode(errors='replace'))
                p.wait()
                rc = p.returncode
            except Exception as e:
                lf.write(str(e).encode())
                outb = str(e).encode()
                rc = -1

        out = outb.decode(errors='replace')
        metrics = parse_single_log(out)

        info_json_path = extract_info_json_path(out)
        info_json, hardware_validation = load_hardware_validation(info_json_path)

        normalized_json_path = log_dir / f'run_{idx}_info.json'
        if info_json:
            payload = dict(info_json)
            payload['repo'] = repo
            payload['run'] = idx
            payload['provisioning_success'] = metrics['provisioning_success']
            payload['hardware_validation'] = hardware_validation or payload.get('hardware_validation', {})
            payload['selected_flavor'] = payload.get('selected_flavor') or (hardware_validation or {}).get('selected_flavor')
            payload['hardware_match'] = payload.get('hardware_match')
            if payload['hardware_match'] is None:
                payload['hardware_match'] = (hardware_validation or {}).get('hardware_match')
            payload['undersized_reasons'] = payload.get('undersized_reasons') or (hardware_validation or {}).get('undersized_reasons', [])
            with open(normalized_json_path, 'w') as f:
                json.dump(payload, f, indent=2)
        elif info_json_path and info_json_path.exists():
            try:
                shutil.copy2(info_json_path, normalized_json_path)
            except Exception as e:
                logger.write(f'Could not copy info JSON for run {idx}: {e}\n')

        row = {
            'repo': repo,
            'rc': rc,
            'log': str(log_path),
            **metrics,
            'info_json': str(normalized_json_path) if normalized_json_path.exists() else (str(info_json_path) if info_json_path else None),
            'hardware_validation': hardware_validation or {},
        }
        results.append(row)

        if row.get('server_id'):
            try:
                os_conn = conn()
                logger.write(f'Deleting server {row["server_id"]}\n')
                try:
                    os_conn.compute.delete_server(row['server_id'])
                    logger.write(f'Delete requested for {row["server_id"]}\n')
                except Exception as e:
                    logger.write(f'Delete failed for {row["server_id"]}: {e}\n')
            except Exception as e:
                logger.write(f'Could not connect to OpenStack to delete server: {e}\n')

        time.sleep(12)
    return results


def parse_existing_logs(repos, log_dir, logger):
    results = []
    for idx, repo in enumerate(repos, 1):
        log_path = log_dir / f'run_{idx}.log'
        if log_path.exists():
            out = log_path.read_text(errors='replace')
            rc = None
            m_rc = re.search(r'Command exited with code\s+(\d+)', out)
            if m_rc:
                rc = int(m_rc.group(1))
            info_json_path = log_dir / f'run_{idx}_info.json'
            if not info_json_path.exists():
                extracted_info_json = extract_info_json_path(out)
                if extracted_info_json and extracted_info_json.exists():
                    info_json_path = extracted_info_json
            info_json, hardware_validation = load_hardware_validation(info_json_path)
            row = {
                'repo': repo,
                'rc': rc,
                'log': str(log_path),
                **parse_single_log(out),
                'info_json': str(info_json_path) if info_json_path else None,
                'hardware_validation': hardware_validation or (info_json.get('hardware_validation', {}) if info_json else {}),
            }
        else:
            row = {
                'repo': repo,
                'rc': None,
                'log': str(log_path),
                'lease_success': False,
                'provisioning_success': False,
                'failure_reason': 'Missing log',
                'server_id': None,
                'flavor': None,
                'fip': None,
                'info_json': None,
                'hardware_validation': {},
            }
        results.append(row)
    return results


def print_summary(results, logger):
    total = len(results)
    lease_successes = sum(1 for r in results if r['lease_success'])
    provisioning_successes = sum(1 for r in results if r['provisioning_success'])

    def get_hw(r):
        hw = r.get('hardware_validation') or {}
        if not hw and r.get('info_json') and Path(r['info_json']).exists():
            try:
                with open(r['info_json']) as f:
                    data = json.load(f)
                hw = data.get('hardware_validation') or {}
            except Exception:
                hw = {}
        return hw

    hardware_matches = []
    gpu_required_count = 0
    gpu_mismatch_count = 0
    undersized_count = 0
    undersized_reasons = Counter()

    for r in results:
        hw = get_hw(r)
        if hw:
            match = hw.get('hardware_match')
            if match is not None:
                hardware_matches.append(bool(match))
                if not match:
                    undersized_count += 1
                    for reason in hw.get('undersized_reasons', []) or []:
                        undersized_reasons[reason] += 1
            if hw.get('predicted_gpu_required'):
                gpu_required_count += 1
                if not hw.get('hardware_match'):
                    gpu_mismatch_count += 1

    reasons = Counter()
    for r in results:
        if not r['provisioning_success']:
            reasons[r['failure_reason'] or 'Other exception'] += 1

    # Detect if this is a KVM@TACC run by checking first log
    is_kvm = False
    if results and results[0].get('log'):
        log_path = Path(results[0]['log'])
        if log_path.exists():
            log_text = log_path.read_text(errors='ignore')
            is_kvm = 'KVM@TACC' in log_text or 'KVM' in log_text

    logger.write('\n=== SUMMARY ===\n')
    logger.write(f'Total repos: {total}\n')
    
    if is_kvm:
        # For KVM runs: skip lease_success (KVM does not use Blazar); report provisioning_success only
        logger.write('⚠  NOTE: KVM@TACC does not use Blazar reservation; lease_success metric is not applicable.\n')
        logger.write(f'Provisioning successes: {provisioning_successes}\n')
        logger.write(f'KVM provisioning success rate: {provisioning_successes}/{total} = {(provisioning_successes/total if total else 0):.2%}\n')
        if hardware_matches:
            hardware_match_rate = sum(1 for m in hardware_matches if m) / len(hardware_matches)
            logger.write(f'Hardware match rate: {sum(1 for m in hardware_matches if m)}/{len(hardware_matches)} = {hardware_match_rate:.2%}\n')
        else:
            logger.write('Hardware match rate: unavailable\n')
        logger.write(f'GPU-required count: {gpu_required_count}\n')
        logger.write(f'GPU-mismatch count: {gpu_mismatch_count}\n')
        logger.write(f'Undersized count: {undersized_count}\n')
        if undersized_reasons:
            logger.write('Top undersized reasons:\n')
            for reason, count in undersized_reasons.most_common():
                logger.write(f'  - {reason}: {count}\n')
    else:
        # For bare-metal runs: report both metrics
        logger.write(f'Lease successes: {lease_successes}\n')
        logger.write(f'Lease success rate: {lease_successes}/{total} = {(lease_successes/total if total else 0):.2%}\n')
        logger.write(f'Provisioning successes: {provisioning_successes}\n')
        logger.write(f'Provisioning success rate: {provisioning_successes}/{total} = {(provisioning_successes/total if total else 0):.2%}\n')
    
    logger.write('Failure reason breakdown:\n')
    for reason, count in reasons.items():
        logger.write(f'  - {reason}: {count}\n')

    for r in results:
        logger.write(f'{r}\n')



def main():
    parser = argparse.ArgumentParser(description='Batch provisioning runner and log parser')
    parser.add_argument('--output-folder', type=str, default='logs_kvm', help='Output folder for logs and results (default: logs_kvm)')
    parser.add_argument('--repos-file', type=str, default=str(REPOS_FILE), help='Repository list file to use for the batch run')
    parser.add_argument('--parse-only', action='store_true', help='Parse existing run_*.log files only; do not execute provisioning.')
    args = parser.parse_args()

    # Create output folder
    log_dir = Path(args.output_folder)
    log_dir.mkdir(exist_ok=True, parents=True)
    
    # Create master log file
    master_log = log_dir / 'batch_provision.log'
    logger = OutputLogger(str(master_log))
    
    try:
        repos_file = Path(args.repos_file)
        repos = [r.strip() for r in repos_file.read_text().splitlines() if r.strip()]

        if args.parse_only:
            results = parse_existing_logs(repos, log_dir, logger)
        else:
            results = run_batch(repos, log_dir, logger)

        print_summary(results, logger)

        # Save summary as JSON
        summary_json = log_dir / 'summary.json'
        with open(summary_json, 'w') as f:
            json.dump(results, f, indent=2)

        logger.write(f'\n✓ Logs saved to {log_dir}\n')
        logger.write(f'✓ Master log: {master_log}\n')
        logger.write(f'✓ Summary JSON: {summary_json}\n')
    finally:
        logger.close()


if __name__ == '__main__':
    main()
