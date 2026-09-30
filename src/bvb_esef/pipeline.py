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
from . import net
from . import validate as val
from .filters import extract_period_end, year_of
from .log import log
from .polite import RateLimiter

FNAME_DATE_RE = re.compile(r"_(\d{4})(\d{2})(\d{2})\d{6}_")
ROMAN_DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-((?:19|20)\d{2})\b")
INFOCONT_RE = re.compile(r"infocont(\d{2})")
LANG_IN_NAME_RE = re.compile(r"[_\-\s](ro|en)(?:[._\-\s]|$)", re.IGNORECASE)


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
        lo = from_year or to_year
        hi = to_year or date.today().year
        if lo > hi:
            raise ValueError(f"from_year {lo} is after to_year {hi}")
        years = tuple(range(lo, hi + 1))
        log.info("collecting zips for years %d..%d", lo, hi)
    if langs:
        log.info("language filter: %s", ", ".join(langs))
    pages, companies = bvb_mod.default_pages(symbols, discover=discover, delay=delay)
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


def _filing_key(hit: bvb_mod.BvbHit) -> tuple:
    fname = hit.filing_url.rsplit("/", 1)[-1]
    period = extract_period_end(fname) or year_of(hit.filing_url) or ""
    lang = LANG_IN_NAME_RE.search(fname)
    return (hit.symbol or "", str(period), lang.group(1).lower() if lang else "")


def probe_candidates(hits: list[bvb_mod.BvbHit], delay: float = 2.0,
                     limit: int = 0) -> tuple[list[bvb_mod.BvbHit], list[tuple]]:
    limiter = RateLimiter(delay)
    if limit:
        hits = hits[:limit]
    best: dict[tuple, tuple[bvb_mod.BvbHit, bool]] = {}
    rejected: list[tuple] = []
    with net.client() as client:
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


def registrant_name(info: esef_mod.EsefInfo, fallback: str | None) -> str:
    return info.display_name or fallback or info.lei or meta.UNKNOWN


def ingest(hits: list[bvb_mod.BvbHit], out_dir: Path, zips_dir: Path,
           names: dict, delay: float = 2.0, precheck: bool = True,
           arelle: bool = False, cache_dir: Path | None = None,
           keep_non_esef: bool = False) -> tuple[list[dict], dict[str, dict]]:
    limiter = RateLimiter(delay)
    records: list[dict] = []
    compliance: dict[str, dict] = {}
    skipped: list[str] = []
    for n, h in enumerate(hits, 1):
        fname = dl.filename_for_url(h.filing_url)
        zpath = zips_dir / fname
        log.info("[%d/%d] %s", n, len(hits), fname)
        try:
            dl.download(h.filing_url, zpath, limiter=limiter)
        except net.BlockedUrl as e:
            log.error("refusing to download %s: %s", h.filing_url, e)
            continue
        except Exception as e:
            log.error("download failed %s: %s", h.filing_url, e)
            continue
        info = esef_mod.inspect_zip(zpath)
        if not keep_non_esef and not (info.has_ixbrl or info.lei):
            log.warning("not ESEF after download, skipping: %s", fname)
            skipped.append(fname)
            continue
        period_end = info.period_end or extract_period_end(fname)
        fdate = filing_date_from_filename(fname) or period_end or str(date.today())
        period_end = period_end or fdate
        digest = dl.sha256(zpath)
        if precheck or arelle:
            result = val.validate(zpath, arelle=arelle, cache_dir=cache_dir,
                                  lang=info.language)
            compliance[h.filing_url] = {"filing_url": h.filing_url, "sha256": digest,
                                        "path": str(zpath), **result.summary()}
            log.info("validate %s -> %s (%d errors, %d warnings)", fname,
                     result.status, len(result.errors), len(result.warnings))
        records.append(meta.filing_record(
            lei=info.lei or meta.UNKNOWN,
            name=registrant_name(info, names.get(h.symbol or "")),
            ticker=h.symbol,
            filing_url=h.filing_url,
            filing_date=fdate,
            period_end=period_end,
            sha256=digest,
            language=info.language or meta.DEFAULT_LANGUAGE,
        ))
    log.info("ingest: %d records, %d compliance entries, %d skipped after download",
             len(records), len(compliance), len(skipped))
    return records, compliance


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


def store_compliance(entries: dict[str, dict], out_dir: Path,
                     merge: bool = True) -> Path:
    dest = out_dir / "compliance.json"
    merged = meta.read_compliance(dest) if merge else {}
    merged.update(entries)
    meta.write_compliance(merged, dest)
    log.info("wrote %d compliance entries → %s", len(merged), dest)
    return dest


def run(out_dir: Path, zips_dir: Path, from_year: int | None = None,
        to_year: int | None = None, url_file: Path | None = None,
        symbols: list[str] | None = None, discover: bool = True,
        issuer_pages: bool = True, sweep_years: bool = True,
        aggregate_pages: bool = True, precheck: bool = True,
        arelle: bool = False, cache_dir: Path | None = None,
        keep_non_esef: bool = False, probe: bool = True, limit: int = 0,
        delay: float = 2.0,
        langs: tuple[str, ...] | None = None) -> list[dict]:
    found = collect(from_year=from_year, to_year=to_year, symbols=symbols,
                    discover=discover, issuer_pages=issuer_pages,
                    sweep_years=sweep_years, aggregate_pages=aggregate_pages,
                    delay=delay, langs=langs)
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
    if arelle and not val.arelle_available():
        log.warning("--arelle requested but Arelle is not installed; "
                    "pre-check only (pip install 'bvb-esef-scraper[validate]')")
    records, compliance = ingest(hits, out_dir, zips_dir, found.symbols, delay=delay,
                                 precheck=precheck, arelle=arelle,
                                 cache_dir=cache_dir, keep_non_esef=keep_non_esef)
    if compliance:
        store_compliance(compliance, out_dir)
    return store(records, out_dir, merge=True)
