#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -q -e . 2>/dev/null || pip install -q -e .
python -m bvb_esef.cli crawl --out-dir data/out --zips-dir data/zips "$@"
echo "--- filings.json: $(python -c "import json;print(len(json.load(open('data/out/filings.json'))['filings']))" 2>/dev/null || echo ?) records"
