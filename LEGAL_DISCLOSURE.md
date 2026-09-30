# Legal and Compliance Disclosure — BVB ESEF Scraper

**Document type:** Internal compliance analysis and public-facing disclosure
**Prepared:** 2026-09-29
**All external sources retrieved:** 2026-09-29 (single access date, recorded per source in Appendix A)
**Status of the project:** Open source, MIT-licensed. Not endorsed by, and not operating under any arrangement with, the Bucharest Stock Exchange (BVB), the Financial Supervisory Authority (ASF), ESMA or XBRL International.

---

## 1. Purpose and scope

### 1.1 What the project is

This repository contains software that:

- reads the publicly reachable report listings published by the Bucharest Stock Exchange at `bvb.ro` and at `iris.bvb.ro` (BVB's Issuers Reporting System);
- filters those listings for annual-report attachment packages in the ESEF Taxonomy Package format (`.zip`);
- uses HTTP range requests to check candidate packages for Inline XBRL (iXBRL) content before deciding whether to download them in full;
- extracts a small set of factual fields from each package it accepts — LEI, ticker, issuer legal name, filing URL, filing date, period end, language, source system, and a SHA-256 digest of the downloaded file;
- writes those fields to `filings.json` / `filings.jsonl`, an index intended to be offered to `filings.xbrl.org`, the Inline XBRL filing index operated by XBRL International.

### 1.2 What this document covers

- Whether the manner in which the project accesses BVB's website is authorised (section 4).
- Whether the filings the project indexes are public regulatory information, and what rights exist in them and in the index itself (section 5).
- Whether open-data / public-sector-information law applies to a Romanian regulated-market operator such as BVB (section 6).
- The technical and organisational measures adopted to minimise harm (section 7), the steps required to become and remain compliant (section 8), and the data-protection and data-minimisation position (sections 9 and 10).

### 1.3 What this document does not cover

- It is **not legal advice** and **not a legal opinion** on Romanian or EU law.
- It is **not a representation, warranty or assurance to any third party** that the project is authorised, compliant, or lawful to operate. Only the owner can decide whether to operate the project, and only qualified Romanian counsel can advise on that.
- It does not address tax, accounting, securities-regulation licensing, or competition-law questions arising from distribution of the index.
- It does not address the position of any individual user who runs the software.

### 1.4 A note on the requested framing

The project owner asked for a statement that the scraper "does not violate any bvb.ro rights and such and the data it's public under european law or something."

**That statement cannot be made honestly, and this document does not make it.** The first sentence of BVB's published Terms and Conditions of Use forbids automated access to and parsing of its website, and requires express written consent to retrieve electronic data for any purpose other than strictly personal information. As published, that condition is not met. Section 2 states this plainly; sections 5 and 6 explain what remains true in the project's favour once the access question is separated from the question of rights in the underlying data; section 8 sets out a real path to compliance.

---

## 2. Summary of conclusions

**(a) BVB's published terms do not authorise automated collection. As things stand, the project is not authorised to run at scale.**

BVB's Terms and Conditions of Use state, in both the Romanian and English versions, that the site is designed for ordinary human-speed navigation, that "it is forbidden to use automated programs to access the web page of BSE and/or parsing of the information contained therein", and that "to retrieve electronic data from BSE, for any purpose other than for strictly personal information you need an express consent from BSE". BVB further reserves the right to block an IP address without notice or explanation where it detects behaviour it cannot justify as normal and reasonable access, or which impedes the proper functioning of its systems. A public-interest filing index is plainly not "strictly personal information". **BVB's express written consent is a genuine prerequisite.** The harm-minimising engineering described in section 3 and section 7 does not satisfy that prerequisite; it reduces the practical impact of the breach, it does not remove it.

**(b) The filings are public regulatory disclosures, which supports the project's public-interest rationale but answers a different question.**

ESEF report packages are made public by issuers because EU law requires them to be prepared and filed. The question "may this data be republished?" and the question "am I permitted to retrieve it by automated means from this particular website?" are legally distinct. Answering the first in the project's favour does not answer the second. The distinction matters in both directions: a public-interest motive strengthens the project's negotiating position with BVB, and it does not make the collection authorised.

**(c) A metadata-only index raises materially weaker intellectual-property concerns than redistributing the reports.**

Individual facts are not protected by copyright, and the sui generis database right protects the investment in obtaining, verifying or presenting contents — which is exactly the kind of investment this project makes, and which it can publish openly. The underlying report text, however, belongs to the issuers, not to BVB, and redistribution of report bodies would raise a different and much heavier set of questions. A metadata index that links to BVB's URLs is the correct design and should be preserved.

**(d) The practical path forward is written consent and/or an alternative distribution channel.**

BVB's own terms direct any party seeking electronic data to a written request, treated under BVB's commercial policy. A written, narrowly-scoped request — permission to retrieve ESEF report packages programmatically at an agreed rate, for a public filing index, with attribution and a takedown contact — is the correct next step. In parallel, the owner should ask ASF whether the same data is obtainable through official channels, and plan to migrate to the European Single Access Point (ESAP) once ESMA has established and operates it, which Regulation (EU) 2023/2859 requires by 10 July 2027.

**(e) What this document is not.**

This is not legal advice. It is not a legal opinion. It is not a representation that the project is authorised, and it does not create any right the owner does not already hold. It is an honest statement of the legal position as it stands on the access date, and it should be read alongside advice from qualified Romanian counsel before the project is scaled.

---

## 3. What the scraper does, technically

This section is factual. It is written so that the measures can be evaluated, not so that they can be mistaken for permission.

- **Sequential, single-connection crawling.** HTTP requests are paced sequentially through per-phase rate limiters. There is no concurrency, no thread pool, and no request fan-out.
- **Low request rate.** Default minimum delay is 1.0 second between requests for `list`, `doctor` and `companies`, and 2.0 seconds for `crawl` and `backfill`. These are configurable upwards.
- **BVB-only host allowlist.** Initial requests and every redirect are checked before transmission; only HTTP/HTTPS URLs on `bvb.ro` or a `bvb.ro` subdomain are permitted.
- **Contactable User-Agent.** `BVB_ESEF_CONTACT` appends a contact address to the HTTP `User-Agent` header, so that a BVB operator receiving a request can identify and reach the person responsible. This is a transparency measure, not a permission.
- **Local caching and resume.** Downloaded packages are stored on disk and subsequent runs skip files already present. Nothing already held locally is re-fetched, so request volume does not grow with repeated use.
- **Range probing before download.** Candidate `.zip` attachments are inspected with HTTP `Range` requests (a tail read and targeted reads of the zip central directory) to determine whether the package contains iXBRL content. Packages that are not iXBRL are rejected without a full download, materially reducing bytes transferred from BVB's servers.
- **Language filtering before transfer.** Where a run is scoped to a single language, filtered-out packages are never probed or downloaded.
- **No authentication bypass.** The tool uses only publicly reachable endpoints. It does not circumvent access controls, does not attempt to use restricted areas, and does not defeat any technical protection measure.
- **Backoff on overload signals.** HTTP 429 and 503 responses trigger a single retry after a backoff pause, and individual errors are skipped rather than retried aggressively.
- **Cease-on-request.** The operator is willing and able to stop all collection immediately on request from BVB.

**Framing.** These are harm-minimisation measures, and they are the right engineering posture regardless of the legal question. They are **not** legal authorisation. BVB's terms do not carve out an exception for polite, low-rate or identifiable automated access; on the contrary, the prohibition is stated without qualification, and the only route the terms offer for non-personal data retrieval is express written consent.

---

## 4. Analysis layer 1 — BVB's Terms and Conditions of Use

### 4.1 Operative clauses, Romanian text

Source: `https://www.bvb.ro/Disclaimer.aspx` (retrieved 2026-09-29). The site text is served without Romanian diacritics; the quotations below are reproduced as served.

> "utilizatorul detine numai dreptul de a vizualiza si de a edita o copie a cuprinsului paginii de WEB a B.V.B. pentru folosinta sa personala, iar nu pentru uzul comercial. Utilizatorii nu au dreptul sa copieze, depoziteze, indiferent daca pe un calculator sau pe un sistem electronic de salvare, sa transmita, transfere, prezinte, difuzeze, publice, reproduca, sa creeze din aceasta o opera secundara, sa expuna, distribuie, vanda, licentieze, inchirieze, concesioneze sau sa transfere in alt mod orice parte a cuprinsului paginii de WEB a B.V.B., oricarei terte persoane ... fara a avea acordul prealabil scris al B.V.B. sau al furnizorului terta parte al continutului."

> "Pagina de WEB a B.V.B. este proiectata pentru utilizarea in contextul navigarii obisnuite, folosind un program de navigare in mod grafic si generand cereri de acces cu o frecventa justificata de capacitatea de informare specific umana in contextul corespunzator. Este interzisa folosirea de programe automate de accesare a paginii WEB a B.V.B. si/sau parsare a informatiilor continute. B.V.B. isi rezerva dreptul de a bloca, fara instiintare prealabila si fara a avea obligatia de a acorda explicatii, accesul unei anumite adrese de Internet la site-ul B.V.B., pe o perioada determinata / nedeterminata, in cazul in care se detecteaza un comportament ce nu poate fi justificat de accesarea normala si rezonabila a site-ului B.V.B. sau daca acest comportament impiedica buna functionare a sistemelor informatice ale B.V.B. Pentru a prelua date electronice de la B.V.B., in alt scop decat pentru informarea dvs. strict personala este necesar acordul expres al B.V.B. si in acest sens va rugam sa adresati o cerere scrisa catre B.V.B., care va fi tratata in acord cu politica comerciala de B.V.B."

> "Accesul utilizatorilor si folosinta de catre acestia a prezentului site de WEB sunt guvernate de toate legile si reglementarile romane aplicabile in materie."

> "B.V.B. isi rezerva dreptul de a modifica oricand prezentii termeni si conditii de utilizare, si se presupune ca utilizatorii sunt in cunostinta de cauza cu privire la orice schimbari care intervin si sunt obligati sa le respecte, incepand de la data editarii acestora pe pagina de WEB a B.V.B."

### 4.2 Operative clauses, English text

Source: `https://iris.bvb.ro/Disclaimer` (retrieved 2026-09-29).

> "It is forbidden to use automated programs to access the web page of BSE and / or parsing of the information contained therein. BSE reserves the right to block, without notice and without any obligation to provide explanations, the access for a particular Internet address (IP) to the BSE site for a specific period / indefinite, if it detects a behavior that cannot be justified by normal and reasonable access to BSE website or if this behavior prevents the proper functioning of systems of BSE. To retrieve electronic data from BSE, for any purpose other than for strictly personal information you need an express consent from BSE and in this regard, please address a written request to BSE, which will be treated in accordance with the BSE policy."

> "User access to and use of this website is subject to all applicable Romanian laws and regulations."

### 4.3 The absence of a robots.txt

`https://www.bvb.ro/robots.txt` and `https://m.bvb.ro/robots.txt` both returned HTTP 404 on 2026-09-29. `https://iris.bvb.ro/robots.txt` returned HTTP 302 (a redirect, not a crawl policy). There is therefore **no machine-readable crawl directive** on these hosts, and the project has not fabricated one.

That absence is not permission. `robots.txt` is a voluntary technical convention and is not, by itself, a contractual instrument; equally, its absence does not override express contractual language in published terms of use. The operative prohibition here is in the terms, not in a robots file.

### 4.4 The governing law, and the status of the English text

The Romanian terms state that access and use are governed by all applicable Romanian laws and regulations. The English-language terms on `iris.bvb.ro` are a substantially equivalent rendering of the same instrument and the same legal instrument, not a separate or relaxed regime. Reading the English version as permissive where the Romanian is restrictive would be a mistake.

### 4.5 Terms of use versus robots.txt — the general question

In several other jurisdictions courts have been asked whether a website's terms of use bind a party who has not clicked "accept", and whether a `robots.txt` file is capable of contracting out of a claim. Those authorities are divided, and the reasoning is jurisdiction-specific: the answers turn on notice, assent and consideration as those concepts operate in the relevant national law. **This document does not rely on any such authority.** The point is, on this record, not finely balanced: the prohibition is not hidden, it is in both language versions of the terms, it is repeated in a dedicated "Restrictions" section, and the terms themselves state the consequence — that a written request is the route to non-personal data retrieval. Whether any residual argument exists is a question for Romanian counsel.

### 4.6 Consequence

1. Automated access to and parsing of BVB's site is **prohibited** by the terms as published.
2. Retrieval of electronic data for any purpose other than strictly personal information **requires express consent** from BVB, obtained in writing.
3. A public-interest filing index is not a personal purpose.
4. BVB may **block the project's IP address** without notice and without giving reasons, and reserves "all remedies available at law and in equity", including blocking, for violations.
5. The terms may be changed at any time, and users are deemed bound by changes from the date of publication. The project must therefore re-verify the terms periodically and treat a change as a re-trigger event for review.

**As published, the project does not satisfy the condition BVB's own terms impose. It should not be operated at scale until written consent is obtained.**

---

## 5. Analysis layer 2 — rights in the filings themselves

### 5.1 The regulatory publication duty

ESEF (the European Single Electronic Reporting Format) is specified by Commission Delegated Regulation (EU) 2019/815 of 17 December 2018, adopted under Article 4(7) of Directive 2004/109/EC (as amended by Directive 2013/50/EU).
Source: `https://eur-lex.europa.eu/eli/reg_del/2019/815/oj`

Verified provisions of that Regulation:

- **Article 3 (Single electronic reporting format):** "Issuers shall prepare their entire annual financial reports in XHTML format."
- **Article 4(1) (Marking up IFRS consolidated financial statements):** "Where annual financial reports include IFRS consolidated financial statements, issuers shall mark up those consolidated financial statements."
- **Article 4(4):** markups use the XBRL markup language and a taxonomy whose elements are those of the core taxonomy, with extension taxonomy elements created where the core taxonomy is not appropriate.
- **Article 6 (Common rules on markups):** markups are embedded in the annual financial report in XHTML format using the Inline XBRL specifications, and comply with the marking-up and filing rules.
- **Annex III, point 3:** "Issuers shall submit the Inline XBRL instance document and the issuer's XBRL extension taxonomy files as a single reporting package..." — replaced by Commission Delegated Regulation (EU) 2025/19 with the wording "as a single reporting package according to the Report Packages 1.0 specification."
- **Article 8 (Entry into force and application):** "It shall apply to annual financial reports containing financial statements for financial years beginning on or after 1 January 2020."

Amendments in force as recorded in the EUR-Lex consolidation (consolidated text as at 7 April 2026, CELEX `02019R0815-20260407`, `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02019R0815-20260407`): Commission Delegated Regulations (EU) 2019/2100, (EU) 2020/1989, (EU) 2022/352, (EU) 2022/2553, (EU) 2025/19 and (EU) 2026/283. The last of these was not in the project's earlier working notes and is recorded here because the consolidated text was re-checked on the access date. *The amendment list should be re-verified against the EUR-Lex "Amended by" table on each review of this document.*

**Consequence.** Romanian issuers admitted to trading on a regulated market are required to prepare and file ESEF report packages. The filings are therefore the product of a legal publication obligation, not of a private commercial decision to distribute. That is a genuine and relevant public-interest fact. It supports the project's rationale, and it is a strong argument to put to BVB. It does not, by itself, authorise retrieval by automated means from BVB's website.

### 5.2 The national market framework

- BVB's own published Regulation of Organisation and Functioning (source: `https://www.bvb.ro/Juridic/files/ROF_BVB.pdf`, retrieved 2026-09-29) states at Article 1 that BVB is a Romanian joint-stock company "formed by change of legal form of the [institutie de interes public] Bucharest Stock Exchange", at Article 2 that it operates in accordance with its own Articles of Incorporation, Law 31/1990 and Law 297/2004, under the authorisation and supervision of the then CNVM, and at Article 3 that it is a market operator and system operator.
- **Law 24/2017 on issuers of financial instruments and market operations** (republished; `https://legislatie.just.ro/Public/DetaliiDocument/187788`) establishes the framework for market operations and for issuers of financial instruments admitted to trading on a regulated market, and identifies the Financial Supervisory Authority (ASF) as the competent authority.
- **Law 126/2018 on financial instrument markets** (`https://brm.ro/wp-content/uploads/Legea-nr.-126-2018.pdf`) regulates, among other things, the authorisation and functioning of market operators and regulated markets, and likewise identifies ASF as competent. ASF is established by Government Emergency Ordinance 93/2012, approved by Law 113/2013.
- **Law 297/2004 on the capital market** is the statute the exchange's own rules cite as its market-law basis.
- **Law 52/1994 on securities and stock exchanges** is a real instrument (published in *Monitorul Oficial* Part I no. 210 of 11 August 1994) but has been substantially superseded — partially replaced by the 2002 statute and then repealed and replaced by Government Emergency Ordinance 28/2002. It should be cited, if at all, as historical background only. *To be confirmed by Romanian counsel before any citation in external material.*

### 5.3 ESAP and the collection gap this project addresses

Regulation (EU) 2023/2859 of 13 December 2023 establishing a European single access point (ESAP).
Source: `https://eur-lex.europa.eu/eli/reg/2023/2859/oj`

- **Article 1(1)(a):** "By 10 July 2027, ESMA shall establish and operate a European single access point (ESAP) providing centralised electronic access to ... information made public pursuant to the Union legislative acts listed in the Annex..."
- **Article 3(1):** "From 10 January 2030, an entity may submit the information referred to in Article 1(1), point (b), to the collection body in the Member State where the entity has its registered office for the purpose of making that information accessible on ESAP."

**Consequence, and the honest case for the project.** Until ESAP exists and is populated, ESEF filings are obtainable only through national collection channels. That is precisely the discoverability gap this project addresses. ESAP is an affirmative argument that the index is premature rather than unnecessary — but it is an argument about *when*, not about *whether consent is needed now*.

### 5.4 Facts, and the sui generis database right

Directive 96/9/EC of 11 March 1996 on the legal protection of databases.
Source: `https://eur-lex.europa.eu/eli/dir/1996/9/oj`

- **Article 7(1):** Member States provide a right for the maker of a database "which shows that there has been qualitatively and/or quantitatively a substantial investment in either the obtaining, verification or presentation of the contents" against unauthorised extraction or re-utilisation of the whole or a substantial part of the contents.
- **Article 7(4):** the right applies "irrespective of the eligibility of that database for protection by copyright or by other rights", and "irrespective of eligibility of the contents of that database for protection by copyright or by other rights" — i.e. the individual contents of a database may be unprotected as such, while the compilation is protected.
- **Article 7(5)** (prohibition of repeated and systematic extraction of insubstantial parts) was interpreted in Case C-203/02, *The British Horseracing Board Ltd and Others v William Hill Organization Ltd*, Judgment of 9 November 2004, ECR 2004 I-10415 (`https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A62002CJ0203`), which held in particular that the fact that a database's contents were made accessible to the public by its maker or with its consent does not affect the right of the maker to prevent extraction or re-utilisation of a substantial part of those contents.

**How this bears on the project.**

- The *facts* recorded in the index — a LEI, a legal name, a ticker, a date, a period end, a language, a URL, a cryptographic hash — are not, as such, protected by copyright. Copyright does not protect facts, only the original expression in which they are presented.
- The *index as an index* is a plausible candidate for the sui generis right: it is the paradigm case of a substantial investment in obtaining (systematic discovery across issuers and years), verifying (LEI validation, iXBRL probing, hash computation) and presenting (a structured, machine-readable filing index) contents. The project should continue to invest openly in those three dimensions, because that investment is what it owns.
- **Important limit.** A defensible investment in the index does not cure a separate contractual problem about *how* BVB's website was accessed. The two questions are independent. A database right that the project may hold does not license the collection method.

### 5.5 Rights in the reports themselves

The report packages are authored by the issuers, not by BVB. BVB is the publisher and host; the exchange's terms confirm that it claims rights in and to "the contents", but the underlying annual financial report text belongs to the issuer. The project's own `GRANT-XBRL.md` states this correctly: "the crawled content remains the property of its respective issuers."

**Design consequence, and a hard rule for the project:** the published index should contain **metadata and links only**. It should not redistribute, mirror or bundle report bodies unless and until consent expressly covers that. See section 9.

### 5.6 The licensing posture of this project

- The software is released under the MIT Licence (`LICENSE.md` / `LICENSE.ro.md`). The owner can license its own code freely.
- `GRANT-XBRL.md` grants XBRL International a perpetual, worldwide, royalty-free, non-exclusive, irrevocable licence to use, copy, modify, publish and distribute the **output data** — filing metadata, indexes and derived datasets — including sublicensing to third parties.
- **Limit of that grant, stated plainly.** A licence can only convey rights the grantor holds. The grant covers the owner's code and the metadata the owner derives. It **cannot** license rights in the issuers' report text, nor can it license rights the owner does not hold in BVB's site content, nor can it waive BVB's terms. `GRANT-XBRL.md` already says the crawled content remains the property of its issuers; this section makes the operational consequence explicit. The grant is an offer of the owner's own output, and is not evidence that the owner is entitled to produce that output at scale.

---

## 6. Analysis layer 3 — open data and public-sector information

Directive 2013/37/EU (the Public Sector Information, or PSI / Open Data Directive) aims to set minimum rules for the re-use of documents held by public sector bodies of the Member States, and creates categories of high-value datasets and a regime for making them available. Its thematic high-value categories were replaced by Annex I to Directive (EU) 2019/1024, which lists six categories, the fifth being **"companies and company ownership"**; the specific dataset list and the minimum conditions for dissemination via APIs are set out in Commission Implementing Regulation (EU) 2023/138.
Sources: `https://eur-lex.europa.eu/eli/dir/2013/37/oj`, `https://eur-lex.europa.eu/eli/reg_impl/2023/138/oj`

**The open question, which this document does not answer.** The regime addresses *public sector bodies*. BVB is a regulated market operator; it was constituted by change of legal form of an entity described in its own published rules as an "institutie de interes public", but it is a private-law joint-stock company that derives its revenue from market activities, including fees from issuers and the sale of market data. Whether a Romanian regulated market operator falls within the scope of the PSI regime — either directly or through the Romanian transposition, which must be identified and read — is a question of Romanian law that was **not** established for this document.

- This document does **not** assert that Directive 2013/37/EU applies to BVB. Doing so without support would be exactly the kind of overstatement this document exists to avoid.
- *This is flagged for Romanian counsel as a priority question, together with the related question of whether Romanian freedom-of-information law reaches BVB or a self-funded body of this kind.*
- If the regime were held to apply, the consequences for this project would be substantial: it would supply both a re-use basis and a route to obtain the data by request rather than by crawling.

---

## 7. Compliance measures adopted

The measures below are already in the code. They are listed with what each does **and does not** achieve, because the second half of that sentence is where the legal risk sits.

| Measure | What it achieves | What it does **not** achieve |
|---|---|---|
| Sequential pacing without concurrency | Eliminates request flooding and load spikes | Does not satisfy the prohibition on automated access |
| 1.0 s default delay for `list`, `doctor` and `companies`; 2.0 s for `crawl` and `backfill`, configurable upwards | Keeps request rates low without parallel request fan-out | Does not create an authorisation; "normal and reasonable access" is not defined to include automation |
| BVB-only allowlist, including redirect checks | Prevents accidental requests to non-BVB hosts | Does not satisfy the prohibition on automated access |
| Contactable User-Agent via `BVB_ESEF_CONTACT` | Makes the operator identifiable and reachable; supports a takedown request being honoured | Does not substitute for consent, and does not cure an unauthorised access |
| Local caching and resume from disk | Nothing already held is re-fetched; request volume does not grow with use | Does not address the lawfulness of the initial retrieval |
| HTTP range probing before full download | Rejects non-iXBRL packages without transferring the whole file; materially reduces bytes served | Does not address the lawfulness of the requests that are made |
| Language filtering before probing and download | Reduces the number of transfers by roughly half on a language-scoped run | Does not address the lawfulness of the requests that are made |
| No authentication bypass; public endpoints only | No circumvention of access controls or technical protection measures | Does not address the lawfulness of automated access to publicly reachable pages |
| Backoff and single retry on HTTP 429 / 503; errors skipped | Respects overload signals; avoids retry storms | Does not convert an unpermitted operation into a permitted one |
| Cease immediately on request | Enables an effective takedown and an honest response to BVB | Does not remove the breach that has already occurred |
| Metadata-only index (no report bodies redistributed) | Minimises the intellectual-property surface; consistent with the sui generis analysis in section 5.4 | Does not address the site-access question |
| SHA-256 of each retrieved package | Enables integrity verification, de-duplication and cross-linking; matches the practice of `filings.xbrl.org` | Not a legal measure |

**The honest summary:** the engineering is good and the posture is cooperative. None of it substitutes for the written consent that BVB's terms require.

---

## 8. Compliance roadmap

These steps are ordered. Steps 1 and 2 are prerequisites to operating the project at scale; the rest make the arrangement durable.

### Step 1 — Obtain BVB's express written consent (blocking)

BVB's own terms direct any party seeking electronic data for a non-personal purpose to "address a written request to BSE, which will be treated in accordance with the BSE policy." BVB's published personal-data policy page gives `dpo@bvb.ro` as the Data Protection Officer contact for the BVB S.A. entity, and the general contact details published on the same page are (+40) 21 307 95 00. The written request should be addressed to the appropriate commercial or data-licensing function at BVB; the DPO address is the only BVB email address this project has verified and it is included as a starting point, not as a determination of the correct recipient.

**What to ask for, precisely:**

1. Permission to retrieve ESEF report packages published on BVB's public report listings, programmatically, using a single sequential connection.
2. At an agreed maximum request rate, and with the right to reduce that rate on request.
3. For the specific purpose of building and maintaining a public index of ESEF filings, offered to `filings.xbrl.org` and to users of the project.
4. Publishing **metadata and links only** — no redistribution of report bodies.
5. Attribution: an agreed form of credit to BVB as the source of the filing URLs, and a statement that filings remain the property of the respective issuers.
6. A named contact point on both sides and a takedown / correction route, with a response-time commitment.
7. Confirmation of whether the permission is granted free of charge, on what terms, and for how long.
8. Whether BVB would prefer instead to supply the data directly, or via its existing data-distribution channels — which would be a better outcome for the project.

**Realistic expectations.** BVB has a commercial policy for electronic data and sells market data. Consent may be granted, may be granted subject to a fee, may be granted only for part of the estate, or may be refused. Each of those outcomes is workable. Silence is not: an unanswered request should be treated as a refusal, and the project should not proceed to scale in the meantime.

**Skeleton of the request:**

```
To:      [BVB — appropriate commercial / data licensing function; dpo@bvb.ro as published contact]
From:    [Owner name, contact e-mail, postal address]        Date: [date]
Subject: Request for express written consent to retrieve ESEF report packages
         programmatically (ref. "Termeni si conditii de utilizare", section "Restrictii")

1. We refer to the Terms and Conditions of Use published at
   https://www.bvb.ro/Disclaimer.aspx, which state that "Este interzisa folosirea de
   programe automate de accesare a paginii WEB a B.V.B." and that "[p]entru a prelua
   date electronice de la B.V.B., in alt scop decat pentru informarea dvs. strict
   personala este necesar acordul expres al B.V.B.", and which invite a written
   request. This is that request.

2. Purpose. We operate an open-source project that builds a public, machine-readable
   index of Romanian ESEF (inline XBRL) annual-report packages, intended to feed
   filings.xbrl.org, the Inline XBRL filing index operated by XBRL International.
   The index addresses the discoverability gap identified on that service's own
   "About" page, which states that "the repository is not complete". Until the
   European Single Access Point is established and operated by ESMA under
   Regulation (EU) 2023/2859, ESEF filings are obtainable only through national
   collection channels.

3. Scope requested. Permission to retrieve ESEF report package files (.zip) and the
   public report listings in which they appear, from BVB's public endpoints only, in
   order to extract filing metadata.

4. Data published. Metadata only: LEI, issuer legal name, ticker symbol, filing URL,
   filing date, period end, language, source system and a SHA-256 digest. We will not
   redistribute, mirror or bundle the report bodies themselves, and we will state
   that the filings remain the property of the respective issuers.

5. Technical characteristics, offered for verification. A single sequential
   connection; a minimum delay of 1.0 second between requests for list/doctor/companies and 2.0 seconds for
   crawl/backfill, configurable upwards; an HTTP User-Agent containing a monitored
   contact address; HTTP range requests used to determine package content before
   any full download; local caching so that nothing already retrieved is fetched
   again; no authentication, no circumvention of any access control, no parallel
   requests; a single retry with backoff on HTTP 429 or 503.

6. Attribution and contact. We will attribute BVB as the source of each filing URL
   and will provide a monitored contact address in our User-Agent header and in our
   published documentation. We will operate a takedown and correction process and
   will cease collection immediately on request.

7. Term. We propose a term of [ ], renewable, terminable on notice, and we accept
   any rate, scope or attribution conditions BVB requires.

8. We would welcome discussion of whether BVB would prefer to supply this data
   through an existing channel instead. We are also exploring obtaining the same data
   from the Financial Supervisory Authority, and plan to migrate to the European
   Single Access Point once available.

Yours faithfully, [Name, role, contact details]
```

### Step 2 — Do not scale before consent (blocking)

Until a written consent exists (or a written refusal is received and acted on), the project should not be run against BVB's servers at backfill scale, and should not be presented to third parties as though it is authorised. An unanswered request is a refusal.

### Step 3 — Ask ASF for the same data through official channels

ASF is the competent authority under Law 24/2017 and Law 126/2018. A parallel written enquiry to ASF asking whether ESEF report packages and their metadata are available through official channels, and on what terms, is appropriate. A refusal or an unfavourable answer from ASF would not change the BVB position, and a favourable one may remove the need to crawl BVB at all. *No contact has been made with ASF in relation to this project, and nothing in this document should be read as implying ASF awareness of or endorsement of it.*

### Step 4 — Plan for ESAP

Regulation (EU) 2023/2859 requires ESMA to establish and operate ESAP by 10 July 2027, with certain functionality milestones in 2028 and 2030. The project should design its ingestion to be source-agnostic so that it can switch to ESAP as the primary source and retain BVB or ASF as a supplementary source. This is the structural fix for the problem the project currently works around.

### Step 5 — Maintain a takedown and erasure process

Publish a monitored contact address, accept takedown requests without argument, remove affected records from the index, and record each request and its resolution. Keep the log; it is evidence of good faith.

### Step 6 — Re-verify BVB's terms periodically

BVB reserves the right to modify the terms at any time, with users deemed bound from the date of publication. Re-check `https://www.bvb.ro/Disclaimer.aspx` and `https://iris.bvb.ro/Disclaimer` at least every six months, and immediately on any change in behaviour observed from BVB's side. Record each check, with its date, in the project's documentation. Any substantive change to the "Restrictions" section is a re-trigger event for this entire analysis.

### Step 7 — Keep a written record of consent

Retain the written request, BVB's full reply, and any resulting agreement or licence, in the repository or in a linked public record, together with the date and the conditions. Consent that cannot be produced cannot be relied on, by a third party or by a regulator.

### Step 8 — Obtain Romanian legal advice before scaling

On at least: (i) the analysis in section 4, including the enforceability of the terms against a party who has not expressly accepted them; (ii) the scope question in section 6; (iii) the copyright status of the report bodies and of the index; (iv) any notification obligation to BVB or ASF.

---

## 9. Data minimisation, retention and accuracy

**Minimisation.** The published index should contain metadata and links only: LEI, issuer legal name, ticker, filing URL, filing date, period end, language, source system, SHA-256. It should **link to** the exchange URL rather than mirror the report body. Mirroring would transform a metadata question into a distribution question and would import the issuers' own copyright position into this project. Mirroring should not be adopted unless consent expressly covers it.

**Integrity.** Publishing the SHA-256 of each retrieved package lets any consumer verify that the file they obtain is byte-identical to the file indexed, and lets a future collection detect that a filing has been amended or replaced. This is the same practice `filings.xbrl.org` describes: it "use[s] hashes to uniquely identify reports within the index. This allows us to detect where the same filing is submitted to multiple authorities, and cross-link them. It also allows us to reliably avoid adding duplicate filings."

**Timestamps.** Each record should carry the date the underlying filing was published and the date the record was added to the index. The second is not the first, and conflating them misleads consumers about currency. `filings.xbrl.org` is candid that the two diverge: there "may be a significant delay between a filing being submitted to the collection authority and it being added to our index."

**Corrections.** Publish a corrections process: a monitored address, a stated handling time, and a record of what was corrected and when. Filings are frequently restated or amended, and the index must be able to represent that honestly rather than presenting a single immutable record as though it were the current state of the world.

**Accuracy and warranty.** BVB's own terms disclaim the accuracy of the information on its site: the content is provided "as is", without warranties of any kind, and BVB "makes no representations about the suitability, completeness or accuracy of the information contained on this site", disclaiming warranties as to "accuracy, timeliness, completeness, currentness, refresh frequency, reliability, noninfringement, merchantability or fitness for any particular purpose". A downstream index inherits that position and must not paper over it. The index should carry an equivalent disclaimer: records are reproduced from the exchange's published listings, are provided "as is", without warranty of accuracy, completeness, timeliness or fitness for any purpose, and consumers must obtain the authoritative version from the source. The project should also state the known limitations that `filings.xbrl.org` itself documents — filings whose LEI and filing date cannot be determined automatically are excluded from its index entirely, and many of its filings carry validation errors and warnings. An index that does not disclose its own gaps will be read as more complete than it is.

**Retention.** Retain raw packages only as long as needed to produce and verify the index, and delete them on a stated schedule. Retain index records and their hashes for the life of the index, so that the historical record remains auditable. Publish the schedule.

---

## 10. Personal data

The crawler collects corporate identifiers and document metadata only: LEI, issuer legal name, ticker symbol, filing URL, filing date, period end, language, source system and a cryptographic hash. These are attributes of legal entities and of documents, not data relating to identified or identifiable natural persons. Some report bodies reference natural persons (directors, signatories), but the index does not extract or publish that content, and the bodies are not redistributed.

On that basis, **the crawler's own index does not appear to engage Regulation (EU) 2016/679 (GDPR)**, and no personal-data processing is described in this project on the access date. Two consequences follow: the project has no basis to publish personal data it does not collect, and it should keep it that way. If the project is later extended to parse report bodies, signatory names or beneficial-ownership data, this assessment must be redone.

This assessment is limited to the crawler's own processing. It is not an assessment of BVB's own personal-data position, which is governed by BVB's published policy.

---

## 11. Limitations and disclaimer

1. **Not legal advice.** This document is an internal compliance analysis prepared by the project owner. It is not legal advice, does not create a lawyer–client relationship, and should not be relied on as such.
2. **Not a legal opinion.** It is not an opinion on Romanian law, on EU law, or on the enforceability of any instrument referred to. Sections 4.5, 5.2 and 6 in particular identify questions that were not resolved here.
3. **Sources as at the access date.** Every external source was retrieved on 2026-09-29 and is listed in Appendix A. BVB's terms of use may be changed by BVB at any time, without notice, and this document does not survive such a change. EU legislation cited may be amended, replaced or repealed; the consolidated texts referred to are the versions current on the access date.
4. **Not an authorisation.** Nothing in this document authorises any person to operate the project, and nothing in it should be quoted as though it did. BVB has not consented, and has not been asked, as at the access date. ASF and ESMA have no involvement with, and no endorsement of, this project. XBRL International operates `filings.xbrl.org`; it has not endorsed this project, and any submission of output data would be made on the terms of the project's `GRANT-XBRL.md`, not by endorsement.
5. **Professional advice required.** The owner should obtain advice from qualified Romanian counsel — and, for the intellectual-property analysis, from counsel experienced with Directive 96/9/EC and Directive 2013/37/EU — before scaling the project, before redistributing any data derived from it, and before relying on this document for any purpose.
6. **No rights conferred.** This document cannot create rights the owner does not have. It cannot license the issuers' report text, it cannot waive BVB's terms, and it cannot substitute for a written consent.
7. **The position stated here is the position as at 2026-09-29.** If any statement in it is later found to be wrong, correct it publicly rather than quietly.

---

## Appendix A — sources checked

All URLs retrieved **2026-09-29**. Section references point into this document.

### A.1 BVB — primary and decisive

- Terms and Conditions of Use (Romanian) — 4.1, 8, 9 — `https://www.bvb.ro/Disclaimer.aspx`
- Terms and Conditions of Use (English, IRIS) — 4.2 — `https://iris.bvb.ro/Disclaimer`
- Regulation of Organisation and Functioning, Art. 1, 2, 3 — 5.2 — `https://www.bvb.ro/Juridic/files/ROF_BVB.pdf`
- `robots.txt` on `www.bvb.ro` and `m.bvb.ro`, both HTTP 404 — 4.3 — `https://www.bvb.ro/robots.txt`, `https://m.bvb.ro/robots.txt`
- `robots.txt` on `iris.bvb.ro`, HTTP 302 redirect, no policy — 4.3 — `https://iris.bvb.ro/robots.txt`

### A.2 EU law

- Commission Delegated Regulation (EU) 2019/815 (ESEF RTS), OJ L 143, 29.5.2019, p. 1 — 5.1 — `https://eur-lex.europa.eu/eli/reg_del/2019/815/oj`
- Consolidated text of (EU) 2019/815 as at 7 April 2026, CELEX 02019R0815-20260407 (amendment list M1–M6) — 5.1 — `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02019R0815-20260407`
- Commission Delegated Regulation (EU) 2025/19, OJ L 19, 15.1.2025, p. 1 — 5.1 — `https://eur-lex.europa.eu/eli/reg_del/2025/19/oj`
- Commission Delegated Regulation (EU) 2022/2553, OJ L 339, 30.12.2022, p. 1 (recital confirming (EU) 2019/815 is made "as referred to in Article 4(7) of Directive 2004/109/EC") — 5.1 — `https://eur-lex.europa.eu/eli/reg_del/2022/2553/oj`
- Directive 2004/109/EC (Transparency Directive), Art. 4(7) — 5.1 — `https://eur-lex.europa.eu/eli/dir/2004/109/oj`
- Directive 2013/50/EU (amending Directive 2004/109/EC) — 5.1 — `https://eur-lex.europa.eu/eli/dir/2013/50/oj`
- Regulation (EU) 2023/2859 (ESAP), Art. 1(1)(a) and Art. 3(1) — 5.3, 8 — `https://eur-lex.europa.eu/eli/reg/2023/2859/oj`
- Directive 96/9/EC (databases), Art. 7(1), 7(4), 7(5) — 5.4 — `https://eur-lex.europa.eu/eli/dir/1996/9/oj`
- Case C-203/02, *The British Horseracing Board Ltd and Others v William Hill Organization Ltd*, 9 November 2004, ECR 2004 I-10415 — 5.4 — `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A62002CJ0203`
- Directive 2013/37/EU (PSI / Open Data) — 6 — `https://eur-lex.europa.eu/eli/dir/2013/37/oj`
- Directive (EU) 2019/1024 (Annex I thematic high-value categories) — 6 — `https://eur-lex.europa.eu/eli/dir/2019/1024/oj`
- Commission Implementing Regulation (EU) 2023/138 (high-value datasets) — 6 — `https://eur-lex.europa.eu/eli/reg_impl/2023/138/oj`
- Regulation (EU) 2016/679 (GDPR) — 10 — `https://eur-lex.europa.eu/eli/reg/2016/679/oj`
- Regulation (EU) No 1095/2010 (ESMA establishment) — 5.3, 8 — `https://eur-lex.europa.eu/eli/reg/2010/1095/oj`

### A.3 Romanian law

*See the caveat in section 5.2. Verify current consolidated text with Romanian counsel before citing externally.*

- Law 24/2017 on issuers of financial instruments and market operations (republished), Art. 1 — 5.2 — `https://legislatie.just.ro/Public/DetaliiDocument/187788`
- Law 126/2018 on financial instrument markets, Art. 2 and Art. 4 — 5.2 — `https://brm.ro/wp-content/uploads/Legea-nr.-126-2018.pdf`
- Law 297/2004 on the capital market — 5.2 — not directly retrieved; cited as the statute named in BVB's own ROF Art. 2
- Law 52/1994 on securities and stock exchanges, *Monitorul Oficial* Part I no. 210 of 11 August 1994 — 5.2, historical only, substantially superseded — see section 5.2

### A.4 Downstream service

- `filings.xbrl.org` About (purpose, stated incompleteness, hash practice, index structure, terms of use) — 5.3, 8, 9 — `https://filings.xbrl.org/docs/about`
- `filings.xbrl.org` API endpoint (documented, not called by this project) — 5.3 — `https://filings.xbrl.org/api/filings`
