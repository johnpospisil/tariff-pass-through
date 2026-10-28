"""Checks on the 2024-26 rows of tariff_actions.csv (P09), against figures stated in the orders."""

from datetime import date

import pytest

from tpt.build import tariff_timeline as tt

ACTIONS = {a.action_id: a for a in tt.load_actions()}


def get(action_id: str) -> tt.TariffAction:
    return ACTIONS[action_id]


@pytest.mark.parametrize(
    ("action_id", "rate", "start", "end"),
    [
        # EO 14326 Annex I, as reproduced in HTSUS 9903.02.xx
        ("IEEPA-RECIP-VN", 0.20, "2025-08-07", "2026-02-24"),
        ("IEEPA-RECIP-IN", 0.25, "2025-08-07", "2026-02-24"),
        ("IEEPA-RECIP-BR", 0.10, "2025-08-07", "2026-02-24"),
        ("IEEPA-RECIP-CH", 0.39, "2025-08-07", "2025-11-14"),
        ("IEEPA-RECIP-LA", 0.40, "2025-08-07", "2026-02-24"),
        ("IEEPA-RECIP-SY", 0.41, "2025-08-07", "2026-02-24"),
        ("IEEPA-RECIP-CN-125", 1.25, "2025-04-10", "2025-05-14"),
        ("IEEPA-RECIP-BASE", 0.10, "2025-04-05", "2026-02-24"),
        ("IEEPA-FENT-CN-20", 0.20, "2025-03-04", "2025-11-10"),
        ("IEEPA-FENT-CA-35", 0.35, "2025-08-01", "2026-02-24"),
        ("IEEPA-BR-40-A", 0.40, "2025-08-06", "2025-11-13"),
        ("IEEPA-IN-RUOIL", 0.25, "2025-08-27", "2026-02-07"),
        ("S232-STEEL-50", 0.50, "2025-06-04", "2026-04-06"),
        ("S232-COPPER-50", 0.50, "2025-08-01", "2026-04-06"),
        ("S122-10", 0.10, "2026-02-24", "2026-07-24"),
        ("S301-FL-CN", 0.125, "2026-07-24", None),
        ("S301-FL-CA", 0.10, "2026-07-24", None),
        ("S301-BR-25", 0.25, "2026-07-22", None),
        ("S338-CA-1", 0.50, "2026-08-22", None),
    ],
)
def test_rates_and_dates_match_orders(action_id, rate, start, end):
    a = get(action_id)
    assert a.rate == pytest.approx(rate)
    assert a.effective_date == date.fromisoformat(start)
    assert a.end_date == (date.fromisoformat(end) if end else None)


def test_ieepa_rows_struck_down_and_ended_by_collection_stop():
    ieepa = [a for a in ACTIONS.values() if a.authority.startswith("IEEPA")]
    assert len(ieepa) > 80
    assert all(a.legal_status == "struck_down" for a in ieepa)
    assert all(a.end_date and a.end_date <= date(2026, 2, 24) for a in ieepa)


def test_deal_floors_are_all_in():
    for i in ["IEEPA-RECIP-EU-B", "IEEPA-RECIP-JP-A", "IEEPA-RECIP-KR-B", "S301-FL-EU27",
              "S232-AUTOS-VEH-JP", "S232-METALS26-FLOOR15"]:  # fmt: skip
        assert get(i).rate_type == "all_in_floor", i
    assert get("S301-FL-JP").rate == pytest.approx(0.125)


def test_forced_labor_covers_the_60_investigations():
    fl = [a for a in ACTIONS.values() if a.action_group == "S301-FL"]
    # 60 investigations: the EU counts once; Nauru-style gaps would show up here
    assert len(fl) == 60
    assert {a.country_iso for a in fl if a.rate == pytest.approx(0.10) and
            a.rate_type == "ad_valorem"} == {
        "AR", "BD", "KH", "CA", "EC", "SV", "GT", "HN", "IN", "ID", "JO", "MY", "MX", "PK", "LK",
        "GB", "TT"}  # fmt: skip


def test_future_rows_are_scheduled():
    for a in ACTIONS.values():
        if a.effective_date > date(2026, 10, 28):
            assert a.legal_status == "scheduled", a.action_id


def test_p08_rows_closed_when_2025_actions_replaced_them():
    for i in ["S232-STEEL-6", "S232-ALUM-6", "S232-STEELDER-4", "S232-ALUMDER-3"]:
        assert get(i).end_date == date(2025, 3, 12)


def test_every_2025_row_cites_the_federal_register():
    for a in ACTIONS.values():
        if a.effective_date >= date(2024, 9, 1):
            assert a.source_url.startswith("https://www.federalregister.gov/d/"), a.action_id
