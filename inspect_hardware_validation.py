#!/usr/bin/env python3
"""
Inspect hardware validation from a recent provisioning run.
Shows predicted vs actual hardware and match status clearly.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def inspect_latest_provision():
    """Find and inspect the latest provisioning JSON output."""
    ws = Path('/home/cc/EnvAgent-plus')
    
    # Find latest *_info.json file
    json_files = sorted(ws.glob('auto-server-*_info.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not json_files:
        print("❌ No provisioning JSON files found. Run a provisioning first.")
        return 1
    
    latest = json_files[0]
    print(f"\n{'='*70}")
    print(f"INSPECTING LATEST PROVISIONING OUTPUT")
    print(f"{'='*70}")
    print(f"File: {latest.name}")
    print(f"Time: {datetime.fromtimestamp(latest.stat().st_mtime)}")
    
    try:
        with open(latest) as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read JSON: {e}")
        return 1
    
    # Extract key info
    print(f"\n{'─'*70}")
    print("PROVISIONING DETAILS")
    print(f"{'─'*70}")
    print(f"Server ID:          {data.get('server_id', 'N/A')}")
    print(f"Server Name:        {data.get('server_name', 'N/A')}")
    print(f"Provisioning Type:  {data.get('provisioning_type', 'N/A')}")
    print(f"Node Type:          {data.get('node_type', 'N/A')}")
    
    # Hardware validation
    hw_val = data.get('hardware_validation', {})
    print(f"\n{'─'*70}")
    print("HARDWARE VALIDATION")
    print(f"{'─'*70}")
    
    print(f"\nPredicted Requirements:")
    print(f"  CPU:             {hw_val.get('predicted_cpu', 'N/A')} cores")
    print(f"  RAM:             {hw_val.get('predicted_ram_gb', 'N/A')} GB")
    print(f"  Disk:            {hw_val.get('predicted_disk_gb', 'N/A')} GB")
    print(f"  GPU Required:    {hw_val.get('predicted_gpu_required', 'N/A')}")
    
    print(f"\nActual Provisioned (Flavor: {hw_val.get('selected_flavor', 'N/A')}):")
    print(f"  CPU:             {hw_val.get('actual_cpu', 'N/A')} cores")
    print(f"  RAM:             {hw_val.get('actual_ram_gb', 'N/A')} GB")
    print(f"  Disk:            {hw_val.get('actual_disk_gb', 'N/A')} GB")
    
    # Match status
    match = hw_val.get('hardware_match')
    print(f"\n{'─'*70}")
    print("MATCH STATUS")
    print(f"{'─'*70}")
    
    if match is True:
        print(f"✓ PASS: Hardware matches all predicted requirements")
    elif match is False:
        print(f"⚠ FAIL: VM provisioned but undersized for predicted workload")
        reasons = hw_val.get('undersized_reasons', [])
        if reasons:
            print(f"\nReasons:")
            for reason in reasons:
                print(f"  • {reason}")
    else:
        print(f"? UNKNOWN: Hardware matching not evaluated")
    
    gpu_warning = hw_val.get('gpu_warning')
    if gpu_warning:
        print(f"\n{gpu_warning}")
    
    print(f"\n{'='*70}\n")
    
    return 0

if __name__ == '__main__':
    sys.exit(inspect_latest_provision())
