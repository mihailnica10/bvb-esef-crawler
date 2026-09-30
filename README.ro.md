# BVB ESEF Scraper & Ingestion Pipeline

Scraper pentru pachetele ESEF `.zip` publicate pe **BVB**
(Bursa de Valori București) plus pipeline de ingestie compatibil cu
`filings.xbrl.org`.

Versiunea în engleză: [README.md](README.md)

> **Statut juridic.** Acest instrument realizează acces automat la site-urile BVB. Termenii și condițiile publicate de BVB interzic accesul/parsarea automată și cer acordul scris expres al BVB pentru preluarea datelor electronice în orice alt scop decât informarea strict personală. Nu opera acest scraper împotriva BVB la scară mare, programat sau pentru redistribuire până la obținerea acordului. Vezi [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md) §§2, 4 și 8. Acel document este o analiză, nu consultanță juridică.

Descoperă emitenții din BVB, colectează arhivele ZIP de raportare din istoricul mobil al emitenților și din paginile agregate de raportare, supune fiecare candidat unei probe prin range, descarcă numai pachetele cu conținut iXBRL confirmat, inspectează metadatele pachetelor și
exportă `filings.json` / `filings.jsonl` / `companies.json`, cu rezultatele pre-verificărilor locale în `compliance.json` și validare Arelle opțională.

## Unde sunt fișierele pe BVB

- Istoricul rapoartelor emitenților: paginile mobile ale emitenților,
  `https://m.bvb.ro/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=SYM`,
  în special tabelul de raportare `gvRepDoc`.
- Listări agregate: `https://bvb.ro/` → *Rapoarte curente*
  (`/FinancialInstruments/SelectedData/CurrentReports`) și *Rezultate financiare*
  (`/FinancialInstruments/SelectedData/FinancialResults`).
- Atașamente: `https://bvb.ro/infocont/infocont{YY}/{NUME_FIȘIER}`
  (`{YY}` = ultimele două cifre ale anului publicării). Denumirile variază; de exemplu,
  `EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip`.
- Vârful raportărilor anuale în România este între **martie și mai**.

## Instalare

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[validate,validate-css]"  # validare ESEF Arelle locală, opțională
```

Directorul local de cache Arelle este exclus din versionare. Înaintea unei rulări Arelle offline, el trebuie să conțină deja schema de bază ESEF și un punct de intrare IFRS; altfel validarea înregistrează pachetul ca omis, nu ca valid sau invalid.

Export-o înainte de a porni comanda, deoarece headerele HTTP sunt construite la pornirea procesului:

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

# pipeline complet: data/zips/*.zip + data/out/{filings.json,filings.jsonl,companies.json,compliance.json}
bvb-esef crawl
./scripts/sync.sh
./scripts/sync.sh --arelle

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

Colectorul verifică dacă fiecare request inițial și redirecționat folosește numai `bvb.ro` sau un subdomeniu `bvb.ro` înainte de a-l trimite.

## Limbă

Mulți emitenți publică rapoarte ESEF atât în română, cât și în engleză. Când o rulare este limitată la o singură limbă cu `--lang`, volumul colectării scade corespunzător. El se aplică la colectare, deci pachetele filtrate nu sunt niciodată
supuse probării sau descărcării:

```bash
bvb-esef list --lang ro
bvb-esef crawl --lang en
bvb-esef backfill --from-year 2024 --to-year 2026 --lang ro --lang en
```

Fiecare pachet colectat produce o înregistrare pentru varianta sa de limbă. Când mai mulți candidați au același emitent, perioadă și limbă, pipeline-ul preferă varianta iXBRL. Fără `--lang` se colectează ambele limbi.

## Limite de rată

Fiecare request HTTP către BVB trece printr-un singur `RateLimiter` secvențial:
delay minim între requesturi HTTP, o reîncercare la 429/503, skip la eroare,
reluare prin omiterea fișierelor deja descărcate și reverificarea redirecționărilor în raport cu allowlist-ul BVB. Se reglează per comandă:

| comanda     | `--delay` implicit |
|-------------|--------------------|
| `list`      | 1.0 s              |
| `doctor`    | 1.0 s              |
| `companies` | 1.0 s              |
| `crawl`     | 2.0 s              |
| `backfill`  | 2.0 s              |

```bash
bvb-esef crawl --delay 2.5
bvb-esef backfill --delay 5 --limit 50
```

Valorile implicite urmăresc o rată mică de requesturi (ordinul a circa cinci requesturi pentru o verificare zilnică restrânsă și circa o sută sau mai multe pentru un backfill amplu), cu o singură conexiune secvențială și fără concurență. Impactul redus este un obiectiv de inginerie, nu o autorizare juridică, iar termenii BVB interzic accesul automat indiferent de rată (vezi [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md) §4).

## Note despre backfill

La data de 2026-09-30, acoperirea României pe `filings.xbrl.org` părea incompletă pentru raportările din 2022 încoace, conform inspectării manuale a indexului său public. Verifică din nou înainte de a te baza pe această afirmație; serviciul precizează că repository-ul său „nu este complet" (`https://filings.xbrl.org/docs/about`). `backfill`
mătură sursele disponibile, păstrează hit-urile al căror URL de publicare intră în
`--from-year..--to-year`, descarcă doar fișierele lipsă și face merge în
`filings.json` existent (deduplicare după `filing_url`), astfel încât reluările fac merge după `filing_url` fără a duplica înregistrările existente.

De asemenea, face postback pe selectorul `ddYear` din pagina Rezultate
financiare o dată pe an din interval și afișează un număr per an. Se poate
dezactiva cu `--no-sweep-years`. Filtrarea după anul publicării se bazează pe anul URL-ului/publicării, nu pe `period_end` al raportului.

### Acoperire și istoric

`bvb-esef doctor` colectează și supune probării prin range candidații pentru anii
dați, fără să descarce nimic, și afișează numărătorile pe surse, astfel încât o
rulare goală poate fi de obicei diagnosticată:

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
(`Range`) și pachetul este acceptat pentru descărcare doar dacă se găsește efectiv marcarea iXBRL.
După descărcare, fiecare pachet este reinspectat, iar pachetele fără iXBRL sunt raportate și ignorate. Folosiți
`--no-probe` pentru a descărca totul sau `--keep-non-esef` pentru a indexa și
pachetele fără iXBRL.

## Validare

Fiecare pachet ingerat primește implicit o pre-verificare structurală offline rapidă. Folosește `--no-precheck` pentru a o omite. Rezultatele detaliate sunt stocate în `data/out/compliance.json`, nu în înregistrările publice ale raportărilor.

Validarea ESEF completă cu Arelle este opțională, deoarece durează circa 60 de secunde per pachet:

```bash
bvb-esef crawl --arelle
bvb-esef validate data/zips/EL_*.zip --arelle
```

Arelle are nevoie de extra-urile `[validate,validate-css]` și de un cache local de taxonomii populat. Dacă acel cache lipsește, rularea înregistrează pachetul ca omis, nu tratează erorile de taxonomie lipsă drept erori obișnuite de validare. Nici pre-verificarea, nici ieșirea Arelle nu reprezintă un certificat de conformitate.

## Logare

Nivelul se setează cu `BVB_ESEF_LOGLEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`,
`CRITICAL`; implicit `INFO`). `DEBUG` arată fiecare request, fiecare ZIP probat cu rezultatul său și fiecare zip respins cu motivul:

```bash
BVB_ESEF_LOGLEVEL=DEBUG bvb-esef backfill --from-year 2024 --to-year 2026
```

```text
https://bvb.ro/infocont/infocont23/EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip
https://bvb.ro/infocont/infocont24/COMI_20240528170804_315700NXLBV70RI3NR23-2023-12-31.zip
```

Pachetele respinse după descărcare sunt raportate și ignorate, nu indexate, deci fișierul poate fi curatoriat fără pre-filtrare.

## Schema de export (`filings.json`)

Vezi `examples/filings.example.json`:

```json
{"filings": [{"entity": {"lei": "...", "name": "...", "ticker": "EL", "country": "RO"},
  "report": {"filing_url": "https://bvb.ro/infocont/...zip", "filing_date": "2023-04-28",
  "period_end": "2022-12-31", "sha256": "...", "source_system": "BVB_IRIS",
  "language": "ro", "is_consolidated": true}}]}
```

Parserul ia LEI-ul din numele fișierului sau din `<xbrli:identifier>` din
`ix:header`, numele entității din `dei:EntityRegistrantName` atunci când există, `period_end` din cel mai nou `<xbrli:endDate/instant>` sau din data
din filename, limba din sufixul `-ro/-en`, SHA-256 din ZIP-ul descărcat, iar
`filing_date` din prefixul timestamp BVB sau dintr-o dată de rezervă atunci când acel prefix lipsește.
`is_consolidated` este în prezent o valoare implicită asumată, nu o valoare detectată din raport. Rezultatele detaliate de pre-verificare și Arelle sunt păstrate separat în `data/out/compliance.json`, indexate după URL-ul raportării.

## Teste

```bash
pytest -q
```

Acestea sunt teste unitare offline. Nu verifica documentația prin rulări live ample împotriva BVB.

## Sync zilnic (cron)

```cron
0 6 * * * /path/to/bvb-esef-scraper/scripts/sync.sh >> /var/log/bvb-esef.log 2>&1
```

## Predare către filings.xbrl.org

1. Rulează `bvb-esef crawl` și `bvb-esef backfill --url-file urls.txt`.
2. Doar după rezolvarea poziției privind acordul și licențierea din [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md) §8, trimite acest repo plus `data/out/filings.json[l]`, `data/out/companies.json` și `data/out/compliance.json`
   la **`filings@xbrl.org`** pentru integrare în colectorul principal.

## Licență

MIT — vezi [LICENSE.md](LICENSE.md) ([română](LICENSE.ro.md)). XBRL
International deține în plus un grant perpetuu și gratuit de utilizare și
redistribuire a datelor de ieșire pentru `filings.xbrl.org`, consemnat în
[GRANT-XBRL.md](GRANT-XBRL.md) ([română](GRANT-XBRL.ro.md)).

Pentru analiza de conformitate a proiectului, vezi [LEGAL_DISCLOSURE.md](LEGAL_DISCLOSURE.md); aceasta nu autorizează operarea.
