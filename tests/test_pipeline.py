from pathlib import Path
import datetime
import json
import time
import zipfile

import pytest

from bvb_esef.bvb import (
    BvbHit,
    default_pages,
    find_reports_tab,
    parse_companies,
    parse_infocont_links,
    parse_report_rows,
)
from bvb_esef.esef import EsefInfo, dei_fact, inspect_zip
from bvb_esef.filters import (
    esef_entry_name,
    extract_lei,
    extract_period_end,
    in_years,
    is_zip_url,
    language_of,
    matches_langs,
    year_of,
)
from bvb_esef.metadata import (
    IS_CONSOLIDATED_ASSUMED,
    filing_record,
    merge_records,
    read_compliance,
    read_index,
)
from bvb_esef.net import BlockedUrl, check_url, host_allowed
from bvb_esef.pipeline import (
    _dedupe,
    filing_date_from_filename,
    guess_symbol,
    read_url_file,
    registrant_name,
)
from bvb_esef.polite import RateLimiter
from bvb_esef.validate import (
    SEV_ERROR,
    SEV_WARNING,
    arelle_findings,
    classify,
    parse_log,
    parse_log_line,
    plugin_load_failure,
    precheck,
)

MINIMAL_XHTML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"'
    ' xmlns:link="http://www.xbrl.org/2003/linkbase"'
    ' xmlns:xbrli="http://www.xbrl.org/2003/instance"'
    ' xmlns:iso4217="http://www.xbrl.org/2003/iso4217"'
    ' xmlns:dei="http://xbrl.sec.gov/dei/2021-01-31"'
    ' xmlns:ext="https://example.test/esef/2025-12-31"'
    ' xml:lang="ro">'
    '<body><div style="display: none;">'
    '<ix:header><ix:references>'
    '<link:schemaRef xlink:type="simple"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink"'
    ' xlink:href="https://example.test/esef/2025-12-31/ext.xsd"/>'
    '</ix:references><ix:hidden>'
    '<xbrli:context id="c1"><xbrli:entity>'
    '<xbrli:identifier scheme="http://standards.iso.org/iso/17442">'
    '549300RG3H390KEL8896</xbrli:identifier>'
    '</xbrli:entity><xbrli:period>'
    '<xbrli:startDate>2025-01-01</xbrli:startDate>'
    '<xbrli:endDate>2025-12-31</xbrli:endDate>'
    '</xbrli:period></xbrli:context>'
    '</ix:hidden></ix:header></div>'
    '<p>Revenue was '
    '<ix:nonFraction name="ext:Revenue" contextRef="c1" unitRef="u1"'
    ' decimals="-3" scale="6">1.234.567</ix:nonFraction> lei.</p>'
    '<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c1">'
    'EXEMPLU  S.A. &#8211; Bucuresti</ix:nonNumeric>'
    '<ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c1">'
    '549300RG3H390KEL8896</ix:nonNumeric>'
    '<ix:nonNumeric name="dei:DocumentType" contextRef="c1">'
    'Annual report</ix:nonNumeric>'
    '<ix:nonNumeric name="dei:DocumentFiscalYearFocus" contextRef="c1">'
    '2025</ix:nonNumeric>'
    '<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c1">'
    'FY</ix:nonNumeric>'
    '</body></html>')

EXT_XSD = (
    "<?xml version='1.0' encoding='utf-8'?>"
    "<xsd:schema xmlns:xsd='http://www.w3.org/2001/XMLSchema'"
    " targetNamespace='https://example.test/esef/2025-12-31'"
    " xmlns:xbrli='http://www.xbrl.org/2003/instance'>"
    "<xsd:import namespace='http://www.xbrl.org/2003/instance'"
    " schemaLocation='http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd'/>"
    "<xsd:import namespace='https://www.esma.europa.eu/taxonomy/2024-03-27/esef_cor'"
    " schemaLocation='https://www.esma.europa.eu/taxonomy/2024-03-27/esef_cor.xsd'/>"
    "</xsd:schema>")

PACKAGE_META = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<taxonomyPackage xmlns="http://xbrl.org/2016/taxonomy-package">'
    "<identifier>https://example.test/esef/2025-12-31</identifier>"
    "<name>ext</name><publisher>Exemplu  S.A.</publisher>"
    "</taxonomyPackage>")


def build_package(path: Path, xhtml: str = MINIMAL_XHTML,
                  xsd: str = EXT_XSD, meta: str = PACKAGE_META,
                  name: str = "TLV_20260327173754_ext-2025-12-31-ro.zip") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ext/reports/ext-2025-12-31-0-ro.xhtml", xhtml)
        if xsd:
            z.writestr("ext/ext.xsd", xsd)
        if meta:
            z.writestr("ext/META-INF/taxonomyPackage.xml", meta)
    return path


def test_extract_lei_and_period_from_url():
    url = ("https://bvb.ro/infocont/infocont23/"
           "EL_20230428175526_213800P4SUNUM5AUDX61-2022-12-31-ro.zip")
    assert extract_lei(url) == "213800P4SUNUM5AUDX61"
    assert extract_period_end(url) == "2022-12-31"
    assert is_zip_url(url)
    assert not is_zip_url("https://bvb.ro/infocont/infocont23/EL.pdf")


def test_parse_infocont_collects_non_infocont_zips():
    html = ('<table><tr><td><a title="Raport anual 2025" '
            'href="http://www.bvb.ro/Raportari/2025/BAC_RA2025_ro.zip">Raport anual '
            '2025</a></td></tr></table>')
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


def test_parse_companies():
    html = ('<table><tr><td><a href="/FinancialInstruments/Details/'
            'FinancialInstrumentsDetails.aspx?s=EL">EL</a></td>'
            '<td>ROELECACNOR5</td><td>SOCIETATEA ENERGETICA ELECTRICA S.A.</td>'
            '<td>Premium</td></tr>'
            '<tr><td><a href="/FinancialInstruments/Details/'
            'FinancialInstrumentsDetails.aspx?s=EL">EL</a></td></tr></table>')
    companies = parse_companies(html)
    assert len(companies) == 1
    assert companies[0].symbol == "EL"
    assert companies[0].category == "Premium"
    assert companies[0].name == "SOCIETATEA ENERGETICA ELECTRICA S.A."


def test_parse_report_rows_filters_by_year():
    html = ('<h2>Raportari</h2><table id="gvRepDoc"><tr><th>Data</th><th>Doc'
            '</th><th></th></tr>'
            '<tr><td>27.03.2026</td><td>Raport anual 2025</td><td>'
            "<a href='/infocont/infocont26/"
            "TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip'>z</a>"
            "<a href='/infocont/infocont26/"
            "TLV_20260327173401_Raport-anual-2025.pdf'>p</a>"
            '</td></tr></table>')
    hits = parse_report_rows(html, "https://m.bvb.ro/x", "TLV", (2026, 2025))
    assert len(hits) == 1
    assert hits[0].symbol == "TLV"
    assert hits[0].filing_url.endswith("ESEF-format-iXBRL-RO-31-12-2025.zip")
    assert "Raport anual 2025" in hits[0].title
    assert parse_report_rows(html, "u", "TLV", (2019,)) == []


def test_find_reports_tab():
    html = ("<li><a href=\"javascript:__doPostBack("
            "'ctl00$body$TabsControlResponsive$0','')\">Sumar</a></li>"
            "<li><a href=\"javascript:__doPostBack("
            "'ctl00$body$TabsControlResponsive$4','')\">Informatii financiare</a></li>")
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


def test_inspect_zip_extracts_registrant_identity(tmp_path: Path):
    z = build_package(tmp_path / "TLV_20260327173754_ext-2025-12-31-ro.zip")
    info = inspect_zip(z)
    assert info.registrant_name == "EXEMPLU S.A. – Bucuresti"
    assert info.central_index_key == "549300RG3H390KEL8896"
    assert info.entity_lei == "549300RG3H390KEL8896"
    assert info.publisher == "Exemplu S.A."
    assert not info.lei_mismatch()


def test_registrant_name_prefers_report_over_fallback():
    assert registrant_name(EsefInfo(registrant_name="From Report"), "From BVB") == \
        "From Report"
    assert registrant_name(EsefInfo(publisher="From Publisher"), "From BVB") == \
        "From Publisher"
    assert registrant_name(EsefInfo(), "From BVB") == "From BVB"
    assert registrant_name(EsefInfo(), None) == "UNKNOWN"
    assert registrant_name(EsefInfo(lei="LEI123"), None) == "LEI123"


def test_dei_fact_sanitises_and_unescapes():
    assert dei_fact(MINIMAL_XHTML, "EntityRegistrantName") == \
        "EXEMPLU S.A. – Bucuresti"
    assert dei_fact(MINIMAL_XHTML, "NoSuchFact") is None
    assert dei_fact("", "EntityRegistrantName") is None
    assert dei_fact('<p name="dei:X"></p>', "X") is None


def test_record_schema():
    r = filing_record(lei="213800P4SUNUM5AUDX61", name="ELECTRICA S.A.", ticker="EL",
                      filing_url="https://bvb.ro/infocont/infocont23/EL_x.zip",
                      filing_date="2023-04-28", period_end="2022-12-31",
                      sha256="abc", language="ro")
    assert r["entity"]["country"] == "RO"
    assert r["report"]["source_system"] == "BVB_IRIS"
    assert r["report"]["is_consolidated"] is IS_CONSOLIDATED_ASSUMED


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
    assert language_of("BRD_20260318062626_BRDSocieteGenerale-2025-12-31-ro.zip") == "ro"
    assert language_of("BRDSocieteGenerale-2025-12-31 ESEF RO xhtml.zip") == "ro"
    assert language_of("549300RG3H390KEL8896-2024-12-31-0-ro.xhtml") == "ro"
    assert language_of("SNY_20260601_Convocator-AGA.zip") is None


def test_matches_langs():
    url = "x/TLV_20260327173754_ESEF-format-iXBRL-RO-31-12-2025.zip"
    assert matches_langs(url, None)
    assert matches_langs(url, ("ro", "en"))
    assert matches_langs(url, ("ro",))
    assert not matches_langs(url, ("en",))


def test_parse_report_rows_language_filter():
    html = ('<table id="gvRepDoc"><tr><td>Data</td><td>Doc</td><td></td></tr>'
            '<tr><td>27.03.2026</td><td>Raport anual</td><td>'
            "<a href='/infocont/infocont26/"
            "TLV_a_ESEF-format-iXBRL-RO-31-12-2025.zip'>ro</a>"
            "<a href='/infocont/infocont26/"
            "TLV_b_ESEF-format-iXBRL-EN-31-12-2025.zip'>en</a>"
            "<a href='/infocont/infocont26/TLV_c_Convocator-AGA.zip'>none</a>"
            '</td></tr></table>')
    assert len(parse_report_rows(html, "u", "TLV", (2026,))) == 3
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
    f.write_text("https://bvb.ro/infocont/infocont23/A.zip\n\nnot-a-zip\n"
                 "https://x.ro/B.zip\n")
    assert read_url_file(f) == ["https://bvb.ro/infocont/infocont23/A.zip",
                                "https://x.ro/B.zip"]


def test_rate_limiter_enforces_gap():
    lim = RateLimiter(0.05)
    lim.wait()
    t0 = time.monotonic()
    lim.wait()
    assert time.monotonic() - t0 >= 0.04
    RateLimiter(0).wait()


def test_net_allowlist_accepts_bvb_hosts():
    assert check_url("https://bvb.ro/infocont/x.zip")
    assert check_url("https://www.bvb.ro/infocont/x.zip")
    assert check_url("http://m.bvb.ro/FinancialInstruments/Details/x")
    assert check_url("https://iris.bvb.ro/PublicReports/Reports")
    assert host_allowed("BVB.RO")
    assert not host_allowed("bvb.ro.evil.example.com")
    assert not host_allowed("")


def test_net_allowlist_rejects_foreign_and_non_http():
    for bad in ("https://evil.example.com/x.zip",
                "https://bvb.ro.evil.example.com/x.zip",
                "https://notbvb.ro/x.zip",
                "http://127.0.0.1:8000/x.zip"):
        try:
            check_url(bad)
        except BlockedUrl:
            pass
        else:
            raise AssertionError(f"{bad} was not blocked")


def test_net_allowlist_rejects_file_scheme():
    for bad in ("file:///etc/passwd", "ftp://bvb.ro/x.zip", "gopher://bvb.ro/",
                "javascript:alert(1)", "//bvb.ro/x.zip"):
        try:
            check_url(bad)
        except BlockedUrl:
            pass
        else:
            raise AssertionError(f"{bad} was not blocked")


def test_precheck_clean_package_has_no_errors(tmp_path: Path):
    result = precheck(build_package(tmp_path / "pkg.zip"), lang="ro")
    assert result.tool == "precheck"
    assert not result.errors
    assert result.status in ("pass", "warnings")
    assert result.ok


def test_precheck_flags_missing_ix_and_namespaces(tmp_path: Path):
    z = build_package(tmp_path / "bad.zip",
                      xhtml='<html xml:lang="ro"><body><p>plain</p></body></html>',
                      xsd="", meta="")
    result = precheck(z, lang="ro")
    codes = {f.code for f in result.findings}
    assert {"pc.no_ix", "pc.no_context", "pc.no_esef_namespace",
            "pc.no_taxonomy_package", "pc.no_registrant_name"} <= codes
    assert result.status == "errors"
    assert not result.ok
    assert all(f.source == "precheck" and f.code.startswith("pc.")
               for f in result.findings)


def test_precheck_flags_missing_report(tmp_path: Path):
    z = tmp_path / "onlyschema.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("ext/ext.xsd", EXT_XSD)
    result = precheck(z)
    assert [f.code for f in result.errors] == ["pc.no_report"]
    assert result.status == "errors"


def test_precheck_flags_foreign_namespace_and_bad_dates(tmp_path: Path):
    xhtml = MINIMAL_XHTML.replace(
        'xmlns:ext="https://example.test/esef/2025-12-31"',
        'xmlns:ext="https://rogue.test/other"')
    xhtml = xhtml.replace("<xbrli:startDate>2025-01-01</xbrli:startDate>",
                          "<xbrli:startDate>2025-13-45</xbrli:startDate>")
    z = build_package(tmp_path / "rogue.zip", xhtml=xhtml, xsd="")
    codes = {f.code for f in precheck(z).errors}
    assert "pc.foreign_namespace" in codes
    assert "pc.invalid_context_date" in codes


def test_precheck_flags_bad_entity_scheme_and_lang(tmp_path: Path):
    xhtml = MINIMAL_XHTML.replace("http://standards.iso.org/iso/17442",
                                  "http://example.test/scheme")
    z = build_package(tmp_path / "scheme.zip", xhtml=xhtml)
    codes = {f.code for f in precheck(z, lang="en").findings}
    assert "pc.entity_scheme_not_lei" in codes
    assert "pc.lang_mismatch" in codes


def test_precheck_accepts_extension_namespace_from_package(tmp_path: Path):
    result = precheck(build_package(tmp_path / "ok.zip"), lang="ro")
    assert "pc.foreign_namespace" not in {f.code for f in result.findings}


def test_precheck_rejects_non_zip(tmp_path: Path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip at all")
    result = precheck(junk)
    assert result.status == "errors"
    assert [f.code for f in result.errors] == ["pc.unreadable"]


ARELLE_LOG = (
    "INFO|info|Activation of plug-in Validate ESMA ESEF successful, version 1.2025.00.\n"
    "INFO|info|loaded in 5.71 secs at 2026-09-29T21:42:54\n"
    "WARNING|ESEF.2.6.3.incorrectNamingConventionReportPackageReportFile|"
    "Inline XBRL document filename SHOULD match {base}-{date}.[x]html\n"
    "WARNING|ESEF.2.2.6.textContentOrdering|text content out of order\n"
    "WARNING|ESEF.RTS.Annex.II.Par.2.missingMandatoryMarkups|markups missing\n"
    "INFO|info:profileActivity|validating ESMA RTS on ESEF-2025 filing rules 3.9 secs\n"
    "DEBUG||Formula xpath2 grammar initialized in 0.01 secs\n"
    "WARNING|message:positive|Reported value is below 0\n"
    "WARNING|ESEF.2.7.1.targetXBRLDocumentWithFormulaWarnings|1 with warnings.\n"
    "INFO|info|validated in 49.56 secs\n")


def test_parse_log_line_splits_level_code_message():
    f = parse_log_line("WARNING|ESEF.2.7.1.foo|a | b | c")
    assert f is not None
    assert (f.severity, f.code, f.message, f.source) == (
        SEV_WARNING, "ESEF.2.7.1.foo", "a | b | c", "arelle")


def test_parse_log_drops_info_debug_and_note_codes():
    findings = parse_log(ARELLE_LOG)
    assert [f.severity for f in findings] == [SEV_WARNING] * 4
    codes = [f.code for f in findings]
    assert "message:positive" not in codes
    assert "info" not in codes and "info:profileActivity" not in codes


def test_parse_log_keeps_errors_and_separates_ioerror():
    log = ("ERROR|IOerror|Could not load file from local filesystem. Disable offline.\n"
           "ERROR|ESEF.2.2.7.improperApplicationOfEscapeAttribute|escaping\n"
           "CRITICAL|xbrl:schemaImportMissing|boom\n")
    findings = parse_log(log)
    assert len(findings) == 3
    assert all(f.severity == SEV_ERROR for f in findings)
    assert findings[0].source == "arelle-environment"
    assert findings[1].source == "arelle"
    assert classify(findings) == "errors"
    assert classify(findings, complete=False) == "errors"


def test_parse_log_ignores_malformed_lines():
    assert parse_log_line("") is None
    assert parse_log_line("INFO") is None
    assert parse_log("plain text without pipes") == []


def test_classify_status_matrix():
    warn = parse_log("WARNING|ESEF.x|y")
    assert classify([]) == "pass"
    assert classify(warn) == "warnings"
    assert classify([], available=False) == "unavailable"
    assert classify([], cached=False) == "skipped"
    assert classify([], complete=False) == "skipped"
    assert classify(warn, complete=False) == "skipped"
    assert classify(parse_log("ERROR|ESEF.x|y"), available=False) == "errors"
    assert classify(parse_log("ERROR|IOerror|cache gap"), complete=False) == "skipped"


def test_plugin_load_failure_detected():
    broken = ("INFO|info|start\n"
              "CRITICAL|pyarelle:ERROR|Unable to load module Validate ESMA ESEF\n"
              "CRITICAL|pyarelle:ERROR|Exception loading plug-in: "
              "No module named 'tinycss2'\n")
    assert "tinycss2" in (plugin_load_failure(broken) or "")
    assert plugin_load_failure(ARELLE_LOG) is None
    findings, complete = arelle_findings(broken)
    assert not complete
    assert [f.code for f in findings] == ["arelle.plugin_load_failed"]
    findings, complete = arelle_findings("INFO|info|nothing useful here\n")
    assert not complete
    assert findings[0].code == "arelle.plugin_not_confirmed"
    findings, complete = arelle_findings(ARELLE_LOG)
    assert complete and len(findings) == 4


def test_cli_options_match_pipeline_signatures():
    import inspect

    from bvb_esef import pipeline
    from bvb_esef.cli import main

    run_params = set(inspect.signature(pipeline.run).parameters)
    for name in ("crawl", "backfill"):
        given = {p.name for p in main.commands[name].params}
        assert given <= run_params, f"{name}: {given - run_params}"

    collect_params = set(inspect.signature(pipeline.collect).parameters)
    for name in ("doctor", "list"):
        given = {p.name for p in main.commands[name].params}
        assert given - {"probe"} <= collect_params, f"{name}: {given - collect_params}"


def test_every_command_callback_accepts_its_own_params():
    import inspect

    from bvb_esef.cli import main

    for name, cmd in main.commands.items():
        params = inspect.signature(cmd.callback).parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            continue
        given = {p.name for p in cmd.params}
        assert given <= set(params), f"{name}: {given - set(params)}"
        assert not set(params) - given - {"ctx"}, f"{name}: {set(params) - given}"


def test_every_command_runs_with_only_its_own_options(monkeypatch):
    from click.testing import CliRunner

    from bvb_esef import pipeline
    from bvb_esef.cli import main

    monkeypatch.setattr("bvb_esef.cli.pipe.run", lambda **kw: kw)
    monkeypatch.setattr("bvb_esef.cli.pipe.collect",
                        lambda **kw: pipeline.Collection(companies=[], hits=[], stats={}))
    monkeypatch.setattr("bvb_esef.cli.pipe.probe_candidates", lambda *a, **k: ([], []))
    monkeypatch.setattr("bvb_esef.cli.bvb_mod.discover_companies", lambda **kw: [])
    runner = CliRunner()
    for name in ("crawl", "backfill", "doctor", "companies", "list"):
        res = runner.invoke(main, [name])
        assert res.exit_code == 0, f"{name}: {res.exception} {res.output}"


def test_cli_run_is_callable_through_click(monkeypatch):
    from click.testing import CliRunner

    from bvb_esef.cli import main

    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr("bvb_esef.cli.pipe.run", fake_run)
    result = CliRunner().invoke(main, ["crawl", "-s", "TLV", "-l", "ro",
                                       "--limit", "1", "--arelle", "--delay", "0"])
    assert result.exit_code == 0, result.output
    assert seen["symbols"] == ("TLV",)
    assert seen["langs"] == ("ro",)
    assert seen["limit"] == 1
    assert seen["arelle"] is True
    assert seen["probe"] is True
    assert seen["precheck"] is True
    assert seen["out_dir"] == Path("data/out")
    assert seen["zips_dir"] == Path("data/zips")


def test_cli_has_no_dead_commands():
    from bvb_esef.cli import main

    assert set(main.commands) == {"crawl", "backfill", "doctor", "companies",
                                   "list", "inspect", "validate"}


def test_every_command_has_help():
    from click.testing import CliRunner

    from bvb_esef.cli import main

    runner = CliRunner()
    assert runner.invoke(main, ["--help"]).exit_code == 0
    for name in main.commands:
        res = runner.invoke(main, [name, "--help"])
        assert res.exit_code == 0, f"{name}: {res.output}"
        assert "Usage:" in res.output


def test_validate_cli_requires_something_to_run(tmp_path: Path):
    from click.testing import CliRunner

    from bvb_esef.cli import main

    pkg = build_package(tmp_path / "p.zip")
    res = CliRunner().invoke(main, ["validate", str(pkg),
                                    "--no-precheck", "--no-arelle"])
    assert res.exit_code != 0
    assert "nothing to run" in res.output


def test_validate_cli_runs_precheck_only(tmp_path: Path):
    from click.testing import CliRunner

    from bvb_esef.cli import main

    pkg = build_package(tmp_path / "p.zip")
    res = CliRunner().invoke(main, ["validate", str(pkg), "--no-arelle"])
    assert res.exit_code == 0, res.output
    assert "status=pass" in res.output
    assert "tool=precheck" in res.output


def test_validate_cli_exits_nonzero_on_precheck_errors(tmp_path: Path):
    from click.testing import CliRunner

    from bvb_esef.cli import main

    pkg = build_package(tmp_path / "bad.zip",
                        xhtml="<html><body>plain</body></html>", xsd="", meta="")
    res = CliRunner().invoke(main, ["validate", str(pkg), "--no-arelle"])
    assert res.exit_code == 1
    assert "pc.no_ix" in res.output


def test_cache_report_rejects_empty_cache(tmp_path: Path):
    from bvb_esef.validate import cache_report

    ok, why = cache_report(tmp_path / "missing")
    assert not ok and "does not exist" in why
    (tmp_path / "empty").mkdir()
    ok, why = cache_report(tmp_path / "empty")
    assert not ok and "no http/https sub-root" in why
    (tmp_path / "partial" / "https" / "www.esma.europa.eu" / "taxonomy" / "2024-03-27")\
        .mkdir(parents=True)
    ok, why = cache_report(tmp_path / "partial")
    assert not ok and "no ESEF core schema" in why
    (tmp_path / "partial" / "https" / "www.esma.europa.eu" / "taxonomy" / "2024-03-27"
     / "esef_cor.xsd").write_text("<schema/>")
    ok, why = cache_report(tmp_path / "partial")
    assert not ok and "no IFRS entry point" in why
    (tmp_path / "partial" / "https" / "xbrl.ifrs.org" / "taxonomy" / "2024-03-27")\
        .mkdir(parents=True)
    ok, _ = cache_report(tmp_path / "partial")
    assert ok


def test_compliance_sidecar_roundtrip(tmp_path: Path):
    from bvb_esef.metadata import read_compliance, write_compliance

    dest = tmp_path / "out" / "compliance.json"
    write_compliance({"u2": {"status": "pass"}, "u1": {"status": "errors"}}, dest)
    data = read_compliance(dest)
    assert list(data) == ["u1", "u2"]
    assert read_compliance(tmp_path / "nope.json") == {}
    (tmp_path / "bad.json").write_text("{oops")
    assert read_compliance(tmp_path / "bad.json") == {}


def test_ingest_writes_index_and_compliance(tmp_path: Path):
    from bvb_esef.pipeline import ingest, store, store_compliance

    zips = tmp_path / "zips"
    out = tmp_path / "out"
    zips.mkdir()
    build_package(zips / "TLV_20260327173754_ext-2025-12-31-ro.zip")
    hits = [BvbHit("https://bvb.ro/infocont/infocont26/"
                   "TLV_20260327173754_ext-2025-12-31-ro.zip", "t", "TLV", "p")]
    records, compliance = ingest(hits, out, zips, {"TLV": "From BVB"}, delay=0,
                                 arelle=False)
    stored = store(records, out)
    store_compliance(compliance, out)
    assert len(stored) == 1
    rec = stored[0]
    assert rec["entity"]["name"] == "EXEMPLU S.A. – Bucuresti"
    assert rec["entity"]["lei"] == "549300RG3H390KEL8896"
    assert rec["entity"]["ticker"] == "TLV"
    assert rec["report"]["period_end"] == "2025-12-31"
    assert rec["report"]["language"] == "ro"
    assert rec["report"]["sha256"]
    assert "validation" not in json.dumps(rec)
    side = read_compliance(out / "compliance.json")
    entry = side[hits[0].filing_url]
    assert entry["status"] in ("pass", "warnings", "errors")
    assert entry["sha256"] == rec["report"]["sha256"]
    assert entry["tool"] == "precheck"
    assert entry["errors"] == 0
    assert entry["status"] in ("pass", "warnings")
    assert entry["ok"] is True
    assert entry["complete"] is True
    assert entry["findings"] == []
    assert entry["codes"] == {}
    assert (out / "filings.jsonl").exists()


def test_collect_year_range_resolution(monkeypatch):
    from bvb_esef import pipeline

    seen: list = []

    def fake_default_pages(symbols, **kwargs):
        return [], []

    def fake_crawl_bvb_pages(pages, years=None, **kwargs):
        seen.append(years)
        return []

    monkeypatch.setattr("bvb_esef.pipeline.bvb_mod.default_pages", fake_default_pages)
    monkeypatch.setattr("bvb_esef.pipeline.bvb_mod.crawl_bvb_pages", fake_crawl_bvb_pages)
    monkeypatch.setattr("bvb_esef.pipeline.bvb_mod.crawl_issuers",
                        lambda *a, **k: [])
    monkeypatch.setattr("bvb_esef.pipeline.bvb_mod.crawl_financial_results",
                        lambda *a, **k: [])

    pipeline.collect()
    assert seen[-1] is None

    pipeline.collect(from_year=2023, to_year=2024)
    assert seen[-1] == (2023, 2024)

    pipeline.collect(to_year=2024)
    assert seen[-1] == (2024,)

    pipeline.collect(from_year=2023)
    today = datetime.date.today().year
    assert seen[-1] == tuple(range(2023, today + 1))

    with pytest.raises(ValueError, match="after"):
        pipeline.collect(from_year=2025, to_year=2024)


def test_run_arelle_maps_exit_codes(monkeypatch, tmp_path: Path):
    import subprocess
    import types

    from bvb_esef import validate as val

    monkeypatch.setattr(val, "arelle_command", lambda: ["fake-arelle"])
    real_argv = val.arelle_argv
    monkeypatch.setattr(val, "arelle_argv",
                        lambda path, cache, log, authority="RO":
                        real_argv(path, cache, log, authority) + [authority])

    def fake_run(argv, **kwargs):
        code = int(argv[-1])
        out = ""
        if code == 3:
            out = ("INFO|info|Activation of plug-in Validate ESMA ESEF "
                   "successful\n")
        return types.SimpleNamespace(returncode=code, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    findings, complete, code, _ = val.run_arelle(tmp_path / "p.zip",
                                                 tmp_path / "cache",
                                                 authority="2")
    assert code == 2
    assert not complete
    assert "arelle.usage_error" in [f.code for f in findings]

    findings, complete, code, _ = val.run_arelle(tmp_path / "p.zip",
                                                 tmp_path / "cache",
                                                 authority="3")
    assert code == 3
    assert "arelle.validation_issues" in [f.code for f in findings]
