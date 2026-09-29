from __future__ import annotations
from dataclasses import dataclass
import re

import httpx
from bs4 import BeautifulSoup

from .config import IRIS_REPORTS, HEADERS
from .filters import looks_like_esef
from .log import log
from .polite import RateLimiter


@dataclass
class IrisReport:
    company: str
    symbol: str | None
    title: str
    date: str
    esef_candidate: bool


def parse_iris_table(html: str) -> list[IrisReport]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="gv_IssuerReports")
    if not table:
        return []
    rows = table.find_all("tr")[1:]
    out: list[IrisReport] = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        company_raw = tds[0].get_text(" ", strip=True)
        title = tds[1].get_text(" ", strip=True)
        date = tds[2].get_text(" ", strip=True)
        m = re.search(r"-\s*([A-Z0-9]+)\s*$", company_raw)
        symbol = m.group(1) if m else None
        out.append(IrisReport(
            company=company_raw, symbol=symbol, title=title, date=date,
            esef_candidate=looks_like_esef(title),
        ))
    return out


def fetch_iris(period: str = "w", delay: float = 1.0) -> list[IrisReport]:
    limiter = RateLimiter(delay)
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
        limiter.wait()
        r = c.get(IRIS_REPORTS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        data = {}
        for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
                     "__VIEWSTATEENCRYPTED"):
            el = soup.find("input", {"name": name})
            if el:
                data[name] = el.get("value", "")
        data["__EVENTTARGET"] = "ctl00$MainContent$ddlPeriod"
        data["__EVENTARGUMENT"] = ""
        ddl = soup.find("select", {"id": "MainContent_ddlPeriod"})
        if ddl:
            data["ctl00$MainContent$ddlPeriod"] = period
        try:
            limiter.wait()
            r2 = c.post(IRIS_REPORTS, data=data)
            r2.raise_for_status()
            reports = parse_iris_table(r2.text)
            log.info("%d IRIS reports (period=%s)", len(reports), period)
            return reports
        except Exception as e:
            log.warning("IRIS postback failed (%s), falling back to GET parse", e)
            return parse_iris_table(r.text)
