"""Federal Register API client: document metadata, full text and HTS codes in annexes (P08+).

API: https://www.federalregister.gov/api/v1 (no key). Used to verify tariff actions
(citation, publication and effective dates, URL) and to extract annex product lists, which
are published as HTS8 (sometimes HTS10) numbers in the document text, e.g. "8471.30.01".
"""

import re

from tpt.ingest._http import CachedClient, Source

API = "https://www.federalregister.gov/api/v1"
FIELDS = ["document_number", "citation", "title", "type", "publication_date", "effective_on",
          "signing_date", "html_url", "raw_text_url", "agencies", "presidential_document_number",
          "executive_order_number", "proclamation_number"]  # fmt: skip

SOURCE = Source("federalregister", 0.5)
HTS_RE = re.compile(r"(?<![\d.])(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d{2}))?(?![\d.])")


def client() -> CachedClient:
    return CachedClient(SOURCE)


def search(
    c: CachedClient,
    term: str,
    *,
    since: str | None = None,
    until: str | None = None,
    agency: str | None = None,
    doc_type: str | None = None,
    per_page: int = 100,
) -> list[dict]:
    """Full-text search; doc_type e.g. PRESDOCU, NOTICE, RULE. Agency slug e.g.
    'trade-representative-office-of-united-states'."""
    params: dict[str, str | list[str]] = {"conditions[term]": term, "per_page": str(per_page),
                                          "order": "oldest", "fields[]": FIELDS}  # fmt: skip
    if since:
        params["conditions[publication_date][gte]"] = since
    if until:
        params["conditions[publication_date][lte]"] = until
    if agency:
        params["conditions[agencies][]"] = agency
    if doc_type:
        params["conditions[type][]"] = doc_type
    return c.get(f"{API}/documents.json", params).json().get("results", [])


def document(c: CachedClient, number: str) -> dict:
    return c.get(f"{API}/documents/{number}.json", {"fields[]": FIELDS}).json()


def full_text(c: CachedClient, doc: dict) -> str:
    return c.get(doc["raw_text_url"]).text


def hts_codes(text: str, include_ch99: bool = False) -> list[str]:
    """HTS numbers in text, digits only, in order of first appearance (HTS8 or HTS10)."""
    seen: dict[str, None] = {}
    for m in HTS_RE.finditer(text):
        code = "".join(g for g in m.groups() if g)
        if not include_ch99 and code.startswith(("98", "99")):
            continue
        seen.setdefault(code, None)
    return list(seen)
