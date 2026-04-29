#!/bin/bash

source venv/bin/activate

FILES=(
  "auto-server-202604281850_info.json"
  "auto-server-202604281906_info.json"
  "auto-server-202604281920_info.json"
  "auto-server-202604281930_info.json"
  "auto-server-202604281941_info.json"
  "auto-server-202604281955_info.json"
  "auto-server-202604282009_info.json"
  "auto-server-202604282023_info.json"
  "auto-server-202604282036_info.json"
  "auto-server-202604282048_info.json"
  "auto-server-202604282100_info.json"
  "auto-server-202604282111_info.json"
  "auto-server-202604282122_info.json"
  "auto-server-202604282135_info.json"
  "auto-server-202604282145_info.json"
)

mkdir -p results

for file in "${FILES[@]}"; do
  basename="${file%_info.json}"
  outfile="results/${basename}_actual_reserved_info.json"
  
  echo "Inspecting $file -> $outfile"
  python 2.0/src/inspect_reserved_info.py --info "$file" --out "$outfile" --prefer-snapshot
  
  if [ $? -eq 0 ]; then
    echo "  ✓ Success"
  else
    echo "  ✗ Failed"
  fi
done

echo ""
echo "Inspection batch complete. Running analysis..."
python analysis_reserved_vs_actual.py
