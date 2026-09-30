from __future__ import annotations

from pathlib import Path
import hashlib
import zipfile

from tqdm import tqdm

from . import net
from .log import log
from .polite import RateLimiter


def _readable_zip(dest: Path) -> bool:
    try:
        with zipfile.ZipFile(dest) as z:
            z.namelist()
        return True
    except (OSError, zipfile.BadZipFile):
        return False


def download(url: str, dest: Path, timeout: float = 120.0,
             limiter: RateLimiter | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        if _readable_zip(dest):
            log.debug("skip %s (%d bytes on disk)", dest.name, dest.stat().st_size)
            return dest
        log.warning("re-downloading unreadable %s (%d bytes on disk)",
                    dest.name, dest.stat().st_size)
        dest.unlink()
    if limiter:
        limiter.wait()
    log.info("download %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with net.stream_get(url, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0) or 0)
        with open(tmp, "wb") as f, tqdm(total=total, unit="B",
                                        unit_scale=True, desc=dest.name,
                                        disable=total == 0) as bar:
            for chunk in r.iter_bytes(chunk_size=1 << 15):
                f.write(chunk)
                bar.update(len(chunk))
    tmp.replace(dest)
    log.debug("saved %s (%d bytes)", dest.name, dest.stat().st_size)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    log.debug("sha256 %s %s", digest[:16], path.name)
    return digest


def filename_for_url(url: str) -> str:
    return url.split("?")[0].rstrip("/").split("/")[-1] or "download.zip"
