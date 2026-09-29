from __future__ import annotations
import json
from pathlib import Path


def filing_record(*, lei, name, ticker, filing_url, filing_date,
                  period_end, sha256, language=None,
                  is_consolidated=True, source_system="BVB_IRIS") -> dict:
    return {
        "entity": {
            "lei": lei,
            "name": name or ticker or lei,
            "ticker": ticker,
            "country": "RO",
        },
        "report": {
            "filing_url": filing_url,
            "filing_date": filing_date,
            "period_end": period_end,
            "sha256": sha256,
            "source_system": source_system,
            "language": language or "ro",
            "is_consolidated": is_consolidated,
        },
    }


def merge_records(existing: list[dict], new: list[dict]) -> list[dict]:
    by_url = {r["report"]["filing_url"]: r for r in existing}
    for r in new:
        by_url[r["report"]["filing_url"]] = r
    return sorted(by_url.values(), key=lambda r: (r["report"]["period_end"] or "",
                                                  r["report"]["filing_url"]))


def read_index(path: Path) -> list[dict]:
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
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return dest
