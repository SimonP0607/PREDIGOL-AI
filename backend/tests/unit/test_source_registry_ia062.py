"""IA-062 (plan piece AD-C01): the registry of sources as versioned data - the directory v2 and the exclusion list, pinned files of
``config/sources`` read by ``fbi.ai.source_registry``. No database: the files, their pins and what they say."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from fbi.ai import source_registry as registry
from fbi.ai.evidence import seed_rows


@pytest.fixture(scope="module")
def directory() -> registry.Directory:
    return registry.bundled_directory()


@pytest.fixture(scope="module")
def rules() -> tuple[registry.DomainRule, ...]:
    return registry.bundled_exclusion()


def test_the_directory_has_the_2001_sources_with_the_counts_of_the_report(directory: registry.Directory) -> None:
    counts = directory.counts()
    assert counts["sources"] == 2001
    assert counts["states"] == {"verificada_autorizada": 3, "verificada_pendiente_derechos": 1289, "solo_referencia": 71,
                                "no_comprobada": 153, "bloqueada": 485}, "the counts per state of the directory v2 (section 2.1)"
    assert counts["families"] == {"A": 276, "B": 498, "C": 230, "D": 326, "E": 671}, "section 2.2"
    assert len({s.source_id for s in directory.sources}) == 2001, "one id per source"
    assert sum(1 for s in directory.sources if s.record.get("origen") == "directorio v1") == 659, "the 659 sources of v1 keep their ids"
    assert {s.source_id for s in directory.sources if s.state == "verificada_autorizada"} == {
        "bra-agencia-brasil-esportes", "co-elnuevodia", "es-apunt-esports"}


def test_every_record_keeps_its_52_fields_and_the_file_says_where_it_came_from(directory: registry.Directory) -> None:
    raw = json.loads(registry.DIRECTORY.path.read_bytes())
    assert len(raw["fields"]) == 52 and all(len(r) == 52 for r in raw["rows"])
    assert len(directory.origin_sha256) == 64
    assert [r[0] for r in raw["rows"]] == sorted(r[0] for r in raw["rows"]), "sorted by id, one per line: a new version diffs by source"


def test_the_ai_reservations_of_the_directory_are_all_read(directory: registry.Directory) -> None:
    access = Counter(s.ai_extraction for s in directory.sources)
    assert access["reserva_ia_robots"] == 51 and access["reserva_ia_terminos"] == 20, "71 reservations (51 robots, 20 terms)"
    reserved = {s.source_id for s in directory.sources if s.ai_reserved or s.state == "solo_referencia"}
    assert len(reserved) == 77, "the 71 of «solo referencia» and the six pending sources whose robots reserve them"
    assert all(s.authority for s in directory.sources), "every source says what it may confirm"


def test_a_file_that_is_not_the_pinned_one_is_refused() -> None:
    data = registry.DIRECTORY.path.read_bytes()
    tampered = data.replace(b'"verificada_pendiente_derechos"', b'"verificada_autorizada"', 1)
    with pytest.raises(registry.RegistryError, match="pinned"):
        registry.read_pinned(registry.DIRECTORY, data=tampered)
    assert registry.read_pinned(registry.DIRECTORY, data=data) == data


def test_a_record_outside_the_vocabulary_is_refused(directory: registry.Directory) -> None:
    good = dict(directory.sources[0].record)
    for key, value in (("estado_verificacion", "autorizada_por_exa"), ("familia", "F"), ("dominio", "not a domain"),
                       ("autoridad_por_afirmacion", "lesiones:confirma mucho"), ("fecha_ultima_revision", "ayer")):
        with pytest.raises(registry.RegistryError):
            registry.source_of(good | {key: value})


def test_the_authority_per_claim_is_parsed_and_never_guessed() -> None:
    parsed = registry.parse_authority("lesiones:informa; declaraciones:informa (cita); convocatorias:confirma (solo del propio club); "
                                      "rumores:solo_rumor; analisis:sin_autoridad")
    assert parsed["declaraciones"] == {"level": "informa", "note": "cita"}
    assert parsed["convocatorias"] == {"level": "confirma", "note": "solo del propio club"}
    assert parsed["rumores"] == {"level": "solo_rumor"} and parsed["analisis"] == {"level": "sin_autoridad"}
    for bad in ("lesiones", "lesiones:quiza", ":informa"):
        with pytest.raises(registry.RegistryError):
            registry.parse_authority(bad)


def test_the_exclusion_list_blocks_the_four_safe_classes_and_queues_the_doubtful(rules: tuple[registry.DomainRule, ...]) -> None:
    counts = registry.exclusion_counts(rules)
    assert counts["domains"] == 559, "570 rows, 559 domains"
    assert counts["actions"] == {"block": 117, "review": 165, "none": 277}
    by = {r.domain: r for r in rules}
    assert by["exa.ai"].action == "block" and by["mediapronos.com"].action == "block"
    assert by["mediapronos.com"].results == 106 + 7, "a domain listed twice adds its counts"
    assert by["sportsmole.co.uk"].action == "none", "a real outlet is only classified"
    assert {r.domain_class for r in rules if r.action == "block"} == set(registry.BLOCKED_CLASSES)


def test_a_domain_with_two_classes_is_refused() -> None:
    raw = (b"dominio;clase;pais_probable;resultados;evidencias;utiles;motivo\n"
           b"x.example.com;dudoso;;1;0;0;a\nx.example.com;medio_real;;1;0;0;b\n")
    with pytest.raises(registry.RegistryError, match="two classes"):
        registry.parse_exclusion(raw)


SIGNED_TIER_CHANGES = {
    # (domain, tiers-v1, what the directory implies): the list of changes the owner signs before ai.sources reads the registry (AD-C01)
    ("calciomercato.com", "aggregator", "media"), ("dongqiudi.com", "aggregator", "media"), ("kooora.com", "aggregator", "media"),
    ("meczyki.pl", "aggregator", "media"), ("tuttomercatoweb.com", "aggregator", "media"), ("fbref.com", "aggregator", "provider"),
    ("transfermarkt.com", "aggregator", "provider"), ("whoscored.com", "aggregator", "provider"),
    ("dimayor.com.co", "competition", "club"),  # the league's domain also carries the fichas of three clubs: the strictest record decides
}


def test_the_tier_the_directory_implies_matches_tiers_v1_but_for_a_listed_set(directory: registry.Directory) -> None:
    """Contract: on the 402 domains of ai.sources, the tier derived from the directory is tiers-v1's, but for the listed changes.
    (Nothing reads the derived tier yet: ai.sources is unchanged.)"""
    from fbi.ai.source_policy import SourcePolicy

    tiers = dict(seed_rows())
    assert len(tiers) == 402
    strictest = SourcePolicy(directory.sources, (), directory_version="t", exclusion_version="t", origin="test").by_domain
    derived = {d: registry.derived_tier(strictest[d]) for d in tiers if d in strictest}
    assert len(derived) == 295
    changes = {(d, tiers[d], t) for d, t in derived.items() if t != tiers[d]}
    assert changes == SIGNED_TIER_CHANGES
