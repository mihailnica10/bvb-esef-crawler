from __future__ import annotations
import os
import re

from . import __version__

BVB_BASE = "https://bvb.ro"
BVB_MOBILE = "https://m.bvb.ro"
IRIS_BASE = "https://iris.bvb.ro"

BVB_CURRENT_REPORTS = f"{BVB_BASE}/FinancialInstruments/SelectedData/CurrentReports"
BVB_FINANCIAL_RESULTS = f"{BVB_BASE}/FinancialInstruments/SelectedData/FinancialResults"
BVB_SHARES = f"{BVB_BASE}/FinancialInstruments/Markets/Shares"
BVB_ISSUER_DETAILS = (f"{BVB_MOBILE}/FinancialInstruments/Details/"
                      f"FinancialInstrumentsDetails.aspx?s={{symbol}}")
IRIS_REPORTS = f"{IRIS_BASE}/PublicReports/Reports"

REPORTS_TABLE_ID = "gvRepDoc"
TAB_TARGET_RE = re.compile(r"__doPostBack\('([^']*TabsControl[^']*)',''\)")
TAB_LABELS = ("informati", "raportari", "raport", "financiar")

INFOCONT_PATTERN = "infocont"

ESEF_KEYWORDS = ("esef", "xhtml", "xbrl")

DEFAULT_DELAY = 1.0
BACKFILL_DELAY = 2.0
BACKFILL_SINCE_YEAR = 2022


def _user_agent() -> str:
    base = f"bvb-esef-scraper/{__version__}"
    contact = os.environ.get("BVB_ESEF_CONTACT", "").strip()
    return f"{base} (+{contact})" if contact else base


HEADERS = {
    "User-Agent": _user_agent(),
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}
