from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from .config import ARELLE_AUTHORITY, ARELLE_CACHE_DIR, ARELLE_TIMEOUT
from .esef import dei_fact, primary_report
from .log import log

SEV_ERROR = "error"
SEV_WARNING = "warning"

SOURCE_PRECHECK = "precheck"
SOURCE_ARELLE = "arelle"
SOURCE_ENV = "arelle-environment"

STATUS_PASS = "pass"
STATUS_WARNINGS = "warnings"
STATUS_ERRORS = "errors"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"

TOOL_ARELLE = "arelle"
TOOL_PRECHECK = "precheck"
ARELLE_LOG_FORMAT = "%(levelname)s|%(messageCode)s|%(message)s"

CACHE_ACTION = ("run one online validation first (no --internetConnectivity offline) "
                "to populate it, or point --cache-dir at a populated Arelle cache")

PLUGIN_LOAD_MARKERS = ("Unable to load module", "Exception loading plug-in")
PLUGIN_SUCCESS_MARKER = "Activation of plug-in Validate ESMA ESEF successful"
NOTE_CODES = ("message:", "info", "profileActivity")
TOOL_ERROR_CODES = ("IOerror",)

ESEF_NS_MARKERS = ("esma.europa.eu/xbrl/esef", "esma.europa.eu/taxonomy")
LEI_SCHEME = "http://standards.iso.org/iso/17442"
STANDARD_NAMESPACES = frozenset({
    "http://www.xbrl.org/2003/instance",
    "http://www.xbrl.org/2003/linkbase",
    "http://xbrl.org/2006/xbrldi",
    "http://xbrl.org/2005/xbrldt",
    "http://www.xbrl.org/2003/iso4217",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
    "http://www.xbrl.org/2008/inlineXBRL",
    "http://www.xbrl.org/2013/inlineXBRL",
    "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12",
    "http://www.xbrl.org/inlineXBRL/transformation/2022-02-16",
    "http://xbrl.sec.gov/dei/2021-01-31",
    "http://xbrl.sec.gov/dei/2023-01-31",
    "http://xbrl.sec.gov/dei/2024-01-31",
})
STANDARD_NS_PREFIXES = ("http://www.xbrl.org/", "http://xbrl.sec.gov/dei/",
                        "http://www.esma.europa.eu/", "https://www.esma.europa.eu/",
                        "http://xbrl.ifrs.org/", "https://xbrl.ifrs.org/")

Q = r"[\"']"
TEXT_ENTRY_RE = re.compile(r"\.(xhtml|html|htm)$", re.IGNORECASE)
SCHEMA_ENTRY_RE = re.compile(r"\.xsd$", re.IGNORECASE)
IX_HEADER_RE = re.compile(r"<ix:header\b", re.IGNORECASE)
IX_HIDDEN_RE = re.compile(r"<ix:hidden\b", re.IGNORECASE)
IX_FACT_RE = re.compile(r"<ix:(?:nonNumeric|nonFraction|fraction)\b", re.IGNORECASE)
XBRLI_CONTEXT_RE = re.compile(r"<xbrli:context\b", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
LANG_ATTR_RE = re.compile(r"\b(?:xml:lang|lang)\s*=\s*" + Q + r"([^\"']*)" + Q, re.I)
NS_DECL_RE = re.compile(r"xmlns:([\w.\-]+)\s*=\s*" + Q + r"([^\"']+)" + Q)
FACT_NAME_RE = re.compile(r"\sname\s*=\s*" + Q + r"([\w.\-]+):([\w.\-]+)" + Q)
TARGET_NS_RE = re.compile(r"targetNamespace\s*=\s*" + Q + r"([^\"']+)" + Q)
PERIOD_DATE_RE = re.compile(
    r"<(?:[\w.\-]+:)?(instant|startDate|endDate|forever)\b[^>]*>\s*([^<]*?)\s*<", re.I)
IDENTIFIER_RE = re.compile(
    r"<(?:[\w.\-]+:)?identifier\b[^>]*?\bscheme\s*=\s*" + Q + r"([^\"']+)" + Q, re.I)
ISODATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

DEI_FACTS = {
    "EntityRegistrantName": "pc.no_registrant_name",
    "EntityCentralIndexKey": "pc.no_central_index_key",
    "DocumentType": "pc.no_document_type",
}
FISCAL_FOCUS = ("DocumentFiscalYearFocus", "DocumentFiscalPeriodFocus")


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    source: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "source": self.source}


@dataclass
class ValidationResult:
    path: str
    tool: str
    status: str
    findings: list[Finding] = field(default_factory=list)
    duration: float = 0.0
    complete: bool = True
    cache_dir: str | None = None

    @property
    def filing_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.source != SOURCE_ENV]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.filing_findings if f.severity == SEV_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.filing_findings if f.severity == SEV_WARNING]

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_PASS, STATUS_WARNINGS)

    def summary(self) -> dict:
        codes: dict[str, int] = {}
        for f in self.filing_findings:
            codes[f.code] = codes.get(f.code, 0) + 1
        return {
            "tool": self.tool,
            "status": self.status,
            "ok": self.ok,
            "complete": self.complete,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "duration_seconds": round(self.duration, 1),
            "codes": dict(sorted(codes.items())),
            "findings": [f.as_dict() for f in self.filing_findings],
            "tool_findings": [f.as_dict() for f in self.findings
                              if f.source == SOURCE_ENV],
        }

    def format(self) -> str:
        head = f"{self.path}  status={self.status} tool={self.tool} ({self.duration:.1f}s)"
        if not self.complete:
            head += "  INCOMPLETE"
        lines = [head]
        for f in self.findings:
            lines.append(f"  {f.severity:7} {f.code} [{f.source}] {f.message}")
        lines.append(f"  -> {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        return "\n".join(lines)


def classify(findings: list[Finding], *, complete: bool = True,
             available: bool = True, cached: bool = True) -> str:
    if any(f.severity == SEV_ERROR and f.source != SOURCE_ENV for f in findings):
        return STATUS_ERRORS
    if not available:
        return STATUS_UNAVAILABLE
    if not cached or not complete:
        return STATUS_SKIPPED
    if any(f.severity == SEV_WARNING for f in findings):
        return STATUS_WARNINGS
    return STATUS_PASS


ARELLE_FALLBACK = "from arelle.CntlrCmdLine import main; main()"


def arelle_command() -> list[str] | None:
    exe = shutil.which("arelleCmdLine")
    if exe:
        return [exe]
    sibling = Path(sys.executable).with_name("arelleCmdLine")
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return [str(sibling)]
    if importlib.util.find_spec("arelle") is not None:
        return [sys.executable, "-c", ARELLE_FALLBACK]
    return None


def arelle_available() -> bool:
    return arelle_command() is not None


def arelle_version() -> str:
    cmd = arelle_command()
    if not cmd:
        return "unavailable"
    try:
        proc = subprocess.run(cmd + ["--version"], capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"unavailable ({e})"
    lines = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return lines[0] if lines else "unknown"


def cache_report(cache_dir: Path) -> tuple[bool, str]:
    root = Path(cache_dir)
    if not root.is_dir():
        return False, f"Arelle cache {root} does not exist; {CACHE_ACTION}"
    roots = [root / s for s in ("http", "https") if (root / s).is_dir()]
    if not roots:
        return False, f"Arelle cache {root} has no http/https sub-root; {CACHE_ACTION}"
    core = [p for base in roots for p in sorted(base.glob(
        "www.esma.europa.eu/taxonomy/*/esef_cor.xsd"))]
    if not core:
        return False, (f"Arelle cache {root} has no ESEF core schema "
                       f"(www.esma.europa.eu/taxonomy/*/esef_cor.xsd); {CACHE_ACTION}")
    if not any((base / "xbrl.ifrs.org" / "taxonomy").is_dir() for base in roots):
        return False, (f"Arelle cache {root} has no IFRS entry point "
                       f"(xbrl.ifrs.org/taxonomy); {CACHE_ACTION}")
    return True, f"Arelle cache {root} has ESEF core schema {core[0]}"


def parse_log_line(line: str) -> Finding | None:
    parts = line.rstrip("\n").split("|", 2)
    if len(parts) < 2:
        return None
    level = parts[0].strip().upper()
    code = parts[1].strip()
    if level not in (SEV_ERROR.upper(), "CRITICAL", SEV_WARNING.upper()):
        return None
    if code.startswith(NOTE_CODES):
        return None
    message = parts[2].strip() if len(parts) > 2 else ""
    severity = SEV_ERROR if level in (SEV_ERROR.upper(), "CRITICAL") else SEV_WARNING
    source = SOURCE_ENV if code.startswith(TOOL_ERROR_CODES) else SOURCE_ARELLE
    return Finding(severity, code, message, source)


def parse_log(text: str) -> list[Finding]:
    out: list[Finding] = []
    for line in (text or "").splitlines():
        finding = parse_log_line(line)
        if finding is not None:
            out.append(finding)
    return out


def plugin_load_failure(text: str) -> str | None:
    hits = [line.strip() for line in (text or "").splitlines()
            if any(marker in line for marker in PLUGIN_LOAD_MARKERS)]
    return " | ".join(hits) if hits else None


@dataclass
class PackageView:
    report_entry: str | None
    report_text: str
    target_namespaces: dict[str, str]
    schema_text: str
    taxonomy_package: str


def read_package(path: Path) -> PackageView:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        report = primary_report(names)
        text = ""
        if report:
            try:
                text = z.read(report).decode("utf-8", errors="ignore")
            except (KeyError, OSError):
                text = ""
        schemas: dict[str, str] = {}
        raw_schemas: list[str] = []
        for name in names:
            if not SCHEMA_ENTRY_RE.search(name):
                continue
            try:
                raw = z.read(name).decode("utf-8", errors="ignore")
            except (KeyError, OSError):
                continue
            raw_schemas.append(raw)
            for ns in TARGET_NS_RE.findall(raw):
                schemas.setdefault(ns, name)
        package_meta = ""
        for name in names:
            if name.rsplit("/", 1)[-1].lower() != "taxonomypackage.xml":
                continue
            try:
                package_meta = z.read(name).decode("utf-8", errors="ignore")
            except (KeyError, OSError):
                package_meta = ""
            if package_meta:
                break
    return PackageView(report, text, schemas, "\n".join(raw_schemas), package_meta)


def namespace_is_standard(ns: str) -> bool:
    return ns in STANDARD_NAMESPACES or ns.startswith(STANDARD_NS_PREFIXES)


def is_iso_date(value: str) -> bool:
    m = ISODATE_RE.match((value or "").strip())
    if not m:
        return False
    try:
        date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return True


def precheck_findings(view: PackageView, lang: str | None) -> list[Finding]:
    out: list[Finding] = []
    body = view.report_text
    schemas = view.target_namespaces
    if not body:
        out.append(Finding(SEV_ERROR, "pc.no_report",
                           "no XHTML report entry point in the package", SOURCE_PRECHECK))
        return out
    if not IX_HEADER_RE.search(body):
        out.append(Finding(SEV_ERROR, "pc.no_ix",
                           "no ix:header: the document is not inline XBRL",
                           SOURCE_PRECHECK))
    if IX_FACT_RE.search(body) and not IX_HIDDEN_RE.search(body):
        out.append(Finding(SEV_WARNING, "pc.no_hidden",
                           "no ix:hidden block for facts not rendered in the report",
                           SOURCE_PRECHECK))
    if not XBRLI_CONTEXT_RE.search(body):
        out.append(Finding(SEV_ERROR, "pc.no_context",
                           "no xbrli:context: the instance declares no contexts",
                           SOURCE_PRECHECK))
    if not any(m in body + view.schema_text for m in ESEF_NS_MARKERS):
        out.append(Finding(SEV_ERROR, "pc.no_esef_namespace",
                           "no ESMA ESEF namespace declared or imported", SOURCE_PRECHECK))
    declared = dict(NS_DECL_RE.findall(body))
    foreign: dict[str, str] = {}
    for prefix, _local in FACT_NAME_RE.findall(body):
        ns = declared.get(prefix)
        if not ns or namespace_is_standard(ns) or ns in schemas:
            continue
        foreign.setdefault(ns, prefix)
    for ns, prefix in sorted(foreign.items()):
        out.append(Finding(SEV_ERROR, "pc.foreign_namespace",
                           f"fact prefix {prefix!r} binds {ns!r}, which is neither a "
                           f"standard namespace nor a targetNamespace shipped in the "
                           f"package", SOURCE_PRECHECK))
    for dei_name, code in DEI_FACTS.items():
        if not dei_fact(body, dei_name):
            out.append(Finding(SEV_WARNING, code,
                               f"cover page has no {dei_name} fact", SOURCE_PRECHECK))
    if not any(dei_fact(body, f) for f in FISCAL_FOCUS):
        out.append(Finding(SEV_WARNING, "pc.no_fiscal_focus",
                           "cover page has no dei:DocumentFiscalYearFocus or "
                           "dei:DocumentFiscalPeriodFocus fact", SOURCE_PRECHECK))
    m_ident = IDENTIFIER_RE.search(body)
    if not m_ident:
        out.append(Finding(SEV_WARNING, "pc.no_entity_identifier",
                           "no xbrli:identifier scheme in any context", SOURCE_PRECHECK))
    elif m_ident.group(1).strip() != LEI_SCHEME:
        out.append(Finding(SEV_ERROR, "pc.entity_scheme_not_lei",
                           f"xbrli:identifier scheme {m_ident.group(1).strip()!r} is not "
                           f"{LEI_SCHEME!r}", SOURCE_PRECHECK))
    bad = sorted({v for _tag, v in PERIOD_DATE_RE.findall(body)
                  if v and not is_iso_date(v)})
    for value in bad:
        out.append(Finding(SEV_ERROR, "pc.invalid_context_date",
                           f"context date {value!r} is not a valid ISO-8601 date",
                           SOURCE_PRECHECK))
    html_tag = HTML_TAG_RE.search(body)
    if html_tag and lang:
        m_lang = LANG_ATTR_RE.search(html_tag.group(0))
        if m_lang and m_lang.group(1).strip().lower().split("-")[0] != lang.lower():
            out.append(Finding(SEV_WARNING, "pc.lang_mismatch",
                               f"html declares language {m_lang.group(1)!r} but the "
                               f"package is tagged {lang!r}", SOURCE_PRECHECK))
    if not view.taxonomy_package:
        out.append(Finding(SEV_WARNING, "pc.no_taxonomy_package",
                           "no META-INF/taxonomyPackage.xml in the report package",
                           SOURCE_PRECHECK))
    return out


def precheck(path: Path, lang: str | None = None) -> ValidationResult:
    start = time.monotonic()
    target = Path(path)
    try:
        view = read_package(target)
    except (OSError, zipfile.BadZipFile) as e:
        findings = [Finding(SEV_ERROR, "pc.unreadable", f"cannot read package: {e}",
                            SOURCE_PRECHECK)]
    else:
        findings = precheck_findings(view, lang)
    return ValidationResult(str(target), TOOL_PRECHECK, classify(findings),
                            findings, time.monotonic() - start)


def arelle_findings(text: str) -> tuple[list[Finding], bool]:
    failure = plugin_load_failure(text)
    if failure:
        return [Finding(SEV_ERROR, "arelle.plugin_load_failed", failure,
                        SOURCE_ARELLE)], False
    if PLUGIN_SUCCESS_MARKER not in text:
        return [Finding(SEV_ERROR, "arelle.plugin_not_confirmed",
                        f"log does not confirm {PLUGIN_SUCCESS_MARKER!r}",
                        SOURCE_ARELLE)], False
    return parse_log(text), True


def arelle_argv(path: Path, cache_dir: Path, logfile: Path,
                authority: str = ARELLE_AUTHORITY) -> list[str]:
    cmd = arelle_command() or ["arelleCmdLine"]
    return cmd + [
        "--plugins", "validate/ESEF",
        "--esefAuthority", authority,
        "--disclosureSystem", "esef",
        "--validate",
        "--validationExitCode",
        "--internetConnectivity", "offline",
        "--cacheDirectory", str(cache_dir),
        "--logFile", str(logfile),
        "--logFileMode", "w",
        "--logFormat", ARELLE_LOG_FORMAT,
        "--file", str(path),
    ]


def run_arelle(path: Path, cache_dir: Path, timeout: int = ARELLE_TIMEOUT,
               authority: str = ARELLE_AUTHORITY) -> tuple[list[Finding], bool, int, float]:
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="bvb-esef-arelle-") as tmp:
        logfile = Path(tmp) / "arelle.log"
        argv = arelle_argv(path, cache_dir, logfile, authority)
        log.debug("arelle: %s", " ".join(argv))
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            findings = [Finding(SEV_ERROR, "arelle.timeout",
                                f"arelle did not finish within {timeout}s", SOURCE_ENV)]
            return findings, False, -1, time.monotonic() - start
        except OSError as e:
            findings = [Finding(SEV_ERROR, "arelle.not_runnable",
                                f"cannot run arelle: {e}", SOURCE_ENV)]
            return findings, False, -1, time.monotonic() - start
        text = ""
        from_log = False
        if logfile.exists():
            text = logfile.read_text(encoding="utf-8", errors="ignore")
            from_log = bool(text.strip())
        console = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if not from_log:
            text = console
    findings, complete = arelle_findings(text)
    if from_log:
        for line in console.splitlines():
            if any(marker in line for marker in PLUGIN_LOAD_MARKERS):
                findings.append(Finding(SEV_ERROR, "arelle.plugin_load_failed",
                                        line.strip(), SOURCE_ARELLE))
                complete = False
    if proc.returncode == 2:
        findings.append(Finding(SEV_ERROR, "arelle.usage_error",
                                "arelle exited 2 (usage error); check invocation",
                                SOURCE_ENV))
        complete = False
    elif proc.returncode == 3:
        if not any(f.source != SOURCE_ENV for f in findings):
            findings.append(Finding(SEV_ERROR, "arelle.validation_issues",
                                    "arelle exited 3 (validation issues) with no "
                                    "parsed findings", SOURCE_ARELLE))
    elif proc.returncode != 0:
        findings.append(Finding(SEV_ERROR, "arelle.exit_code",
                                f"arelle exited {proc.returncode}", SOURCE_ENV))
        complete = False
    if any(f.source == SOURCE_ENV for f in findings):
        complete = False
    return findings, complete, proc.returncode, time.monotonic() - start


def validate(path: Path, arelle: bool = True, cache_dir: Path | None = None,
             lang: str | None = None, screen: bool = True,
             timeout: int = ARELLE_TIMEOUT,
             authority: str = ARELLE_AUTHORITY) -> ValidationResult:
    target = Path(path)
    result = precheck(target, lang=lang) if screen \
        else ValidationResult(str(target), TOOL_PRECHECK, STATUS_PASS)
    if not arelle:
        return result
    if not arelle_available():
        result.findings.append(Finding(
            SEV_ERROR, "arelle.not_installed",
            "arelleCmdLine is not on PATH and the arelle package is not importable "
            "(pip install 'bvb-esef-scraper[validate]')", SOURCE_ENV))
        result.status = classify(result.findings, available=False)
        return result
    cache = Path(cache_dir or ARELLE_CACHE_DIR)
    result.cache_dir = str(cache)
    cached, why = cache_report(cache)
    if not cached:
        log.warning("%s", why)
        result.findings.append(Finding(SEV_WARNING, "arelle.cache_not_populated", why,
                                       SOURCE_ENV))
        result.status = classify(result.findings, cached=False)
        return result
    findings, complete, code, seconds = run_arelle(target, cache, timeout, authority)
    result.findings.extend(findings)
    result.duration += seconds
    result.tool = TOOL_ARELLE
    result.complete = result.complete and complete
    result.status = classify(result.findings, complete=result.complete)
    log.info("arelle exit=%s complete=%s status=%s in %.1fs", code, result.complete,
             result.status, seconds)
    return result
