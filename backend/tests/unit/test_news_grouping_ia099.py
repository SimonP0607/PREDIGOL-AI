"""IA-099 (AD-G02): duplicates and stories, ``stories-v1`` - pure, no database.

The file's tests: canonical URL and fingerprint (``canon-v1``/``fp-v1`` are IA-080's: a new version of the same article is the same item),
a wire copy reprinted by five outlets is ONE story with five sources, near duplicates, the same fact by its entities, across languages,
broad types never merged by entities alone, the window, and a second pass that moves nothing (incremental)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.news import canonical, grouping
from fbi.news.grouping import ItemSignal, OpenStory

AT = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
WIRE = "Atlético Nacional confirma la baja de su delantero para la final ante Junior"


def item(n: int, title: str | None, *, domain: str = "a.invalid", url: str | None = None, minutes: int = 0, lang: str | None = "es",
         teams: frozenset[int] = frozenset(), players: frozenset[int] = frozenset(), claim: str | None = None,
         content: str | None = None) -> ItemSignal:
    u = url or f"https://{domain}/n/{n}"
    return ItemSignal(n, canonical.url_sha256(u), canonical.fingerprint(content or title or u), domain, AT + timedelta(minutes=minutes),
                      AT + timedelta(minutes=minutes - 5), title, lang, claim, teams, players)


def keyed(seed: object) -> str:
    return f"st-{str(seed)[:24]}"


def stories(assigned: list[grouping.Assignment]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for a in assigned:
        out.setdefault(a.story_key, []).append(a.item_id)
    return out


def test_tracking_parameters_amp_and_mobile_are_the_same_canonical_url() -> None:
    a = canonical.canonical_url("http://m.medio.invalid/futbol/nota-1/amp?utm_source=x&fbclid=1")
    b = canonical.canonical_url("https://www.medio.invalid/futbol/nota-1/")
    assert a == b == "https://medio.invalid/futbol/nota-1"
    assert canonical.fingerprint("BAJA de Pérez, ¡confirmada!") == canonical.fingerprint("baja de perez confirmada")


def test_a_wire_copy_reprinted_by_five_outlets_is_one_story_with_five_sources() -> None:
    copies = [item(i, WIRE, domain=f"medio{i}.invalid", minutes=i * 7, teams=frozenset({11})) for i in range(1, 6)]
    found = grouping.group(copies, [], story_key=keyed)
    groups = stories(found)
    assert len(groups) == 1 and sorted(next(iter(groups.values()))) == [1, 2, 3, 4, 5]
    assert [a.method for a in found] == ["url", "huella", "huella", "huella", "huella"]
    assert found[0].new_story and not any(a.new_story for a in found[1:])


def test_a_new_version_of_an_article_already_in_a_story_stays_in_it() -> None:
    first = item(1, WIRE, url="https://medio.invalid/n/1")
    open_story = OpenStory("st-open-story", [first])
    again = item(2, WIRE + " (actualizado)", url="https://www.medio.invalid/n/1/?utm_campaign=x", minutes=30)
    (a,) = grouping.group([again], [open_story], story_key=keyed)
    assert (a.story_key, a.method, a.new_story) == ("st-open-story", "url", False)


def test_a_reworded_title_is_a_near_duplicate_and_another_fact_is_not() -> None:
    a = item(1, "Nacional confirma la baja de su delantero Pérez para la final ante Junior")
    b = item(2, "Nacional confirma baja del delantero Pérez para final ante Junior", domain="b.invalid", minutes=20)
    c = item(3, "Millonarios presenta a su nuevo entrenador para 2027", domain="c.invalid", minutes=30)
    found = grouping.group([a, b, c], [], story_key=keyed)
    assert found[1].method == "similitud" and found[1].story_key == found[0].story_key
    assert found[2].new_story


def test_the_same_fact_by_its_player_and_by_its_team_with_shared_words() -> None:
    a = item(1, "Pérez, baja ante Junior por lesión", teams=frozenset({11}), players=frozenset({901}))
    b = item(2, "El delantero no estará el domingo: lesión muscular", domain="b.invalid", minutes=90, teams=frozenset({11}),
             players=frozenset({901}))
    c = item(3, "Otra lesión en el club: el lateral Gómez también se lesionó ante Junior", domain="c.invalid", minutes=120,
             teams=frozenset({11}), players=frozenset({902}))
    found = grouping.group([a, b, c], [], story_key=keyed)
    assert found[1].method == "entidades" and found[1].story_key == found[0].story_key
    assert found[2].new_story, "another player of the same team, few shared words: another fact"


def test_broad_types_are_never_merged_by_their_entities_alone() -> None:
    a = item(1, "Análisis: cómo juega Nacional", teams=frozenset({11}), players=frozenset({901}), claim="analisis")
    b = item(2, "La previa de Nacional y su once", domain="b.invalid", teams=frozenset({11}), players=frozenset({901}), claim="analisis")
    found = grouping.group([a, b], [], story_key=keyed)
    assert len(stories(found)) == 2


def test_the_same_fact_in_another_language_is_the_same_story() -> None:
    a = item(1, "Pérez se pierde la final por lesión", teams=frozenset({11, 12}), players=frozenset({901}), lang="es")
    b = item(2, "Pérez ruled out of the final with an injury", domain="en.invalid", minutes=200, teams=frozenset({11, 12}),
             players=frozenset({901}), lang="en")
    found = grouping.group([a, b], [], story_key=keyed)
    assert found[1].method == "idiomas" and found[1].story_key == found[0].story_key


def test_an_item_beyond_the_window_opens_a_new_story() -> None:
    a = item(1, WIRE, teams=frozenset({11}))
    late = item(2, WIRE, domain="b.invalid", minutes=int(grouping.WINDOW.total_seconds() // 60) + 60, teams=frozenset({11}))
    found = grouping.group([a, late], [], story_key=keyed)
    assert found[1].new_story


def test_a_second_pass_groups_only_what_is_new_and_moves_nothing() -> None:
    first = [item(i, WIRE, domain=f"medio{i}.invalid", minutes=i) for i in range(1, 4)]
    pass1 = grouping.group(first, [], story_key=keyed)
    key = pass1[0].story_key
    open_story = OpenStory(key, list(first))
    newcomer = item(9, WIRE, domain="medio9.invalid", minutes=60)
    pass2 = grouping.group([newcomer], [open_story], story_key=keyed)
    assert [(a.item_id, a.story_key, a.method) for a in pass2] == [(9, key, "huella")]


def test_simhash_is_a_signed_bigint_and_short_titles_have_none() -> None:
    h = grouping.simhash(WIRE)
    assert h is not None and -(2 ** 63) <= h < 2 ** 63
    assert grouping.simhash("Gol") is None
    assert grouping.bits_apart(h, h) == 0


def test_the_type_of_claim_of_a_title() -> None:
    assert grouping.claim_type_of_title("Pérez, baja por lesión") == "lesiones"
    assert grouping.claim_type_of_title("Suspendido tres fechas tras la roja") == "sanciones"
    assert grouping.claim_type_of_title("Millonarios ficha a un lateral") == "fichajes"
    assert grouping.claim_type_of_title("Real Madrid could sign a striker") == "fichajes", "a transfer rumour is a transfer (level: rumour)"
    assert grouping.claim_type_of_title("Real Madrid linked with a striker") == "rumores"
    assert grouping.claim_type_of_title("Una tarde en el estadio") == "contexto"


def test_the_measure_of_a_replay_counts_exact_and_near_duplicates() -> None:
    items = [item(1, WIRE, url="https://a.invalid/x"), item(2, WIRE, url="https://a.invalid/x?utm_source=1", minutes=1),
             item(3, WIRE, domain="b.invalid", minutes=2), item(4, "Otro hecho distinto sin relación alguna", domain="c.invalid", minutes=3)]
    m = grouping.measure(items).as_json()
    assert m["items"] == 4 and m["stories"] == 2
    assert m["exact_duplicates"] == 2 and m["stories_with_2plus_domains"] == 1


def test_a_pass_of_three_thousand_items_is_fast() -> None:
    import random
    import time

    rnd = random.Random(7)
    vocab = [f"palabra{i}" for i in range(400)]
    items = [item(n, " ".join(rnd.sample(vocab, 8)), domain=f"m{n % 40}.invalid", minutes=n * 7, teams=frozenset({rnd.randint(1, 300)}),
                  claim=rnd.choice(["lesiones", "fichajes", "contexto"])) for n in range(3000)]
    start = time.monotonic()
    found = grouping.group(items, [], story_key=keyed)
    assert len(found) == 3000 and time.monotonic() - start < 20


def test_a_sites_templates_about_different_matches_are_never_one_story() -> None:
    """The first replay's false merges (17-nov-2026): «X vs Y Preview & Prediction | ...» of one site, one story per match."""
    a = item(1, "Bonaire vs Cuba Preview & Prediction | 2026-27 CONCACAF Nations League", domain="stats.invalid", teams=frozenset({1, 2}),
             claim="calendario")
    b = item(2, "Aruba vs Martinique Preview & Prediction | 2026-27 CONCACAF Nations League", domain="stats.invalid", minutes=5,
             teams=frozenset({3, 4}), claim="calendario")
    c = item(3, "Bonaire vs Cuba: preview & prediction, CONCACAF Nations League", domain="other.invalid", minutes=9, teams=frozenset({1, 2}),
             claim="calendario")
    found = grouping.group([a, b, c], [], story_key=keyed)
    assert found[1].new_story, "other teams: another story"
    assert found[2].story_key == found[0].story_key and found[2].method == "similitud"


def test_titles_in_chinese_are_compared_by_their_characters_not_by_their_digits() -> None:
    a = item(1, "【国际友谊十一月】立陶宛vs苏里南伤病名单最新(2026年11月13日)", domain="q.invalid")
    b = item(2, "【国际友谊十一月】法国U20vs丹麦U20伤病名单最新(2026年11月13日)", domain="q2.invalid", minutes=3)
    assert "立" in grouping.tokens(a.title) and "2026" not in grouping.tokens(a.title)
    found = grouping.group([a, b], [], story_key=keyed)
    assert found[1].new_story, "Lithuania-Suriname and France U20-Denmark U20 are two stories"
    same = item(3, "【國際友誼十一月】阿聯酋vs洪都拉斯傷病名單最新(2026年11月13日)", domain="q3.invalid", content="x 2026 11 13")
    other = item(4, "【國際友誼十一月】中國臺北vs吉爾吉斯斯坦傷病名單最新(2026年11月13日)", domain="q4.invalid", minutes=2,
                 content="x 2026 11 13")
    pair = grouping.group([same, other], [], story_key=keyed)
    assert pair[1].method != "huella", "a fingerprint shared by folding everything away is not the same text"


def test_one_outlets_templates_and_two_different_pairs_are_two_stories() -> None:
    a = item(1, "Sheffield Wednesday v Accrington preview | WAWAW News", domain="w.invalid", claim="calendario")
    b = item(2, "Sheffield Wednesday v Plymouth preview | WAWAW News", domain="w.invalid", minutes=4, claim="calendario")
    c = item(3, "Sheffield Wednesday v Plymouth: preview and team news", domain="x.invalid", minutes=6, claim="calendario")
    d = item(4, "Sheffield Wednesday vs Plymouth preview, team news", domain="y.invalid", minutes=8, claim="calendario")
    found = grouping.group([a, b, c, d], [], story_key=keyed)
    assert found[1].new_story, "the same outlet's template about another match"
    assert found[2].new_story is False and found[2].story_key == found[1].story_key
    assert found[3].story_key == found[1].story_key
    assert grouping.versus("Preview: Mansfield Town vs Chesterfield - prediction") == (frozenset({"town"}),
                                                                                       frozenset({"chesterfield"}))
    assert grouping.conflict(a, b) and not grouping.conflict(b, c)


def test_subdomains_are_one_outlet_and_a_womens_or_youth_side_is_another_team() -> None:
    assert grouping.outlet("zht.qiumiwu.com") == grouping.outlet("m.qiumiwu.com") == "qiumiwu.com"
    assert grouping.outlet("www.bbc.co.uk") == "bbc.co.uk"
    men = item(1, "Köln vs Leipzig Tipp, Prognose & Quoten", domain="a.invalid", claim="calendario")
    women = item(2, "Köln vs Leipzig Frauen Tipp, Prognose & Quoten", domain="b.invalid", minutes=3, claim="calendario")
    assert grouping.conflict(men, women)
    a = item(3, "【国际友谊十一月】越南U23vs泰国U23伤病名单最新", domain="m.q.invalid", teams=frozenset({5}), claim="lesiones")
    b = item(4, "【國際友誼十一月】泰國U23vs卡塔爾U23傷病名單最新", domain="zht.q.invalid", teams=frozenset({5}), claim="lesiones")
    assert grouping.versus(a.title) is not None and grouping.conflict(a, b)
