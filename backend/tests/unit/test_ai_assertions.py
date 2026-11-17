"""``assertions-v1`` / ``ladder-v2`` (IA-089, plan piece AD-C07): authority per type of claim, the ladder by independent ORIGIN (syndication
counts once), the four dates, the leak guard and the contradictions - alerts, never corrections."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fbi.ai import deep_pages
from fbi.ai.assertions import (
    LADDER_VERSION,
    RANK,
    Assertion,
    SourceFacts,
    as_of,
    authority_for,
    contradictions,
    facts,
    four_dates,
    rung,
    source_facts,
    speaker_of,
)
from fbi.ai.source_policy import SourcePolicy
from fbi.ai.source_registry import Source, parse_authority

AT = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
KICKOFF = AT + timedelta(hours=20)
CLUB = SourceFacts("alfafc.example", "x-alfa", "Alfa FC", "oficial",
                   parse_authority("convocatorias:confirma; alineaciones:confirma; lesiones:confirma (solo lo propio); rumores:sin_autoridad"),
                   clubs=("Alfa FC",))
PRESS = parse_authority("lesiones:informa; convocatorias:informa; alineaciones:informa (probables); declaraciones:informa (cita); "
                        "rumores:solo_rumor")
STORY = ("Delantero Uno se perderá el partido ante Beta FC por una lesión muscular, informó el club. El jugador estará de baja entre dos y "
         "tres semanas, según el parte médico. ") * 3


def press(domain: str, *, group: str = "", network: str = "", tier: str | None = "C") -> SourceFacts:
    return SourceFacts(domain, f"id-{domain}", domain, "prensa_deportiva", PRESS, group, network, (), tier)


def item(src: SourceFacts, *, claim: str = "OUT", subject: int = 91001, text: str = STORY, speaker: str | None = None,
         seen: datetime = AT - timedelta(hours=2), quote: str = "Delantero Uno se perderá el partido") -> Assertion:
    level, why = authority_for(src, claim, team_names=["Alfa FC"], quote=quote)
    pub, origin, seen_at, fact, until = four_dates(published_at=seen - timedelta(hours=1), seen_at=seen, kickoff_at=KICKOFF,
                                                   applies_to="THIS_MATCH", claim_type=claim)
    return Assertion("PLAYER", subject, 1, claim, f"https://{src.domain}/n", src, level, why, seen_at, pub, origin, fact, until, "THIS_MATCH",
                     1, speaker, deep_pages.simhash(text), quote)


def test_version() -> None:
    assert LADDER_VERSION == "ladder-v2"


def test_a_club_confirms_its_own_absentees_and_only_informs_about_another_team() -> None:
    assert authority_for(CLUB, "OUT", team_names=["Alfa FC"]) == ("confirma", "directory:lesiones")
    assert authority_for(CLUB, "OUT", team_names=["Beta FC"])[0] == "informa"
    assert authority_for(CLUB, "STARTER", team_names=["Alfa FC"])[0] == "confirma"


def test_the_press_never_confirms_and_a_rumour_is_a_rumour() -> None:
    p = press("diario.example")
    assert authority_for(p, "OUT")[0] == "informa"
    assert authority_for(p, "OUT", quote="Según fuentes del club, Delantero Uno podría perderse el partido")[0] == "solo_rumor"
    assert authority_for(None, "OUT")[0] == "desconocida"


def test_the_ladder() -> None:
    assert rung([item(CLUB)])[0] == "OFICIAL"
    assert rung([item(press("a.example"))])[0] == "REPORTE"
    two = [item(press("a.example"), text=STORY), item(press("b.example"), text="Otra crónica distinta: Delantero Uno, baja. " * 6)]
    assert rung(two)[0] == "CONFIRMADO"
    assert rung([item(press("a.example"), speaker="coach:1")])[0] == "DECLARACION"
    assert rung([item(press("blog.example", tier="D")), item(press("tips.example", tier="D"), text="x " * 50)])[0] == "RUMOR"


def test_three_copies_of_one_wire_are_one_origin() -> None:
    copies = [item(press(d), text=pre + STORY) for d, pre in (("a.example", ""), ("b.example", "Última hora. "), ("c.example", "AGENCIA. "))]
    assert rung(copies) == ("REPORTE", "one origin informs")


def test_the_same_group_or_network_counts_once() -> None:
    a = item(press("mirror.example", group="reach plc"), text=STORY)
    b = item(press("express.example", network="reach plc"), text="Crónica propia sin relación: Delantero Uno baja. " * 6)
    assert rung([a, b])[0] == "REPORTE"


def test_the_same_speaker_quoted_by_two_outlets_is_one_origin() -> None:
    a = item(press("a.example"), speaker="coach:1")
    b = item(press("b.example"), speaker="coach:1", text="Distinto texto, el técnico habló de Delantero Uno. " * 6)
    assert rung([a, b])[0] == "DECLARACION"


def test_property_more_corroboration_never_lowers_a_rung_and_d_never_lifts() -> None:
    rng = random.Random(7)
    pool = [item(press(f"m{i}.example", group=rng.choice(["", "g1", "g2"]), tier=rng.choice(["B", "C", "D"])),
                 text=rng.choice([STORY, f"Texto propio número {i} sobre Delantero Uno. " * 6]), speaker=rng.choice([None, None, "coach:1"]),
                 quote=rng.choice(["Delantero Uno se perderá el partido", "Delantero Uno podría perderse el partido"])) for i in range(30)]
    pool.append(item(CLUB))
    for _ in range(400):
        base = rng.sample(pool, rng.randint(0, 5))
        more = base + rng.sample(pool, rng.randint(1, 4))
        assert RANK[rung(more)[0]] >= RANK[rung(base)[0]]
        only_d = [replace(a, source=replace(a.source, tier="D")) for a in more]
        assert rung(only_d)[0] == "RUMOR"


def test_four_dates() -> None:
    pub, origin, seen, fact, until = four_dates(published_at=AT + timedelta(days=2), seen_at=AT, kickoff_at=KICKOFF, applies_to="UNSPECIFIED",
                                                claim_type="OUT")
    assert pub is None and origin == "none", "a page date in the future of when it was seen is not a date"
    assert seen == AT and fact == AT and until > AT
    pub, origin, _, fact, _ = four_dates(published_at=AT - timedelta(hours=3), seen_at=AT, kickoff_at=KICKOFF, applies_to="THIS_MATCH",
                                         claim_type="OUT")
    assert origin == "page" and pub == AT - timedelta(hours=3) and fact == KICKOFF


def test_a_fact_seen_after_the_decision_does_not_exist_for_it() -> None:
    early, late = item(press("a.example"), seen=AT - timedelta(hours=3)), item(CLUB, seen=AT + timedelta(hours=1))
    assert as_of([early, late], AT) == [early]
    assert [f.rung for f in facts([early, late], at=AT)] == ["REPORTE"]
    assert all(a.seen_at <= AT for a in as_of([early, late], AT))


def test_contradictions_are_alerts() -> None:
    out = item(press("a.example"))
    back = replace(item(press("b.example"), claim="AVAILABLE", text="Delantero Uno vuelve y estará disponible. " * 6),
                   quote="Delantero Uno vuelve y estará disponible")
    alerts = contradictions([out, back], at=AT)
    assert [a.rule for a in alerts] == ["CC1"]
    assert rung([out])[0] == "REPORTE", "an alert never corrects"
    s1, s2 = replace(out, attributed_to="coach:1"), replace(back, attributed_to="coach:1")
    assert [a.rule for a in contradictions([s1, s2], at=AT)] == ["CS1"]


def test_an_official_time_that_differs_from_the_provider_raises_co1() -> None:
    official = replace(item(CLUB, claim="SCHEDULE"), authority="confirma", quote="El partido ante Beta FC se jugará a las 18:30 en el estadio")
    assert [a.rule for a in contradictions([official], at=AT, kickoff_times={"20:00", "15:00"})] == ["CO1"]
    assert contradictions([official], at=AT, kickoff_times={"18:30"}) == []
    ground = replace(official, claim_type="VENUE", quote="El partido se jugará en el Estadio Nuevo por obras")
    assert [a.rule for a in contradictions([ground], at=AT, venue="Estadio Viejo", venues=["Estadio Nuevo", "Estadio Viejo"])] == ["CO2"]


def test_speaker_by_code() -> None:
    assert speaker_of("El entrenador dijo en rueda de prensa que Delantero Uno no estará", team_id=1) == "coach:1"
    assert speaker_of("Delantero Uno dijo: «estoy listo»", team_id=1, players=[91001]) == "player:91001"
    assert speaker_of("Delantero Uno no jugará, confirmó el club", team_id=1, players=[91001]) == "club:1"
    assert speaker_of("Delantero Uno no estará", team_id=1, players=[91001]) is None


def test_source_facts_reads_group_and_network_from_the_directory() -> None:
    record = {"grupo_editorial": "Reach plc", "sindicacion": "Red Reach plc (Mirror, Express): artículos compartidos", "clubes_cubiertos": ""}
    src = Source("uk-mirror", "mirror.co.uk", "Mirror", "B", "prensa_generalista", "verificada_pendiente_derechos", "no_revisado", "no_revisado",
                 "", "", parse_authority("lesiones:informa"), None, record=record)
    policy = SourcePolicy([src], [], directory_version="t", exclusion_version="t", origin="test")
    got = source_facts(policy, "https://www.mirror.co.uk/sport/x")
    assert got.domain == "mirror.co.uk" and got.group == "reach plc" and got.network == "reach plc"
