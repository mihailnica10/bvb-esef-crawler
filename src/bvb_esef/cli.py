from __future__ import annotations
from datetime import date
from pathlib import Path

import click

from . import bvb as bvb_mod
from . import iris as iris_mod
from . import pipeline as pipe
from .config import DEFAULT_DELAY, BACKFILL_DELAY, BACKFILL_SINCE_YEAR
from .log import ENV_VAR, log, setup

setup()


@click.group(help="BVB ESEF scraper and ingestion pipeline.")
def main():
    pass


def _delay(default: float):
    return click.option("--delay", type=float, default=default, show_default=True,
                        help="Minimum seconds between HTTP requests.")


def _source_opts(fn):
    fn = click.option("--symbol", "-s", multiple=True,
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
    return click.option("--lang", "-l", multiple=True,
                        type=click.Choice(["ro", "en"]),
                        help="Only collect these report languages (repeatable; "
                             "default both).")(fn)


def _year_opts(fn):
    fn = click.option("--from-year", type=int, default=None,
                      help="Earliest publication year (default: 2022).")(fn)
    fn = click.option("--to-year", type=int, default=None,
                      help="Latest publication year (default: this year).")(fn)
    return fn


@main.command(name="doctor", help="Report coverage per source without downloading.")
@_year_opts
@_source_opts
@_lang_opt
@_delay(DEFAULT_DELAY)
def doctor(from_year, to_year, symbol, discover, issuer_pages, sweep_years,
           aggregate_pages, lang, delay):
    found = pipe.collect(from_year=from_year or BACKFILL_SINCE_YEAR,
                         to_year=to_year or date.today().year,
                         symbols=list(symbol or []), discover=discover,
                         issuer_pages=issuer_pages, sweep_years=sweep_years,
                         aggregate_pages=aggregate_pages, delay=delay,
                         langs=lang or None)
    hits, rejected = pipe.probe_candidates(found.hits, delay=delay)
    click.echo("")
    click.echo("Coverage")
    click.echo("-------")
    click.echo(f"issuers discovered : {len(found.companies)}")
    click.echo(f"zips in range      : {len(found.hits)}")
    click.echo(f"ESEF after probe   : {len(hits)}")
    click.echo(f"not ESEF           : {len(rejected)}")
    per_year = found.stats.get("fr_per_year") or {}
    if per_year:
        click.echo(f"FinancialResults   : {per_year}")
    years = sorted({h.filing_url for h in hits})
    if years:
        click.echo("")
        click.echo(f"First {min(10, len(years))} ESEF packages:")
        for u in years[:10]:
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
@click.option("--out-dir", default="data/out", type=click.Path(path_type=Path))
@click.option("--zips-dir", default="data/zips", type=click.Path(path_type=Path))
@click.option("--url-file", type=click.Path(exists=True, path_type=Path),
              help="Extra .zip URLs to ingest (one per line).")
@click.option("--probe/--no-probe", default=True,
              help="Range-probe each zip for iXBRL before downloading.")
@click.option("--validate/--no-validate", default=False)
@click.option("--keep-non-esef", is_flag=True,
              help="Index packages without iXBRL/LEI.")
@click.option("--limit", type=int, default=0, help="Max packages to probe (0 = all).")
@_delay(BACKFILL_DELAY)
def crawl(from_year, to_year, symbol, discover, issuer_pages, sweep_years,
          aggregate_pages, lang, out_dir, zips_dir, url_file, probe, validate,
          keep_non_esef, limit, delay):
    log.debug("log level from %s", ENV_VAR)
    pipe.run(out_dir, zips_dir, from_year=from_year, to_year=to_year,
             url_file=url_file, symbols=list(symbol or []), discover=discover,
             issuer_pages=issuer_pages, sweep_years=sweep_years,
             aggregate_pages=aggregate_pages, probe=probe, validate=validate,
             keep_non_esef=keep_non_esef, limit=limit, delay=delay,
             langs=lang or None)


@main.command(name="backfill",
              help="Same as crawl, defaulting to 2022 onward and merging.")
@_year_opts
@_source_opts
@_lang_opt
@click.option("--out-dir", default="data/out", type=click.Path(path_type=Path))
@click.option("--zips-dir", default="data/zips", type=click.Path(path_type=Path))
@click.option("--url-file", type=click.Path(exists=True, path_type=Path),
              help="Extra .zip URLs to ingest (one per line).")
@click.option("--probe/--no-probe", default=True,
              help="Range-probe each zip for iXBRL before downloading.")
@click.option("--validate/--no-validate", default=False)
@click.option("--keep-non-esef", is_flag=True,
              help="Index packages without iXBRL/LEI.")
@click.option("--limit", type=int, default=0, help="Max packages to probe (0 = all).")
@_delay(BACKFILL_DELAY)
def backfill_cmd(from_year, to_year, symbol, discover, issuer_pages, sweep_years,
                 aggregate_pages, lang, out_dir, zips_dir, url_file, probe,
                 validate, keep_non_esef, limit, delay):
    pipe.run(out_dir, zips_dir, from_year=from_year or BACKFILL_SINCE_YEAR,
             to_year=to_year or date.today().year, url_file=url_file,
             symbols=list(symbol or []), discover=discover,
             issuer_pages=issuer_pages, sweep_years=sweep_years,
             aggregate_pages=aggregate_pages, probe=probe,
             validate=validate, keep_non_esef=keep_non_esef, limit=limit,
             delay=delay, langs=lang or None)


@main.command(name="list", help="List candidate zips for the given years.")
@_year_opts
@_source_opts
@_lang_opt
@click.option("--probe/--no-probe", default=True,
              help="Range-probe each zip for iXBRL.")
@_delay(DEFAULT_DELAY)
def list_cmd(from_year, to_year, symbol, discover, issuer_pages, sweep_years,
             aggregate_pages, lang, probe, delay):
    found = pipe.collect(from_year=from_year, to_year=to_year,
                         symbols=list(symbol or []), discover=discover,
                         issuer_pages=issuer_pages, sweep_years=sweep_years,
                         aggregate_pages=aggregate_pages, delay=delay,
                         langs=lang or None)
    hits = found.hits
    if probe and hits:
        hits, _ = pipe.probe_candidates(hits, delay=delay)
    for h in hits:
        click.echo(f"{h.symbol or '?':10} {h.filing_url}")


@main.command(name="scan-iris", help="Show the raw IRIS documents feed.")
@click.option("--period", type=click.Choice(["d", "w", "m"]), default="w",
              show_default=True)
@_delay(DEFAULT_DELAY)
def scan_iris(period, delay):
    for r in iris_mod.fetch_iris(period, delay=delay):
        flag = "ESEF?" if r.esef_candidate else "     "
        click.echo(f"[{flag}] {r.date} {r.symbol or '?':10} {r.title}")


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


@main.command(name="validate", help="Validate an ESEF package with Arelle.")
@click.argument("zip_path", type=click.Path(exists=True, path_type=Path))
def validate_cmd(zip_path):
    from .validate import validate, arelle_available
    if not arelle_available():
        raise click.ClickException("arelleCmdLine not found (pip install arelle-release)")
    ok, vlog = validate(zip_path)
    click.echo(vlog)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
