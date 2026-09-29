from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import struct
import zipfile
import zlib

from .filters import (extract_lei, extract_period_end, esef_entry_name,
                      language_of)

IDENTIFIER_RE = re.compile(
    r"<(?:link:schemaRef|xbrli:identifier|identifier)[^>]*>\s*([0-9A-Z]{18}[0-9]{2})\s*<",
    re.IGNORECASE)
PERIOD_RE = re.compile(
    r"<(?:xbrli:endDate|xbrli:instant)[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*<",
    re.IGNORECASE)
IXHDR_RE = re.compile(r"<ix:header", re.IGNORECASE)
IXBRL_RE = re.compile(r"(?:xmlns:ix=|in\s+XBRL|iXBRL|xbrli:context)", re.IGNORECASE)
TEXT_ENTRY_RE = re.compile(r"\.(xhtml|html|htm)$", re.IGNORECASE)
SCHEMA_ENTRY_RE = re.compile(r"\.(xsd)$", re.IGNORECASE)

EOCD_SIG = b"PK\x05\x06"
CD_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"
TAIL_BYTES = 65536
MAX_ENTRY_BYTES = 3_000_000


@dataclass
class EsefInfo:
    lei: str | None = None
    period_end: str | None = None
    language: str | None = None
    has_ixbrl: bool = False
    xhtml_files: list[str] = field(default_factory=list)
    taxonomy_files: list[str] = field(default_factory=list)
    all_files: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    is_esef: bool
    reason: str
    entries: list[str] = field(default_factory=list)
    has_ixbrl: bool = False
    has_xhtml: bool = False
    has_taxonomy: bool = False
    reachable: bool = True


def _classify(names: list[str]) -> tuple[bool, bool, bool]:
    xhtml = [n for n in names if TEXT_ENTRY_RE.search(n)]
    schema = [n for n in names if SCHEMA_ENTRY_RE.search(n)]
    return bool(xhtml), bool(schema), bool(xhtml or schema)


def classify_names(names: list[str]) -> str:
    has_xhtml, has_tax, any_doc = _classify(names)
    if not any_doc:
        return "no xhtml or xsd entries"
    if has_xhtml and has_tax:
        return "xhtml+xsd present"
    if has_xhtml:
        return "xhtml present, no xsd"
    return "xsd only"


def inspect_zip(path: Path) -> EsefInfo:
    info = EsefInfo()
    fname = path.name
    info.lei = extract_lei(fname)
    info.period_end = extract_period_end(fname)
    info.language = language_of(fname)
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            info.all_files = names
            info.xhtml_files = [n for n in names
                                if TEXT_ENTRY_RE.search(n)]
            info.taxonomy_files = [n for n in names
                                   if n.lower().endswith((".xsd", ".xml", ".xbrl"))]
            for x in info.xhtml_files[:3]:
                if not info.language:
                    info.language = language_of(x)
                if not info.lei:
                    found = extract_lei(x)
                    if found:
                        info.lei = found
                if not info.period_end:
                    found = extract_period_end(x)
                    if found:
                        info.period_end = found
                try:
                    text = z.read(x).decode("utf-8", errors="ignore")
                except KeyError:
                    continue
                if IXHDR_RE.search(text):
                    info.has_ixbrl = True
                if not info.lei:
                    mm = IDENTIFIER_RE.search(text)
                    if mm:
                        info.lei = mm.group(1).upper()
                dates = PERIOD_RE.findall(text)
                if dates:
                    latest = sorted(dates)[-1]
                    if not info.period_end or latest > info.period_end:
                        info.period_end = latest
                if info.has_ixbrl and info.lei and info.period_end:
                    break
    except zipfile.BadZipFile:
        pass
    return info


def _find_eocd(tail: bytes) -> int:
    idx = tail.rfind(EOCD_SIG)
    return idx


def _parse_central_directory(blob: bytes) -> list[tuple[str, int, int, int]]:
    entries: list[tuple[str, int, int, int]] = []
    pos = 0
    while pos + 46 <= len(blob):
        if blob[pos:pos + 4] != CD_SIG:
            nxt = blob.find(CD_SIG, pos)
            if nxt == -1:
                break
            pos = nxt
            continue
        (method,) = struct.unpack_from("<H", blob, pos + 10)
        (comp_size,) = struct.unpack_from("<I", blob, pos + 20)
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", blob, pos + 28)
        (local_off,) = struct.unpack_from("<I", blob, pos + 42)
        name = blob[pos + 46:pos + 46 + name_len].decode("utf-8", errors="ignore")
        entries.append((name, method, comp_size, local_off))
        pos += 46 + name_len + extra_len + comment_len
    return entries


def _fetch_range(client, url: str, start: int | None = None,
                 end: int | None = None) -> bytes:
    headers = {}
    if start is None:
        headers["Range"] = f"bytes=-{TAIL_BYTES}"
    else:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"
    r = client.get(url, headers=headers)
    r.raise_for_status()
    return r.content


def _read_entry_head(client, url: str, method: int, comp_size: int,
                     local_off: int, want: int) -> bytes | None:
    if comp_size <= 0:
        return None
    want = min(comp_size, want)
    head = _fetch_range(client, url, local_off, local_off + 29)
    if head[:4] != LOCAL_SIG:
        return None
    name_len, extra_len = struct.unpack_from("<HH", head, 26)
    data_start = local_off + 30 + name_len + extra_len
    raw = _fetch_range(client, url, data_start, data_start + want - 1)
    if method == 0:
        return raw
    if method == 8:
        try:
            return zlib.decompressobj(-15).decompress(raw)
        except zlib.error:
            return b""
    return None


def probe_remote(client, url: str, head_limit: int = 2,
                 sniff_bytes: int = 1_500_000) -> ProbeResult:
    try:
        tail = _fetch_range(client, url)
    except Exception as e:
        return ProbeResult(False, f"unreachable: {e}", reachable=False)
    eocd = _find_eocd(tail)
    if eocd == -1:
        return ProbeResult(False, "not a zip (no central directory)")
    if eocd + 22 > len(tail):
        return ProbeResult(False, "truncated central directory")
    cd_size, cd_offset = struct.unpack_from("<II", tail, eocd + 12)
    if cd_offset >= eocd:
        blob = tail[tail.find(CD_SIG, 0, eocd):eocd]
    else:
        try:
            blob = _fetch_range(client, url, cd_offset, cd_offset + cd_size - 1)
        except Exception as e:
            return ProbeResult(False, f"central directory fetch failed: {e}",
                               reachable=False)
    entries = _parse_central_directory(blob)
    if not entries:
        return ProbeResult(False, "empty central directory")
    names = [e[0] for e in entries]
    has_xhtml, has_tax, _ = _classify(names)
    if not has_xhtml and not has_tax:
        return ProbeResult(False, classify_names(names), names)
    named = [n for n in names if esef_entry_name(n)]
    text_entries = sorted(
        (e for e in entries if TEXT_ENTRY_RE.search(e[0])),
        key=lambda e: e[2], reverse=True)
    for name, method, comp_size, local_off in text_entries[:head_limit]:
        data = _read_entry_head(client, url, method, comp_size, local_off,
                                sniff_bytes)
        if not data:
            continue
        head = data.decode("utf-8", errors="ignore")
        if IXHDR_RE.search(head) or IXBRL_RE.search(head):
            return ProbeResult(True, "iXBRL markup in xhtml", names, True,
                               has_xhtml, has_tax)
    if named:
        return ProbeResult(True, f"ESEF entry name: {named[0].rsplit('/', 1)[-1]}",
                           names, False, has_xhtml, has_tax)
    if has_xhtml and has_tax:
        return ProbeResult(True, "xhtml+taxonomy, no iXBRL in head", names,
                           False, has_xhtml, has_tax)
    return ProbeResult(False, classify_names(names), names, False,
                       has_xhtml, has_tax)
