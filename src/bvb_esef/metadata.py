from __future__ import annotations

from pathlib import Path
import json

IS_CONSOLIDATED_ASSUMED = True
SOURCE_SYSTEM = "BVB_IRIS"
DEFAULT_LANGUAGE = "ro"
DEFAULT_COUNTRY = "RO"
UNKNOWN = "UNKNOWN"


def filing_record(*, lei, name, ticker, filing_url, filing_date,
                  period_end, sha256, language=None,
                  is_consolidated=IS_CONSOLIDATED_ASSUMED,
                  source_system=SOURCE_SYSTEM) -> dict:
    return {
        "entity": {
            "lei": lei,
            "name": name or ticker or lei,
            "ticker": ticker,
            "country": DEFAULT_COUNTRY,
        },
        "report": {
            "filing_url": filing_url,
            "filing_date": filing_date,
            "period_end": period_end,
            "sha256": sha256,
            "source_system": source_system,
            "language": language or DEFAULT_LANGUAGE,
            "is_consolidated": is_consolidated,
        },
    }


def merge_records(existing: list[dict], new: list[dict]) -> list[dict]:
    by_url = {r["report"]["filing_url"]: r for r in existing}
    for r in new:
        by_url[r["report"]["filing_url"]] = r
    return sorted(by_url.values(), key=lambda r: (r["report"]["period_end"] or "",
                                                  r["report"]["filing_url"]))


def read_index(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("filings", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def write_index(records: list[dict], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"filings": records}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return dest


def write_jsonl(records: list[dict], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
    return dest


def read_compliance(path: Path | str) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_compliance(entries: dict[str, dict], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: entries[k] for k in sorted(entries)}
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return dest
