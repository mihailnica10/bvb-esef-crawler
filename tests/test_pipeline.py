import time
import zipfile
from pathlib import Path
from bvb_esef.filters import (looks_like_esef, match_reason, extract_lei,
                              extract_period_end)
from bvb_esef.bvb import (parse_infocont_links, parse_companies, default_pages,
                          parse_report_rows, find_reports_tab, BvbHit)
from bvb_esef.esef import inspect_zip
from bvb_esef.metadata import filing_record, merge_records, read_index
from bvb_esef.pipeline import (guess_symbol, read_url_file, _dedupe,
                              filing_date_from_filename)
from bvb_esef.filters import year_of, in_years, esef_entry_name
from bvb_esef.filters import language_of, matches_langs
from bvb_esef.polite import RateLimiter


def test_filters():
    url = "https://bvb.ro/infocont/infocont23/EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip"
    assert looks_like_esef("Raport anual format ESEF", url)
    assert extract_lei(url) == "213800P4SUNUM5AUDX61"
    assert extract_period_end(url) == "2022-12-31"
    assert not looks_like_esef("Raport curent", "https://bvb.ro/infocont/infocont26/X_2026.pdf")


def test_financial_statements_zip_is_not_esef():
    url = "http://www.bvb.ro/Raportari/2025/BAC_RA2025_ro.zip"
    assert not looks_like_esef("Raport anual 2025", url)
    assert match_reason("Raport anual 2025", url) is None


def test_parse_infocont_collects_non_infocont_zips():
    html = ('<table><tr><td><a title="Raport anual 2025" '
            'href="http://www.bvb.ro/Raportari/2025/BAC_RA2025_ro.zip">Raport anual 2025</a>'
            '</td></tr></table>')
    hits = parse_infocont_links(html, "https://bvb.ro/page")
    assert len(hits) == 1
    assert hits[0].filing_url.endswith("BAC_RA2025_ro.zip")
    assert "Raport anual 2025" in hits[0].title


def test_dedupe_hits():
    h = BvbHit("https://bvb.ro/infocont/infocont23/EL_x.zip", "t", "EL", "p")
    assert len(_dedupe([h, h, h])) == 1


def test_filing_date_alternative_formats():
    assert filing_date_from_filename("BAC_RA2025_ro.zip") is None
    vesy = "VESY_20260616105735_vesy-ESEF-format-xhtml-RO-31-12-2025.zip"
    assert filing_date_from_filename(vesy) == "2026-06-16"
    assert extract_period_end(vesy) == "2025-12-31"
    assert filing_date_from_filename(
        "EL_20230428175526_x-2022-12-31-ro.zip") == "2023-04-28"
    assert filing_date_from_filename("EL_infocont23_x.zip") == "2023-12-31"


def test_parse_infocont():
    html = '<tr><td>EL - test</td><td><a href="/infocont/infocont23/EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip">Raport anual ESEF</a></td></tr>'
    hits = parse_infocont_links(html, "https://bvb.ro/page")
    assert len(hits) == 1 and hits[0].filing_url.endswith(".zip")


def test_parse_companies():
    html = ('<table><tr><td><a href="/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=EL">EL</a></td>'
            '<td>ROELECACNOR5</td><td>SOCIETATEA ENERGETICA ELECTRICA S.A.</td>'
            '<td>Premium</td></tr>'
            '<tr><td><a href="/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=EL">EL</a></td></tr></table>')
    companies = parse_companies(html)
    assert len(companies) == 1
    assert companies[0].symbol == "EL"
    assert companies[0].category == "Premium"
    assert companies[0].name == "SOCIETATEA ENERGETICA ELECTRICA S.A."


def test_parse_report_rows_filters_by_year():
    html = ('<h2>Raportari</h2><table id="gvRepDoc"><tr><th>Data</th><th>Doc'
            '</th><th></th></tr>'
            '<tr><td>27.03.2026</td><td>Raport anual 2025</td><td>'
            "<a href='/infocont/infocont26/TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip'>z</a>"
            "<a href='/infocont/infocont26/TLV_20260327173401_Raport-anual-2025.pdf'>p</a>"
            '</td></tr></table>')
    hits = parse_report_rows(html, "https://m.bvb.ro/x", "TLV", (2026, 2025))
    assert len(hits) == 1
    assert hits[0].symbol == "TLV"
    assert hits[0].filing_url.endswith("ESEF-format-iXBRL-RO-31-12-2025.zip")
    assert "Raport anual 2025" in hits[0].title
    assert parse_report_rows(html, "u", "TLV", (2019,)) == []


def test_find_reports_tab():
    html = ("<li><a href=\"javascript:__doPostBack('ctl00$body$TabsControlResponsive$0','')\">Sumar</a></li>"
            "<li><a href=\"javascript:__doPostBack('ctl00$body$TabsControlResponsive$4','')\">Informatii financiare</a></li>")
    assert find_reports_tab(html) == "ctl00$body$TabsControlResponsive$4"
    assert find_reports_tab("<div>nothing</div>") is None


def test_default_pages_no_company_pages_by_default():
    pages, companies = default_pages(discover=False)
    assert len(pages) == 2
    assert companies == []


def test_inspect_zip(tmp_path: Path):
    z = tmp_path / "EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip"
    xhtml = ('<html><ix:header xmlns:ix="x"><xbrli:xbrl xmlns:xbrli="y">'
             '<xbrli:identifier>213800P4SUNUM5AUDX61</xbrli:identifier>'
             '<xbrli:endDate>2022-12-31</xbrli:endDate></xbrli:xbrl></ix:header></html>')
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("report.xhtml", xhtml)
        zz.writestr("ext.xsd", "<schema/>")
    info = inspect_zip(z)
    assert info.lei == "213800P4SUNUM5AUDX61"
    assert info.period_end == "2022-12-31"
    assert info.has_ixbrl and info.language == "ro"


def test_record_schema():
    r = filing_record(lei="213800P4SUNUM5AUDX61", name="ELECTRICA S.A.", ticker="EL",
                      filing_url="https://bvb.ro/infocont/infocont23/EL_x.zip",
                      filing_date="2023-04-28", period_end="2022-12-31",
                      sha256="abc", language="ro")
    assert r["entity"]["country"] == "RO"
    assert r["report"]["source_system"] == "BVB_IRIS"


def test_merge_records_dedupes_by_url():
    old = [filing_record(lei="L", name="N", ticker="EL", filing_url="u1",
                         filing_date="2023-01-01", period_end="2022-12-31",
                         sha256="a", language="ro")]
    new = [filing_record(lei="L", name="N", ticker="EL", filing_url="u1",
                         filing_date="2023-01-01", period_end="2022-12-31",
                         sha256="b", language="ro"),
           filing_record(lei="L", name="N", ticker="EL", filing_url="u2",
                         filing_date="2024-01-01", period_end="2023-12-31",
                         sha256="c", language="ro")]
    merged = merge_records(old, new)
    assert [r["report"]["filing_url"] for r in merged] == ["u1", "u2"]
    assert merged[0]["report"]["sha256"] == "b"


def test_read_index_missing(tmp_path: Path):
    assert read_index(tmp_path / "nope.json") == []


def test_year_of():
    assert year_of("https://bvb.ro/infocont/infocont23/EL_x.zip") == 2023
    assert year_of("https://bvb.ro/infocont/infocont24/x-2023-12-31.zip") == 2024
    assert year_of("https://bvb.ro/Raportari/2025/BAC_RA2025_ro.zip") == 2025
    assert year_of("https://bvb.ro/TLV_RA2015_ro.zip") == 2015
    assert year_of("https://bvb.ro/some/page") is None


def test_in_years():
    url = "https://bvb.ro/infocont/infocont23/EL_x.zip"
    assert in_years(url, (2022, 2023, 2024))
    assert not in_years(url, (2024, 2025))
    assert in_years(url, None)
    assert in_years("https://bvb.ro/unknown.zip", (2024,)) is True


def test_language_of():
    assert language_of("TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip") == "ro"
    assert language_of("TLV_20250429075638_ESEF-format-iXBRL-EN-31-12-2024.zip") == "en"
    assert language_of("EL_20260327182639_213800P4SUNUM5AUDX61-2025-12-31-1-ro.zip") == "ro"
    assert language_of("BRD_20260318062626_BRDSocieteGenerale-2025-12-31-ro.zip") == "ro"
    assert language_of("BRDSocieteGenerale-2025-12-31 ESEF RO xhtml.zip") == "ro"
    assert language_of("549300RG3H390KEL8896-2024-12-31-0-ro.xhtml") == "ro"
    assert language_of("EL_20240429185049_213800P4SUNUM5AUDX61-2023-12-31-en.zip") == "en"
    assert language_of("SNY_20260601_Convocator-AGA.zip") is None


def test_matches_langs():
    url = "x/TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip"
    assert matches_langs(url, None)
    assert matches_langs(url, ("ro", "en"))
    assert matches_langs(url, ("ro",))
    assert not matches_langs(url, ("en",))


def test_parse_report_rows_language_filter():
    html = ('<table id="gvRepDoc"><tr><td>Data</td><td>Doc</td><td></td></tr>'
            "<tr><td>27.03.2026</td><td>Raport anual</td><td>"
            "<a href='/infocont/infocont26/TLV_a_ESEF-format-iXBRL-RO-31-12-2025.zip'>ro</a>"
            "<a href='/infocont/infocont26/TLV_b_ESEF-format-iXBRL-EN-31-12-2025.zip'>en</a>"
            "<a href='/infocont/infocont26/TLV_c_Convocator-AGA.zip'>none</a>"
            '</td></tr></table>')
    both = parse_report_rows(html, "u", "TLV", (2026,))
    assert len(both) == 3
    ro = parse_report_rows(html, "u", "TLV", (2026,), ("ro",))
    assert [h.filing_url.rsplit("/", 1)[-1] for h in ro] == [
        "TLV_a_ESEF-format-iXBRL-RO-31-12-2025.zip"]
    en = parse_report_rows(html, "u", "TLV", (2026,), ("en",))
    assert [h.filing_url.rsplit("/", 1)[-1] for h in en] == [
        "TLV_b_ESEF-format-iXBRL-EN-31-12-2025.zip"]


def test_esef_entry_name():
    assert esef_entry_name("549300RG3H390KEL8896-2024-12-31-0-ro.xhtml")
    assert not esef_entry_name("ESEF IXBRL.xhtml")


def test_guess_symbol():
    assert guess_symbol("EL_20230428175526_x.zip") == "EL"
    assert guess_symbol("VESY_20260616105735_y.zip") == "VESY"
    assert guess_symbol("nope.zip") is None


def test_read_url_file(tmp_path: Path):
    f = tmp_path / "urls.txt"
    f.write_text("https://bvb.ro/infocont/infocont23/A.zip\n\nnot-a-zip\nhttps://x.ro/B.zip\n")
    assert read_url_file(f) == ["https://bvb.ro/infocont/infocont23/A.zip",
                                 "https://x.ro/B.zip"]


def test_rate_limiter_enforces_gap():
    lim = RateLimiter(0.05)
    lim.wait()
    t0 = time.monotonic()
    lim.wait()
    assert time.monotonic() - t0 >= 0.04
    RateLimiter(0).wait()
