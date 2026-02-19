# Key Results

This folder contains consolidated outputs for the 27 repositories matched between `Label/hardware.json` and `EnvAgent-plus/logs`.

## Included Files

- `cpu_comparison.png`
- `ram_comparison.png`
- `disk_comparison.png`
- `gpu_comparison.png`
- `sufficiency_summary.json`
- `envagent_vs_actual_table.csv`

## Core Metrics

- Actual reserved sufficient ratio (all 4 resources): `0/27 = 0.0000`
- AI predicted sufficient ratio (all 4 resources): `8/27 = 0.2963`

Average redundancy percentages:

- Reserved resources:
  - CPU: `-100.0%`
  - RAM: `-100.0%`
  - Disk: `-100.0%`
  - GPU: `N/A` (no positive GPU requirement in this matched set)
- AI predicted resources:
  - CPU: `135.19%`
  - RAM: `456.02%`
  - Disk: `116.20%`
  - GPU: `N/A` (no positive GPU requirement in this matched set)
