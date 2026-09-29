# BVB ESEF Scraper & Ingestion Pipeline

Scraper for the ESEF `.zip` packages published through **IRIS / BVB**
(Bucharest Stock Exchange) plus an ingestion pipeline compatible with
`filings.xbrl.org`.

Romanian version: [README.ro.md](README.ro.md)

It crawls IRIS and `bvb.ro/infocont/infocont{YY}/…`, filters ESEF attachments,
downloads them, inspects each package (LEI, period end, SHA-256) and exports
`filings.json` / `filings.jsonl`, with optional Arelle validation.

## Where the files live on BVB

- IRIS feed: `https://iris.bvb.ro/` → *Public Reports* (`/PublicReports/Reports`,
  server-rendered ASP.NET table `gv_IssuerReports`: Company - Symbol / Title / Date).
- BVB portal: `https://bvb.ro/` → *Current Reports*
  (`/FinancialInstruments/SelectedData/CurrentReports`) and *Financial Results*
  (`/FinancialInstruments/SelectedData/FinancialResults`).
- Attachments: `https://bvb.ro/infocont/infocont{YY}/{FILE_NAME}`
  (`{YY}` = last two digits of the publication year). Naming convention:
  `{SYMBOL}_{TIMESTAMP}_{LEI}-{PERIOD_END}-{LANG}.zip`, e.g.
  `EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip`.
- Annual reporting in Romania peaks between **March and May**.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install arelle-release   # optional, ESMA reference engine for ESEF validation
```

Set `BVB_ESEF_CONTACT` to append contact info to the HTTP User-Agent:

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

# raw IRIS feed (titles, ESEF? flag)
bvb-esef scan-iris --period m

# full pipeline: data/zips/*.zip + data/out/{filings.json,filings.jsonl,companies.json}
bvb-esef crawl
./scripts/sync.sh
./scripts/sync.sh --validate

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

IRIS is WebForms (`__VIEWSTATE` + `__doPostBack`); `scan-iris` replays the
`ddlPeriod` post. Attachment details that require JS resolve most faithfully
with Playwright (watch the *Network* tab).

## Language

Most issuers publish every ESEF report in both Romanian and English, so the
language filter roughly halves the requests a full run makes. It is applied
while collecting, so filtered-out packages are never probed or downloaded:

```bash
bvb-esef list --lang ro
bvb-esef crawl --lang en
bvb-esef backfill --from-year 2024 --to-year 2026 --lang ro --lang en
```

Romanian and English are kept as separate filings (one record per package), and
duplicate variants of the same filing (same issuer, period and language) are
collapsed, preferring the iXBRL package. Without `--lang`, both languages are
collected.

## Rate limits

Every command that hits BVB goes through one sequential `RateLimiter`: a
minimum delay between HTTP requests, one retry on 429/503, skip-on-error, and
resume by skipping files already on disk. Tune it per command:

| command   | default `--delay` |
|-----------|-------------------|
| `list`    | 1.0 s             |
| `crawl`   | 1.0 s             |
| `backfill`| 2.0 s             |
| `scan-iris` | 1.0 s           |

```bash
bvb-esef crawl --delay 2.5
bvb-esef backfill --delay 5 --limit 50
```

The defaults keep a full run (~5 requests daily, ~100+ for backfill with
company pages) far below anything that could bother BVB's servers.

## Backfill notes

`filings.xbrl.org` holds no Romania data since 2022. `backfill` sweeps the
available sources, keeps hits whose year (`infocontYY`, `Raportari/YYYY` or the
period date in the filename) falls in `--from-year..--to-year`, downloads only
missing files, and merges records into the existing `filings.json`
(deduplicated by `filing_url`), so reruns are safe.

It also posts back to the `ddYear` selector on the Financial Results page once
per year in range, and logs a per-year count. Use `--no-sweep-years` to skip
that.

### Coverage and history

`bvb-esef doctor` collects and range-probes candidates for the given years
without downloading anything, and prints the per-source counts so an empty run
is always explainable:

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
is accepted only if iXBRL markup is actually present. Packages are downloaded
in full only after that probe passes. Pass `--no-probe` to download everything,
or `--keep-non-esef` to index non-iXBRL packages anyway.

## Logging

Set the level with `BVB_ESEF_LOGLEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`,
`CRITICAL`; default `INFO`). `DEBUG` shows every request, every kept link with
the rule that matched, and every rejected zip with its reason:

```bash
BVB_ESEF_LOGLEVEL=DEBUG bvb-esef backfill --from-year 2024 --to-year 2026
```

```text
https://bvb.ro/infocont/infocont23/EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip
https://bvb.ro/infocont/infocont24/COMI_20240528170804_315700NXLBV70RI3NR23-2023-12-31.zip
```

Non-ESEF zips listed here are downloaded, reported and skipped, so the file can
be curated without pre-filtering.

## Export schema (`filings.json`)

See `examples/filings.example.json`:

```json
{"filings": [{"entity": {"lei": "...", "name": "...", "ticker": "EL", "country": "RO"},
  "report": {"filing_url": "https://bvb.ro/infocont/...zip", "filing_date": "2023-04-28",
  "period_end": "2022-12-31", "sha256": "...", "source_system": "BVB_IRIS",
  "language": "ro", "is_consolidated": true}}]}
```

The parser takes the LEI from the filename or the `<xbrli:identifier>` inside
`ix:header`, `period_end` from the newest `<xbrli:endDate/instant>` or the
filename date, the language from the `-ro/-en` suffix, the SHA-256 of the
downloaded ZIP, and `filing_date` from the BVB timestamp prefix.

## Tests

```bash
pytest -q
```

## Daily sync (cron)

```cron
0 6 * * * /path/to/bvb-esef-crawler/scripts/sync.sh >> /var/log/bvb-esef.log 2>&1
```

## Handover to filings.xbrl.org

1. Run `bvb-esef crawl` and `bvb-esef backfill --url-file urls.txt`.
2. Send this repo plus `data/out/filings.json[l]` and `data/out/companies.json`
   to **`filings@xbrl.org`** for integration into the main collector.

## License

MIT — see [LICENSE.md](LICENSE.md) ([Romanian](LICENSE.ro.md)). XBRL
International additionally holds a perpetual, royalty-free grant to use and
redistribute the output data for `filings.xbrl.org`, recorded in
[GRANT-XBRL.md](GRANT-XBRL.md) ([Romanian](GRANT-XBRL.ro.md)).
