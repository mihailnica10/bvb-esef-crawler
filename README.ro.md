# BVB ESEF Scraper & Ingestion Pipeline

Scraper pentru pachetele ESEF `.zip` publicate prin **IRIS / BVB**
(Bursa de Valori București) plus pipeline de ingestie compatibil cu
`filings.xbrl.org`.

Versiunea în engleză: [README.md](README.md)

Scanează IRIS și `bvb.ro/infocont/infocont{YY}/…`, filtrează atașamentele ESEF,
le descarcă, inspectează fiecare pachet (LEI, sfârșit de perioadă, SHA-256) și
exportă `filings.json` / `filings.jsonl`, cu validare Arelle opțională.

## Unde sunt fișierele pe BVB

- Fluxul IRIS: `https://iris.bvb.ro/` → *Public Reports* (`/PublicReports/Reports`,
  tabel ASP.NET randat server-side `gv_IssuerReports`: Company - Symbol / Title / Date).
- Portalul BVB: `https://bvb.ro/` → *Rapoarte curente*
  (`/FinancialInstruments/SelectedData/CurrentReports`) și *Rezultate financiare*
  (`/FinancialInstruments/SelectedData/FinancialResults`).
- Atașamente: `https://bvb.ro/infocont/infocont{YY}/{NUME_FIȘIER}`
  (`{YY}` = ultimele două cifre ale anului publicării). Convenția de denumire:
  `{SIMBOL}_{TIMESTAMP}_{LEI}-{DATA_SFÂRȘIT_PERIOADĂ}-{LIMBA}.zip`, ex.
  `EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip`.
- Vârful raportărilor anuale în România este între **martie și mai**.

## Instalare

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install arelle-release   # opțional, motorul de referință ESMA pentru validare ESEF
```

Setează `BVB_ESEF_CONTACT` pentru a adăuga date de contact în User-Agent-ul HTTP:

```bash
export BVB_ESEF_CONTACT="nume-prenume@example.com"
```

## Utilizare

```bash
# descoperă emitenții live din Markets/Shares (fără listă hardcodată)
bvb-esef companies

# listează atașamentele candidate (fără download)
bvb-esef list
bvb-esef list -s EL --no-discover

# fluxul IRIS brut (titluri, flag ESEF?)
bvb-esef scan-iris --period m

# pipeline complet: data/zips/*.zip + data/out/{filings.json,filings.jsonl,companies.json}
bvb-esef crawl
./scripts/sync.sh
./scripts/sync.sh --validate

# backfill 2022..azi (face merge în același filings.json, sare peste fișierele existente)
bvb-esef backfill
bvb-esef backfill --from-year 2022 --to-year 2024 --delay 3
bvb-esef backfill --url-file urls.txt   # ingeră URL-uri .zip cunoscute, unul pe linie

# inspecție / validare punctuală
bvb-esef inspect data/zips/EL_*.zip
bvb-esef validate data/zips/EL_*.zip

# explică acoperirea pe surse (de ce e gol rezultatul?)
bvb-esef doctor --from-year 2022 --to-year 2026
```

Istoricul rapoartelor se află pe paginile de emitent **mobile**. Fiecare pagină
`https://m.bvb.ro/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=SYM`
își încarcă tab-urile client-side, deci tab-ul de rapoarte se atinge refăcând
`__doPostBack` al lui (ținta evenimentului e detectată din eticheta tab-ului,
niciodată codificată fix). Răspunsul conține `table#gvRepDoc` cu istoricul
complet de rapoarte și atașamentele `.zip`, cel puțin până în 2012. Paginile
desktop `bvb.ro/.../FinancialInstrumentsDetails.aspx` nu expun acest tab.

IRIS este WebForms (`__VIEWSTATE` + `__doPostBack`); `scan-iris` reface POST-ul
`ddlPeriod`. Detaliile cu atașamente care necesită JS se rezolvă cel mai fidel
cu Playwright (tab-ul *Network*).

## Limbă

Majoritatea emitenților publică fiecare raport ESEF în română și în engleză, deci
filtrul de limbă reduce aproximativ la jumătate numărul de cereri al unei rulări
complete. El se aplică la colectare, deci pachetele filtrate nu sunt niciodată
supuse probării sau descărcării:

```bash
bvb-esef list --lang ro
bvb-esef crawl --lang en
bvb-esef backfill --from-year 2024 --to-year 2026 --lang ro --lang en
```

Româna și engleza rămân înregistrări separate (un record per pachet), iar
variantele duplicate ale aceluiași raport (același emitent, perioadă și limbă)
sunt reunite, păstrând pachetul iXBRL. Fără `--lang` se colectează ambele limbi.

## Limite de rată

Fiecare comandă care atinge BVB trece printr-un singur `RateLimiter` secvențial:
delay minim între requesturi HTTP, o reîncercare la 429/503, skip la eroare și
reluare prin omiterea fișierelor deja descărcate. Se reglează per comandă:

| comanda   | `--delay` implicit |
|-----------|--------------------|
| `list`    | 1.0 s              |
| `crawl`   | 1.0 s              |
| `backfill`| 2.0 s              |
| `scan-iris` | 1.0 s            |

```bash
bvb-esef crawl --delay 2.5
bvb-esef backfill --delay 5 --limit 50
```

Valorile implicite mențin o rulare completă (~5 requesturi zilnic, ~100+ pentru
backfill cu pagini de companie) mult sub orice nivel care ar putea deranja
serverele BVB.

## Note despre backfill

`filings.xbrl.org` nu are date pentru România din 2022 încoace. `backfill`
mătură sursele disponibile, păstrează hit-urile al căror an (`infocontYY`,
`Raportari/YYYY` sau data perioadei din numele fișierului) intră în
`--from-year..--to-year`, descarcă doar fișierele lipsă și face merge în
`filings.json` existent (deduplicare după `filing_url`), deci reluările sunt
sigure.

De asemenea, face postback pe selectorul `ddYear` din pagina Rezultate
financiare o dată pe an din interval și afișează un număr per an. Se poate
dezactiva cu `--no-sweep-years`.

### Acoperire și istoric

`bvb-esef doctor` colectează și supune probării prin range candidații pentru anii
dați, fără să descarce nimic, și afișează numărătorile pe surse, astfel încât o
rulare goală e întotdeauna explicabilă:

```bash
bvb-esef doctor --from-year 2024 --to-year 2026
bvb-esef doctor --from-year 2024 --to-year 2026 --lang ro
```

### Nu orice `.zip` este ESEF, iar numele fișierului nu e un filtru fiabil

BVB publică și pachete cu situații financiare (de ex.
`Raportari/2025/BAC_RA2025_ro.zip`) care sunt doar PDF-uri într-un zip. Numele
fișierelor sunt inconsistente: pachete ESEF reale apar atât ca
`TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip`, cât și ca
`BRD_20260318062626_BRDSocieteGenerale-2025-12-31-ro.zip` sau
`BRDSocieteGenerale-2025-12-31 ESEF RO xhtml.zip`, fără să conțină ESEF într-o
formă utilizabilă. Așadar **fiecare** zip candidat e supus probei prin range:
se citește directorul central ZIP, se decompune xhtml dintr-un interval de octeți
(`Range`) și pachetul e acceptat doar dacă marcarea iXBRL e prezentă efectiv.
Pachetele sunt descărcate integral doar după ce proba trece. Folosiți
`--no-probe` pentru a descărca totul sau `--keep-non-esef` pentru a indexa și
pachetele fără iXBRL.

## Logare

Nivelul se setează cu `BVB_ESEF_LOGLEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`,
`CRITICAL`; implicit `INFO`). `DEBUG` arată fiecare request, fiecare link
păstrat cu regula care l-a potrivit și fiecare zip respins cu motivul:

```bash
BVB_ESEF_LOGLEVEL=DEBUG bvb-esef backfill --from-year 2024 --to-year 2026
```

```text
https://bvb.ro/infocont/infocont23/EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip
https://bvb.ro/infocont/infocont24/COMI_20240528170804_315700NXLBV70RI3NR23-2023-12-31.zip
```

Zipurile care nu sunt ESEF din această listă sunt descărcate, raportate și
ignorate, deci fișierul poate fi curatoriat fără pre-filtrare.

## Schema de export (`filings.json`)

Vezi `examples/filings.example.json`:

```json
{"filings": [{"entity": {"lei": "...", "name": "...", "ticker": "EL", "country": "RO"},
  "report": {"filing_url": "https://bvb.ro/infocont/...zip", "filing_date": "2023-04-28",
  "period_end": "2022-12-31", "sha256": "...", "source_system": "BVB_IRIS",
  "language": "ro", "is_consolidated": true}}]}
```

Parserul ia LEI-ul din numele fișierului sau din `<xbrli:identifier>` din
`ix:header`, `period_end` din cel mai nou `<xbrli:endDate/instant>` sau din data
din filename, limba din sufixul `-ro/-en`, SHA-256 din ZIP-ul descărcat, iar
`filing_date` din prefixul timestamp BVB.

## Teste

```bash
pytest -q
```

## Sync zilnic (cron)

```cron
0 6 * * * /path/to/bvb-esef-crawler/scripts/sync.sh >> /var/log/bvb-esef.log 2>&1
```

## Predare către filings.xbrl.org

1. Rulează `bvb-esef crawl` și `bvb-esef backfill --url-file urls.txt`.
2. Trimite acest repo plus `data/out/filings.json[l]` și `data/out/companies.json`
   la **`filings@xbrl.org`** pentru integrare în colectorul principal.

## Licență

MIT — vezi [LICENSE.md](LICENSE.md) ([română](LICENSE.ro.md)). XBRL
International deține în plus un grant perpetuu și gratuit de utilizare și
redistribuire a datelor de ieșire pentru `filings.xbrl.org`, consemnat în
[GRANT-XBRL.md](GRANT-XBRL.md) ([română](GRANT-XBRL.ro.md)).
