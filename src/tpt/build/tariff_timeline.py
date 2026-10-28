"""Tariff timeline: schema and validator for data/reference/tariff_actions.csv (P07).

One row per action component: an authority (e.g. Section 301) applying a rate to a set of HS
codes from a set of countries over a date range. P10 expands the rows into an
HS10 x country x month rate panel.

Columns (see COLUMNS; empty cells mean "not applicable"):
  action_id          unique id, e.g. S301-CN-L3-25
  action_group       groups components of one action, e.g. S301-CN-L3
  authority          see AUTHORITIES
  country_iso        ISO 3166 alpha-2, "ALL", or a group in country_groups.csv
  cty_code           Census country code, "ALL", or the same group name
  exclude_cty_codes  Census codes or group names excluded from an "ALL" row, ';'-separated
  hs_scope           ';'-separated HS prefixes (2/4/6/8/10 digits), "ALL", or
                     "file:hs_lists/<name>.csv" (column "hs"; tokens may be mixed with prefixes)
  hs_exclude         same syntax; codes carved out of hs_scope (e.g. Annex II exemptions)
  ch99_heading       HTSUS Chapter 99 heading(s) that carry the duty, e.g. 9903.88.03 (';'-sep.).
                     Duties are entered under these headings, which never appear in import
                     statistics, so hs_scope always lists the product codes themselves.
  rate_type          ad_valorem | specific | ad_valorem_plus_specific | all_in_floor
                     all_in_floor: the additional duty tops the column 1 (MFN) rate up to `rate`,
                     i.e. max(0, rate - MFN) (e.g. the EU and Japan "15% all-in" deals)
  rate               additional ad valorem rate as a decimal (0.25 = 25%)
  specific_rate      additional specific duty, with specific_unit (e.g. "kg")
  value_basis        value the rate applies to: empty/full | metal_content (S232 metals before
                     2026-04-06, copper) | non_us_content | unidentified_subset (the duty applies
                     only to a subset of the HS scope that trade data cannot identify, e.g.
                     patented drugs or chips above a performance threshold; P10 reports these
                     separately rather than applying them to the whole HS scope)
  usmca              treatment of USMCA-qualifying goods of Canada/Mexico: empty (none) |
                     exempt | non_us_content (rate applies to the non-US content only)
  effective_date     first day goods entered for consumption are subject to the rate
  end_date           first day they are no longer subject (exclusive); empty = in effect
  supersedes         action_id(s) this row replaces where they overlap (';'-separated)
  stacking           "cumulative", or "not_with:<X>[,<X>...]": the rate does not apply to goods
                     subject to the listed authorities or action groups (e.g. reciprocal not on
                     S232 goods; steel derivatives not on S232-AUTOS parts). May be followed by
                     ";also_with:<GROUP>[,...]" to declare that it intentionally stacks with
                     another action group of the same authority (e.g. steel and aluminum
                     derivative duties on the same product).
  exclusions_ref     where product exclusions are listed (citation or file)
  legal_status       see LEGAL_STATUSES
  source_type        see SOURCE_TYPES
  source_citation    e.g. "84 FR 43304" or "EO 14257"; required
  source_url         https URL on an official domain (OFFICIAL_DOMAINS); required
  verified_on        date the row was checked against the source; required, not in the future
  notes              free text

Overlap rule: two rows with the same authority whose countries, HS scopes and dates all overlap
are an error unless one supersedes the other (directly or through a chain), or their stacking
declares them mutually exclusive (not_with) or intentionally cumulative (also_with).

Run: make timeline-validate
"""

import csv
import re
import sys
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import polars as pl
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from tpt import config

ACTIONS_CSV = config.REFERENCE_DIR / "tariff_actions.csv"
COUNTRY_GROUPS_CSV = config.REFERENCE_DIR / "country_groups.csv"
COUNTRIES_CSV = config.REFERENCE_DIR / "census_countries.csv"
HS10_CODES = config.INTERIM_DIR / "hs10_codes.parquet"

COLUMNS = [
    "action_id", "action_group", "authority", "country_iso", "cty_code", "exclude_cty_codes",
    "hs_scope", "hs_exclude", "ch99_heading", "rate_type", "rate", "specific_rate", "specific_unit",
    "value_basis", "usmca", "effective_date", "end_date", "supersedes", "stacking",
    "exclusions_ref", "legal_status", "source_type", "source_citation", "source_url",
    "verified_on", "notes",
]  # fmt: skip

AUTHORITIES = (
    "S232",  # Trade Expansion Act 1962 s.232 (national security)
    "S301",  # Trade Act 1974 s.301 (unfair practices)
    "S201",  # Trade Act 1974 s.201 (safeguards)
    "S122",  # Trade Act 1974 s.122 (balance of payments surcharge)
    "S338",  # Tariff Act 1930 s.338 (discrimination against US commerce)
    "IEEPA_FENTANYL",
    "IEEPA_RECIPROCAL",
    "IEEPA_OTHER",
    "DE_MINIMIS",
    "AD_CVD",
    "OTHER",
)
LEGAL_STATUSES = ("in_effect", "terminated", "expired", "superseded", "struck_down", "refunded",
                  "stayed", "enjoined", "scheduled")  # fmt: skip
VALUE_BASES = ("full", "metal_content", "non_us_content", "unidentified_subset")
USMCA = ("exempt", "non_us_content")
SOURCE_TYPES = ("federal_register", "proclamation", "executive_order", "ustr_notice", "cbp_csms",
                "hts", "court_ruling", "statute", "other_official")  # fmt: skip
OFFICIAL_DOMAINS = (
    "federalregister.gov", "govinfo.gov", "whitehouse.gov", "ustr.gov", "cbp.gov", "usitc.gov",
    "supremecourt.gov", "uscourts.gov", "congress.gov", "commerce.gov", "trade.gov",
    "regulations.gov", "treasury.gov", "ecfr.gov", "archives.gov",
)  # fmt: skip
HS_TOKEN = re.compile(r"^(\d{2}|\d{4}|\d{6}|\d{8}|\d{10})$")
_IDS = r"[A-Z0-9_-]+(,[A-Z0-9_-]+)*"
STACKING = re.compile(rf"^(cumulative|not_with:{_IDS})(;also_with:{_IDS})?$")


def _none_if_blank(v):
    return None if isinstance(v, str) and not v.strip() else v


class TariffAction(BaseModel):
    action_id: str
    action_group: str
    authority: Literal[AUTHORITIES]  # type: ignore[valid-type]
    country_iso: str
    cty_code: str
    exclude_cty_codes: str | None = None
    hs_scope: str
    hs_exclude: str | None = None
    ch99_heading: str | None = None
    rate_type: Literal["ad_valorem", "specific", "ad_valorem_plus_specific", "all_in_floor"]
    rate: float | None = None
    specific_rate: float | None = None
    specific_unit: str | None = None
    value_basis: Literal[VALUE_BASES] | None = None  # type: ignore[valid-type]
    usmca: Literal[USMCA] | None = None  # type: ignore[valid-type]
    effective_date: date
    end_date: date | None = None
    supersedes: str | None = None
    stacking: str
    exclusions_ref: str | None = None
    legal_status: Literal[LEGAL_STATUSES]  # type: ignore[valid-type]
    source_type: Literal[SOURCE_TYPES]  # type: ignore[valid-type]
    source_citation: str
    source_url: str
    verified_on: date
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def blanks_to_none(cls, data: dict) -> dict:
        return {k: _none_if_blank(v) for k, v in data.items()}

    @field_validator("rate", "specific_rate", mode="before")
    @classmethod
    def plain_decimal(cls, v):
        if v is not None and not re.fullmatch(r"\d+(\.\d+)?", str(v).strip()):
            raise ValueError("must be a non-negative decimal such as 0.25 (no % sign)")
        return v

    @field_validator("country_iso")
    @classmethod
    def iso_format(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z]{2}|ALL|[A-Z][A-Z0-9_]+", v):
            raise ValueError("must be ISO alpha-2, ALL, or a country group name")
        return v

    @field_validator("ch99_heading")
    @classmethod
    def ch99_format(cls, v: str | None) -> str | None:
        if v and not all(re.fullmatch(r"99\d{2}\.\d{2}\.\d{2}", t) for t in _split(v)):
            raise ValueError("must be Chapter 99 headings like 9903.88.03, ';'-separated")
        return v

    @field_validator("stacking")
    @classmethod
    def stacking_rule(cls, v: str) -> str:
        if not STACKING.fullmatch(v):
            raise ValueError("must be 'cumulative' or 'not_with:X[,X...]', optionally followed by "
                             "';also_with:GROUP[,GROUP...]'")  # fmt: skip
        return v

    @field_validator("source_url")
    @classmethod
    def official_url(cls, v: str) -> str:
        url = urlparse(v)
        host = url.hostname or ""
        if url.scheme != "https" or not any(host == d or host.endswith("." + d)
                                            for d in OFFICIAL_DOMAINS):  # fmt: skip
            raise ValueError(f"must be an https URL on an official domain, got {v!r}")
        return v

    @field_validator("verified_on")
    @classmethod
    def not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("verified_on is in the future")
        return v

    @model_validator(mode="after")
    def consistent(self) -> "TariffAction":
        if self.end_date and self.end_date <= self.effective_date:
            raise ValueError("end_date must be after effective_date")
        if self.rate_type in ("ad_valorem", "ad_valorem_plus_specific", "all_in_floor") and (
            self.rate is None
        ):
            raise ValueError(f"rate required for rate_type {self.rate_type}")
        if self.rate_type in ("specific", "ad_valorem_plus_specific") and (
            self.specific_rate is None or not self.specific_unit
        ):
            raise ValueError(f"specific_rate and specific_unit required for {self.rate_type}")
        if self.rate is not None and self.rate > 10:
            raise ValueError("rate above 10 (1000%) looks like a percentage, use a decimal")
        if self.exclude_cty_codes and self.cty_code != "ALL":
            raise ValueError("exclude_cty_codes only applies to cty_code ALL")
        return self

    # derived

    @property
    def excluded(self) -> set[str]:
        return set(_split(self.exclude_cty_codes))

    @property
    def end(self) -> date:
        return self.end_date or date.max

    @property
    def not_with(self) -> set[str]:
        first = self.stacking.split(";")[0]
        return set(first.removeprefix("not_with:").split(",")) if first != "cumulative" else set()

    @property
    def also_with(self) -> set[str]:
        parts = self.stacking.split(";also_with:")
        return set(parts[1].split(",")) if len(parts) > 1 else set()


def _split(value: str | None) -> list[str]:
    return [t.strip() for t in (value or "").split(";") if t.strip()]


# --- loading -----------------------------------------------------------------


def read_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path.name}: header must be exactly {COLUMNS}")
        return list(reader)


def load_actions(path: Path = ACTIONS_CSV) -> list[TariffAction]:
    """Parse and type every row; raises ValueError listing all problems."""
    if errs := validate_file(path, check_references=False):
        raise ValueError("\n".join(errs))
    return [TariffAction.model_validate(r) for r in read_rows(path)]


# --- HS scope ----------------------------------------------------------------


def expand_scope(scope: str | None, base_dir: Path) -> set[str]:
    """';'-separated tokens -> set of HS prefixes ("ALL" kept as is; files read)."""
    out: set[str] = set()
    for token in _split(scope):
        if token.startswith("file:"):
            path = base_dir / token.removeprefix("file:")
            if path.exists():  # a missing file is reported by validate_file
                out |= set(_read_list(path))
        else:
            out.add(token)
    return out


@cache
def _read_list(path: Path) -> tuple[str, ...]:
    df = pl.read_csv(path, infer_schema=False)
    return tuple(df["hs"].str.strip_chars().drop_nulls())


class _PrefixIndex:
    def __init__(self, codes: set[str]):
        self.prefixes = {c[:n] for c in codes for n in (2, 4, 6, 8, 10)}

    def resolves(self, token: str) -> bool:
        return token in self.prefixes


def _scope_errors(label: str, scope: str | None, base: Path, index: _PrefixIndex | None,
                  required: bool) -> list[str]:  # fmt: skip
    tokens = _split(scope)
    if not tokens:
        return [f"{label}: empty"] if required else []
    errs = []
    for token in tokens:
        if token == "ALL":
            continue
        if token.startswith("file:"):
            path = base / token.removeprefix("file:")
            if not path.exists():
                errs.append(f"{label}: list file not found: {token.removeprefix('file:')}")
                continue
            codes = _read_list(path)
            bad = [c for c in codes if not HS_TOKEN.fullmatch(c)]
            unresolved = [c for c in codes if HS_TOKEN.fullmatch(c) and index
                          and not index.resolves(c)]  # fmt: skip
            if bad:
                errs.append(f"{label}: malformed codes in {path.name}: {bad[:10]}")
            if unresolved:
                errs.append(f"{label}: codes in {path.name} match no HS10: {unresolved[:10]}")
        elif not HS_TOKEN.fullmatch(token):
            errs.append(f"{label}: malformed HS token {token!r} (2/4/6/8/10 digits)")
        elif index and not index.resolves(token):
            errs.append(f"{label}: {token} matches no HS10 code")
    return errs


# --- overlaps ----------------------------------------------------------------


def expand_countries(tokens: set[str], groups: dict[str, set[str]]) -> set[str]:
    """Census codes and group names -> Census codes."""
    out: set[str] = set()
    for t in tokens:
        out |= groups.get(t, {t})
    return out


def _countries_overlap(a: TariffAction, b: TariffAction, groups: dict[str, set[str]]) -> bool:
    def members(x: TariffAction) -> set[str] | None:  # None = ALL
        if x.cty_code == "ALL":
            return None
        return groups.get(x.cty_code, {x.cty_code})

    ma, mb = members(a), members(b)
    if ma is None and mb is None:
        return True
    if ma is None:
        return bool(mb - expand_countries(a.excluded, groups))
    if mb is None:
        return bool(ma - expand_countries(b.excluded, groups))
    return bool(ma & mb)


def _hs_overlap(sa: set[str], sb: set[str]) -> bool:
    if "ALL" in sa or "ALL" in sb:
        return True
    small, large = sorted((sa, sb), key=len)
    for token in small:
        if any(token[:n] in large for n in range(2, len(token) + 1, 2)):
            return True
        if any(c.startswith(token) for c in large):
            return True
    return False


def _supersede_closure(actions: list[TariffAction]) -> set[tuple[str, str]]:
    """Pairs of actions linked by supersedes, directly or through a chain (both directions)."""
    links = {a.action_id: set(_split(a.supersedes)) for a in actions if a.supersedes}
    pairs = set()
    for start in links:
        stack, seen = list(links[start]), set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            pairs |= {(start, cur), (cur, start)}
            stack += links.get(cur, [])
    return pairs


def resolve_hs10(scope: str | None, exclude: str | None, base: Path, codes: set[str]) -> set[str]:
    """HS10 codes covered by a scope after exclusions ("ALL" = every code)."""

    def covered(prefixes: set[str]) -> set[str]:
        if "ALL" in prefixes:
            return set(codes)
        return {c for c in codes if any(c[:n] in prefixes for n in range(2, 11, 2))}

    return covered(expand_scope(scope, base)) - covered(expand_scope(exclude, base))


def _declared_apart(a: TariffAction, b: TariffAction) -> bool:
    """a's stacking says it never applies with b (not_with) or knowingly stacks on b."""
    return bool(a.not_with & {b.authority, b.action_group}) or b.action_group in a.also_with


def overlap_errors(actions: list[TariffAction], base: Path, groups: dict[str, set[str]],
                   hs10: set[str] | None = None) -> list[str]:  # fmt: skip
    """Same-authority rows overlapping in countries, dates and products, not linked by
    supersedes. With an HS10 universe, products are compared as HS10 sets net of hs_exclude;
    otherwise as prefixes (exclusions ignored, so more conservative)."""
    linked = _supersede_closure(actions)
    if hs10:
        sets = {a.action_id: resolve_hs10(a.hs_scope, a.hs_exclude, base, hs10) for a in actions}

        def products_overlap(x: TariffAction, y: TariffAction) -> bool:
            return bool(sets[x.action_id] & sets[y.action_id])
    else:
        scopes = {a.action_id: expand_scope(a.hs_scope, base) for a in actions}

        def products_overlap(x: TariffAction, y: TariffAction) -> bool:
            return _hs_overlap(scopes[x.action_id], scopes[y.action_id])

    errs = []
    for i, a in enumerate(actions):
        for b in actions[i + 1 :]:
            if a.authority != b.authority or (a.action_id, b.action_id) in linked:
                continue
            if _declared_apart(a, b) or _declared_apart(b, a):
                continue
            if a.effective_date >= b.end or b.effective_date >= a.end:
                continue
            if not _countries_overlap(a, b, groups):
                continue
            if products_overlap(a, b):
                errs.append(f"{a.action_id} / {b.action_id}: overlap in authority, countries, HS "
                            "scope and dates with no supersedes link")  # fmt: skip
    return errs


# --- validate ----------------------------------------------------------------


def _default_hs10() -> set[str] | None:
    if not HS10_CODES.exists():
        return None
    return set(pl.read_parquet(HS10_CODES, columns=["hs10"])["hs10"].unique())


def _default_countries() -> set[str]:
    df = pl.read_csv(COUNTRIES_CSV, infer_schema=False)
    return set(df.filter(pl.col("is_individual") == "true")["cty_code"])


def _groups() -> dict[str, set[str]]:
    if not COUNTRY_GROUPS_CSV.exists():
        return {}
    df = pl.read_csv(COUNTRY_GROUPS_CSV, infer_schema=False)
    return {g: set(sub["cty_code"]) for (g,), sub in df.group_by("group")}


def validate_file(
    path: Path = ACTIONS_CSV,
    hs10_codes: set[str] | None = None,
    cty_codes: set[str] | None = None,
    check_references: bool = True,
) -> list[str]:
    """Return a list of problems (empty = valid)."""
    try:
        rows = read_rows(path)
    except ValueError as exc:
        return [str(exc)]
    base = path.parent
    groups = _groups()
    hs10 = hs10_codes if hs10_codes is not None else (_default_hs10() if check_references else None)
    countries = cty_codes if cty_codes is not None else _default_countries()
    index = _PrefixIndex(hs10) if hs10 else None
    if rows and check_references and index is None:
        return ["HS10 code list missing: run `make ingest-reference` before validating"]

    errs: list[str] = []
    actions: list[TariffAction] = []
    for n, raw in enumerate(rows, start=2):
        label = f"line {n} ({raw.get('action_id') or '?'})"
        try:
            act = TariffAction.model_validate(raw)
        except ValidationError as exc:
            for e in exc.errors():
                field = ".".join(str(x) for x in e["loc"]) or "row"
                errs.append(f"{label}: {field}: {e['msg']}")
            continue
        actions.append(act)
        if check_references:
            valid_cty = countries | set(groups) | {"ALL"}
            if act.cty_code not in valid_cty:
                errs.append(f"{label}: cty_code {act.cty_code} is not an individual Census "
                            "country, a group in country_groups.csv, or ALL")  # fmt: skip
            bad_excl = act.excluded - countries - set(groups)
            if bad_excl:
                errs.append(f"{label}: exclude_cty_codes not Census countries: {sorted(bad_excl)}")
            errs += _scope_errors(f"{label}: hs_scope", act.hs_scope, base, index, required=True)
            errs += _scope_errors(f"{label}: hs_exclude", act.hs_exclude, base, index,
                                  required=False)  # fmt: skip

    ids = [a.action_id for a in actions]
    errs += [f"duplicate action_id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    names = set(AUTHORITIES) | {a.action_group for a in actions}
    errs += [f"{a.action_id}: stacking names unknown authority or action group {x}"
             for a in actions for x in sorted((a.not_with | a.also_with) - names)]  # fmt: skip
    known = set(ids)
    errs += [f"{a.action_id}: supersedes unknown action {sid}"
             for a in actions for sid in _split(a.supersedes) if sid not in known]  # fmt: skip
    pairs: dict[str, set[str]] = {}
    for a in actions:
        if a.country_iso not in ("ALL", *groups):
            pairs.setdefault(a.country_iso, set()).add(a.cty_code)
    errs += [f"country_iso {iso} used with several cty_codes: {sorted(c)}"
             for iso, c in pairs.items() if len(c) > 1]  # fmt: skip
    if check_references:
        errs += overlap_errors(actions, base, groups, hs10)
    return errs


def main() -> None:
    errs = validate_file()
    n = len(read_rows(ACTIONS_CSV))
    if errs:
        print(f"{ACTIONS_CSV.name}: {len(errs)} problem(s) in {n} rows")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    print(f"{ACTIONS_CSV.name}: {n} rows, valid")


if __name__ == "__main__":
    main()
