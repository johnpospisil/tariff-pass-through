"""Product lists for the 2025-26 tariff actions (P09).

Source: Harmonized Tariff Schedule of the United States, Chapter 99 (official PDFs from
hts.usitc.gov). As in P08, the Federal Register annexes of the 2025-26 orders are published as
images, so the product lists come from the HTSUS notes that implement them:

- 2025 HTS Revision 28 (in force 2025-11-10 to 2025-11-17): Annex II and the Brazil exemptions
  before the 2025-11-13 agricultural additions (EO 14360, EO 14361).
- 2026 HTS Revision 3 (in force 2026-02-12 to 2026-02-25): the IEEPA notes as they stood just
  before the Supreme Court decision (subchapter III note 2), and the Section 232 metals regime in
  force until 2026-04-05 (notes 16, 19 and the copper note).
- 2026 HTS Revision 21 (in force from 2026-10-09): current Section 232 notes (16, 33, 37-40,
  43), Section 301 (notes 31, 50, 52), Section 338 (note 51) and the terminated Section 122
  surcharge (note 2(aa)).

Lists in the PDF text run together ("7606760576047601", "7616.99.5160760976087607"), so they are
split by `note_codes`, which keeps a reading only if each piece is a real HS prefix in the
2017+ import statistics. Codes that resolve to nothing go to <name>_unmatched.csv.

Run: make hs-lists   (after the P08 lists)
"""

import re
from functools import cache

import polars as pl

from tpt.build.hs_lists import HS10_CODES, LISTS_DIR, chapter99_text

RELEASE_PRE_NOV25 = "2025HTSRev28"
RELEASE_PRE_COURT = "2026HTSRev3"
RELEASE_CURRENT = "2026HTSRev21"

FORMS = [re.compile(p) for p in (r"\d{4}\.\d{2}\.\d{4}", r"\d{4}\.\d{2}\.\d{2}",
                                 r"\d{4}\.\d{2}", r"\d{4}")]  # fmt: skip
RUN = re.compile(r"(?<![\d.,/:])\d{4}[\d.]*")


def prefix_index(hs10: set[str]) -> set[str]:
    return {c[:n] for c in hs10 for n in (4, 6, 8, 10)}


def _segment(run: str, valid: set[str]) -> list[str] | None:
    """Split a run of digits and dots into HTS numbers, all valid, preferring fewer pieces."""

    @cache
    def best(i: int) -> tuple[str, ...] | None:
        if i == len(run):
            return ()
        options = []
        for form in FORMS:
            m = form.match(run, i)
            if not m:
                continue
            code = m.group().replace(".", "")
            if code not in valid:
                continue
            rest = best(m.end())
            if rest is not None:
                options.append((code, *rest))
        return min(options, key=len) if options else None

    found = best(0)
    return list(found) if found is not None else None


def note_codes(text: str, valid: set[str]) -> tuple[list[str], list[str]]:
    """HTS numbers in a note's text (run-together or separated), digits only, in order.

    Returns (codes, unmatched). A run that cannot be split into valid codes is reported as
    unmatched if it looks like an HTS number (dddd.dd.dd...), else ignored as prose."""
    codes: dict[str, None] = {}
    unmatched: dict[str, None] = {}
    for m in RUN.finditer(text):
        run = m.group().rstrip(".")
        if run.startswith(("98", "99")) and len(run) <= 13:
            continue
        pieces = _segment(run, valid)
        if pieces is not None:
            for p in pieces:
                if not p.startswith(("98", "99")):
                    codes.setdefault(p, None)
        elif re.fullmatch(r"\d{4}\.\d{2}(\.\d{2,4})?", run):
            unmatched.setdefault(run.replace(".", ""), None)
    return list(codes), list(unmatched)


def block(text: str, start: str, end: str | None) -> str:
    if start not in text:
        raise ValueError(f"start marker not found: {start!r}")
    i = text.index(start)
    if end is None:
        return text[i:]
    j = text.find(end, i + len(start))
    if j < 0:
        raise ValueError(f"end marker not found: {end!r}")
    return text[i:j]


def country_rate_rows(text: str, heading: str) -> list[tuple[str, str, float]]:
    """(heading, country, rate) for heading-table rows like
    '... articles the product of Algeria, as provided ...  9903.02.03  ... + 30%'."""
    body = text[text.index("Heading/\nSubheading") :]
    toks = list(re.finditer(r"^(?:\d/)?(9903\.\d\d\.\d\d)", body, re.M))
    out = []
    for i, m in enumerate(toks):
        if not re.match(heading, m.group(1)):
            continue
        desc = re.sub(r"\s+", " ", body[toks[i - 1].end() if i else 0 : m.start()])
        nxt = toks[i + 1].start() if i + 1 < len(toks) else m.end() + 300
        after = re.sub(r"\s+", " ", body[m.end() : nxt])[:200]
        cty = re.findall(r"(?:articles|products) the product of (?:the )?([A-Z][^,.]+?)"
                         r"(?:,| as | with | that | for )", desc)  # fmt: skip
        rate = re.search(r"\+ ?(\d+(?:\.\d+)?)%", after)
        if cty and rate:
            out.append((m.group(1), cty[-1].strip(), round(float(rate.group(1)) / 100, 4)))
    return out


# --- list specifications -----------------------------------------------------
# (file name, release, start marker, end marker). Markers are verbatim HTSUS text.

R28, R3, R21 = RELEASE_PRE_NOV25, RELEASE_PRE_COURT, RELEASE_CURRENT
_N52 = "the duties imposed by headings 9903.05.20–9903.05.84 shall not apply to"
SPECS: list[tuple[str, str, str, str | None]] = [
    # IEEPA reciprocal Annex II and Brazil exemptions before 2025-11-13, Rev 28
    ("ieepa_recip_annex2_pre_2025_11.csv", R28, "(iii) As provided in heading 9903.01.32",
     "(iv) As provided in 9903.01.26"),
    ("ieepa_brazil_exempt_pre_2025_11.csv", R28, "(iii) As provided in heading 9903.01.81",
     "(iv) As provided in heading 9903.01.82"),
    # IEEPA reciprocal (subchapter III note 2(v)), Rev 3
    ("ieepa_recip_annex2.csv", R3, "(a) As provided for in heading 9903.01.32",
     "(b) As provided in heading 9903.02.78"),
    ("ieepa_recip_ag_2025_11.csv", R3, "(b) As provided in heading 9903.02.78",
     "(iv) As provided in 9903.01.26"),
    ("ieepa_recip_eu_natres.csv", R3, "(xx) As provided in heading 9903.02.74",
     "(xxi) As provided in heading 9903.02.75"),
    ("ieepa_recip_eu_aircraft.csv", R3, "(xxii) As provided in heading 9903.02.76",
     "(xxiii) As provided in heading 9903.02.77"),
    ("ieepa_recip_eu_pharma.csv", R3, "(xxiii) As provided in heading 9903.02.77",
     "(a) As provided in headings 9903.02.79 and 9903.02.80"),
    ("ieepa_recip_kr_aircraft.csv", R3, "(b) As provided in heading 9903.02.81",
     "(a) As provided in headings 9903.02.82 and 9903.02.83"),
    ("ieepa_recip_ch_natres.csv", R3, "(b) As provided in headings 9903.02.84 and 9903.02.89",
     "(c) As provided in headings 9903.02.85 and 9903.02.90"),
    ("ieepa_recip_ch_aircraft.csv", R3, "(c) As provided in headings 9903.02.85 and 9903.02.90",
     "(d) As provided in headings 9903.02.86 and 9903.02.91"),
    ("ieepa_recip_ch_pharma.csv", R3, "(d) As provided in headings 9903.02.86 and 9903.02.91",
     "(w) Products of China and Hong Kong are not eligible"),
    ("ieepa_recip_jp_aircraft.csv", R3, "(b) As provided in heading 9903.96.02",
     "Harmonized Tariff Schedule of the United States Revision 3 (2026)\nAnnotated for "
     "Statistical Reporting Purposes\nXXII\n99 - III - 3"),
    # IEEPA Brazil (note 2(x)), Rev 3
    ("ieepa_brazil_exempt.csv", R3, "(a) As provided in heading 9903.01.81",
     "(b) As provided in heading 9903.01.90"),
    ("ieepa_brazil_ag_2025_11.csv", R3, "(b) As provided in heading 9903.01.90",
     "(iv) As provided in heading 9903.01.82"),
    ("ieepa_brazil_aircraft.csv", R3, "(iv) As provided in heading 9903.01.82",
     "(v) The additional duties imposed by heading 9903.01.77"),
    # Section 232 metals before 2026-04-06 (metal-content basis), Rev 3 note 16 and 19
    ("s232_steel_deriv_2025_03.csv", R3, "(m) The rates of duty set forth in heading 9903.81.90",
     "(n) The rates of duty in heading 9903.81.91"),
    ("s232_steel_deriv_2025_03b.csv", R3, "(n) The rates of duty in heading 9903.81.91",
     "(2) all imported derivative iron or steel products that are classified in the following"),
    ("s232_steel_deriv_2025_06.csv", R3,
     "(2) all imported derivative iron or steel products that are classified in the following",
     "(3) all imported derivative iron or steel products that are classified in the following"),
    ("s232_steel_deriv_2025_08.csv", R3,
     "(3) all imported derivative iron or steel products that are classified in the following",
     "(o) Any importer entering the iron or steel products"),
    ("s232_alum_deriv_2025_03.csv", R3,
     "(j) The rates of duty set forth in heading 9903.85.07",
     "(k) The rates of duty in heading 9903.85.08"),
    ("s232_alum_deriv_2025_0608.csv", R3, "(k) The rates of duty in heading 9903.85.08",
     "(l) Any importer entering the aluminum products"),
    ("s232_copper_2025.csv", R3, "(b) The rates of duty set forth in heading 9903.78.01",
     "(c) Heading 9903.78.02 applies"),
    # Section 232 metals from 2026-04-06 (full value), Rev 21 note 16(c)
    ("s232_metals26_50.csv", R21, "(i) Articles of aluminum:",
     "(vi) Derivative aluminum articles:"),
    ("s232_metals26_50_alst.csv", R21, "(i) Articles of aluminum:", "(v) Articles of copper:"),
    ("s232_metals26_25.csv", R21, "(vi) Derivative aluminum articles:",
     "(ix) Derivative aluminum articles:"),
    ("s232_metals26_25_xi.csv", R21, "(xi) Derivative steel articles:",
     "(d) Headings 9903.82.04 and 9903.82.05 apply"),
    ("s232_metals26_floor15.csv", R21, "(ix) Derivative aluminum articles:",
     "(xi) Derivative steel articles:"),
    # Section 232 sectors, Rev 21
    ("s232_autos_vehicles.csv", R21, "(b) The rates of duty set forth in headings 9903.94.01",
     "(c) Heading 9903.94.02 applies to"),
    ("s232_autos_parts.csv", R21, "(g) Subject to a manufacturer's import adjustment offset",
     "(h) Heading 9903.94.06 applies to"),
    ("s232_lumber_softwood.csv", R21, "(b) The rates of duty set forth in heading 9903.76.01",
     "(c) Heading 9903.76.02 provides"),
    ("s232_lumber_upholstered.csv", R21, "(d) The rates of duty set forth in headings 9903.76.02",
     "(e) Except for as provided by heading 9903.76.04"),
    ("s232_lumber_cabinets.csv", R21, "(f) Except for as provided by heading 9903.76.04, the rates",
     "(g) Heading 9903.76.04 applies"),
    ("s232_trucks_vehicles.csv", R21, "(b) The rate of duty set forth in heading 9903.74.01",
     "(c) Heading 9903.74.02 applies"),
    ("s232_trucks_buses.csv", R21, "(c) Heading 9903.74.02 applies", "(d) Heading 9903.74.03"),
    ("s232_trucks_parts.csv", R21, "(i) Subject to a manufacturer’s import adjustment offset",
     "(j) Heading 9903.74.09 applies"),
    ("s232_pharma.csv", R21, "(c) The headings provided in subdivision (a) of this note and the",
     "(i) “Pharmaceutical articles” refers to"),
    ("s232_drones.csv", R21, "(c) Headings 9903.08.21–9903.08.26 apply",
     "(d) Headings 9903.08.23 and 9903.08.24"),
    ("s232_uk_aircraft.csv", R21, "(a) As provided in heading 9903.96.01",
     "(b) As provided in heading 9903.96.02"),
    # Section 122 surcharge exemptions (note 2(aa)), Rev 21
    ("s122_exempt_annex.csv", R21, "(ii) As provided in heading 9903.03.03",
     "(iii) As provided in heading 9903.03.04"),
    ("s122_exempt_particular.csv", R21, "(iii) As provided in heading 9903.03.04",
     "(iv) As provided in heading 9903.03.05"),
    ("s122_exempt_aircraft.csv", R21, "(iv) As provided in heading 9903.03.05",
     "(v) As provided in heading 9903.03.06"),
    # Section 301 China four-year review (note 31), Rev 21
    ("s301_cn_4yr_25_2024.csv", R21, "(b) Heading 9903.91.01 applies", "(c) Heading 9903.91.02"),
    ("s301_cn_4yr_50_2024.csv", R21, "(c) Heading 9903.91.02 applies", "(d) Heading 9903.91.03"),
    ("s301_cn_4yr_100_2024.csv", R21, "(d) Heading 9903.91.03 applies", "(e) Heading 9903.91.04"),
    ("s301_cn_4yr_25_2024_masks.csv", R21, "(e) Heading 9903.91.04 applies",
     "(i) Heading 9903.91.05"),
    ("s301_cn_4yr_50_2025.csv", R21, "(i) Heading 9903.91.05 applies",
     "(ii) The additional rate of duty under heading 9903.91.05"),
    ("s301_cn_4yr_25_2026.csv", R21, "(g) Heading 9903.91.06 applies", "(h) Heading 9903.91.07"),
    ("s301_cn_4yr_50_2026.csv", R21, "(h) Heading 9903.91.07 applies", "(i) Heading 9903.91.08"),
    ("s301_cn_4yr_100_2026.csv", R21, "(i) Heading 9903.91.08 applies", "(j) Heading 9903.91.11"),
    ("s301_cn_4yr_25_2025.csv", R21, "(j) Heading 9903.91.11 applies",
     "(k)\n(i) Heading 9903.91.12"),
    # Section 301 Brazil (note 50) and forced labor (note 52), Rev 21
    ("s301_brazil_exempt.csv", R21, "(ii) As provided in heading 9903.05.03",
     "(iv) As provided in heading 9903.05.05"),
    ("s301_brazil_aircraft_pharma.csv", R21, "(iv) As provided in heading 9903.05.05",
     "(vi) As provided in heading 9903.05.07"),
    ("s301_fl_exempt.csv", R21, f"(b) As provided in heading 9903.05.86, {_N52}",
     "(g) As provided in heading 9903.05.93"),
    # Section 338 Canada (note 51), Rev 21
    ("s338_ca_list1.csv", R21, "(1) Heading 9903.03.12 applies", "(2) Heading 9903.03.13"),
    ("s338_ca_list2.csv", R21, "(2) Heading 9903.03.13 applies", "(3) Heading 9903.03.14"),
    ("s338_ca_list3.csv", R21, "(3) Heading 9903.03.14 applies",
     "(c) As provided in heading 9903.03.15"),
]  # fmt: skip


def run() -> None:
    hs10 = set(pl.read_parquet(HS10_CODES, columns=["hs10"])["hs10"])
    valid = prefix_index(hs10)
    texts = {r: chapter99_text(r) for r in {s[1] for s in SPECS}}
    LISTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, release, start, end in SPECS:
        codes, unmatched = note_codes(block(texts[release], start, end), valid)
        if not codes:
            raise ValueError(f"{name}: no codes found")
        pl.DataFrame({"hs": codes}).write_csv(LISTS_DIR / name)
        extra = LISTS_DIR / name.replace(".csv", "_unmatched.csv")
        if unmatched:
            pl.DataFrame({"hs": unmatched}).write_csv(extra)
        elif extra.exists():
            extra.unlink()
        print(f"{name}: {len(codes):,} codes" + (f" ({len(unmatched)} unmatched)" if unmatched
                                                  else ""))  # fmt: skip
    split_aluminum_derivatives()


def split_aluminum_derivatives() -> None:
    """Note 19(k) lists the 2025-06-23 and 2025-08-18 aluminum derivative additions together;
    the June ones are the appliance codes also listed for steel in note 16(n)(2)."""
    alum = pl.read_csv(LISTS_DIR / "s232_alum_deriv_2025_0608.csv", infer_schema=False)["hs"]
    june = set(pl.read_csv(LISTS_DIR / "s232_steel_deriv_2025_06.csv", infer_schema=False)["hs"])
    for name, keep in [("s232_alum_deriv_2025_06.csv", True),
                       ("s232_alum_deriv_2025_08.csv", False)]:  # fmt: skip
        codes = [c for c in alum if (c in june) == keep]
        pl.DataFrame({"hs": codes}).write_csv(LISTS_DIR / name)
        print(f"{name}: {len(codes):,} codes")
    (LISTS_DIR / "s232_alum_deriv_2025_0608.csv").unlink()


if __name__ == "__main__":
    run()
