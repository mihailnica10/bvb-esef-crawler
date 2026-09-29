from __future__ import annotations
import shutil
import subprocess
from pathlib import Path


def arelle_available() -> bool:
    return shutil.which("arelleCmdLine") is not None


def validate(path: Path, timeout: int = 300) -> tuple[bool, str]:
    if not arelle_available():
        return False, "arelleCmdLine not on PATH (pip install arelle-release)"
    cmd = ["arelleCmdLine", "--plugins", "validate/ESEF",
           "-f", str(path), "--noCertificateCheck"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        log = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0 and "error" not in log.lower().split("warning")[0][-500:]
        return ok, log[-4000:]
    except subprocess.TimeoutExpired:
        return False, "Arelle timeout"
