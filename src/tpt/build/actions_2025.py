"""2024-26 rows of data/reference/tariff_actions.csv (P09).

The 2025-26 actions run to several hundred rows (one per country for the reciprocal and
forced-labor schedules), so they are written by this module instead of by hand. Every row cites
the order that sets its rate and dates (Federal Register document, verified through the
Federal Register API on VERIFIED_ON). Country rate schedules are parsed from the official
HTSUS Chapter 99 heading tables, which reproduce the orders' annexes (the Federal Register
annexes are images); product lists come from hs_lists_2025.

Running this module replaces the rows of the action groups it generates that take effect on or
after GENERATED_FROM, and keeps every other row (the 2018-19 validation set from P08), closing or
amending the P08 rows that the 2025 actions changed.

Run: make timeline-2025   (then make timeline-validate)
"""

import csv
from datetime import date

from tpt.build import hs_lists_2025 as h25
from tpt.build import tariff_timeline as tt
from tpt.build.hs_lists import chapter99_text

VERIFIED_ON = "2026-10-28"
GENERATED_FROM = "2024-09-01"  # rows from this effective date on are written by this module

# ISO alpha-2 and Census code for every country named in the 2025-26 schedules.
COUNTRIES = {
    "Afghanistan": ("AF", "5310"), "Algeria": ("DZ", "7210"), "Angola": ("AO", "7620"),
    "Argentina": ("AR", "3570"), "Australia": ("AU", "6021"), "Bahamas": ("BS", "2360"),
    "Bahrain": ("BH", "5250"), "Bangladesh": ("BD", "5380"), "Bolivia": ("BO", "3350"),
    "Bosnia and Herzegovina": ("BA", "4793"), "Botswana": ("BW", "7930"),
    "Brazil": ("BR", "3510"), "Brunei": ("BN", "5610"), "Cambodia": ("KH", "5550"),
    "Cameroon": ("CM", "7420"), "Canada": ("CA", "1220"), "Chad": ("TD", "7560"),
    "Chile": ("CL", "3370"), "China": ("CN", "5700"), "Colombia": ("CO", "3010"),
    "Costa Rica": ("CR", "2230"), "Côte d’Ivoire": ("CI", "7480"),
    "Democratic Republic of the Congo": ("CD", "7660"), "Dominican Republic": ("DO", "2470"),
    "Ecuador": ("EC", "3310"), "Egypt": ("EG", "7290"), "El Salvador": ("SV", "2110"),
    "Equatorial Guinea": ("GQ", "7380"), "Falkland Islands": ("FK", "3720"),
    "Fiji": ("FJ", "6863"), "Ghana": ("GH", "7490"), "Guatemala": ("GT", "2050"),
    "Guyana": ("GY", "3120"), "Honduras": ("HN", "2150"), "Hong Kong": ("HK", "5820"),
    "Iceland": ("IS", "4000"), "India": ("IN", "5330"), "Indonesia": ("ID", "5600"),
    "Iraq": ("IQ", "5050"), "Israel": ("IL", "5081"), "Japan": ("JP", "5880"),
    "Jordan": ("JO", "5110"), "Kazakhstan": ("KZ", "4634"), "Kuwait": ("KW", "5130"),
    "Laos": ("LA", "5530"), "Lesotho": ("LS", "7990"), "Libya": ("LY", "7250"),
    "Liechtenstein": ("LI", "4411"), "Macau": ("MO", "5660"), "Madagascar": ("MG", "7880"),
    "Malawi": ("MW", "7970"), "Malaysia": ("MY", "5570"), "Mauritius": ("MU", "7850"),
    "Mexico": ("MX", "2010"), "Moldova": ("MD", "4641"), "Morocco": ("MA", "7140"),
    "Mozambique": ("MZ", "7870"), "Myanmar (Burma)": ("MM", "5460"), "Namibia": ("NA", "7920"),
    "New Zealand": ("NZ", "6141"), "Nicaragua": ("NI", "2190"), "Nigeria": ("NG", "7530"),
    "North Macedonia": ("MK", "4794"), "Norway": ("NO", "4039"), "Oman": ("OM", "5230"),
    "Pakistan": ("PK", "5350"), "Papua New Guinea": ("PG", "6040"), "Peru": ("PE", "3330"),
    "Philippines": ("PH", "5650"), "Qatar": ("QA", "5180"), "Russia": ("RU", "4621"),
    "Saudi Arabia": ("SA", "5170"), "Serbia": ("RS", "4801"), "Singapore": ("SG", "5590"),
    "South Africa": ("ZA", "7910"), "South Korea": ("KR", "5800"), "Sri Lanka": ("LK", "5420"),
    "Switzerland": ("CH", "4419"), "Syria": ("SY", "5020"), "Taiwan": ("TW", "5830"),
    "Thailand": ("TH", "5490"), "Trinidad and Tobago": ("TT", "2740"),
    "Tunisia": ("TN", "7230"), "Turkey": ("TR", "4890"), "Türkiye": ("TR", "4890"),
    "Uganda": ("UG", "7780"), "United Arab Emirates": ("AE", "5200"),
    "United Kingdom": ("GB", "4120"), "Uruguay": ("UY", "3550"), "Vanuatu": ("VU", "6224"),
    "Venezuela": ("VE", "3070"), "Vietnam": ("VN", "5520"), "Zambia": ("ZM", "7940"),
    "Zimbabwe": ("ZW", "7960"),
}  # fmt: skip
NOT_IN_TRADE_DATA = {"Nauru"}  # named in the reciprocal schedule; no Census country code


def cty(name: str) -> tuple[str, str]:
    return COUNTRIES[name]


def fr(doc: str) -> str:
    return f"https://www.federalregister.gov/d/{doc}"


def lst(*names: str) -> str:
    return ";".join(f"file:hs_lists/{n}.csv" for n in names)


# Orders: key -> (source_type, citation, Federal Register document number)
SRC = {
    "EO14193": ("executive_order", "EO 14193, 90 FR 9113", "2025-02406"),
    "EO14194": ("executive_order", "EO 14194, 90 FR 9117", "2025-02407"),
    "EO14195": ("executive_order", "EO 14195, 90 FR 9121", "2025-02408"),
    "EO14197": ("executive_order", "EO 14197, 90 FR 9183 (Canada duties delayed to 2025-03-04)",
                "2025-02478"),
    "EO14198": ("executive_order", "EO 14198, 90 FR 9185 (Mexico duties delayed to 2025-03-04)",
                "2025-02479"),
    "EO14228": ("executive_order", "EO 14228, 90 FR 11463", "2025-03775"),
    "EO14231": ("executive_order", "EO 14231, 90 FR 11785", "2025-03990"),
    "EO14232": ("executive_order", "EO 14232, 90 FR 11787", "2025-03991"),
    "EO14256": ("executive_order", "EO 14256, 90 FR 14899", "2025-06027"),
    "EO14257": ("executive_order", "EO 14257, 90 FR 15041", "2025-06063"),
    "EO14259": ("executive_order", "EO 14259, 90 FR 15509", "2025-06378"),
    "EO14266": ("executive_order", "EO 14266, 90 FR 15625", "2025-06462"),
    "EO14289": ("executive_order", "EO 14289, 90 FR 18907", "2025-07835"),
    "EO14298": ("executive_order", "EO 14298, 90 FR 21831", "2025-09297"),
    "EO14309": ("executive_order", "EO 14309, 90 FR 26419", "2025-11473"),
    "EO14323": ("executive_order", "EO 14323, 90 FR 37739", "2025-14896"),
    "EO14324": ("executive_order", "EO 14324, 90 FR 37775", "2025-14897"),
    "EO14325": ("executive_order", "EO 14325, 90 FR 37957", "2025-14999"),
    "EO14326": ("executive_order", "EO 14326, 90 FR 37963", "2025-15010"),
    "EO14329": ("executive_order", "EO 14329, 90 FR 38701", "2025-15267"),
    "EO14345": ("executive_order", "EO 14345, 90 FR 43535", "2025-17389"),
    "EO14357": ("executive_order", "EO 14357, 90 FR 50725", "2025-19825"),
    "EO14358": ("executive_order", "EO 14358, 90 FR 50729", "2025-19826"),
    "EO14360": ("executive_order", "EO 14360, 90 FR 54091", "2025-21203"),
    "EO14361": ("executive_order", "EO 14361, 90 FR 54467", "2025-21417"),
    "EO14384": ("executive_order", "EO 14384, 91 FR 6501", "2026-02818"),
    "EO14388": ("executive_order", "EO 14388, 91 FR 9433", "2026-03829"),
    "EO14389": ("executive_order", "EO 14389, 91 FR 9437", "2026-03832"),
    "JP-NOTICE": ("federal_register", "90 FR 44638 (Commerce, US-Japan Agreement)", "2025-17908"),
    "EU-NOTICE": ("federal_register", "90 FR 46136 (Commerce, US-EU Framework)", "2025-18660"),
    "KR-NOTICE": ("federal_register", "90 FR 55964 (USTR, US-Korea Deal)", "2025-21940"),
    "CH-NOTICE": ("federal_register", "90 FR 59281 (USTR, US-Switzerland-Liechtenstein)",
                  "2025-23316"),
    "TW-NOTICE": ("federal_register", "91 FR 31818 (Commerce, US-Taiwan Agreement)", "2026-10571"),
    "P10895": ("proclamation", "Proclamation 10895, 90 FR 9807", "2025-02832"),
    "P10896": ("proclamation", "Proclamation 10896, 90 FR 9817", "2025-02833"),
    "P10908": ("proclamation", "Proclamation 10908, 90 FR 14705", "2025-05930"),
    "P10947": ("proclamation", "Proclamation 10947, 90 FR 24199", "2025-10524"),
    "BIS-INCL": ("federal_register", "90 FR 40326 (BIS, Section 232 inclusions)", "2025-15819"),
    "P10962": ("proclamation", "Proclamation 10962, 90 FR 37727", "2025-14893"),
    "P10976": ("proclamation", "Proclamation 10976, 90 FR 48127", "2025-19482"),
    "P11000": ("proclamation", "Proclamation 11000, 91 FR 1039", "2026-00327"),
    "P10984": ("proclamation", "Proclamation 10984, 90 FR 48451", "2025-19639"),
    "P11002": ("proclamation", "Proclamation 11002, 91 FR 2443", "2026-01052"),
    "P11012": ("proclamation", "Proclamation 11012, 91 FR 9339", "2026-03824"),
    "P11020": ("proclamation", "Proclamation 11020, 91 FR 18183", "2026-06956"),
    "P11021": ("proclamation", "Proclamation 11021, 91 FR 18201", "2026-06960"),
    "P11032": ("proclamation", "Proclamation 11032, 91 FR 34085", "2026-11314"),
    "P11046": ("proclamation", "Proclamations 11046-11048, 91 FR 46639/46653/46663; effective "
               "date moved to 2026-08-22 by Proclamation 11056, 91 FR 54789", "2026-14991"),
    "P11064": ("proclamation", "Proclamations 11064-11065, 91 FR 58331/58339", "2026-18838"),
    "P11055": ("proclamation", "Proclamation 11055, 91 FR 53699", "2026-16979"),
    "S301-BR": ("other_official", "Presidential action, 91 FR 45619 (Section 301, Brazil)",
                "2026-14654"),
    "S301-FL": ("ustr_notice", "91 FR 47318 (USTR notice of action, 60 forced-labor "
                "investigations); Presidential memorandum 91 FR 47717", "2026-15181"),
    "S301-4YR": ("ustr_notice", "89 FR 76581 (USTR, four-year review modifications)",
                 "2024-21217"),
}  # fmt: skip

IEEPA_END = "2026-02-24"  # EO 14389: IEEPA duties end 12:00 a.m. ET 2026-02-24 (CBP)
IEEPA_STATUS_NOTE = (
    "IEEPA tariffs held unlawful, Learning Resources v. Trump (S. Ct., 2026-02-20); collection "
    "ended 2026-02-24 under EO 14389; refunds ordered (CIT) and being paid. Census calculated "
    "duties record the duty as assessed at entry."
)
EU27 = "EU27"
FLOOR_DEALS_2026 = ["AR", "EC", "SV", "GT", "JP", "KR", "LI", "CH", "TW", "GB"]


def row(action_id: str, group: str, authority: str, country: str | tuple[str, str], scope: str,
        rate: float | None, start: str, src: str, *, end: str = "", **kw) -> dict:  # fmt: skip
    iso, code = (country, country) if isinstance(country, str) else country
    source_type, citation, doc = SRC[src]
    base = {
        "action_id": action_id, "action_group": group, "authority": authority,
        "country_iso": iso, "cty_code": code, "hs_scope": scope, "rate_type": "ad_valorem",
        "rate": "" if rate is None else f"{rate:g}", "effective_date": start, "end_date": end,
        "stacking": "cumulative", "legal_status": "in_effect", "source_type": source_type,
        "source_citation": citation, "source_url": fr(doc), "verified_on": VERIFIED_ON,
    }  # fmt: skip
    base.update(kw)
    return {c: base.get(c, "") for c in tt.COLUMNS}


def ieepa(r: dict) -> dict:
    r["legal_status"] = "struck_down"
    r["notes"] = (r["notes"] + " " if r["notes"] else "") + IEEPA_STATUS_NOTE
    return r


# --- IEEPA -------------------------------------------------------------------


def fentanyl() -> list[dict]:
    energy = "27"  # EO 14156 sec. 8 energy; approximated by HS chapter 27 (see notes)
    potash = "310420;310430;310490"
    ca, mx = cty("Canada"), cty("Mexico")
    usmca_note = (
        "USMCA-qualifying goods exempt from 2025-03-07: P10 applies the share of "
        "imports entered under USMCA."
    )
    g = "IEEPA-FENT"
    rows = [
        row("IEEPA-FENT-CN-10", f"{g}-CN", "IEEPA_FENTANYL", cty("China"), "ALL", 0.10,
            "2025-02-04", "EO14195", end="2025-03-04", ch99_heading="9903.01.20"),
        row("IEEPA-FENT-CN-20", f"{g}-CN", "IEEPA_FENTANYL", cty("China"), "ALL", 0.20,
            "2025-03-04", "EO14228", end="2025-11-10", ch99_heading="9903.01.24"),
        row("IEEPA-FENT-CN-10B", f"{g}-CN", "IEEPA_FENTANYL", cty("China"), "ALL", 0.10,
            "2025-11-10", "EO14357", end=IEEPA_END, ch99_heading="9903.01.24",
            notes="Reduced under the US-China arrangement of 2025-11-01."),
        row("IEEPA-FENT-HK-10", f"{g}-CN", "IEEPA_FENTANYL", cty("Hong Kong"), "ALL", 0.10,
            "2025-02-04", "EO14195", end="2025-03-04", ch99_heading="9903.01.20",
            notes="Products of China include Hong Kong (EO 14195 sec. 2)."),
        row("IEEPA-FENT-HK-20", f"{g}-CN", "IEEPA_FENTANYL", cty("Hong Kong"), "ALL", 0.20,
            "2025-03-04", "EO14228", end="2025-11-10", ch99_heading="9903.01.24"),
        row("IEEPA-FENT-HK-10B", f"{g}-CN", "IEEPA_FENTANYL", cty("Hong Kong"), "ALL", 0.10,
            "2025-11-10", "EO14357", end=IEEPA_END, ch99_heading="9903.01.24"),
        # Canada: 25% (energy, potash 10%) from 2025-03-04 after the 30-day pause
        row("IEEPA-FENT-CA-25", f"{g}-CA", "IEEPA_FENTANYL", ca, "ALL", 0.25, "2025-03-04",
            "EO14197", end="2025-03-07", hs_exclude=energy, ch99_heading="9903.01.10",
            stacking="not_with:S232",
            notes="EO 14193 (90 FR 9113) rates, effective 2025-03-04 after EO 14197 pause."),
        row("IEEPA-FENT-CA-25U", f"{g}-CA", "IEEPA_FENTANYL", ca, "ALL", 0.25, "2025-03-07",
            "EO14231", end="2025-08-01", hs_exclude=f"{energy};{potash}", usmca="exempt",
            ch99_heading="9903.01.10", stacking="not_with:S232", supersedes="IEEPA-FENT-CA-25",
            notes=usmca_note),
        row("IEEPA-FENT-CA-35", f"{g}-CA", "IEEPA_FENTANYL", ca, "ALL", 0.35, "2025-08-01",
            "EO14325", end=IEEPA_END, hs_exclude=f"{energy};{potash}", usmca="exempt",
            ch99_heading="9903.01.10", stacking="not_with:S232",
            supersedes="IEEPA-FENT-CA-25U", notes=usmca_note),
        row("IEEPA-FENT-CA-EN", f"{g}-CA-ENERGY", "IEEPA_FENTANYL", ca, energy, 0.10,
            "2025-03-04", "EO14197", end="2025-03-07", ch99_heading="9903.01.13",
            stacking="not_with:S232",
            notes="Energy per EO 14156 sec. 8 approximated by HS chapter 27 (excludes uranium "
                  "and critical minerals)."),
        row("IEEPA-FENT-CA-ENU", f"{g}-CA-ENERGY", "IEEPA_FENTANYL", ca, f"{energy};{potash}",
            0.10, "2025-03-07", "EO14231", end=IEEPA_END, usmca="exempt",
            ch99_heading="9903.01.13;9903.01.15", stacking="not_with:S232",
            supersedes="IEEPA-FENT-CA-EN",
            notes="Energy (HS 27 approximation) and potash (310420/30/90) at 10%. " + usmca_note),
        row("IEEPA-FENT-MX-25", f"{g}-MX", "IEEPA_FENTANYL", mx, "ALL", 0.25, "2025-03-04",
            "EO14198", end="2025-03-07", ch99_heading="9903.01.01", stacking="not_with:S232",
            notes="EO 14194 (90 FR 9117) rate, effective 2025-03-04 after EO 14198 pause."),
        row("IEEPA-FENT-MX-25U", f"{g}-MX", "IEEPA_FENTANYL", mx, "ALL", 0.25, "2025-03-07",
            "EO14232", end=IEEPA_END, hs_exclude=potash, usmca="exempt",
            ch99_heading="9903.01.01", stacking="not_with:S232",
            supersedes="IEEPA-FENT-MX-25", notes=usmca_note),
        row("IEEPA-FENT-MX-POT", f"{g}-MX-POTASH", "IEEPA_FENTANYL", mx, potash, 0.10,
            "2025-03-07", "EO14232", end=IEEPA_END, usmca="exempt", ch99_heading="9903.01.05",
            stacking="not_with:S232"),
    ]  # fmt: skip
    for r in rows:
        if r["stacking"] == "not_with:S232":
            r["notes"] = (r["notes"] + " " if r["notes"] else "") + (
                "Not applied to goods subject to Section 232 duties (EO 14289; HTSUS note 2 "
                "and notes 16, 19, 33, 37, 38)."
            )
    return [ieepa(r) for r in rows]


def reciprocal() -> list[dict]:
    g, auth = "IEEPA-RECIP", "IEEPA_RECIPROCAL"
    annex2_early, annex2 = lst("ieepa_recip_annex2_pre_2025_11"), lst("ieepa_recip_annex2")
    s232 = "not_with:S232"
    rows = [
        row("IEEPA-RECIP-BASE", g, auth, "ALL", "ALL", 0.10, "2025-04-05", "EO14257",
            end=IEEPA_END, exclude_cty_codes="1220;2010", hs_exclude=annex2_early,
            ch99_heading="9903.01.25", stacking=s232,
            notes="Baseline 10% for all countries not given a country rate. Canada and Mexico "
                  "exempt (9903.01.26/27). Annex II exemptions (9903.01.32) as of 2025 HTS Rev 28 "
                  "(incl. the electronics exemption of 2025-04-11, retroactive to 2025-04-05); "
                  "Annex II changes under EO 14346 (Sept 2025) not dated separately. Not applied "
                  "to Section 232 goods (9903.01.33). The country rates of 2025-04-09 were "
                  "suspended after one day (EO 14266) and are not modelled."),
    ]  # fmt: skip
    # China: escalation, then the 2025-05-14 truce back to the 10% baseline
    for name in ("China", "Hong Kong", "Macau"):
        iso, code = cty(name)
        rows += [
            row(f"IEEPA-RECIP-{iso}-84", g, auth, (iso, code), "ALL", 0.84, "2025-04-09",
                "EO14259", end="2025-04-10", hs_exclude=annex2_early, ch99_heading="9903.01.63",
                stacking=s232, supersedes="IEEPA-RECIP-BASE"),
            row(f"IEEPA-RECIP-{iso}-125", g, auth, (iso, code), "ALL", 1.25, "2025-04-10",
                "EO14266", end="2025-05-14", hs_exclude=annex2_early, ch99_heading="9903.01.63",
                stacking=s232, supersedes="IEEPA-RECIP-BASE",
                notes="After 2025-05-14 the 34% country rate was suspended (EO 14298, extended "
                      "by EO 14334 and EO 14358) and the 10% baseline applies."),
        ]  # fmt: skip
    # EO 14326 country schedule from 2025-08-07, as reproduced in 9903.02.02-9903.02.71
    floors = {"Japan", "South Korea", "Switzerland", "Liechtenstein"}
    sched = h25.country_rate_rows(chapter99_text(h25.RELEASE_PRE_COURT), r"9903\.02\.[0-7]")
    ag = "IEEPA-RECIP-AG"
    country_ids = ["IEEPA-RECIP-BASE"]
    for heading, name, rate in sched:
        if name in NOT_IN_TRADE_DATA:
            continue
        iso, code = cty(name)
        end = "2025-11-14" if name in floors else IEEPA_END
        if name == "Japan":
            continue  # replaced retroactively by the 15% floor (EO 14345)
        rows.append(row(f"IEEPA-RECIP-{iso}", g, auth, (iso, code), "ALL", rate, "2025-08-07",
                        "EO14326", end=end, hs_exclude=annex2_early, ch99_heading=heading,
                        stacking=s232, supersedes="IEEPA-RECIP-BASE"))  # fmt: skip
        country_ids.append(f"IEEPA-RECIP-{iso}")
    # 15% all-in floors (rate tops MFN up to 15%)
    floor = dict(rate_type="all_in_floor", stacking=s232, supersedes="IEEPA-RECIP-BASE")
    rows += [
        row("IEEPA-RECIP-EU-A", g, auth, EU27, "ALL", 0.15, "2025-08-07", "EO14326",
            end="2025-09-01", hs_exclude=annex2_early, ch99_heading="9903.02.19;9903.02.20",
            **floor),
        row("IEEPA-RECIP-EU-B", g, auth, EU27, "ALL", 0.15, "2025-09-01", "EU-NOTICE",
            end=IEEPA_END, ch99_heading="9903.02.19;9903.02.20",
            hs_exclude=";".join([annex2_early, lst("ieepa_recip_eu_natres",
                                 "ieepa_recip_eu_aircraft", "ieepa_recip_eu_pharma")]),
            notes="EU framework exemptions from 2025-09-01: unavailable natural resources, civil "
                  "aircraft and parts, non-patented pharmaceuticals (9903.02.74-77).", **floor),
        row("IEEPA-RECIP-JP-A", g, auth, cty("Japan"), "ALL", 0.15, "2025-08-07", "EO14345",
            end="2025-09-16", hs_exclude=annex2_early, ch99_heading="9903.02.72;9903.02.73",
            notes="Floor applies retroactively from 2025-08-07 (EO 14345 sec. 2(d)), replacing "
                  "the 15% additional rate of heading 9903.02.30.", **floor),
        row("IEEPA-RECIP-JP-B", g, auth, cty("Japan"), "ALL", 0.15, "2025-09-16", "JP-NOTICE",
            end=IEEPA_END, hs_exclude=f"{annex2_early};{lst('ieepa_recip_jp_aircraft')}",
            ch99_heading="9903.02.72;9903.02.73",
            notes="Civil aircraft exemption (9903.96.02) from 2025-09-16.", **floor),
        row("IEEPA-RECIP-KR-B", g, auth, cty("South Korea"), "ALL", 0.15, "2025-11-14",
            "KR-NOTICE", end=IEEPA_END, ch99_heading="9903.02.79;9903.02.80",
            hs_exclude=f"{annex2};{lst('ieepa_recip_kr_aircraft')}", **floor),
        row("IEEPA-RECIP-CH-B", g, auth, cty("Switzerland"), "ALL", 0.15, "2025-11-14",
            "CH-NOTICE", end=IEEPA_END, ch99_heading="9903.02.82;9903.02.83",
            hs_exclude=f"{annex2};" + lst("ieepa_recip_ch_natres", "ieepa_recip_ch_aircraft",
                                          "ieepa_recip_ch_pharma"),
            notes="Replaces the 39% rate of heading 9903.02.58.", **floor),
        row("IEEPA-RECIP-LI-B", g, auth, cty("Liechtenstein"), "ALL", 0.15, "2025-11-14",
            "CH-NOTICE", end=IEEPA_END, ch99_heading="9903.02.87;9903.02.88",
            hs_exclude=f"{annex2};" + lst("ieepa_recip_ch_natres", "ieepa_recip_ch_aircraft",
                                          "ieepa_recip_ch_pharma"), **floor),
    ]  # fmt: skip
    for r in rows[-3:]:
        r["supersedes"] = f"IEEPA-RECIP-BASE;IEEPA-RECIP-{r['country_iso']}"
    country_ids += ["IEEPA-RECIP-EU-A", "IEEPA-RECIP-EU-B", "IEEPA-RECIP-JP-A",
                    "IEEPA-RECIP-JP-B", "IEEPA-RECIP-KR-B", "IEEPA-RECIP-CH-B",
                    "IEEPA-RECIP-LI-B"]  # fmt: skip
    for name in ("China", "Hong Kong", "Macau"):
        iso = cty(name)[0]
        country_ids += [f"IEEPA-RECIP-{iso}-84", f"IEEPA-RECIP-{iso}-125"]
    # 2025-11-13 agricultural exemptions: a 0% row superseding every reciprocal row
    rows.append(row(
        ag, ag, auth, "ALL", lst("ieepa_recip_annex2", "ieepa_recip_ag_2025_11"), 0.0,
        "2025-11-13", "EO14360", end=IEEPA_END, hs_exclude=annex2_early,
        ch99_heading="9903.01.32;9903.02.78", stacking=s232, supersedes=";".join(country_ids),
        notes="Products added to Annex II on 2025-11-13 (beef, coffee, tea, fruit, spices and "
              "others; HTS Rev 3 Annex II less Rev 28 Annex II) and the particular articles of "
              "9903.02.78 become exempt (rate 0)."))  # fmt: skip
    return [ieepa(r) for r in rows]


def ieepa_other() -> list[dict]:
    br, ind = cty("Brazil"), cty("India")
    rows = [
        row("IEEPA-BR-40-A", "IEEPA-BRAZIL", "IEEPA_OTHER", br, "ALL", 0.40, "2025-08-06",
            "EO14323", end="2025-11-13", ch99_heading="9903.01.77",
            hs_exclude=lst("ieepa_brazil_exempt_pre_2025_11", "ieepa_brazil_aircraft"),
            stacking="not_with:S232",
            notes="Exemptions 9903.01.81 as of 2025 HTS Rev 28; civil aircraft 9903.01.82."),
        row("IEEPA-BR-40-B", "IEEPA-BRAZIL", "IEEPA_OTHER", br, "ALL", 0.40, "2025-11-13",
            "EO14361", end=IEEPA_END, ch99_heading="9903.01.77",
            hs_exclude=lst("ieepa_brazil_exempt", "ieepa_brazil_ag_2025_11",
                           "ieepa_brazil_aircraft"),
            stacking="not_with:S232", supersedes="IEEPA-BR-40-A",
            notes="Agricultural exemptions (beef, coffee, fruit and others) from 2025-11-13."),
        row("IEEPA-IN-RUOIL", "IEEPA-INDIA-RUOIL", "IEEPA_OTHER", ind, "ALL", 0.25,
            "2025-08-27", "EO14329", end="2026-02-07", ch99_heading="9903.01.84",
            hs_exclude=lst("ieepa_recip_annex2_pre_2025_11"), stacking="not_with:S232",
            notes="Russian-oil duty on India; terminated 2026-02-07 by EO 14384 (91 FR 6501). "
                  "Exemptions approximated by Annex II."),
    ]  # fmt: skip
    return [ieepa(r) for r in rows]


def de_minimis() -> list[dict]:
    marker = (
        "Event marker, not a duty rate (rate 0): duty-free de minimis entry (19 U.S.C. "
        "1321) no longer available. Low-value shipments were mostly absent from trade "
        "statistics before; see P14."
    )
    rows = [
        row("DM-CN-2025-05", "DE-MINIMIS", "DE_MINIMIS", cty("China"), "ALL", 0.0,
            "2025-05-02", "EO14256", end="2025-08-29", notes=marker),
        row("DM-HK-2025-05", "DE-MINIMIS", "DE_MINIMIS", cty("Hong Kong"), "ALL", 0.0,
            "2025-05-02", "EO14256", end="2025-08-29", notes=marker),
        row("DM-ALL-2025-08", "DE-MINIMIS", "DE_MINIMIS", "ALL", "ALL", 0.0, "2025-08-29",
            "EO14324", end="2026-02-24", supersedes="DM-CN-2025-05;DM-HK-2025-05",
            notes=marker + " Imposed under IEEPA (see legal status)."),
        row("DM-ALL-2026-02", "DE-MINIMIS", "DE_MINIMIS", "ALL", "ALL", 0.0, "2026-02-24",
            "EO14388", supersedes="DM-ALL-2025-08",
            notes=marker + " Continued after the IEEPA ruling; corrected text 91 FR 17839."),
    ]  # fmt: skip
    return rows


# --- Section 232 -------------------------------------------------------------


def s232_metals() -> list[dict]:
    uk, ru = cty("United Kingdom"), "4621"
    # Metals duties do not apply to goods under the autos, trucks or semiconductor duties
    autos = "not_with:S232-AUTOS,S232-TRUCKS,S232-SEMI"
    content = dict(value_basis="metal_content")
    # 7302.90.9000 and 7616.99.51(30/40/90) are listed as derivatives (notes 16(m), 19(j))
    steel, steel_x = lst("s232_steel"), lst("s232_steel_exclude") + ";7302909000"
    alum, alum_x = lst("s232_aluminum"), "7616995130;7616995140;7616995190"
    sd = {"2025-03-12": lst("s232_steel_derivatives", "s232_steel_deriv_2025_03",
                            "s232_steel_deriv_2025_03b"),
          "2025-06-23": lst("s232_steel_deriv_2025_06"),
          "2025-08-18": lst("s232_steel_deriv_2025_08")}  # fmt: skip
    ad = {"2025-03-12": lst("s232_aluminum_derivatives", "s232_alum_deriv_2025_03"),
          "2025-06-23": lst("s232_alum_deriv_2025_06"),
          "2025-08-18": lst("s232_alum_deriv_2025_08")}  # fmt: skip
    new26 = "2026-04-06"
    rows = [
        row("S232-STEEL-25-2025", "S232-STEEL", "S232", "ALL", steel, 0.25, "2025-03-12",
            "P10896", end="2025-06-04", hs_exclude=steel_x, ch99_heading="9903.81.87",
            stacking=autos, notes="All country exemptions, quotas and product exclusions ended."),
        row("S232-STEEL-50", "S232-STEEL", "S232", "ALL", steel, 0.50, "2025-06-04", "P10947",
            end=new26, exclude_cty_codes=uk[1], hs_exclude=steel_x, ch99_heading="9903.81.87",
            stacking=autos, supersedes="S232-STEEL-25-2025"),
        row("S232-STEEL-UK25", "S232-STEEL", "S232", uk, steel, 0.25, "2025-06-04", "P10947",
            end=new26, hs_exclude=steel_x, ch99_heading="9903.81.94", stacking=autos,
            supersedes="S232-STEEL-25-2025"),
        row("S232-ALUM-25-2025", "S232-ALUM", "S232", "ALL", alum, 0.25, "2025-03-12",
            "P10895", end="2025-06-04", exclude_cty_codes=ru, hs_exclude=alum_x,
            ch99_heading="9903.85.02",
            stacking=autos, notes="Rate raised from 10%; exemptions ended. Russia stays at 200%."),
        row("S232-ALUM-50", "S232-ALUM", "S232", "ALL", alum, 0.50, "2025-06-04", "P10947",
            end=new26, exclude_cty_codes=f"{ru};{uk[1]}", hs_exclude=alum_x,
            ch99_heading="9903.85.02", stacking=autos, supersedes="S232-ALUM-25-2025"),
        row("S232-ALUM-UK25", "S232-ALUM", "S232", uk, alum, 0.25, "2025-06-04", "P10947",
            end=new26, hs_exclude=alum_x, ch99_heading="9903.85.12", stacking=autos,
            supersedes="S232-ALUM-25-2025"),
        row("S232-COPPER-50", "S232-COPPER", "S232", "ALL", lst("s232_copper_2025"), 0.50,
            "2025-08-01", "P10962", end=new26, ch99_heading="9903.78.01",
            stacking=autos + ";also_with:S232-STEELDER,S232-ALUMDER", **content,
            notes="Semi-finished copper and intensive copper derivatives; duty on copper content "
                  "(non-copper content 9903.78.02 exempt from it)."),
    ]  # fmt: skip
    for start, scope in sd.items():
        tag = start[2:7].replace("-", "")
        first = start == "2025-03-12"
        if first:
            rows.append(row("S232-STEELDER-25-2025", "S232-STEELDER", "S232", "ALL", scope, 0.25,
                            start, "P10896", end="2025-06-04",
                            ch99_heading="9903.81.89;9903.81.90",
                            stacking=autos + ";also_with:S232-ALUMDER,S232-COPPER",
                            **content))  # fmt: skip
        src = "P10947" if start != "2025-08-18" else "BIS-INCL"
        s50 = max(start, "2025-06-04")
        sup = "S232-STEELDER-25-2025" if first else ""
        rows += [
            row(f"S232-STEELDER-50-{tag}", "S232-STEELDER", "S232", "ALL", scope, 0.50, s50, src,
                end=new26, exclude_cty_codes=uk[1], ch99_heading="9903.81.90;9903.81.91",
                stacking=autos + ";also_with:S232-ALUMDER,S232-COPPER", supersedes=sup,
                **content),
            row(f"S232-STEELDER-UK25-{tag}", "S232-STEELDER", "S232", uk, scope, 0.25, s50, src,
                end=new26, ch99_heading="9903.81.97;9903.81.98",
                stacking=autos + ";also_with:S232-ALUMDER,S232-COPPER", supersedes=sup,
                **content),
        ]  # fmt: skip
    for start, scope in ad.items():
        tag = start[2:7].replace("-", "")
        first = start == "2025-03-12"
        if first:
            rows.append(row("S232-ALUMDER-25-2025", "S232-ALUMDER", "S232", "ALL", scope, 0.25,
                            start, "P10895", end="2025-06-04", exclude_cty_codes=ru,
                            ch99_heading="9903.85.04;9903.85.07",
                            stacking=autos + ";also_with:S232-STEELDER,S232-COPPER",
                            **content))  # fmt: skip
        src = "P10947" if start != "2025-08-18" else "BIS-INCL"
        s50 = max(start, "2025-06-04")
        sup = "S232-ALUMDER-25-2025" if first else ""
        rows += [
            row(f"S232-ALUMDER-50-{tag}", "S232-ALUMDER", "S232", "ALL", scope, 0.50, s50, src,
                end=new26, exclude_cty_codes=f"{ru};{uk[1]}", ch99_heading="9903.85.07;9903.85.08",
                stacking=autos + ";also_with:S232-STEELDER,S232-COPPER", supersedes=sup,
                **content),
            row(f"S232-ALUMDER-UK25-{tag}", "S232-ALUMDER", "S232", uk, scope, 0.25, s50, src,
                end=new26, ch99_heading="9903.85.14;9903.85.15",
                stacking=autos + ";also_with:S232-STEELDER,S232-COPPER", supersedes=sup,
                **content),
        ]  # fmt: skip
    # From 2026-04-06: one regime for aluminum, steel and copper on full customs value
    m = "S232-METALS26"
    full = "Full customs value (Proclamation 11021). For articles outside chapters 72-76 the duty "
    full += "applies only if the metal is at least 15% of weight (not observable; P11)."
    rows += [
        row("S232-METALS26-50", m, "S232", "ALL", lst("s232_metals26_50"), 0.50, new26,
            "P11021", exclude_cty_codes=f"{ru};{uk[1]}", ch99_heading="9903.82.02",
            stacking=autos, notes=full + " Lists 16(c)(i)-(v) as of HTS 2026 Rev 21 (incl. "
            "Proclamation 11032 changes of 2026-06-08)."),
        row("S232-METALS26-UK25", m, "S232", uk, lst("s232_metals26_50_alst"), 0.25, new26,
            "P11021", ch99_heading="9903.82.04", stacking=autos,
            notes="UK aluminum and steel (UK-melted/smelted content assumed)."),
        row("S232-METALS26-UK-CU50", m, "S232", uk, lst("s232_metals26_50"), 0.50, new26,
            "P11021", hs_exclude=lst("s232_metals26_50_alst"), ch99_heading="9903.82.02",
            stacking=autos, notes="UK copper articles: no UK rate."),
        row("S232-METALS26-25", m, "S232", "ALL",
            lst("s232_metals26_25", "s232_metals26_25_xi"), 0.25, new26, "P11021",
            exclude_cty_codes=f"{ru};{uk[1]}", ch99_heading="9903.82.09", stacking=autos,
            notes=full),
        row("S232-METALS26-UK15", m, "S232", uk, lst("s232_metals26_25", "s232_metals26_25_xi"),
            0.15, new26, "P11021", ch99_heading="9903.82.05", stacking=autos,
            notes="UK derivatives; list 16(c)(viii) (copper) and (xi) assumed at the UK rate."),
        row("S232-METALS26-FLOOR15", m, "S232", "ALL", lst("s232_metals26_floor15"), 0.15,
            new26, "P11021", rate_type="all_in_floor", exclude_cty_codes=ru,
            ch99_heading="9903.82.10;9903.82.11", stacking=autos,
            notes="Derivatives (agricultural equipment, HVAC and others) at 15% including MFN, "
                  "until 2027-12-31. Non-NTR countries 25% (9903.82.12) not modelled."),
    ]  # fmt: skip
    for iso in [*FLOOR_DEALS_2026, EU27]:
        code = iso if iso == EU27 else next(c for i, c in COUNTRIES.values() if i == iso)
        rows.append(row(f"S232-METALS26-XI-{iso}", m, "S232", (iso, code),
                        lst("s232_metals26_25_xi"), 0.15, "2026-06-08", "P11032",
                        rate_type="all_in_floor", ch99_heading="9903.82.22", stacking=autos,
                        supersedes="S232-METALS26-25" + (";S232-METALS26-UK15" if iso == "GB"
                                                          else ""),
                        notes="Derivative steel list 16(c)(xi) at 15% including MFN for deal "
                              "partners (Proclamation 11032 clause 2(b))."))  # fmt: skip
    return rows


def s232_sectors() -> list[dict]:
    jp, kr, uk, tw = cty("Japan"), cty("South Korea"), cty("United Kingdom"), cty("Taiwan")
    veh, parts = lst("s232_autos_vehicles"), lst("s232_autos_parts")
    a, t = "S232-AUTOS", "S232-TRUCKS"
    floor = dict(rate_type="all_in_floor")
    parts_stack = "not_with:S232-SEMI,S232-DRONES"  # note 39(a)(2); drones approximated
    rows = [
        row("S232-AUTOS-VEH", a, "S232", "ALL", veh, 0.25, "2025-04-03", "P10908",
            exclude_cty_codes=f"{uk[1]};{EU27};{jp[1]};{kr[1]}", usmca="non_us_content",
            ch99_heading="9903.94.01",
            notes="USMCA vehicles pay on non-US content. Deal partners (UK, EU, Japan, Korea) "
                  "have their own rows, at 25% until their deal dates."),
    ]  # fmt: skip
    for iso, code, start, src, part_start in [
        ("GB", uk[1], "2025-06-30", "EO14309", "2025-06-30"),
        ("EU27", EU27, "2025-08-01", "EU-NOTICE", "2025-08-01"),
        ("JP", jp[1], "2025-09-16", "JP-NOTICE", "2025-09-16"),
        ("KR", kr[1], "2025-11-01", "KR-NOTICE", "2025-11-01"),
    ]:
        cap = 0.10 if iso == "GB" else 0.15
        rows += [
            row(f"S232-AUTOS-VEH-{iso}-25", a, "S232", (iso, code), veh, 0.25, "2025-04-03",
                "P10908", end=start, ch99_heading="9903.94.01"),
            row(f"S232-AUTOS-VEH-{iso}", a, "S232", (iso, code), veh, cap, start, src,
                ch99_heading="9903.94.31" if iso == "GB" else "9903.94.40;9903.94.41",
                supersedes=f"S232-AUTOS-VEH-{iso}-25", **floor,
                notes=("UK: 10% including MFN within a 100,000-vehicle annual quota (quota not "
                       "modelled); effective on publication of the implementing notice."
                       if iso == "GB" else "15% including MFN.")),
            row(f"S232-AUTOS-PARTS-{iso}-25", a, "S232", (iso, code), parts, 0.25, "2025-05-03",
                "P10908", end=part_start, ch99_heading="9903.94.05", stacking=parts_stack),
            row(f"S232-AUTOS-PARTS-{iso}", a, "S232", (iso, code), parts, cap, part_start, src,
                ch99_heading="9903.94.33" if iso == "GB" else "9903.94.44;9903.94.45",
                supersedes=f"S232-AUTOS-PARTS-{iso}-25", stacking=parts_stack, **floor),
        ]  # fmt: skip
    rows += [
        row("S232-AUTOS-PARTS", a, "S232", "ALL", parts, 0.25, "2025-05-03", "P10908",
            exclude_cty_codes=f"{uk[1]};{EU27};{jp[1]};{kr[1]}", usmca="exempt",
            ch99_heading="9903.94.05", stacking=parts_stack,
            notes="USMCA-qualifying parts exempt. Import adjustment offsets for US assembly "
                  "(Proclamation 10925) and later parts inclusions not modelled."),
        row("S232-AUTOS-PARTS-TW", a, "S232", tw, parts, 0.15, "2026-05-01", "TW-NOTICE",
            rate_type="all_in_floor", ch99_heading="9903.94.66;9903.94.67",
            supersedes="S232-AUTOS-PARTS", stacking=parts_stack),
        row("S232-TRUCKS-VEH", t, "S232", "ALL", lst("s232_trucks_vehicles"), 0.25, "2025-11-01",
            "P10984", usmca="non_us_content", ch99_heading="9903.74.01",
            stacking="cumulative;also_with:S232-AUTOS"),
        row("S232-TRUCKS-BUS", t, "S232", "ALL", lst("s232_trucks_buses"), 0.10, "2025-11-01",
            "P10984", usmca="non_us_content", ch99_heading="9903.74.02",
            stacking="cumulative;also_with:S232-AUTOS"),
        row("S232-TRUCKS-PARTS", t, "S232", "ALL", lst("s232_trucks_parts"), 0.25, "2025-11-01",
            "P10984", usmca="exempt", ch99_heading="9903.74.08",
            hs_exclude="8706000300;8706000520;8706000575;8706002500",
            stacking="not_with:S232-AUTOS",
            notes="Parts that are also passenger-vehicle parts take the auto parts duty. Chassis "
                  "with engines (8706) listed as both vehicles and parts are treated as vehicles."),
    ]  # fmt: skip
    # Timber, lumber and derivatives
    lum, eu_jp = "S232-LUMBER", [("EU27", EU27), ("JP", jp[1])]
    sw, up, cab = (lst("s232_lumber_softwood"), lst("s232_lumber_upholstered"),
                   lst("s232_lumber_cabinets"))  # fmt: skip
    deal = f"{uk[1]};{EU27};{jp[1]}"
    rows += [
        row("S232-LUMBER-SW", lum, "S232", "ALL", sw, 0.10, "2025-10-14", "P10976",
            ch99_heading="9903.76.01", notes="Softwood timber and lumber."),
        row("S232-LUMBER-UPH", lum, "S232", "ALL", up, 0.25, "2025-10-14", "P10976",
            end="2027-01-01", exclude_cty_codes=deal, ch99_heading="9903.76.02",
            notes="Upholstered wooden furniture; increase to 30% delayed from 2026-01-01 to "
                  "2027-01-01 (Proclamation 11000)."),
        row("S232-LUMBER-CAB", lum, "S232", "ALL", cab, 0.25, "2025-10-14", "P10976",
            end="2027-01-01", exclude_cty_codes=deal, ch99_heading="9903.76.03",
            notes="Kitchen cabinets and vanities; increase to 50% delayed to 2027-01-01."),
        row("S232-LUMBER-UPH-2027", lum, "S232", "ALL", up, 0.30, "2027-01-01", "P11000",
            exclude_cty_codes=deal, legal_status="scheduled", ch99_heading="9903.76.02",
            supersedes="S232-LUMBER-UPH"),
        row("S232-LUMBER-CAB-2027", lum, "S232", "ALL", cab, 0.50, "2027-01-01", "P11000",
            exclude_cty_codes=deal, legal_status="scheduled", ch99_heading="9903.76.03",
            supersedes="S232-LUMBER-CAB"),
        row("S232-LUMBER-UK", lum, "S232", uk, f"{up};{cab}", 0.10, "2025-10-14", "P10976",
            ch99_heading="9903.76.20", notes="UK rate for furniture and cabinets."),
    ]  # fmt: skip
    for iso, code in eu_jp:
        rows.append(row(f"S232-LUMBER-{iso}", lum, "S232", (iso, code), f"{up};{cab}", 0.15,
                        "2025-10-14", "P10976", rate_type="all_in_floor",
                        ch99_heading="9903.76.21;9903.76.22;9903.76.23",
                        notes="Not to exceed 15% including MFN (Proclamation 10976)."))  # fmt: skip
    # Semiconductors, pharmaceuticals, drones: duties on subsets trade data cannot identify
    sub = dict(value_basis="unidentified_subset")
    rows += [
        row("S232-SEMI-25", "S232-SEMI", "S232", "ALL", "847150;847180;847330", 0.25,
            "2026-01-15", "P11002", ch99_heading="9903.79.01", **sub,
            notes="Only advanced logic chips above performance thresholds (note 39(b)) and not "
                  "for US data centers, R&D, startups and other listed uses; HS scope is the "
                  "set of provisions where they can be entered."),
        row("S232-PHARMA-100", "S232-PHARMA", "S232", "ALL", lst("s232_pharma"), 1.00,
            "2026-09-29", "P11020", exclude_cty_codes=f"{EU27};{jp[1]};{kr[1]};4419;4411;{uk[1]}",
            ch99_heading="9903.04.60", **sub,
            notes="Patented pharmaceuticals only (generics 9903.04.67 and companies with "
                  "onshoring plans exempt); companies listed in Annex III from 2026-07-31."),
        row("S232-PHARMA-UK0", "S232-PHARMA", "S232", uk, lst("s232_pharma"), 0.0, "2026-09-29",
            "P11020", ch99_heading="9903.04.63", **sub),
        row("S232-DRONES", "S232-DRONES", "S232", "ALL", lst("s232_drones"), 0.25, "2026-09-03",
            "P11055", ch99_heading="9903.08.21;9903.08.22", **sub,
            notes="Rates by weight and thermal imaging (100% or 25%) not identifiable by HS; "
                  "25% used as a lower bound. Deal caps (UK 10%, EU/JP/KR/TW/CH 15%) and "
                  "components (2027-02-09) not modelled."),
    ]  # fmt: skip
    for iso, code in [("EU27", EU27), ("JP", jp[1]), ("KR", kr[1]), ("CH", "4419"),
                      ("LI", "4411")]:  # fmt: skip
        rows.append(row(f"S232-PHARMA-{iso}", "S232-PHARMA", "S232", (iso, code),
                        lst("s232_pharma"), 0.15, "2026-09-29", "P11020",
                        rate_type="all_in_floor", ch99_heading="9903.04.62", **sub))  # fmt: skip
    return rows


# --- Section 122, 301 (2024-26), 338 -----------------------------------------


def s122() -> list[dict]:
    return [row(
        "S122-10", "S122", "S122", "ALL", "ALL", 0.10, "2026-02-24", "P11012", end="2026-07-24",
        hs_exclude=lst("s122_exempt_annex", "s122_exempt_particular", "s122_exempt_aircraft"),
        usmca="exempt", ch99_heading="9903.03.01", stacking="not_with:S232",
        legal_status="expired",
        notes="Balance-of-payments surcharge for 150 days; expired at the close of 2026-07-23. "
              "Exempt: Annex products, civil aircraft, Section 232 goods, patented "
              "pharmaceuticals, USMCA goods, CAFTA-DR textiles (not modelled). The CIT held the "
              "surcharge unlawful in 2026-05; stayed on appeal (Federal Circuit), no refunds as of "
              "the verification date.")]  # fmt: skip


def s301_2026() -> list[dict]:
    rows = [row(
        "S301-BR-25", "S301-BRAZIL", "S301", cty("Brazil"), "ALL", 0.25, "2026-07-22", "S301-BR",
        hs_exclude=lst("s301_brazil_exempt", "s301_brazil_aircraft_pharma"),
        ch99_heading="9903.05.01", stacking="not_with:S232",
        notes="Brazil digital trade and payments investigation (91 FR 33854). Exemptions: "
              "note 50(a)(ii)-(vi).")]  # fmt: skip
    fl = "S301-FL"
    exempt = lst("s301_fl_exempt")
    stack = (
        "not_with:S232;also_with:S301-BRAZIL,S301-CN-L1,S301-CN-L2,S301-CN-L3,S301-CN-L4A,"
        "S301-CN-4YR"
    )
    sched = h25.country_rate_rows(chapter99_text(h25.RELEASE_CURRENT), r"9903\.05\.[2-8]")
    for heading, name, rate in sched:
        iso, code = cty(name)
        rows.append(row(f"{fl}-{iso}", fl, "S301", (iso, code), "ALL", rate, "2026-07-24",
                        "S301-FL", hs_exclude=exempt, ch99_heading=heading,
                        usmca="exempt" if iso in ("CA", "MX") else "", stacking=stack))  # fmt: skip
    for iso, code, rate, heads in [
        ("EU27", EU27, 0.10, "9903.05.38;9903.05.39"),
        ("JP", "5880", 0.125, "9903.05.48;9903.05.49"),
        ("KR", "5800", 0.125, "9903.05.70;9903.05.71"),
        ("CH", "4419", 0.125, "9903.05.73;9903.05.74"),
        ("TW", "5830", 0.10, "9903.05.75;9903.05.76"),
    ]:  # fmt: skip
        rows.append(row(f"{fl}-{iso}", fl, "S301", (iso, code), "ALL", rate, "2026-07-24",
                        "S301-FL", rate_type="all_in_floor", hs_exclude=exempt,
                        ch99_heading=heads, stacking=stack,
                        notes="Rate net of MFN: tops MFN up to the rate."))  # fmt: skip
    for r in rows[1:]:
        r["notes"] = (r["notes"] + " " if r["notes"] else "") + (
            "Exemptions: note 52(b)-(f) (incl. Section 232 goods); country-specific exemptions "
            "for framework partners (9903.05.95-9903.06.21) and textile TRQs not modelled."
        )
    return rows


def s301_china_review() -> list[dict]:
    cn = cty("China")
    p08 = "S301-CN-L1;S301-CN-L2;S301-CN-L3-25;S301-CN-L4A-7.5"
    spec = [
        ("25-2024", "s301_cn_4yr_25_2024", 0.25, "2024-09-27", "9903.91.01",
         "Steel and aluminum products, critical minerals, lithium-ion EV batteries, STS cranes "
         "and others."),
        ("50-2024", "s301_cn_4yr_50_2024", 0.50, "2024-09-27", "9903.91.02", "Solar cells."),
        ("100-2024", "s301_cn_4yr_100_2024", 1.00, "2024-09-27", "9903.91.03",
         "Electric vehicles and syringes."),
        ("25-2024M", "s301_cn_4yr_25_2024_masks", 0.25, "2024-09-27", "9903.91.04",
         "Disposable textile facemasks."),
        ("50-2025", "s301_cn_4yr_50_2025", 0.50, "2025-01-01", "9903.91.05",
         "Semiconductors, polysilicon, wafers; increase scheduled 2027-06-23."),
        ("25-2025", "s301_cn_4yr_25_2025", 0.25, "2025-01-01", "9903.91.11", "Tungsten products."),
        ("25-2026", "s301_cn_4yr_25_2026", 0.25, "2026-01-01", "9903.91.06",
         "Non-EV lithium-ion batteries, natural graphite, permanent magnets."),
        ("50-2026", "s301_cn_4yr_50_2026", 0.50, "2026-01-01", "9903.91.07",
         "Medical gloves and respirators (10-digit lines)."),
        ("100-2026", "s301_cn_4yr_100_2026", 1.00, "2026-01-01", "9903.91.08",
         "Rubber medical and surgical gloves (4015.12.10)."),
    ]  # fmt: skip
    return [row(f"S301-CN-4YR-{tag}", "S301-CN-4YR", "S301", cn, lst(f), rate, start, "S301-4YR",
                ch99_heading=heading,
                supersedes=p08 + (";S301-CN-4YR-25-2024M" if tag == "50-2026" else ""),
                notes=desc + " Modelled as replacing the 2018-19 list rate where products "
                "overlap (the four-year review raised the Section 301 rate on these products); "
                "to be checked against implied rates in P11.")
            for tag, f, rate, start, heading, desc in spec]  # fmt: skip


def s338() -> list[dict]:
    ca = cty("Canada")
    return [
        row(f"S338-CA-{i}", "S338-CANADA", "S338", ca, lst(f"s338_ca_list{i}"), 0.50,
            "2026-08-22", "P11046", ch99_heading=f"9903.03.1{i + 1}",
            stacking="not_with:S232" if i == 2 else "cumulative",
            notes=(f"Note 51(b)({i}) products as of HTS 2026 Rev 21 (after the 2026-09-15 "
                   "modifications, Proclamations 11064-11065; earlier lists not dated "
                   "separately). Applies to USMCA goods. Civil aircraft exempt (9903.03.16). "
                   "Modification effective 2026-10-30 not yet in the HTS.")
            + (" Not applied to Section 232 goods (9903.03.15)." if i == 2 else ""))
        for i in (1, 2, 3)
    ]  # fmt: skip


# --- assemble ----------------------------------------------------------------

# P08 rows replaced by the 2025 Section 232 actions (Proclamations 10895 and 10896)
CLOSE_P08 = {"S232-STEEL-6": "2025-03-12", "S232-ALUM-6": "2025-03-12",
             "S232-STEELDER-4": "2025-03-12", "S232-ALUMDER-3": "2025-03-12"}  # fmt: skip
RU200 = {"S232-ALUM-RU200", "S232-ALUMDER-RU200"}  # Russia 200% continues (9903.85.67/68)


def rows() -> list[dict]:
    out = (fentanyl() + reciprocal() + ieepa_other() + de_minimis() + s232_metals()
           + s232_sectors() + s122() + s301_2026() + s301_china_review() + s338())  # fmt: skip
    return out


def main() -> None:
    new = rows()
    assert all(r["effective_date"] >= GENERATED_FROM for r in new)
    groups = {r["action_group"] for r in new}
    with open(tt.ACTIONS_CSV, newline="") as f:
        old = list(csv.DictReader(f))
    keep = [r for r in old
            if r["action_group"] not in groups or r["effective_date"] < GENERATED_FROM]  # fmt: skip
    for r in keep:
        if r["action_id"] in CLOSE_P08 and not r["end_date"]:
            r["end_date"] = CLOSE_P08[r["action_id"]]
            r["notes"] += (
                " Ended 2025-03-12: replaced by Proclamations 10895/10896 (all country "
                "exemptions terminated)."
            )
            r["verified_on"] = VERIFIED_ON
        if r["action_id"] in RU200 and r["stacking"] == "cumulative":
            r["stacking"] = "not_with:S232-AUTOS,S232-TRUCKS,S232-SEMI"
            r["notes"] += (
                " From 2025 not applied to goods under the autos, trucks or "
                "semiconductor duties (EO 14289; HTSUS notes 33, 38, 39)."
            )
    with open(tt.ACTIONS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tt.COLUMNS)
        w.writeheader()
        w.writerows(keep + new)
    print(f"{tt.ACTIONS_CSV.name}: {len(keep)} kept + {len(new)} generated rows "
          f"({date.today()})")  # fmt: skip


if __name__ == "__main__":
    main()
