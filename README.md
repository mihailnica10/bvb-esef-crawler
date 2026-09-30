# BVB ESEF Scraper & Ingestion Pipeline

Scraper for the ESEF `.zip` packages published on **BVB**
(Bucharest Stock Exchange) plus an ingestion pipeline compatible with
`filings.xbrl.org`.

Romanian version: [README.ro.md](README.ro.md)

> **Legal status.** This tool performs automated access to BVB websites. BVB's published Terms and Conditions prohibit automated access/parsing and require BVB's express written consent to retrieve electronic data for any non-personal purpose. Do not operate this scraper against BVB at scale, on a schedule, or for redistribution until that consent is obtained. See [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md) §§2, 4 and 8. That document is analysis, not legal advice.

It discovers issuers from BVB, collects report ZIPs from mobile issuer history and aggregate report pages, range-probes every candidate, downloads probe-positive packages, keeps filings with iXBRL content or an LEI identifier (skipping other downloads without indexing them), inspects package metadata, and exports
`filings.json` / `filings.jsonl` / `companies.json`, with local pre-check results in `compliance.json` and opt-in Arelle validation.

## Where the files live on BVB

- Issuer report history: mobile issuer pages,
  `https://m.bvb.ro/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=SYM`,
  especially report table `gvRepDoc`.
- Aggregate listings: `https://bvb.ro/` → *Current Reports*
  (`/FinancialInstruments/SelectedData/CurrentReports`) and *Financial Results*
  (`/FinancialInstruments/SelectedData/FinancialResults`).
- Attachments: `https://bvb.ro/infocont/infocont{YY}/{FILE_NAME}`
  (`{YY}` = last two digits of the publication year). Naming varies; for example,
  `EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip`.
- Annual reporting in Romania peaks between **March and May**.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[validate,validate-css]"  # optional local Arelle ESEF validation
```

The Arelle cache directory is local and excluded from version control. It must already contain the ESEF core schema and an IFRS entry point before an offline Arelle run; otherwise validation reports the package as skipped rather than as valid or invalid.

Export it before starting the command, because the HTTP headers are constructed when the process starts:

```bash
export BVB_ESEF_CONTACT="your-name@example.com"
```

## Usage

```bash
# discover issuers live from Markets/Shares (no hardcoded list)
bvb-esef companies

# list candidate attachments without downloading
bvb-esef list
bvb-esef list -s EL --no-discover

# full pipeline: data/zips/*.zip + data/out/{filings.json,filings.jsonl,companies.json,compliance.json}
bvb-esef crawl
./scripts/sync.sh
./scripts/sync.sh --arelle

# backfill 2022..today (merges into the same filings.json, skips existing files)
bvb-esef backfill
bvb-esef backfill --from-year 2022 --to-year 2024 --delay 3
bvb-esef backfill --url-file urls.txt   # ingest known .zip URLs, one per line

# one-off inspection / validation
bvb-esef inspect data/zips/EL_*.zip
bvb-esef validate data/zips/EL_*.zip

# explain per-source coverage (why is the result empty?)
bvb-esef doctor --from-year 2022 --to-year 2026
```

Issuer report history lives on the **mobile** issuer pages. Each
`https://m.bvb.ro/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=SYM`
page loads its tabs client-side, so the reports tab is reached by replaying its
`__doPostBack` (the event target is detected from the tab label, never
hardcoded). The response contains `table#gvRepDoc` with the issuer's full report
history and its `.zip` attachments, back to at least 2012. The desktop
`bvb.ro/.../FinancialInstrumentsDetails.aspx` pages do not expose this tab.

The collector checks that every initial and redirected request uses only `bvb.ro` or a `bvb.ro` subdomain before sending it.

## Language

Many issuers publish ESEF reports in both Romanian and English. When a run is scoped to one language with `--lang`, collection volume is correspondingly lower. It is applied
while collecting, so filtered-out packages are never probed or downloaded:

```bash
bvb-esef list --lang ro
bvb-esef crawl --lang en
bvb-esef backfill --from-year 2024 --to-year 2026 --lang ro --lang en
```

Each collected package yields one record per language variant. Where multiple candidates share issuer, period and language, the pipeline prefers the iXBRL variant. Without `--lang`, both languages are
collected.

## Rate limits

Every BVB HTTP request goes through one sequential `RateLimiter`: a
minimum delay between HTTP requests, one retry on 429/503, skip-on-error,
resume by skipping files already on disk, and redirects rechecked against the BVB-only allowlist. Tune it per command:

| command    | default `--delay` |
|------------|-------------------|
| `list`     | 1.0 s             |
| `doctor`   | 1.0 s             |
| `companies`| 1.0 s             |
| `crawl`    | 2.0 s             |
| `backfill` | 2.0 s             |

```bash
bvb-esef crawl --delay 2.5
bvb-esef backfill --delay 5 --limit 50
```

The defaults aim for a low request rate (on the order of about five requests for a narrow daily check, and about one hundred or more for a broad backfill), with a single sequential connection and no concurrency. Low impact is an engineering goal, not a legal authorization, and BVB's terms prohibit automated access regardless of rate (see [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md) §4).

## Backfill notes

As of 2026-09-30, Romania coverage on `filings.xbrl.org` appeared incomplete for filings since 2022 from manual inspection of its public index. Re-verify before relying on this; the service states its repository "is not complete" (`https://filings.xbrl.org/docs/about`). `backfill` sweeps the
available sources, keeps hits whose publication URL falls in `--from-year..--to-year`, downloads only
missing files, and merges records into the existing `filings.json`
(deduplicated by `filing_url`), so reruns merge by `filing_url` without duplicating existing records.

It also posts back to the `ddYear` selector on the Financial Results page once
per year in range, and logs a per-year count. Use `--no-sweep-years` to skip
that. Publication-year filtering is based on the URL/publication year, not the report's `period_end`.

### Coverage and history

`bvb-esef doctor` collects and range-probes candidates for the given years
without downloading anything, and prints the per-source counts so an empty run
is usually diagnosable:

```bash
bvb-esef doctor --from-year 2024 --to-year 2026
bvb-esef doctor --from-year 2024 --to-year 2026 --lang ro
```

### Not every `.zip` is ESEF, and the filename is not a reliable filter

BVB also publishes Financial Statements bundles (e.g.
`Raportari/2025/BAC_RA2025_ro.zip`) that are just PDFs in a zip. Filenames are
inconsistent: real ESEF packages appear both as
`TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip` and as
`BRD_20260318062626_BRDSocieteGenerale-2025-12-31-ro.zip` or
`BRDSocieteGenerale-2025-12-31 ESEF RO xhtml.zip`, none of which name ESEF in
any usable way. So **every** candidate zip is range-probed: the ZIP central
directory is read, an XHTML entry is inflated from a byte range, and the package
is accepted for download only if iXBRL markup is actually found. After download, each package is re-inspected, and non-iXBRL packages are reported and skipped. Pass `--no-probe` to download everything,
or `--keep-non-esef` to index non-iXBRL packages anyway.

## Validation

Every ingested package receives a free offline structural pre-check by default. Use `--no-precheck` to skip it. Detailed results are stored in `data/out/compliance.json`, not in the public filing records.

Full Arelle ESEF validation is opt-in because it takes about 60 seconds per package:

```bash
bvb-esef crawl --arelle
bvb-esef validate data/zips/EL_*.zip --arelle
```

Arelle needs the `[validate,validate-css]` extras and a populated local taxonomy cache. If that cache is absent, the run records the package as skipped rather than treating missing-taxonomy errors as ordinary validation failures. Neither the pre-check nor Arelle output is a compliance certificate.

## Logging

Set the level with `BVB_ESEF_LOGLEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`,
`CRITICAL`; default `INFO`). `DEBUG` shows every request, every probed ZIP with its result, and every rejected ZIP with its reason:

```bash
BVB_ESEF_LOGLEVEL=DEBUG bvb-esef backfill --from-year 2024 --to-year 2026
```

```text
https://bvb.ro/infocont/infocont23/EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip
https://bvb.ro/infocont/infocont24/COMI_20240528170804_315700NXLBV70RI3NR23-2023-12-31.zip
```

Packages rejected after download are reported and skipped, not indexed, so the DEBUG list can be curated without pre-filtering.

## Export schema (`filings.json`)

See `examples/filings.example.json`:

```json
{"filings": [{"entity": {"lei": "...", "name": "...", "ticker": "EL", "country": "RO"},
  "report": {"filing_url": "https://bvb.ro/infocont/...zip", "filing_date": "2023-04-28",
  "period_end": "2022-12-31", "sha256": "...", "source_system": "BVB_IRIS",
  "language": "ro", "is_consolidated": true}}]}
```

The parser takes the LEI from the filename or the `<xbrli:identifier>` inside
`ix:header`, the entity name from `dei:EntityRegistrantName` when present, `period_end` from the newest `<xbrli:endDate/instant>` or the
filename date, the language from the `-ro/-en` suffix, the SHA-256 of the
downloaded ZIP, and `filing_date` from the BVB timestamp prefix or fallback date when that prefix is absent.
`is_consolidated` is currently an assumed default, not a value detected from the report. Detailed pre-check and Arelle results are kept separately in `data/out/compliance.json`, keyed by filing URL.

## Tests

```bash
pytest -q
```

These are offline unit tests. Do not verify the documentation by running broad live crawls against BVB.

## Daily sync (cron)

```cron
0 6 * * * /path/to/bvb-esef-scraper/scripts/sync.sh >> /var/log/bvb-esef.log 2>&1
```

## Handover to filings.xbrl.org

1. Run `bvb-esef crawl` and `bvb-esef backfill --url-file urls.txt`.
2. Only after the consent and licensing position in [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md) §8 is resolved, send this repo plus `data/out/filings.json[l]`, `data/out/companies.json`, and `data/out/compliance.json`
   to **`filings@xbrl.org`** for integration into the main collector.

## License

MIT — see [LICENSE.md](LICENSE.md) ([Romanian](LICENSE.ro.md)). XBRL
International additionally holds a perpetual, royalty-free grant to use and
redistribute the output data for `filings.xbrl.org`, recorded in
[GRANT-XBRL.md](GRANT-XBRL.md) ([Romanian](GRANT-XBRL.ro.md)).

For the project compliance analysis, see [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md); it does not authorize operation.
