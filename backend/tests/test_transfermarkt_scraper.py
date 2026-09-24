import pytest

from backend.sources import transfermarkt_scraper as tm


@pytest.mark.parametrize(
    "text, expected",
    [
        ("€45.00m", 45_000_000.0),
        ("€850k", 850_000.0),
        ("€1,50m", 1_500_000.0),
        ("  €10.5m ", 10_500_000.0),
        ("€2", 2.0),
        ("-", None),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_market_value(text, expected):
    assert tm.parse_market_value(text) == expected


def test_search_query_candidates_expand_ambiguous_fpl_names():
    # Bare FPL short names resolve to lookalike clubs, so they are aliased first.
    assert tm._search_query_candidates("Spurs")[0] == "Tottenham Hotspur"
    assert tm._search_query_candidates("Bournemouth")[0] == "AFC Bournemouth"
    assert tm._search_query_candidates("Nott'm Forest")[0] == "Nottingham Forest"


def test_search_query_candidates_strip_suffix_and_fall_back():
    assert tm._search_query_candidates("Crystal Palace FC") == ["Crystal Palace", "Crystal"]
    assert tm._search_query_candidates("Brighton & Hove Albion FC") == [
        "Brighton & Hove Albion",
        "Brighton and Hove Albion",
        "Brighton",
    ]
    assert tm._search_query_candidates("AFC Bournemouth")[0] == "AFC Bournemouth"


def test_pick_best_candidate_prefers_real_club_over_lookalike_with_same_suffix():
    # Regression: "Crystal Palace FC" used to exact-match the obscure id 77201
    # entry, so the real club (873) was never scraped.
    candidates = [
        ("Crystal Palace", "crystal-palace", "873"),
        ("Crystal Palace U21", "crystal-palace-u23", "6945"),
        ("Crystal Palace FC", "crystal-palace-fc", "77201"),
    ]
    assert tm._pick_best_candidate("Crystal Palace FC", candidates)[2] == "873"


def test_pick_best_candidate_falls_back_to_fuzzy_then_first():
    candidates = [("Wolverhampton Wanderers", "wolves", "543"), ("Other", "other", "1")]
    assert tm._pick_best_candidate("Wolverhampton Wanderers FC", candidates)[2] == "543"
    assert tm._pick_best_candidate("Zzzz", candidates)[2] == "543"


CLUB_SEARCH_HTML = """
<div class="box"><h2>Search results for players</h2></div>
<div class="box"><h2>Search results: Clubs</h2>
<table><tbody>
  <tr><td class="hauptlink"><a href="/crystal-palace/startseite/verein/873">Crystal Palace</a></td></tr>
  <tr><td class="hauptlink"><a href="/crystal-palace/startseite/verein/873">Crystal Palace</a></td></tr>
  <tr><td class="hauptlink"><a href="/not-a-club/profil/spieler/1">Ignored</a></td></tr>
</tbody></table></div>
"""


def test_find_club_candidates_parses_and_dedupes():
    assert tm._find_club_candidates(CLUB_SEARCH_HTML) == [("Crystal Palace", "crystal-palace", "873")]


def test_find_club_candidates_without_clubs_box_is_empty():
    assert tm._find_club_candidates("<div class='box'><h2>Players</h2></div>") == []


def _squad_row(name, position, age, country, value, contract="30/06/2028"):
    return f"""
    <tr>
      <td>1</td>
      <td><table class="inline-table">
            <tr><td class="hauptlink">{name}</td></tr>
            <tr><td>{position}</td></tr>
          </table></td>
      <td>{age}</td>
      <td><img title="{country}"/></td>
      <td>{contract}</td>
      <td>{value}</td>
    </tr>"""


SQUAD_HTML = f"""
<table class="items"><tbody>
{_squad_row("Erling Haaland", "Centre-Forward", 26, "Norway", "€220.00m")}
{_squad_row("Young Keeper", "Goalkeeper", "", "England", "-")}
<tr><td>too</td><td>short</td></tr>
</tbody></table>
"""


def test_fetch_squad_parses_rows(monkeypatch):
    monkeypatch.setattr(
        tm, "resolve_club_id",
        lambda name: {"name": "Manchester City FC", "slug": "manchester-city", "id": "281"},
    )
    monkeypatch.setattr(tm, "_get_html", lambda *a, **k: SQUAD_HTML)

    players = tm.fetch_squad("Manchester City FC")

    assert players == [
        {
            "name": "Erling Haaland",
            "position": "Centre-Forward",
            "age": 26,
            "nationality": "Norway",
            "club": "Manchester City FC",
            "market_value_eur": 220_000_000.0,
            "contract_expiry": "2028-06-30",
        },
        {
            "name": "Young Keeper",
            "position": "Goalkeeper",
            "age": None,
            "nationality": "England",
            "club": "Manchester City FC",
            "market_value_eur": None,
            "contract_expiry": "2028-06-30",
        },
    ]


def test_fetch_squad_labels_players_with_transfermarkt_club_name(monkeypatch):
    monkeypatch.setattr(
        tm, "resolve_club_id",
        lambda name: {"name": "Man City", "slug": "manchester-city", "id": "281"},
    )
    monkeypatch.setattr(tm, "_get_html", lambda *a, **k: SQUAD_HTML)

    assert {p["club"] for p in tm.fetch_squad("Man City")} == {"Man City"}


def test_fetch_squad_rejects_implausibly_cheap_squad(monkeypatch):
    """A lookalike club resolves and parses fine; only the value gives it away."""
    import pytest

    cheap = SQUAD_HTML.replace("€220.00m", "€50k")
    monkeypatch.setattr(
        tm, "resolve_club_id",
        lambda name: {"name": "Bournemouth", "slug": "bournemouth", "id": "83929"},
    )
    monkeypatch.setattr(tm, "_get_html", lambda *a, **k: cheap)

    with pytest.raises(RuntimeError, match="wrong club"):
        tm.fetch_squad("Bournemouth")


def test_fetch_squad_unresolved_club_returns_empty(monkeypatch):
    monkeypatch.setattr(tm, "resolve_club_id", lambda name: None)
    assert tm.fetch_squad("Nowhere FC") == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("30/06/2028", (2028, 6, 30)),
        (" 31/12/2026 ", (2026, 12, 31)),
        ("-", None),
        ("", None),
        ("on loan", None),
        ("31/02/2027", None),   # not a real date
    ],
)
def test_parse_contract_expiry(text, expected):
    result = tm.parse_contract_expiry(text)

    if expected is None:
        assert result is None
    else:
        assert (result.year, result.month, result.day) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("€95.00m", ("fee", 95_000_000.0)),
        ("€850k", ("fee", 850_000.0)),
        ("free transfer", ("free", None)),
        ("loan transfer", ("loan", None)),
        ("Loan fee: €100k", ("loan", None)),
        ("End of loan 30/06/2026", ("loan_return", None)),
        ("-", ("unknown", None)),
        ("?", ("unknown", None)),
    ],
)
def test_parse_fee(text, expected):
    assert tm.parse_fee(text) == expected


def _transfer_row(name, position, age, fee):
    return f"""
    <tr>
      <td></td>
      <td><table class="inline-table">
            <tr><td rowspan="2"><img/></td><td class="hauptlink"><a>{name}</a></td></tr>
            <tr><td>{position}</td></tr>
          </table></td>
      <td class="zentriert">{age}</td>
      <td class="zentriert"><img title="France"/></td>
      <td><table class="inline-table"><tr><td class="hauptlink"><a>Lille</a></td></tr></table></td>
      <td class="rechts hauptlink"><a>{fee}</a></td>
    </tr>"""


TRANSFERS_HTML = f"""
<div class="box"><h2>Arrivals</h2><table class="items"><tbody>
{_transfer_row("Ayyoub Bouaddi", "Defensive Midfield", 18, "€95.00m")}
{_transfer_row("Vitor Reis", "Centre-Back", 20, "End of loan<br/><i>30/06/2026</i>")}
<tr><td>too</td><td>short</td></tr>
</tbody></table></div>
<div class="box"><h2>Departures</h2><table class="items"><tbody>
{_transfer_row("Rodri", "Defensive Midfield", 30, "€60.00m")}
</tbody></table></div>
"""


def test_fetch_arrivals_reads_only_the_arrivals_table(monkeypatch):
    monkeypatch.setattr(tm, "resolve_club_id", lambda name: {"slug": "manchester-city", "id": "281"})
    monkeypatch.setattr(tm, "_get_html", lambda *a, **k: TRANSFERS_HTML)

    assert tm.fetch_arrivals("Man City", 2026) == [
        {"name": "Ayyoub Bouaddi", "age": 18, "club": "Man City", "season": 2026,
         "fee_kind": "fee", "fee_eur": 95_000_000.0},
        {"name": "Vitor Reis", "age": 20, "club": "Man City", "season": 2026,
         "fee_kind": "loan_return", "fee_eur": None},
    ]


def test_fetch_arrivals_unresolved_club_returns_empty(monkeypatch):
    monkeypatch.setattr(tm, "resolve_club_id", lambda name: None)
    assert tm.fetch_arrivals("Nowhere FC", 2026) == []


class _Response:
    def __init__(self, text, ok=True):
        self.text = text
        self.ok = ok

    def raise_for_status(self):
        if not self.ok:
            raise tm.requests.HTTPError("503")


def _cached_page(tmp_path, monkeypatch, age_hours):
    import os
    import time

    monkeypatch.setattr(tm, "TRANSFERMARKT_RAW_DIR", tmp_path)
    monkeypatch.setattr(tm, "_throttle", lambda: None)
    page = tmp_path / "squad_11.html"
    page.write_text("cached")
    old = time.time() - age_hours * 3600
    os.utime(page, (old, old))


def test_get_html_reuses_a_fresh_page_without_a_request(tmp_path, monkeypatch):
    _cached_page(tmp_path, monkeypatch, age_hours=1)
    monkeypatch.setattr(tm.requests, "get", lambda *a, **k: pytest.fail("should not fetch"))

    assert tm._get_html("https://x", "squad_11", max_age_hours=24) == "cached"


def test_get_html_refetches_a_stale_page(tmp_path, monkeypatch):
    _cached_page(tmp_path, monkeypatch, age_hours=200)
    monkeypatch.setattr(tm.requests, "get", lambda *a, **k: _Response("fresh"))

    assert tm._get_html("https://x", "squad_11", max_age_hours=168) == "fresh"
    assert (tmp_path / "squad_11.html").read_text() == "fresh"


def test_get_html_falls_back_to_the_stale_page_when_the_refetch_fails(tmp_path, monkeypatch):
    _cached_page(tmp_path, monkeypatch, age_hours=200)
    monkeypatch.setattr(tm.requests, "get", lambda *a, **k: _Response("", ok=False))

    assert tm._get_html("https://x", "squad_11", max_age_hours=168) == "cached"


def test_get_html_keeps_pages_without_a_max_age_for_good(tmp_path, monkeypatch):
    _cached_page(tmp_path, monkeypatch, age_hours=10_000)
    monkeypatch.setattr(tm.requests, "get", lambda *a, **k: pytest.fail("should not fetch"))

    assert tm._get_html("https://x", "squad_11") == "cached"
