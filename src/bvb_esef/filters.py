from __future__ import annotations
import re

from .config import ESEF_KEYWORDS

LEI_RE = re.compile(r"(?<![0-9A-Z])([0-9A-Z]{18}[0-9]{2})(?![0-9A-Z])")
PERIOD_RE = re.compile(r"(19|20)\d{2}-\d{2}-\d{2}")
ZIP_RE = re.compile(r"\.zip(\?.*)?$", re.IGNORECASE)
TEXT_ENTRY_RE = re.compile(r"\.(xhtml|html|htm)$", re.IGNORECASE)


def is_zip_url(url: str) -> bool:
    return bool(ZIP_RE.search(url or ""))


def match_reason(title: str = "", url: str = "", anchor_text: str = "") -> str | None:
    blob = f"{title} {url} {anchor_text}".lower()
    if ".zip" in blob and any(k in blob for k in ESEF_KEYWORDS):
        return "esef-keyword+zip"
    if is_zip_url(url) and LEI_RE.search(url.upper()) and PERIOD_RE.search(url):
        return "lei+date-in-url"
    return None


def esef_entry_name(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return bool(TEXT_ENTRY_RE.search(base)) and bool(LEI_RE.search(base.upper())) \
        and bool(PERIOD_RE.search(base))


LANG_RE = re.compile(r"(?:^|[_\-\s.])(ro|en)(?:[._\-\s]|$)", re.IGNORECASE)


def looks_like_esef(title: str = "", url: str = "", anchor_text: str = "") -> bool:
    return match_reason(title, url, anchor_text) is not None


def extract_lei(text: str) -> str | None:
    m = LEI_RE.search((text or "").upper())
    return m.group(1) if m else None


LANG_RE = re.compile(r"(?:^|[_\-\s.])(ro|en)(?:[._\-\s]|$)", re.IGNORECASE)


def language_of(name: str) -> str | None:
    found = LANG_RE.findall(name or "")
    return found[-1].lower() if found else None


def matches_langs(name: str, langs: tuple[str, ...] | None) -> bool:
    if not langs:
        return True
    return language_of(name) in langs


def year_of(url: str) -> int | None:
    m = re.search(r"infocont(\d{2})", url)
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r"(?:Raportari|Rapoarte)/((?:19|20)\d{2})", url)
    if m:
        return int(m.group(1))
    m = re.search(r"((?:19|20)\d{2})-\d{2}-\d{2}", url)
    if m:
        return int(m.group(1))
    m = re.search(r"RA((?:19|20)\d{2})", url)
    if m:
        return int(m.group(1))
    return None


def in_years(url: str, years: tuple[int, ...] | None) -> bool:
    if not years:
        return True
    y = year_of(url)
    return y is None or y in years


def extract_period_end(text: str) -> str | None:
    iso = re.findall(r"(?:19|20)\d{2}-\d{2}-\d{2}", text or "")
    if iso:
        return iso[-1]
    for d, m, y in re.findall(r"\b(\d{2})-(\d{2})-((?:19|20)\d{2})\b", text or ""):
        return f"{y}-{m}-{d}"
    return None
