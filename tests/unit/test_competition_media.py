from __future__ import annotations

from fbi.catalog.media import league_media


def test_logos_and_flags_come_from_the_stored_leagues_payload() -> None:
    body = {"response": [
        {"league": {"id": 39, "name": "Premier League", "logo": "https://media.api-sports.io/football/leagues/39.png"},
         "country": {"name": "England", "code": "GB-ENG", "flag": "https://media.api-sports.io/flags/gb-eng.svg"}},
        {"league": {"id": 1, "name": "World Cup", "logo": "https://media.api-sports.io/football/leagues/1.png"},
         "country": {"name": "World", "code": None, "flag": None}},
        {"league": {"id": 2, "logo": "http://insecure.example/2.png"}, "country": {"code": "not a code"}},
        {"league": {"name": "no id"}},
    ]}
    got = {m.provider_league_id: m for m in league_media(body)}
    assert got[39].country_code == "GB-ENG" and got[39].flag_url and got[39].logo_url
    assert got[1].country_code is None and got[1].flag_url is None and got[1].logo_url
    # anything that is not an https URL or a country code is "not told", never stored
    assert got[2].logo_url is None and got[2].country_code is None
    assert set(got) == {39, 1, 2}
