from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin
import re
import time

from bs4 import BeautifulSoup
import httpx

from . import net
from .config import BVB_BASE, BVB_CURRENT_REPORTS, BVB_FINANCIAL_RESULTS, BVB_SHARES
from .filters import in_years, is_zip_url, matches_langs
from .log import log
from .polite import RateLimiter


@dataclass
class BvbHit:
    filing_url: str
    title: str
    symbol: str | None
    source_page: str


@dataclass
class Company:
    symbol: str
    name: str | None = None
    category: str | None = None


SYMBOL_LINK_RE = re.compile(r"FinancialInstrumentsDetails\.aspx\?s=([A-Z0-9]+)")
CATEGORY_RE = re.compile(r"\b(Premium|Standard|Intl|AeRO)\b", re.IGNORECASE)
ISIN_RE = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z]{2}[A-Z0-9]{10}\b")
DATE_CELL_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def _abs(href: str) -> str:
    return urljoin(BVB_BASE + "/", href)


def _clean_cell(cell: str, symbol: str) -> str:
    if ISIN_RE.search(cell):
        cell = ISIN_RE.sub("", cell)
        cell = re.sub(rf"\b{re.escape(symbol)}\b", "", cell, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cell).strip(" -")


def parse_companies(html: str) -> list[Company]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Company] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        m = SYMBOL_LINK_RE.search(a["href"])
        if not m:
            continue
        symbol = m.group(1).upper()
        if symbol in seen:
            continue
        seen.add(symbol)
        name, category = None, None
        tr = a.find_parent("tr")
        if tr:
            raw = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cm = CATEGORY_RE.search(" | ".join(raw))
            if cm:
                category = cm.group(1)
            cleaned = [_clean_cell(c, symbol) for c in raw]
            candidates = [c for c in cleaned
                          if c and not CATEGORY_RE.fullmatch(c)
                          and not DATE_CELL_RE.search(c)]
            if candidates:
                multi = [c for c in candidates if " " in c]
                name = max(multi or candidates, key=len)[:200]
        out.append(Company(symbol=symbol, name=name, category=category))
    return sorted(out, key=lambda c: c.symbol)


def fetch(url: str, client: httpx.Client | None = None,
          limiter: RateLimiter | None = None) -> str:
    own = client is None
    c = client or net.client()
    try:
        for attempt in (1, 2):
            if limiter:
                limiter.wait()
            log.debug("GET %s", url)
            r = net.get(c, url)
            if r.status_code in (429, 503) and attempt == 1:
                backoff = (limiter.delay if limiter else 1.0) * 5
                log.warning("HTTP %s on %s, retrying in %.1fs", r.status_code, url, backoff)
                time.sleep(backoff)
                continue
            r.raise_for_status()
            log.debug("HTTP %s %s (%d bytes)", r.status_code, url, len(r.text))
            return r.text
    finally:
        if own:
            c.close()


def discover_companies(delay: float = 1.0) -> list[Company]:
    try:
        companies = parse_companies(fetch(BVB_SHARES, limiter=RateLimiter(delay)))
        log.info("%d companies discovered", len(companies))
        return companies
    except Exception as e:
        log.warning("company discovery failed (%s), continuing without issuer pages", e)
        return []


def parse_infocont_links(html: str, source_page: str) -> list[BvbHit]:
    soup = BeautifulSoup(html, "lxml")
    hits: list[BvbHit] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        low = href.lower()
        if "infocont" not in low and not low.endswith(".zip"):
            continue
        url = _abs(href)
        anchor = a.get_text(" ", strip=True)
        ctx = anchor
        title = a.get("title") or ""
        parent = a.find_parent(["tr", "div", "li", "td"])
        if parent:
            ctx = parent.get_text(" ", strip=True)[:500]
        symbol = None
        m = re.search(r"[?&]s=([A-Z0-9]+)", source_page)
        if m:
            symbol = m.group(1)
        else:
            m2 = re.search(r"\b([A-Z]{2,6}\d*[A-Z]?)\b", ctx)
            if m2:
                symbol = m2.group(1)
        hits.append(BvbHit(filing_url=url, title=(title + " " + ctx).strip(),
                           symbol=symbol, source_page=source_page))
    return hits


def crawl_bvb_pages(pages: list[str], years: tuple[int, ...] | None = None,
                    delay: float = 1.0, stats: dict | None = None,
                    langs: tuple[str, ...] | None = None) -> list[BvbHit]:
    limiter = RateLimiter(delay)
    out: list[BvbHit] = []
    links = 0
    out_of_year = 0
    for page in pages:
        try:
            html = fetch(page, client=None, limiter=limiter)
        except Exception as e:
            log.warning("fetch failed %s: %s", page, e)
            continue
        kept = 0
        for h in parse_infocont_links(html, page):
            links += 1
            if not is_zip_url(h.filing_url):
                continue
            if not in_years(h.filing_url, years):
                out_of_year += 1
                continue
            if not matches_langs(h.filing_url, langs):
                continue
            kept += 1
            out.append(h)
        log.info("%s: %d zips in range", page, kept)
    log.info("aggregate pages: %d zips in range (%d links scanned, %d out of year)",
             len(out), links, out_of_year)
    if stats is not None:
        stats["page_zips"] = len(out)
    return out


def post_financial_results_year(page: str, year: str) -> str:
    with net.client() as client:
        html = fetch(page, client)
        soup = BeautifulSoup(html, "lxml")
        form = soup.find("form")
        if not form:
            raise RuntimeError("FinancialResults: no form found")
        data: dict[str, str] = {}
        for i in form.find_all("input"):
            n = i.get("name")
            t = (i.get("type") or "text").lower()
            if n and t not in ("submit", "button", "image", "file", "reset"):
                data[n] = i.get("value") or ""
        for s in form.find_all("select"):
            n = s.get("name")
            sel = s.find("option", selected=True)
            if n:
                data[n] = sel.get("value") if sel else ""
        for s in form.find_all("select"):
            if s.get("id") == "ddYear":
                data[s.get("name")] = year
                break
        log.debug("POST %s ddYear=%s", page, year)
        r = net.post(client, page, data=data)
        r.raise_for_status()
        return r.text


def crawl_financial_results(years: tuple[int, ...] = (),
                            delay: float = 1.0, stats: dict | None = None,
                            langs: tuple[str, ...] | None = None) -> list[BvbHit]:
    from .config import BVB_FINANCIAL_RESULTS
    limiter = RateLimiter(delay)
    out: list[BvbHit] = []
    per_year: dict[str, int] = {}
    for year in years:
        limiter.wait()
        try:
            html = post_financial_results_year(BVB_FINANCIAL_RESULTS, str(year))
        except Exception as e:
            log.warning("FinancialResults %s failed: %s", year, e)
            continue
        hits = [h for h in parse_infocont_links(html, BVB_FINANCIAL_RESULTS)
                if is_zip_url(h.filing_url) and matches_langs(h.filing_url, langs)]
        per_year[str(year)] = len(hits)
        out.extend(hits)
        log.info("FinancialResults %s: %d zips", year, len(hits))
    empty = [y for y, n in per_year.items() if not n]
    log.info("FinancialResults: %d zips across %d years%s",
             len(out), len(per_year),
             f" (empty: {', '.join(empty)})" if empty else "")
    if stats is not None:
        stats["fr_per_year"] = per_year
    return out


def find_reports_tab(html: str) -> str | None:
    from .config import TAB_LABELS, TAB_TARGET_RE
    soup = BeautifulSoup(html, "lxml")
    fallback = None
    for a in soup.find_all("a", href=True):
        m = TAB_TARGET_RE.search(a["href"].replace("&#39;", "'").replace("&apos;", "'"))
        if not m:
            continue
        if fallback is None:
            fallback = m.group(1)
        label = a.get_text(" ", strip=True).lower()
        for key in TAB_LABELS:
            if key in label:
                return m.group(1)
    return fallback


def parse_report_rows(html: str, source_page: str, symbol: str,
                      years: tuple[int, ...] | None = None,
                      langs: tuple[str, ...] | None = None) -> list[BvbHit]:
    from .config import REPORTS_TABLE_ID
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=REPORTS_TABLE_ID)
    if table is None:
        return []
    hits: list[BvbHit] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        date_txt = cells[0].get_text(" ", strip=True)
        desc = cells[1].get_text(" ", strip=True)
        for a in tr.find_all("a", href=True):
            url = _abs(a["href"])
            if not is_zip_url(url) or not in_years(url, years):
                continue
            if not matches_langs(a["href"], langs):
                continue
            hits.append(BvbHit(filing_url=url,
                               title=f"{desc} {date_txt}".strip(),
                               symbol=symbol, source_page=source_page))
    return hits


def fetch_issuer_reports(symbol: str, years: tuple[int, ...] | None,
                         limiter: RateLimiter, client: httpx.Client,
                         langs: tuple[str, ...] | None = None) -> list[BvbHit]:
    from .config import BVB_ISSUER_DETAILS
    url = BVB_ISSUER_DETAILS.format(symbol=symbol.upper())
    try:
        html = fetch(url, client, limiter)
    except Exception as e:
        log.warning("%s: issuer page failed: %s", symbol, e)
        return []
    target = find_reports_tab(html)
    if not target:
        log.warning("%s: no reports tab", symbol)
        return []
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form")
    if not form:
        return []
    data: dict[str, str] = {}
    for i in form.find_all("input"):
        n = i.get("name")
        t = (i.get("type") or "text").lower()
        if n and t not in ("submit", "button", "image", "file", "reset"):
            data[n] = i.get("value") or ""
    data["__EVENTTARGET"] = target
    data["__EVENTARGUMENT"] = ""
    try:
        limiter.wait()
        log.debug("%s: postback %s", symbol, target)
        r = net.post(client, url, data=data)
        r.raise_for_status()
    except Exception as e:
        log.warning("%s: reports tab postback failed: %s", symbol, e)
        return []
    hits = parse_report_rows(r.text, url, symbol.upper(), years, langs)
    log.info("%s: %d zips in range", symbol, len(hits))
    return hits


def crawl_issuers(companies: list[Company], years: tuple[int, ...] | None = None,
                  delay: float = 2.0, stats: dict | None = None,
                  langs: tuple[str, ...] | None = None) -> list[BvbHit]:
    limiter = RateLimiter(delay)
    out: list[BvbHit] = []
    empty: list[str] = []
    with net.client() as client:
        for n, c in enumerate(companies, 1):
            log.info("[%d/%d] %s", n, len(companies), c.symbol)
            hits = fetch_issuer_reports(c.symbol, years, limiter, client, langs)
            if not hits:
                empty.append(c.symbol)
            out.extend(hits)
    log.info("issuer report tabs: %d zips in range from %d issuers",
             len(out), len(companies))
    if empty:
        log.info("no zips in range for %d issuers", len(empty))
    if stats is not None:
        stats["issuer_zips"] = len(out)
        stats["issuers_scanned"] = len(companies)
        stats["issuers_empty"] = len(empty)
    return out


def default_pages(symbols: list[str] | None = None, discover: bool = True,
                   include_company_pages: bool = False,
                   delay: float = 1.0) -> tuple[list[str], list[Company]]:
    pages = [BVB_CURRENT_REPORTS, BVB_FINANCIAL_RESULTS]
    companies: list[Company] = discover_companies(delay) if discover else []
    extra = {s.upper() for s in (symbols or [])}
    extra -= {c.symbol for c in companies}
    companies += [Company(symbol=s) for s in sorted(extra)]
    if include_company_pages:
        from .config import BVB_ISSUER_DETAILS
        for c in companies:
            pages.append(BVB_ISSUER_DETAILS.format(symbol=c.symbol))
        log.info("added %d per-issuer pages (rolling recent-announcements window)",
                 len(companies))
    return pages, companies
