from __future__ import annotations
import hashlib
from pathlib import Path

import httpx
from tqdm import tqdm

from .config import HEADERS
from .log import log
from .polite import RateLimiter


def download(url: str, dest: Path, timeout: int = 120,
             limiter: RateLimiter | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        log.debug("skip %s (%d bytes on disk)", dest.name, dest.stat().st_size)
        return dest
    if limiter:
        limiter.wait()
    log.info("download %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, headers=HEADERS, timeout=timeout,
                      follow_redirects=True) as r:
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
