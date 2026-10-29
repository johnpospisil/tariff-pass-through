"""Product explorer in a browser (P23): loads under 3 s on the bundle, search works, charts
render, dark mode switches palette. Needs the rendered site (`make report`) and
`playwright install chromium-headless-shell` (`make setup`); skipped otherwise."""

import functools
import http.server
import threading
import time

import pytest

from tpt import config

SITE = config.REPORT_DIR / "_site"
pw = pytest.importorskip("playwright.sync_api")
SEARCH = "washing machines, toys, 8450 …"
CHARTS = ("#chart-tariff svg", "#chart-price svg", "#chart-sources svg")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    if not (SITE / "explore.html").exists() or not (SITE / "explorer_data/index.json").exists():
        pytest.skip("site not rendered (make report)")
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Quiet, directory=str(SITE))
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def session(server):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser binary not installed
            pytest.skip(f"chromium unavailable: {e}")
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        t0 = time.perf_counter()
        page.goto(f"{server}/explore.html")
        for sel in CHARTS:
            page.wait_for_selector(sel, timeout=15_000)
        yield {"page": page, "load_s": time.perf_counter() - t0, "errors": errors}
        browser.close()


def _search(page, text: str) -> str:
    """Type a query; return the HS10 shown in the product header once it updates."""
    page.get_by_placeholder(SEARCH).fill(text)
    page.wait_for_timeout(300)
    for sel in CHARTS:
        page.wait_for_selector(sel)
    return page.locator("#explorer-product h3").inner_text()


def _first_code(page) -> str:
    return page.locator("#explorer-results tbody tr").first.locator("td").nth(1).inner_text()


def test_loads_under_three_seconds_with_charts(session):
    print(f"explorer load to first charts: {session['load_s']:.2f}s")
    assert session["load_s"] < 3.0
    assert session["errors"] == []


def test_default_product_is_a_washing_machine(session):
    page = session["page"]
    assert _first_code(page).startswith("8450.")
    assert page.locator("#explorer-product h3").inner_text().startswith("8450.")


@pytest.mark.parametrize(("query", "prefix"), [
    ("toys", "9503."), ("laptops", "8471.30"), ("solar panels", "8541.43"),
    ("8517.13", "8517.13"),
])  # fmt: skip
def test_search_finds_product_and_redraws(session, query, prefix):
    page = session["page"]
    header = _search(page, query)
    assert _first_code(page).startswith(prefix), query
    assert header.startswith(prefix), header
    # the tariff chart draws one line per named supplier
    assert page.locator("#chart-tariff svg path[stroke]").count() >= 1


def test_choosing_another_row_updates_product(session):
    page = session["page"]
    _search(page, "toys")
    row = page.locator("#explorer-results tbody tr").nth(1)
    code = row.locator("td").nth(1).inner_text()
    row.locator("input").check()
    page.wait_for_function(
        "c => document.querySelector('#explorer-product h3').innerText.startsWith(c)", arg=code
    )
    assert page.locator("#chart-price svg[viewBox]").count() >= 1


def test_no_match_message(session):
    page = session["page"]
    page.get_by_placeholder(SEARCH).fill("zzqx")
    page.wait_for_selector(".explorer-empty")
    assert "No product matches" in page.locator(".explorer-empty").inner_text()


def test_dark_mode_switches_chart_palette(session):
    page = session["page"]
    _search(page, "washing machines")
    page.locator(".quarto-color-scheme-toggle").first.click()
    page.wait_for_function("document.body.classList.contains('quarto-dark')")
    page.wait_for_timeout(300)
    html = page.locator("#chart-price").inner_html()
    assert "#3987e5" in html and "#2a78d6" not in html
    page.locator(".quarto-color-scheme-toggle").first.click()
    assert session["errors"] == []
