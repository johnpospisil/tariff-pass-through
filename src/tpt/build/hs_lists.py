"""Product lists and country groups for the 2018-19 tariff actions (P08).

Source: Harmonized Tariff Schedule of the United States, Chapter 99 (official PDF from
hts.usitc.gov). The Federal Register annexes for these actions are published as images, so the
HTSUS notes that implement them are used instead:

- Section 301 (China), subchapter III U.S. note 20, 2020 Basic Edition, plus codes created after
  2020 (HS2022 renumbering) as listed in note 20 of 2026 HTS Revision 21:
    20(b) heading 9903.88.01 (List 1), 20(d) 9903.88.02 (List 2), 20(f) 9903.88.03 (List 3),
    20(g) 9903.88.04 (List 3 products defined as an HTS8 except named 10-digit lines),
    20(s) 9903.88.15 (List 4A: (i) HTS8 table, (ii) partial products).
- Section 201 exempt countries: note 17(b) (washers), note 18(b) (solar), 2020 Basic Edition.
- Section 232 product scopes are written out below from notes 16(b) and 19(b) (2020 Basic) and the
  derivative notes for headings 9903.80.03 and 9903.85.03 (2021 Basic Edition).

Run: make hs-lists   (writes data/reference/hs_lists/*.csv and data/reference/country_groups.csv)
"""

import re

import polars as pl
from pypdf import PdfReader

from tpt import config
from tpt.ingest._http import CachedClient, Source

HTS_FILE = "https://hts.usitc.gov/reststop/file"
SOURCE = Source("usitc", 1.0)
LISTS_DIR = config.REFERENCE_DIR / "hs_lists"
GROUPS_CSV = config.REFERENCE_DIR / "country_groups.csv"
COUNTRIES_CSV = config.REFERENCE_DIR / "census_countries.csv"
HS10_CODES = config.INTERIM_DIR / "hs10_codes.parquet"

RELEASE_2020 = "2020HTSABasicB"
# The 2020 notes predate the HS2022 renumbering; codes created later are taken from the current
# notes (P11: e.g. 8543.40.00 e-cigarettes, split from List 2's 8543.70.99, pays 25% in the data).
RELEASE_CURRENT = "2026HTSRev21"
BASE_YEAR = 2020
# 20(s)(ii) names 8517.62.00 except .0010/.0020 (2020 numbering); 8517.62.0050 was discontinued at
# the end of 2018, before List 4A (2019-09-01), and is covered by List 3 only.
L4A_EXTRA_EXCLUDE = ["8517620050"]

# Section 232 scopes (HS prefixes), from the notes cited in the module docstring. Note 16(b) names
# subheading 7302.90.00; the statistics split it into 10-digit lines under 7302.90, hence "730290".
S232_STEEL = (
    ["7206", "7207", "7208", "7209", "7210", "7211", "7212", "7213", "7214", "7215", "7216",
     "7217", "7218", "7219", "7220", "7221", "7222", "7223", "7224", "7225", "7226", "7227",
     "7228", "7229", "73011000", "730210", "73024000", "730290", "7304", "7305", "7306"]
)  # fmt: skip
S232_STEEL_EXCLUDE = ["72166100", "72166900", "72169100"]
S232_ALUMINUM = ["7601", "7604", "7605", "7606", "7607", "7608", "7609", "76169951"]
# Proclamation 9980 derivatives. 8708.10.30 and 8708.29.21 were split into steel and aluminum
# statistical lines only in 2021; the pre-2021 lines (..3010, ..2100) are assigned to steel.
S232_STEEL_DERIV = ["73170030", "7317005503", "7317005505", "7317005507", "7317005560",
                    "7317005580", "7317006560", "8708103010", "8708103020", "8708292100",
                    "8708292120"]  # fmt: skip
S232_ALUMINUM_DERIV = ["76141050", "76149020", "76149040", "76149050", "8708103030",
                       "8708292130"]  # fmt: skip

EU28 = ["AUSTRIA", "BELGIUM", "BULGARIA", "CROATIA", "CYPRUS", "CZECH REPUBLIC", "DENMARK",
        "ESTONIA", "FINLAND", "FRANCE", "GERMANY", "GREECE", "HUNGARY", "IRELAND", "ITALY",
        "LATVIA", "LITHUANIA", "LUXEMBOURG", "MALTA", "NETHERLANDS", "POLAND", "PORTUGAL",
        "ROMANIA", "SLOVAKIA", "SLOVENIA", "SPAIN", "SWEDEN", "UNITED KINGDOM"]  # fmt: skip
NAME_FIXES = {
    "BURMA": "BURMA", "CAPE VERDE": "CABO VERDE", "CONGO (BRAZZAVILLE)": "CONGO",
    "CONGO (KINSHASA)": "DEMOCRATIC REPUBLIC OF THE CONGO", "CÔTE D’IVOIRE": "COTE D'IVOIRE",
    "COTE D’IVOIRE": "COTE D'IVOIRE", "THE GAMBIA": "GAMBIA", "SAINT LUCIA": "ST LUCIA",
    "SAINT VINCENT AND THE GRENADINES": "ST VINCENT AND THE GRENADINES",
    "SAO TOMÉ AND PRINCIPE": "SAO TOME AND PRINCIPE", "SOLOMON ISLAND": "SOLOMON ISLANDS",
    "SWAZILAND [ESWATINI]": "ESWATINI", "YEMEN (REPUBLIC OF)": "YEMEN",
}  # fmt: skip


# --- HTS text ----------------------------------------------------------------


def chapter99_text(release: str, client: CachedClient | None = None) -> str:
    client = client or CachedClient(SOURCE)
    resp = client.get(HTS_FILE, {"release": release, "filename": "Chapter 99"})
    reader = PdfReader(resp.path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


def table_hts8(text: str) -> list[str]:
    """HTS8 numbers from a note table; the PDF text runs them together ('0101.90.300101.30.00')."""
    seen: dict[str, None] = {}
    for a, b, c in re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", text):
        if not a.startswith(("98", "99")):
            seen.setdefault(a + b + c, None)
    return list(seen)


def partial_items(text: str) -> tuple[list[str], list[str]]:
    """'... provided for in [subheading] 8517.62.00, except ... 8517.62.0090' items ->
    (HTS8 included, HTS10 excluded). The PDF text can break lines inside 'provided for in'."""
    include, exclude = [], []
    for item in re.split(r"\n\s*\d+\.\s", text)[1:]:
        m = re.search(
            r"provided\s+for\s+in\s+(?:\[subheading\]\s+|subheading\s+)?(\d{4})\.(\d{2})\.(\d{2})",
            item,
        )
        if not m:
            continue
        include.append("".join(m.groups()))
        tail = item[m.end() :]
        for a, b, c in re.findall(r"(\d{4})\.(\d{2})\.(\d{4,5})", tail):
            # note 20(s)(ii) prints "9401.71.00031" for statistical number 9401.71.0031
            exclude.append(a + b + (c[1:] if len(c) == 5 and c[0] == "0" else c[:4]))
    return include, exclude


def section_301_lists(text: str) -> dict[str, list[str]]:
    n20 = text[text.index("20. (a) For the purposes of heading 9903.88.01") :]
    list1 = between(
        n20, "(b) Heading 9903.88.01 applies", "(c) For the purposes of heading 9903.88.02"
    )
    list2 = between(
        n20, "(d) Heading 9903.88.02 applies", "(e) For the purposes of heading 9903.88.03"
    )
    list3 = between(
        n20, "(f) Heading 9903.88.03 applies", "(g) For the purposes of heading 9903.88.04"
    )
    l3_partial = between(
        n20, "(g) For the purposes of heading 9903.88.04", "(h) The U.S. Trade Representative"
    )
    l4a = between(
        n20, "(s) Heading 9903.88.15 applies", "(t) For the purposes of heading 9903.88.16"
    )
    l4a_table, l4a_partial = l4a.split("(ii) the following products of China", 1)
    l3_inc, l3_exc = partial_items(l3_partial)
    l4_inc, l4_exc = partial_items(l4a_partial)
    return {
        "s301_cn_list1.csv": table_hts8(list1),
        "s301_cn_list2.csv": table_hts8(list2),
        "s301_cn_list3.csv": table_hts8(list3) + l3_inc,
        "s301_cn_list3_exclude.csv": l3_exc,
        "s301_cn_list4a.csv": table_hts8(l4a_table) + l4_inc,
        "s301_cn_list4a_exclude.csv": l4_exc + L4A_EXTRA_EXCLUDE,
    }  # fmt: skip


def country_list(text: str, start: str) -> list[str]:
    """Country names in a '... the following developing countries ...: A, B, ... and Z.' note."""
    block = text[text.index(start) :]
    block = block[block.index(":", block.index("developing countries")) + 1 :]
    block = re.sub(r"\s+", " ", block[: block.index(".")])
    names = [n.strip() for n in block.split(",") if n.strip()]
    names[-1:] = names[-1].split(" and ")  # only the final "X and Y" separates two names
    return [n.strip() for n in names]


# --- country groups ----------------------------------------------------------


def census_codes(names: list[str], countries: pl.DataFrame) -> list[tuple[str, str]]:
    lookup = dict(zip(countries["cty_name"], countries["cty_code"], strict=True))
    out, missing = [], []
    for name in names:
        key = NAME_FIXES.get(name.upper(), name.upper())
        if key in lookup:
            out.append((lookup[key], key))
        else:
            missing.append(name)
    if missing:
        raise ValueError(f"no Census code for: {missing}")
    return out


def country_groups(text: str) -> pl.DataFrame:
    countries = pl.read_csv(COUNTRIES_CSV, infer_schema=False).filter(
        pl.col("is_individual") == "true"
    )
    washers = ["Canada"] + country_list(text, "the application of subheadings 9903.45.01 through")
    solar = country_list(text, "the application of subheadings 9903.45.21 through")
    groups = {
        "EU28": (EU28, "EU member states 2018-01-31 to 2020-01-31 (incl. UK)"),
        "EU27": ([n for n in EU28 if n != "UNITED KINGDOM"], "EU member states from 2020-02-01"),
        "S201_WASHERS_EXEMPT": (washers, "HTSUS ch. 99 subch. III note 17(b), 2020 Basic"),
        "S201_SOLAR_EXEMPT": (solar, "HTSUS ch. 99 subch. III note 18(b), 2020 Basic"),
    }
    rows = []
    for group, (names, source) in groups.items():
        rows += [(group, code, name, source) for code, name in census_codes(names, countries)]
    return pl.DataFrame(rows, schema=["group", "cty_code", "cty_name", "source"], orient="row")


# --- run ---------------------------------------------------------------------


def later_codes(codes: list[str], code_years: dict[str, set[int]], base_year: int) -> list[str]:
    """Codes none of whose HS10 lines existed in or before base_year (created by later
    renumberings), in input order."""
    old = {c[:n] for c, ys in code_years.items() if min(ys) <= base_year for n in (4, 6, 8, 10)}
    new = {c[:n] for c, ys in code_years.items() if min(ys) > base_year for n in (4, 6, 8, 10)}
    return [c for c in codes if c in new and c not in old]


def section_301_hs2022(base: dict[str, list[str]], current: dict[str, list[str]],
                       code_years: dict[str, set[int]]) -> dict[str, list[str]]:  # fmt: skip
    """2020 lists extended with the codes in the current notes created after BASE_YEAR."""
    return {name: codes + later_codes(current[name], code_years, BASE_YEAR)
            for name, codes in base.items()}  # fmt: skip


def write_list(name: str, codes: list[str], hs10: set[str]) -> None:
    """Write a list; codes matching no HS10 in the 2017+ statistics (e.g. monetary gold, which is
    outside trade statistics) go to <name>_unmatched.csv so the legal list stays visible."""
    LISTS_DIR.mkdir(parents=True, exist_ok=True)
    prefixes = {c[:n] for c in hs10 for n in (2, 4, 6, 8, 10)}
    codes = list(dict.fromkeys(codes))
    matched = [c for c in codes if c in prefixes]
    unmatched = [c for c in codes if c not in prefixes]
    pl.DataFrame({"hs": matched}).write_csv(LISTS_DIR / name)
    extra = LISTS_DIR / name.replace(".csv", "_unmatched.csv")
    if unmatched:
        pl.DataFrame({"hs": unmatched}).write_csv(extra)
        print(
            f"  {name}: {len(unmatched)} code(s) not in trade statistics "
            f"-> {extra.name}: {unmatched}"
        )
    elif extra.exists():
        extra.unlink()


def run() -> None:
    text = chapter99_text(RELEASE_2020)
    years = pl.read_parquet(HS10_CODES, columns=["year", "hs10"]).group_by("hs10").agg("year")
    code_years = {h: set(y) for h, y in years.iter_rows()}
    s301 = section_301_hs2022(
        section_301_lists(text), section_301_lists(chapter99_text(RELEASE_CURRENT)), code_years
    )
    lists = s301 | {
        "s232_steel.csv": S232_STEEL,
        "s232_steel_exclude.csv": S232_STEEL_EXCLUDE,
        "s232_aluminum.csv": S232_ALUMINUM,
        "s232_steel_derivatives.csv": S232_STEEL_DERIV,
        "s232_aluminum_derivatives.csv": S232_ALUMINUM_DERIV,
    }
    hs10 = set(pl.read_parquet(HS10_CODES, columns=["hs10"])["hs10"])
    for name, codes in lists.items():
        write_list(name, codes, hs10)
        print(f"{name}: {len(set(codes)):,} codes")
    groups = country_groups(text)
    groups.write_csv(GROUPS_CSV)
    print("country groups:", dict(groups.group_by("group").len().sort("group").iter_rows()))


if __name__ == "__main__":
    run()
