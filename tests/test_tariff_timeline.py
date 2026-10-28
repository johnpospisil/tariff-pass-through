"""Tests for the tariff timeline schema and validator (P07)."""

import csv
from datetime import date
from pathlib import Path

import pytest

from tpt.build import tariff_timeline as tt

HS10 = {"7208100000", "7208250000", "8471300100", "8471500150", "6110200010", "0101210010"}
COUNTRIES = {"5700", "5520", "1220", "2010"}


def row(**overrides) -> dict:
    base = {
        "action_id": "S232-STEEL-2018",
        "action_group": "S232-STEEL",
        "authority": "S232",
        "country_iso": "ALL",
        "cty_code": "ALL",
        "exclude_cty_codes": "",
        "hs_scope": "7208",
        "hs_exclude": "",
        "rate_type": "ad_valorem",
        "rate": "0.25",
        "specific_rate": "",
        "specific_unit": "",
        "effective_date": "2018-03-23",
        "end_date": "",
        "supersedes": "",
        "stacking": "cumulative",
        "exclusions_ref": "",
        "legal_status": "in_effect",
        "source_type": "proclamation",
        "source_citation": "Proclamation 9705, 83 FR 11625",
        "source_url": "https://www.federalregister.gov/d/2018-05478",
        "verified_on": "2026-10-28",
        "notes": "",
    }
    return base | overrides


def write(tmp_path: Path, rows: list[dict], lists: dict[str, list[str]] | None = None) -> Path:
    path = tmp_path / "tariff_actions.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tt.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    for name, codes in (lists or {}).items():
        lp = tmp_path / "hs_lists" / name
        lp.parent.mkdir(exist_ok=True)
        lp.write_text("hs\n" + "\n".join(codes) + "\n")
    return path


def errors(tmp_path, rows, lists=None) -> list[str]:
    path = write(tmp_path, rows, lists)
    return tt.validate_file(path, hs10_codes=HS10, cty_codes=COUNTRIES)


# --- schema ------------------------------------------------------------------


def test_header_matches_columns():
    assert tt.COLUMNS[0] == "action_id"
    assert len(set(tt.COLUMNS)) == len(tt.COLUMNS)


def test_valid_row_passes(tmp_path):
    assert errors(tmp_path, [row()]) == []


@pytest.mark.parametrize("field", ["source_citation", "source_url", "verified_on"])
def test_citation_fields_required(tmp_path, field):
    errs = errors(tmp_path, [row(**{field: ""})])
    assert any(field in e for e in errs)


def test_source_url_must_be_official_https(tmp_path):
    assert errors(tmp_path, [row(source_url="http://www.federalregister.gov/x")])
    assert errors(tmp_path, [row(source_url="https://someblog.example.com/tariffs")])
    assert errors(tmp_path, [row(source_url="https://www.cbp.gov/trade/csms")]) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("effective_date", "2018-13-01"),
        ("end_date", "March 2019"),
        ("verified_on", "yesterday"),
        ("authority", "SECTION_9000"),
        ("rate_type", "percent"),
        ("legal_status", "maybe"),
        ("source_type", "blog"),
        ("rate", "25%"),
        ("rate", "-0.1"),
        ("stacking", "sometimes"),
        ("ch99_heading", "9903.88"),
        ("ch99_heading", "7208.10.00"),
    ],
)
def test_bad_values_rejected(tmp_path, field, value):
    assert errors(tmp_path, [row(**{field: value})])


def test_ch99_headings(tmp_path):
    assert errors(tmp_path, [row(ch99_heading="9903.80.01")]) == []
    assert errors(tmp_path, [row(ch99_heading="9903.88.01;9903.88.15")]) == []


def test_end_date_after_effective_date(tmp_path):
    assert errors(tmp_path, [row(end_date="2018-03-01")])
    assert errors(tmp_path, [row(end_date="2019-01-01")]) == []


def test_verified_on_not_in_future(tmp_path):
    assert errors(tmp_path, [row(verified_on="2999-01-01")])


def test_action_ids_unique(tmp_path):
    assert errors(tmp_path, [row(), row()])


def test_specific_rate_needs_unit(tmp_path):
    bad = row(rate_type="specific", rate="", specific_rate="1.5", specific_unit="")
    assert errors(tmp_path, [bad])
    ok = row(rate_type="specific", rate="", specific_rate="1.5", specific_unit="kg")
    assert errors(tmp_path, [ok]) == []


def test_stacking_not_with_names_known_authorities(tmp_path):
    assert errors(tmp_path, [row(stacking="not_with:S232,IEEPA_FENTANYL")]) == []
    assert errors(tmp_path, [row(stacking="not_with:S999")])


# --- countries ---------------------------------------------------------------


def test_unknown_census_country_rejected(tmp_path):
    assert errors(tmp_path, [row(country_iso="ZZ", cty_code="9999")])
    assert errors(tmp_path, [row(country_iso="CN", cty_code="5700")]) == []


def test_iso_census_pairs_consistent(tmp_path):
    rows = [
        row(action_id="A", country_iso="CN", cty_code="5700"),
        row(action_id="B", country_iso="CN", cty_code="5520", hs_scope="8471"),
    ]
    assert any("CN" in e for e in errors(tmp_path, rows))


def test_exclude_countries_only_with_all(tmp_path):
    assert errors(tmp_path, [row(exclude_cty_codes="1220;2010")]) == []
    assert errors(tmp_path, [row(country_iso="CN", cty_code="5700", exclude_cty_codes="1220")])


# --- HS scope ----------------------------------------------------------------


@pytest.mark.parametrize("scope", ["72", "7208", "720810", "72081000", "7208100000", "72;8471"])
def test_hs_prefixes_resolve(tmp_path, scope):
    assert errors(tmp_path, [row(hs_scope=scope)]) == []


@pytest.mark.parametrize("scope", ["7209", "720", "72x8", "", "84713001009"])
def test_bad_or_unresolvable_hs_rejected(tmp_path, scope):
    assert errors(tmp_path, [row(hs_scope=scope)])


def test_hs_scope_all(tmp_path):
    assert errors(tmp_path, [row(hs_scope="ALL", hs_exclude="7208")]) == []


def test_hs_list_file_resolves(tmp_path):
    ok = errors(tmp_path, [row(hs_scope="file:hs_lists/list1.csv")],
                {"list1.csv": ["72081000", "84713001"]})  # fmt: skip
    assert ok == []
    missing = errors(tmp_path, [row(hs_scope="file:hs_lists/nope.csv")])
    assert any("nope.csv" in e for e in missing)
    bad = errors(tmp_path, [row(hs_scope="file:hs_lists/list2.csv")],
                 {"list2.csv": ["72081000", "99999999"]})  # fmt: skip
    assert any("99999999" in e for e in bad)


def test_expand_scope():
    assert tt.expand_scope("72;8471", Path(".")) == {"72", "8471"}


# --- overlaps ----------------------------------------------------------------


def test_overlap_same_authority_country_hs_dates_rejected(tmp_path):
    rows = [
        row(action_id="A", hs_scope="7208", effective_date="2018-03-23"),
        row(action_id="B", hs_scope="720810", effective_date="2018-06-01", rate="0.5"),
    ]
    assert any("overlap" in e for e in errors(tmp_path, rows))


def test_overlap_allowed_with_supersedes(tmp_path):
    rows = [
        row(action_id="A", hs_scope="7208", effective_date="2018-03-23"),
        row(
            action_id="B", hs_scope="7208", effective_date="2025-06-04", rate="0.5", supersedes="A"
        ),  # fmt: skip
    ]
    assert errors(tmp_path, rows) == []


def test_supersedes_accepts_several_ids(tmp_path):
    rows = [
        row(action_id="A", hs_scope="7208", end_date="2019-05-20"),
        row(action_id="B", hs_scope="7208", effective_date="2019-05-20", rate="0.1"),
        row(
            action_id="T",
            hs_scope="7208",
            country_iso="CN",
            cty_code="5700",
            rate="0.5",
            effective_date="2018-08-13",
            end_date="2019-05-21",
            supersedes="A;B",
        ),  # fmt: skip
    ]
    assert errors(tmp_path, rows) == []
    rows[2]["supersedes"] = "A"
    assert any("overlap" in e for e in errors(tmp_path, rows))


def test_partial_products_split_by_hs10_exclusions_do_not_overlap(tmp_path):
    codes = HS10 | {"8517620010", "8517620020", "8517620090"}
    rows = [
        row(action_id="L3", authority="S301", country_iso="CN", cty_code="5700",
            hs_scope="85176200", hs_exclude="8517620090"),
        row(action_id="L4", authority="S301", country_iso="CN", cty_code="5700",
            hs_scope="85176200", hs_exclude="8517620010;8517620020", rate="0.15"),
    ]  # fmt: skip
    path = write(tmp_path, rows)
    assert tt.validate_file(path, hs10_codes=codes, cty_codes=COUNTRIES) == []
    rows[1]["hs_exclude"] = "8517620010"
    path = write(tmp_path, rows)
    assert any(
        "overlap" in e for e in tt.validate_file(path, hs10_codes=codes, cty_codes=COUNTRIES)
    )


def test_supersedes_must_reference_existing_action(tmp_path):
    assert errors(tmp_path, [row(supersedes="NOPE")])


def test_no_overlap_when_dates_disjoint_or_scopes_differ(tmp_path):
    rows = [
        row(action_id="A", hs_scope="7208", end_date="2019-05-20"),
        row(action_id="B", hs_scope="7208", effective_date="2019-05-20", rate="0.1"),
        row(action_id="C", hs_scope="8471", effective_date="2018-06-01"),
        row(
            action_id="D",
            hs_scope="7208",
            country_iso="CN",
            cty_code="5700",
            exclude_cty_codes="",
            authority="S301",
            effective_date="2018-07-06",
        ),  # fmt: skip
    ]
    assert errors(tmp_path, rows) == []


def test_overlap_detected_between_all_and_specific_country(tmp_path):
    rows = [
        row(action_id="A", hs_scope="7208"),
        row(action_id="B", hs_scope="7208", country_iso="CN", cty_code="5700", rate="0.5"),
    ]
    assert any("overlap" in e for e in errors(tmp_path, rows))


def test_excluded_country_does_not_overlap(tmp_path):
    rows = [
        row(action_id="A", hs_scope="7208", exclude_cty_codes="1220"),
        row(action_id="B", hs_scope="7208", country_iso="CA", cty_code="1220", rate="0.1"),
    ]
    assert errors(tmp_path, rows) == []


# --- loading -----------------------------------------------------------------


def test_load_actions_types(tmp_path):
    path = write(tmp_path, [row(end_date="2019-01-01")])
    (a,) = tt.load_actions(path)
    assert a.rate == pytest.approx(0.25)
    assert a.effective_date == date(2018, 3, 23)
    assert a.end_date == date(2019, 1, 1)
    assert a.stacking == "cumulative"


def test_reference_file_validates():
    """The committed timeline must always pass validation (empty until P08/P09)."""
    assert tt.ACTIONS_CSV.exists()
    assert tt.validate_file(tt.ACTIONS_CSV) == []
