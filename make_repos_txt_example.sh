#!/usr/bin/env bash
# Generate an example repos.txt showing expected format
set -euo pipefail

cat > repos.txt << 'EOF'
# One GitHub repo URL per line. Lines starting with # are ignored.
# Blank lines are ignored too.

https://github.com/wonglkd/Baleen-FAST24
https://github.com/BurntSushi/ripgrep
# Add more below...
EOF

echo "Example repos.txt written to ./repos.txt"
