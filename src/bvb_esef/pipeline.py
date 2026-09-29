from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import json
import re

from . import bvb as bvb_mod
from . import downloader as dl
from . import esef as esef_mod
from . import metadata as meta
from .filters import extract_period_end, year_of, language_of
from .log import log
from .polite import RateLimiter

FNAME_DATE_RE = re.compile(r"_(\d{4})(\d{2})(\d{2})\d{6}_")
ROMAN_DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-((?:19|20)\d{2})\b")
INFOCONT_RE = re.compile(r"infocont(\d{2})")


def filing_date_from_filename(fname: str) -> str | None:
    m = FNAME_DATE_RE.search(fname)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = ROMAN_DATE_RE.search(fname)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = INFOCONT_RE.search(fname)
    if m:
        return f"20{m.group(1)}-12-31"
    return None


def guess_symbol(fname: str) -> str | None:
    m = re.match(r"([A-Za-z0-9]{2,8})_", fname)
    return m.group(1).upper() if m else None


def read_url_file(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.lower().endswith(".zip"):
            urls.append(line.split()[0])
    log.info("read %d .zip URLs from %s", len(urls), path)
    return urls


def _dedupe(hits: list[bvb_mod.BvbHit]) -> list[bvb_mod.BvbHit]:
    seen: set[str] = set()
    out: list[bvb_mod.BvbHit] = []
    for h in hits:
        if h.filing_url in seen:
            continue
        seen.add(h.filing_url)
        out.append(h)
    if len(out) != len(hits):
        log.debug("dropped %d duplicate candidates", len(hits) - len(out))
    return out


@dataclass
class Collection:
    hits: list[bvb_mod.BvbHit] = field(default_factory=list)
    companies: list[bvb_mod.Company] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def symbols(self) -> dict[str, str]:
        return {c.symbol: c.name for c in self.companies if c.name}


def collect(from_year: int | None = None, to_year: int | None = None,
            symbols: list[str] | None = None, discover: bool = True,
            issuer_pages: bool = True, sweep_years: bool = True,
            aggregate_pages: bool = True, delay: float = 2.0,
            langs: tuple[str, ...] | None = None) -> Collection:
    years = None
    if from_year or to_year:
        lo = from_year or from_year
        hi = to_year or date.today().year
        years = tuple(range(lo, hi + 1))
        log.info("collecting zips for years %d..%d", lo, hi)
    if langs:
        log.info("language filter: %s", ", ".join(langs))
    pages, companies = bvb_mod.default_pages(symbols, discover=discover,
                                             delay=delay, langs=langs)
    result = Collection(companies=companies)
    if aggregate_pages:
        result.hits += bvb_mod.crawl_bvb_pages(pages, years=years, delay=delay,
                                               stats=result.stats, langs=langs)
    if issuer_pages and companies:
        result.hits += bvb_mod.crawl_issuers(companies, years=years,
                                             delay=delay, stats=result.stats,
                                             langs=langs)
    elif not issuer_pages:
        log.info("issuer report tabs skipped")
    if sweep_years and years:
        result.hits += bvb_mod.crawl_financial_results(years, delay=delay,
                                                       stats=result.stats,
                                                       langs=langs)
    result.hits = _dedupe(result.hits)
    log.info("collected %d unique zip candidates", len(result.hits))
    return result


def write_companies(companies: list, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "companies.json").write_text(
        json.dumps([{"symbol": c.symbol, "name": c.name,
                     "category": c.category} for c in companies],
                   indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("%d issuers → %s", len(companies), out_dir / "companies.json")


LANG_IN_NAME_RE = re.compile(r"[_\-\s](ro|en)(?:[._\-\s]|$)", re.IGNORECASE)


def _filing_key(hit: bvb_mod.BvbHit) -> tuple:
    fname = hit.filing_url.rsplit("/", 1)[-1]
    period = extract_period_end(fname) or year_of(hit.filing_url) or ""
    lang = LANG_IN_NAME_RE.search(fname)
    return (hit.symbol or "", str(period), lang.group(1).lower() if lang else "")


def probe_candidates(hits: list[bvb_mod.BvbHit], delay: float = 2.0,
                     limit: int = 0) -> tuple[list[bvb_mod.BvbHit], list[tuple]]:
    import httpx
    from .config import HEADERS
    limiter = RateLimiter(delay)
    if limit:
        hits = hits[:limit]
    best: dict[tuple, tuple[bvb_mod.BvbHit, bool]] = {}
    rejected: list[tuple] = []
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for n, h in enumerate(hits, 1):
            if limiter:
                limiter.wait()
            r = esef_mod.probe_remote(client, h.filing_url)
            name = h.filing_url.rsplit("/", 1)[-1]
            if not r.is_esef:
                rejected.append((name, r.reason))
                log.debug("[%d/%d] skip %s (%s)", n, len(hits), name, r.reason)
                continue
            log.debug("[%d/%d] ESEF %s (%s)", n, len(hits), name, r.reason)
            key = _filing_key(h)
            prev = best.get(key)
            if prev is None:
                best[key] = (h, r.has_ixbrl)
            elif r.has_ixbrl and not prev[1]:
                log.info("preferring iXBRL variant over duplicate: %s", name)
                best[key] = (h, r.has_ixbrl)
            else:
                log.info("duplicate filing for %s, keeping %s", key,
                         prev[0].filing_url.rsplit("/", 1)[-1])
    keep = [h for h, _ in best.values()]
    keep.sort(key=lambda x: x.filing_url)
    log.info("probe: %d ESEF packages, %d not ESEF, %d duplicate variants dropped",
             len(keep), len(rejected), len(hits) - len(keep) - len(rejected))
    for name, reason in rejected[:20]:
        log.info("  not ESEF: %s (%s)", name, reason)
    if len(rejected) > 20:
        log.info("  ... and %d more", len(rejected) - 20)
    return keep, rejected


def ingest(hits: list[bvb_mod.BvbHit], out_dir: Path, zips_dir: Path,
           names: dict, delay: float = 2.0, validate: bool = False,
           keep_non_esef: bool = False) -> list[dict]:
    from .validate import validate as _validate
    limiter = RateLimiter(delay)
    records: list[dict] = []
    for n, h in enumerate(hits, 1):
        fname = dl.filename_for_url(h.filing_url)
        zpath = zips_dir / fname
        log.info("[%d/%d] %s", n, len(hits), fname)
        try:
            dl.download(h.filing_url, zpath, limiter=limiter)
        except Exception as e:
            log.error("download failed %s: %s", h.filing_url, e)
            continue
        info = esef_mod.inspect_zip(zpath)
        if not keep_non_esef and not (info.has_ixbrl or info.lei):
            log.warning("not ESEF after download, skipping: %s", fname)
            continue
        fdate = filing_date_from_filename(fname) or str(date.today())
        period_end = info.period_end or extract_period_end(fname) or fdate
        if validate:
            ok, vlog = _validate(zpath)
            log.info("validate %s: %s", fname, "OK" if ok else "FAIL")
            if not ok:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{zpath.stem}.validation.log").write_text(vlog)
        records.append(meta.filing_record(
            lei=info.lei or "UNKNOWN",
            name=names.get(h.symbol or "") or h.symbol or "UNKNOWN",
            ticker=h.symbol,
            filing_url=h.filing_url,
            filing_date=fdate,
            period_end=period_end,
            sha256=dl.sha256(zpath),
            language=info.language or "ro",
        ))
    return records


def store(records: list[dict], out_dir: Path, merge: bool = True) -> list[dict]:
    if merge:
        existing = meta.read_index(out_dir / "filings.json")
        if existing:
            log.info("merging into %d existing records", len(existing))
        records = meta.merge_records(existing, records)
    meta.write_index(records, out_dir / "filings.json")
    meta.write_jsonl(records, out_dir / "filings.jsonl")
    log.info("wrote %d records → %s", len(records), out_dir / "filings.json")
    return records


def run(out_dir: Path, zips_dir: Path, from_year: int | None = None,
        to_year: int | None = None, url_file: Path | None = None,
        symbols: list[str] | None = None, discover: bool = True,
        issuer_pages: bool = True, sweep_years: bool = True,
        aggregate_pages: bool = True, validate: bool = False,
        keep_non_esef: bool = False, no_probe: bool = False,
        limit: int = 0, delay: float = 2.0) -> list[dict]:
    found = collect(from_year=from_year, to_year=to_year, symbols=symbols,
                    discover=discover, issuer_pages=issuer_pages,
                    sweep_years=sweep_years, aggregate_pages=aggregate_pages,
                    delay=delay)
    write_companies(found.companies, out_dir)
    hits = found.hits
    if url_file:
        for url in read_url_file(url_file):
            fname = dl.filename_for_url(url)
            hits.append(bvb_mod.BvbHit(filing_url=url, title=fname,
                                       symbol=guess_symbol(fname),
                                       source_page=str(url_file)))
        hits = _dedupe(hits)
    if not hits:
        log.warning("no zip candidates for the requested years")
    if probe and hits:
        hits, _ = probe_candidates(hits, delay=delay, limit=limit)
    elif limit:
        hits = hits[:limit]
    return store(ingest(hits, out_dir, zips_dir, found.symbols, delay=delay,
                        validate=validate, keep_non_esef=keep_non_esef),
                 out_dir, merge=True)
