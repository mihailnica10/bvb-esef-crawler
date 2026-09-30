from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from . import bvb as bvb_mod
from . import pipeline as pipe
from .config import (
    ARELLE_CACHE_DIR,
    ARELLE_RUN_SECONDS,
    ARELLE_TIMEOUT,
    BACKFILL_DELAY,
    BACKFILL_SINCE_YEAR,
    DEFAULT_DELAY,
)
from .log import ENV_VAR, log, setup

setup()


@click.group(help="BVB ESEF scraper and ingestion pipeline.")
def main():
    pass


def syms(symbols) -> list[str] | None:
    return list(symbols) if symbols else None


def _delay(default: float):
    return click.option("--delay", type=float, default=default, show_default=True,
                        help="Minimum seconds between HTTP requests.")


def _year_opts(fn):
    fn = click.option("--from-year", type=int, default=None,
                      help="Earliest publication year (default: 2022).")(fn)
    fn = click.option("--to-year", type=int, default=None,
                      help="Latest publication year (default: this year).")(fn)
    return fn


def _source_opts(fn):
    fn = click.option("--symbol", "-s", "symbols", multiple=True,
                      help="Restrict to these issuer symbols.")(fn)
    fn = click.option("--discover/--no-discover", default=True,
                      help="Auto-discover issuers from Markets/Shares.")(fn)
    fn = click.option("--issuer-pages/--no-issuer-pages", default=True,
                      help="Crawl each issuer's reports tab (gvRepDoc).")(fn)
    fn = click.option("--sweep-years/--no-sweep-years", default=True,
                      help="Post back to the FinancialResults year selector.")(fn)
    fn = click.option("--aggregate-pages/--no-aggregate-pages", default=True,
                      help="Crawl the CurrentReports/FinancialResults pages.")(fn)
    return fn


def _lang_opt(fn):
    return click.option("--lang", "-l", "langs", multiple=True,
                        type=click.Choice(["ro", "en"]),
                        help="Only collect these report languages (repeatable; "
                             "default both).")(fn)


def _probe_opt(fn):
    return click.option("--probe/--no-probe", default=True,
                        help="Range-probe each zip for iXBRL before downloading.")(fn)


def _io_opts(fn):
    fn = click.option("--zips-dir", default="data/zips",
                      type=click.Path(path_type=Path), show_default=True,
                      help="Where downloaded packages are kept.")(fn)
    fn = click.option("--out-dir", default="data/out",
                      type=click.Path(path_type=Path), show_default=True,
                      help="Where filings.json/jsonl/companies.json/compliance.json "
                           "are written.")(fn)
    return fn


def _url_opt(fn):
    return click.option("--url-file", type=click.Path(exists=True, path_type=Path),
                        help="Extra .zip URLs to ingest (one per line).")(fn)


def _keep_opt(fn):
    return click.option("--keep-non-esef", is_flag=True,
                        help="Index packages without iXBRL/LEI.")(fn)


def _check_opts(fn):
    fn = click.option("--arelle/--no-arelle", default=False,
                      help=f"Also run the full Arelle ESEF validator (opt-in: about "
                           f"{ARELLE_RUN_SECONDS}s per package). Needs the [validate] "
                           f"extra and a populated {ARELLE_CACHE_DIR}.")(fn)
    fn = click.option("--cache-dir", default=ARELLE_CACHE_DIR,
                      type=click.Path(path_type=Path), show_default=True,
                      help="Arelle taxonomy cache; must already contain the ESEF core "
                           "schema and an IFRS entry point or the run is skipped.")(fn)
    fn = click.option("--precheck/--no-precheck", default=True,
                      help="Offline structural screen of every package (free, no "
                           "Arelle).")(fn)
    return fn


def _ingest_opts(fn):
    fn = _check_opts(fn)
    fn = _keep_opt(fn)
    fn = click.option("--limit", type=int, default=0, show_default=True,
                      help="Max packages to probe (0 = all).")(fn)
    fn = _probe_opt(fn)
    fn = _url_opt(fn)
    fn = _io_opts(fn)
    return fn


@main.command(name="doctor", help="Report coverage per source without downloading.")
@_year_opts
@_source_opts
@_lang_opt
@_delay(DEFAULT_DELAY)
def doctor(from_year, to_year, symbols, discover, issuer_pages, sweep_years,
           aggregate_pages, langs, delay):
    found = pipe.collect(from_year=from_year or BACKFILL_SINCE_YEAR,
                         to_year=to_year or date.today().year,
                         symbols=syms(symbols), discover=discover,
                         issuer_pages=issuer_pages, sweep_years=sweep_years,
                         aggregate_pages=aggregate_pages, delay=delay,
                         langs=langs or None)
    hits, rejected = pipe.probe_candidates(found.hits, delay=delay)
    urls = sorted({h.filing_url for h in hits})
    per_year = found.stats.get("fr_per_year") or {}
    click.echo("")
    click.echo("Coverage")
    click.echo("-------")
    click.echo(f"issuers discovered : {len(found.companies)}")
    click.echo(f"zips in range      : {len(found.hits)}")
    click.echo(f"ESEF after probe   : {len(urls)}")
    click.echo(f"not ESEF           : {len(rejected)}")
    if per_year:
        click.echo(f"FinancialResults   : {per_year}")
    if urls:
        click.echo("")
        click.echo(f"First {min(10, len(urls))} ESEF packages:")
        for u in urls[:10]:
            click.echo(f"  {u}")


@main.command(name="companies", help="Auto-discover BVB issuers and print them.")
@_delay(DEFAULT_DELAY)
def companies_cmd(delay):
    for c in bvb_mod.discover_companies(delay=delay):
        click.echo(f"{c.symbol:10} {(c.category or '?'):8} {c.name or ''}")


@main.command(name="crawl", help="Collect, probe and ingest ESEF filings.")
@_year_opts
@_source_opts
@_lang_opt
@_ingest_opts
@_delay(BACKFILL_DELAY)
def crawl(**kw):
    log.debug("log level from %s", ENV_VAR)
    pipe.run(**kw)


@main.command(name="backfill",
              help="Same as crawl, defaulting to 2022 onward and merging.")
@_year_opts
@_source_opts
@_lang_opt
@_ingest_opts
@_delay(BACKFILL_DELAY)
def backfill_cmd(from_year, to_year, **kw):
    kw.update(from_year=from_year or BACKFILL_SINCE_YEAR,
              to_year=to_year or date.today().year)
    pipe.run(**kw)


@main.command(name="list", help="List candidate zips for the given years.")
@_year_opts
@_source_opts
@_lang_opt
@_probe_opt
@_delay(DEFAULT_DELAY)
def list_cmd(from_year, to_year, symbols, discover, issuer_pages, sweep_years,
             aggregate_pages, langs, probe, delay):
    found = pipe.collect(from_year=from_year, to_year=to_year,
                         symbols=syms(symbols), discover=discover,
                         issuer_pages=issuer_pages, sweep_years=sweep_years,
                         aggregate_pages=aggregate_pages, delay=delay,
                         langs=langs or None)
    hits = found.hits
    if probe and hits:
        hits, _ = pipe.probe_candidates(hits, delay=delay)
    for h in hits:
        click.echo(f"{h.symbol or '?':10} {h.filing_url}")


@main.command(name="inspect", help="Inspect an ESEF package on disk.")
@click.argument("zip_path", type=click.Path(exists=True, path_type=Path))
def inspect_cmd(zip_path):
    from .esef import inspect_zip
    info = inspect_zip(zip_path)
    click.echo(f"LEI:      {info.lei}")
    click.echo(f"period:   {info.period_end}")
    click.echo(f"language: {info.language}")
    click.echo(f"has_ixbrl:{info.has_ixbrl}")
    click.echo(f"xhtml:    {info.xhtml_files[:5]}")
    click.echo(f"taxonomy: {len(info.taxonomy_files)} files")
    click.echo(f"registrant:{info.registrant_name}")
    click.echo(f"publisher:{info.publisher}")
    click.echo(f"report LEI:{info.claimed_lei}")
    cross = ("MISMATCH" if info.lei_mismatch()
             else "ok" if info.lei and info.claimed_lei else "not comparable")
    click.echo(f"lei cross:{cross} (filename {info.lei})")


@main.command(name="validate",
              help="Screen an ESEF package on disk. Not a compliance certificate: "
                   "the pre-check is a structural screen and Arelle is opt-in.")
@click.argument("zip_path", type=click.Path(exists=True, path_type=Path))
@_check_opts
@click.option("--timeout", type=int, default=ARELLE_TIMEOUT, show_default=True,
              help="Seconds to allow one Arelle run.")
def validate_cmd(zip_path, arelle, cache_dir, precheck, timeout):
    from .filters import language_of
    from .validate import arelle_available, arelle_version, validate
    if not precheck and not arelle:
        raise click.UsageError("enable --precheck and/or --arelle, nothing to run")
    path = Path(zip_path)
    result = validate(path, arelle=arelle, cache_dir=cache_dir, screen=precheck,
                      lang=language_of(path.name), timeout=timeout)
    click.echo(result.format())
    if arelle:
        click.echo("arelle: "
                   f"{arelle_version() if arelle_available() else 'unavailable'}")
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
