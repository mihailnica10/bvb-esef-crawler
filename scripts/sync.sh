#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

LOCK=data/out/.sync.lock
mkdir -p "$(dirname "$LOCK")"

if [ -n "${BVB_ESEF_NO_LOCK:-}" ]; then
  run_locked() { "$@"; }
elif command -v flock >/dev/null 2>&1; then
  run_locked() { flock -w 3600 "$LOCK" "$@"; }
else
  echo "flock not available, running without a lock" >&2
  run_locked() { "$@"; }
fi

PY="${BVB_ESEF_PYTHON:-python3}"
PIP_FLAGS=(--disable-pip-version-check --no-input)

if ! "$PY" -c "import bvb_esef" >/dev/null 2>&1; then
  echo "bvb_esef not importable, installing (offline-friendly)"
  "$PY" -m pip install "${PIP_FLAGS[@]}" --prefer-binary -e . ||
    "$PY" -m pip install "${PIP_FLAGS[@]}" -e .
else
  echo "bvb_esef already importable, skipping install"
fi

run_locked "$PY" -m bvb_esef.cli crawl --out-dir data/out --zips-dir data/zips "$@"

"$PY" - <<'PY'
import json
import pathlib

out = pathlib.Path("data/out")
try:
    index = json.loads((out / "filings.json").read_text(encoding="utf-8"))
    print(f"--- filings.json: {len(index.get('filings', []))} records")
except (OSError, ValueError):
    print("--- filings.json: unavailable")
try:
    side = json.loads((out / "compliance.json").read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for entry in side.values():
        key = str(entry.get("status", "?")) + (
            "" if entry.get("complete", True) else " (incomplete)")
        counts[key] = counts.get(key, 0) + 1
    print("--- compliance.json: "
          + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty"))
except (OSError, ValueError):
    print("--- compliance.json: none")
PY
