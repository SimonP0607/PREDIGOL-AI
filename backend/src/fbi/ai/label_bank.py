"""A bank labelled by people (IA-030, R2 of the audit of 10 Nov 2026): what the claim extractor wrote and what the post-match review of the
chronicle said, checked by hand against the source each one cites.

Two banks, each a sheet a person fills in:

* ``claims``     pieces of evidence the extractors wrote from web pages (``ai.evidence``, ``origin = 'web'``, ``extract-v1``, ``extract-v2``,
                 ``extract-v3``): the person opens the cited page and says whether it says THAT, about THAT subject, for THIS match.
* ``sentences``  sentences of the chronicle with the verdict the post-match review gave them (``ai.chronicle_reviews``,
                 ``chronicle-review-v1``): the person reads the sentence, the facts it cites and the match, and gives the verdict the review
                 should have given - and, apart, whether the sentence says only what its sources say.

The sample is stratified and deterministic: the rows of each stratum are ordered by a hash of a seed and their id, the quota is shared
equally between the strata (what a small stratum cannot use goes to the others) and a share of every stratum (``DOUBLE_SHARE``, at least a
quarter) is marked for a second, blind labeller.

The scorer reads the filled sheet. The HUMAN label is the reference; a model's output is never the truth here, a row nobody labelled is left
out (never guessed), and two labels that disagree are listed and kept apart (never resolved by the code). Every rate carries its cases and
its 95 % interval (``fbi.ai.intervals``). It INFORMS and decides nothing (``"decides": False``): no gate, threshold, agent or prompt reads it.
Pure: no database, no clock (the readers are ``fbi.ai.label_bank_readers``)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, get_args

from fbi.ai.contracts.claim import ClaimType
from fbi.ai.intervals import Proportion

BANK_VERSION: Final = "label-bank-v1"
CLAIMS: Final = "claims"
SENTENCES: Final = "sentences"
BANKS: Final = (CLAIMS, SENTENCES)
QUOTA: Final[dict[str, int]] = {CLAIMS: 150, SENTENCES: 60}
DOUBLE_SHARE: Final = 0.25
"""The share of every stratum a second labeller reads blind (rounded up, so the bank as a whole has at least this share)."""
SEED: Final = "label-bank-v1"

# -- the label sets ---------------------------------------------------------------------------------------------------------------------

CLAIM_LABELS: Final[dict[str, str]] = {
    "CORRECT": "la página citada dice esto, de este sujeto y para este partido (o sin partido, si la afirmación no lo nombra)",
    "WRONG_FACT": "la página habla del sujeto pero dice otra cosa (otro tipo: una duda guardada como baja, un regreso como baja...)",
    "WRONG_SUBJECT": "lo que dice la página es de otro jugador, otro equipo u otro entrenador",
    "WRONG_MATCH": "lo que dice la página es de otro partido o es viejo (una lesión ya curada, una sanción ya cumplida)",
    "NOT_IN_SOURCE": "la página no dice nada parecido",
    "SOURCE_UNAVAILABLE": "la página ya no se puede abrir o no muestra el texto",
    "UNCLEAR": "con la página no se puede decidir",
}
"""What a person says of one piece of evidence, against the page it cites and nothing else."""
CLAIM_TYPES: Final[tuple[str, ...]] = (*get_args(ClaimType), "NONE")
"""The types of ``claim-v1`` and ``NONE`` (no claim of any type about that subject and that match): the type the page supports, asked when
the label is WRONG_FACT so that the system's type and the person's meet in one matrix."""
NO_CLAIM: Final = frozenset({"WRONG_SUBJECT", "WRONG_MATCH", "NOT_IN_SOURCE"})
"""Labels that mean the page supports no claim of that subject for that match: their human type is ``NONE``."""

SENTENCE_LABELS: Final[dict[str, str]] = {
    "HELD": "la frase anticipaba algo que el partido podía refutar (quién juega) y el partido lo confirmó",
    "CONTRADICTED": "la frase anticipaba algo y el partido mostró lo contrario (un jugador dado de baja que jugó)",
    "NOT_EVALUABLE": "la frase no anticipa nada que un resultado refute: historia, contexto, forma, o una duda (se cuenta, no se juzga)",
    "NOT_CHECKABLE": "anticipa algo, pero los datos del partido no lo pueden decir (un nombre que las alineaciones no ubican, sin minutos)",
    "UNCLEAR": "no se puede decidir",
}
"""The verdict the review of the chronicle should have given the sentence, judged by a person."""
SUPPORT_LABELS: Final[dict[str, str]] = {
    "SUPPORTED": "lo que dice la frase está en los hechos que cita",
    "NOT_IN_SOURCES": "la frase dice algo que sus hechos citados no dicen (añadido o inventado)",
    "CONTRADICTED_BY_SOURCES": "los hechos citados dicen lo contrario de la frase",
    "UNCLEAR": "no se puede decidir",
}
"""Apart from the review: whether the sentence, as it was written before the match, says only what its cited facts say."""
UNDECIDED: Final = frozenset({"UNCLEAR", "SOURCE_UNAVAILABLE"})
"""Labels that decide nothing: counted, never in the denominator of a rate."""

REVIEW_CLASS: Final[dict[str, str]] = {"held": "HELD", "contradicted": "CONTRADICTED", "played": "NOT_EVALUABLE", "did_not_play": "NOT_EVALUABLE",
                                       "not_evaluable": "NOT_EVALUABLE", "pending": "NOT_CHECKABLE", "not_checkable": "NOT_CHECKABLE"}
"""The verdict of ``chronicle-review-v1`` in the words a person labels with: a doubt that played or did not is told, not judged."""

TYPE_OF_V1: Final[dict[tuple[str, str], str]] = {
    ("injury", "out"): "OUT", ("injury", "available"): "AVAILABLE", ("injury", "doubtful"): "DOUBT", ("doubtful", "doubtful"): "DOUBT",
    ("doubtful", "out"): "DOUBT", ("suspension", "out"): "SUSPENSION", ("suspension", "doubtful"): "DOUBT", ("lineup", "starts"): "STARTER",
    ("coach", "info"): "COACH", ("schedule", "info"): "SCHEDULE", ("news", "info"): "OTHER"}
"""The type of ``claim-v1`` an ``extract-v1`` item says, from its kind and its assertion (v1 wrote no type; v2 and v3 do)."""

SHEET_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    CLAIMS: ("bank", "id", "stratum", "system_class", "double", "extract_version", "subject", "kind", "assertion", "claim_type", "applies_to",
             "text", "source_url", "source_domain", "result_title", "published_at", "retrieved_at", "match", "status", "instruction_like",
             "label_a", "type_a", "label_b", "type_b", "notes"),
    SENTENCES: ("bank", "id", "stratum", "system_class", "double", "review_version", "match", "score", "section", "text", "refs", "checks",
                "cited", "label_a", "support_a", "label_b", "support_b", "notes"),
}
LABEL_COLUMNS: Final[dict[str, tuple[str, ...]]] = {CLAIMS: ("label_a", "type_a", "label_b", "type_b", "notes"),
                                                    SENTENCES: ("label_a", "support_a", "label_b", "support_b", "notes")}


@dataclass(frozen=True, slots=True)
class Candidate:
    """A row that may be sampled: its bank, a stable id, its stratum, the class the system gave it and what the sheet shows of it."""

    bank: str
    id: str
    stratum: str
    system_class: str
    fields: Mapping[str, Any] = field(default_factory=dict)


# -- the candidates ---------------------------------------------------------------------------------------------------------------------

def type_of(kind: str | None, assertion: str | None, claim_type: str | None) -> str:
    """The ``claim-v1`` type a piece of evidence says: its own (v2, v3) or the one its kind and assertion make (v1); ``OTHER`` when neither."""
    if claim_type in CLAIM_TYPES and claim_type != "NONE":
        return str(claim_type)
    return TYPE_OF_V1.get((str(kind or ""), str(assertion or "info")), "OTHER")


def _iso(x: Any) -> str:
    return "" if x is None else (x.isoformat() if hasattr(x, "isoformat") else str(x))


def claim_candidate(row: Mapping[str, Any]) -> Candidate:
    """A piece of web evidence (a row of ``label_bank_readers.CLAIMS_SQL``) as a candidate of the claims bank, stratified by the extractor's
    version and the type it says."""
    version = str(row.get("extract_version") or "unknown")
    kind = type_of(row.get("kind"), row.get("assertion"), row.get("claim_type"))
    who = row.get("player_name") or row.get("team_name") or ""
    subject = f"{row.get('subject_type') or ('PLAYER' if row.get('provider_player_id') else 'TEAM')}: {who}".strip()
    if row.get("team_name") and row.get("player_name"):
        subject += f" ({row['team_name']})"
    match = ""
    if row.get("home_name") and row.get("away_name"):
        match = f"{row['home_name']} - {row['away_name']} ({_iso(row.get('kickoff_at'))})"
    fields = {"extract_version": version, "subject": subject, "kind": row.get("kind") or "", "assertion": row.get("assertion") or "",
              "claim_type": row.get("claim_type") or "", "applies_to": row.get("applies_to") or "", "text": " ".join(str(row.get("claim") or "").split()),
              "source_url": row.get("source_url") or "", "source_domain": row.get("source_domain") or row.get("source_name") or "",
              "result_title": row.get("result_title") or "", "published_at": _iso(row.get("published_at")),
              "retrieved_at": _iso(row.get("retrieved_at")), "match": match, "status": row.get("status") or "",
              "instruction_like": bool(row.get("instruction_like"))}
    return Candidate(CLAIMS, f"ev:{int(row['id'])}", f"{version}|{kind}", kind, fields)


def sentence_candidate(row: Mapping[str, Any]) -> Candidate:
    """A sentence of a reviewed chronicle (a row of ``label_bank_readers.SENTENCES_SQL``: the review and one of its items) as a candidate of
    the sentences bank, stratified by the review's own verdict."""
    item: Mapping[str, Any] = row["item"] or {}
    verdict = str(item.get("verdict") or "not_evaluable")
    outcome: Mapping[str, Any] = row.get("outcome") or {}
    score = "" if outcome.get("home_goals") is None else f"{outcome.get('home_goals')}-{outcome.get('away_goals')}"
    match = f"{row.get('home_name') or ''} - {row.get('away_name') or ''} ({_iso(row.get('kickoff_at'))})"
    fields = {"review_version": row.get("version") or "", "match": match, "score": score,
              "section": f"{item.get('section')}.{item.get('index')}", "text": " ".join(str(item.get("text") or "").split()),
              "refs": list(item.get("refs") or []), "checks": list(item.get("checks") or []), "cited": [],
              "narrative_id": int(row["narrative_id"]), "packet_id": None if row.get("packet_id") is None else int(row["packet_id"])}
    rid = f"cr:{int(row['review_id'])}:{item.get('section')}:{item.get('index')}"
    return Candidate(SENTENCES, rid, verdict, REVIEW_CLASS.get(verdict, "NOT_EVALUABLE"), fields)


# -- the sample -------------------------------------------------------------------------------------------------------------------------

def rank(seed: str, salt: str, id_: str) -> str:
    """The order of a row inside its stratum: a hash of the seed, a salt and the id - the same rows in, the same rows out, on any machine."""
    return hashlib.sha256(f"{seed}|{salt}|{id_}".encode()).hexdigest()


def allocate(sizes: Mapping[str, int], quota: int) -> dict[str, int]:
    """The quota shared equally between the strata; a stratum smaller than its share gives the rest to the others; what is left after an
    equal share goes, one row each, to the strata in the order of their names."""
    out = dict.fromkeys(sizes, 0)
    open_ = sorted(s for s, n in sizes.items() if n > 0)
    left = max(0, quota)
    while left > 0 and open_:
        share = left // len(open_)
        if share == 0:
            for s in open_[:left]:
                out[s] += 1
            break
        for s in list(open_):
            take = min(share, sizes[s] - out[s])
            out[s] += take
            left -= take
        open_ = [s for s in open_ if out[s] < sizes[s]]
    return out


def sample(candidates: Iterable[Candidate], *, quota: int, seed: str = SEED, double_share: float = DOUBLE_SHARE) -> list[dict[str, Any]]:
    """The sheet of a bank: per stratum, the rows of the lowest rank up to its allocation, and the ones of the lowest second rank (at least
    ``double_share`` of them, rounded up) marked ``double`` for the blind second labeller. One bank at a time; a repeated id counts once."""
    seen: dict[str, Candidate] = {}
    for c in candidates:
        seen.setdefault(c.id, c)
    if not seen:
        return []
    banks = {c.bank for c in seen.values()}
    if len(banks) != 1:
        raise ValueError(f"one bank per sheet, not {sorted(banks)}")
    bank = banks.pop()
    strata: dict[str, list[Candidate]] = defaultdict(list)
    for c in seen.values():
        strata[c.stratum].append(c)
    take = allocate({s: len(v) for s, v in strata.items()}, quota)
    rows: list[dict[str, Any]] = []
    for stratum in sorted(strata):
        chosen = sorted(strata[stratum], key=lambda c: rank(seed, bank, c.id))[:take[stratum]]
        doubles = {c.id for c in sorted(chosen, key=lambda c: rank(seed, "double", c.id))[:math.ceil(double_share * len(chosen))]}
        for c in chosen:
            row: dict[str, Any] = {"bank": bank, "id": c.id, "stratum": c.stratum, "system_class": c.system_class, "double": c.id in doubles}
            row.update(c.fields)
            row.update(dict.fromkeys(LABEL_COLUMNS[bank], ""))
            rows.append(row)
    return rows


def sheet(rows: Sequence[Mapping[str, Any]], *, bank: str, seed: str, window: Mapping[str, str]) -> dict[str, Any]:
    """The JSON sheet: the rows and everything a labeller needs to read them (the label sets and their meaning)."""
    labels = ({"label": CLAIM_LABELS, "type": list(CLAIM_TYPES)} if bank == CLAIMS
              else {"label": SENTENCE_LABELS, "support": SUPPORT_LABELS})
    strata = Counter(str(r["stratum"]) for r in rows)
    return {"version": BANK_VERSION, "bank": bank, "seed": seed, "window": dict(window), "double_share": DOUBLE_SHARE, "labels": labels,
            "strata": dict(sorted(strata.items())), "rows": [dict(r) for r in rows], "decides": False}


def _cell(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return "" if value is None else str(value)


def to_csv(rows: Sequence[Mapping[str, Any]], *, bank: str) -> str:
    """The sheet as CSV (UTF-8 text, the bank's columns in their order; lists and objects as JSON in their cell)."""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(SHEET_COLUMNS[bank]), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: _cell(r.get(k)) for k in SHEET_COLUMNS[bank]})
    return out.getvalue()


def read_sheet(text: str) -> list[dict[str, Any]]:
    """A filled sheet, JSON (``sheet``) or CSV (``to_csv``)."""
    stripped = text.lstrip("﻿").lstrip()
    if stripped.startswith("{"):
        return [dict(r) for r in json.loads(stripped).get("rows") or []]
    return [dict(r) for r in csv.DictReader(io.StringIO(stripped))]


# -- the score --------------------------------------------------------------------------------------------------------------------------

def _word(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _double(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "1", "yes", "si", "sí")


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's kappa of two labellers over the same rows; None without rows, or when chance alone agrees every time (one label for all)."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected >= 1:
        return None
    return round((observed - expected) / (1 - expected), 3)


def _agreement(rows: Sequence[Mapping[str, Any]], a_key: str, b_key: str, allowed: Iterable[str]) -> dict[str, Any]:
    ok = set(allowed)
    pairs = [(str(r[a_key]), str(r[b_key]), str(r["id"])) for r in rows if r.get(a_key) in ok and r.get(b_key) in ok]
    agree = sum(1 for a, b, _ in pairs if a == b)
    return {"both_labelled": len(pairs), "agree": Proportion(agree, len(pairs)).as_json(), "kappa": cohen_kappa([(a, b) for a, b, _ in pairs]),
            "disagreements": [{"id": i, "a": a, "b": b} for a, b, i in pairs if a != b]}


def _reference(a: str | None, b: str | None) -> tuple[str | None, str]:
    """The human label of a row and how it was had: both labellers alike, one of them, disputed (kept apart) or none."""
    if a and b:
        return (a, "both") if a == b else (None, "disputed")
    if a or b:
        return a or b, "single"
    return None, "none"


def _confusion(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """System class against human class: the matrix, the precision of each class the system gave and the recall of each class people gave
    (within the bank: a claim the extractor never wrote is not in it), each with its interval."""
    matrix = Counter(pairs)
    systems = sorted({s for s, _ in pairs})
    humans = sorted({h for _, h in pairs})
    return {"pairs": len(pairs), "matrix": {f"{s}|{h}": n for (s, h), n in sorted(matrix.items())},
            "accuracy": Proportion(sum(n for (s, h), n in matrix.items() if s == h), len(pairs)).as_json(),
            "precision": {s: Proportion(matrix[(s, s)], sum(n for (x, _), n in matrix.items() if x == s)).as_json() for s in systems},
            "recall": {h: Proportion(matrix[(h, h)], sum(n for (_, y), n in matrix.items() if y == h)).as_json() for h in humans}}


def score(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The score of a filled sheet (one bank; a sheet with both is scored bank by bank)."""
    out: dict[str, Any] = {"version": BANK_VERSION, "decides": False, "reference": "the human label: never a model's output", "banks": {}}
    by_bank: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by_bank[str(r.get("bank") or "")].append(r)
    for bank, items in sorted(by_bank.items()):
        if bank not in BANKS:
            out.setdefault("unknown_banks", []).append(bank)
            continue
        out["banks"][bank] = _score_bank(bank, items)
    return out


def _clean(rows: Sequence[Mapping[str, Any]], bank: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The rows with their labels in upper case and checked against the bank's sets; a word out of a set is listed and counts as no label."""
    sets = ({"label_a": CLAIM_LABELS, "label_b": CLAIM_LABELS, "type_a": CLAIM_TYPES, "type_b": CLAIM_TYPES} if bank == CLAIMS
            else {"label_a": SENTENCE_LABELS, "label_b": SENTENCE_LABELS, "support_a": SUPPORT_LABELS, "support_b": SUPPORT_LABELS})
    clean: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for r in rows:
        c = dict(r)
        c["double"] = _double(r.get("double"))
        for key, allowed in sets.items():
            w = _word(r.get(key))
            if w is not None and w not in allowed:
                invalid.append({"id": r.get("id"), "column": key, "value": r.get(key)})
                w = None
            c[key] = w
        clean.append(c)
    return clean, invalid


def _human_type(row: Mapping[str, Any], label: str, how: str) -> str | None:
    """The type of ``claim-v1`` the page supports, for a claim whose human label is known: the system's when CORRECT, the labellers' type
    when WRONG_FACT (both alike when both labelled), NONE when the page supports no claim of that subject for that match."""
    if label == "CORRECT":
        return str(row["system_class"])
    if label in NO_CLAIM:
        return "NONE"
    if label == "WRONG_FACT":
        a, b = row.get("type_a"), row.get("type_b")
        if how == "both":
            return a if a and a == b else None
        return a or b
    return None


def _score_bank(bank: str, raw: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows, invalid = _clean(raw, bank)
    labels = CLAIM_LABELS if bank == CLAIMS else SENTENCE_LABELS
    counts: Counter[str] = Counter()
    refs: list[tuple[Mapping[str, Any], str, str]] = []
    disputed: list[dict[str, Any]] = []
    for r in rows:
        ref, how = _reference(r.get("label_a"), r.get("label_b"))
        counts[how] += 1
        if ref is not None:
            refs.append((r, ref, how))
        elif how == "disputed":
            disputed.append({"id": r["id"], "a": r["label_a"], "b": r["label_b"]})
    decided = [(r, ref, how) for r, ref, how in refs if ref not in UNDECIDED]
    report: dict[str, Any] = {
        "rows": len(rows), "double": sum(1 for r in rows if r["double"]),
        "labelled": {"both_alike": counts["both"], "single": counts["single"], "disputed": counts["disputed"], "none": counts["none"]},
        "invalid_labels": invalid,
        "agreement": _agreement(rows, "label_a", "label_b", labels), "disputed": disputed,
        "human_labels": dict(sorted(Counter(ref for _, ref, _ in refs).items())),
        "undecided": sum(1 for _, ref, _ in refs if ref in UNDECIDED)}
    if bank == CLAIMS:
        report["correct"] = Proportion(sum(1 for _, ref, _ in decided if ref == "CORRECT"), len(decided)).as_json()
        per: dict[str, list[str]] = defaultdict(list)
        for item, ref, _ in decided:
            per[str(item["stratum"])].append(ref)
        report["correct_by_stratum"] = {s: Proportion(sum(1 for x in v if x == "CORRECT"), len(v)).as_json() for s, v in sorted(per.items())}
        pairs = [(str(r["system_class"]), t) for r, ref, how in decided if (t := _human_type(r, ref, how)) is not None]
        report["types"] = _confusion(pairs)
        report["wrong_fact_without_type"] = sum(1 for r, ref, how in decided if ref == "WRONG_FACT" and _human_type(r, ref, how) is None)
    else:
        report["review"] = _confusion([(str(r["system_class"]), ref) for r, ref, _ in decided])
        report["support_agreement"] = _agreement(rows, "support_a", "support_b", SUPPORT_LABELS)
        support = [s for r in rows if (s := _reference(r.get("support_a"), r.get("support_b"))[0]) is not None]
        firm = [s for s in support if s not in UNDECIDED]
        report["support"] = {"labels": dict(sorted(Counter(support).items())),
                             "supported": Proportion(sum(1 for s in firm if s == "SUPPORTED"), len(firm)).as_json(),
                             "not_in_sources": Proportion(sum(1 for s in firm if s == "NOT_IN_SOURCES"), len(firm)).as_json()}
    return report


def _ci(p: Mapping[str, Any]) -> str:
    if not p.get("cases"):
        return "0 casos"
    w = p.get("ci95_wilson_pct") or ["-", "-"]
    return f"{p['counted']}/{p['cases']} · {p['pct']} % · IC95 {w[0]}-{w[1]} %"


def lines(rep: Mapping[str, Any]) -> list[str]:
    """The score for a person, in Spanish."""
    out = [f"Banco etiquetado {rep['version']} (informa, no decide; la referencia es la etiqueta humana)"]
    for bank, b in rep.get("banks", {}).items():
        lab = b["labelled"]
        out.append(f"  {bank}: {b['rows']} filas ({b['double']} para doble revisión); etiquetadas por los dos y de acuerdo {lab['both_alike']}, "
                   f"por uno {lab['single']}, en disputa {lab['disputed']}, sin etiqueta {lab['none']}; indecisas {b['undecided']}")
        ag = b["agreement"]
        out.append(f"      acuerdo entre etiquetadores {_ci(ag['agree'])} · kappa {ag['kappa']}")
        if bank == CLAIMS:
            out.append(f"      correctas {_ci(b['correct'])}")
            out += [f"        {s}: {_ci(p)}" for s, p in b["correct_by_stratum"].items()]
            t = b["types"]
            out.append(f"      tipo del sistema frente al humano: exactitud {_ci(t['accuracy'])}")
            out += [f"        precisión {s}: {_ci(p)}" for s, p in t["precision"].items()]
            out += [f"        exhaustividad {h}: {_ci(p)}" for h, p in t["recall"].items()]
        else:
            rv = b["review"]
            out.append(f"      veredicto de la revisión frente al humano: exactitud {_ci(rv['accuracy'])}")
            out += [f"        precisión {s}: {_ci(p)}" for s, p in rv["precision"].items()]
            out += [f"        exhaustividad {h}: {_ci(p)}" for h, p in rv["recall"].items()]
            sp = b["support"]
            out.append(f"      frases que solo dicen lo que citan {_ci(sp['supported'])}; con algo que sus hechos no dicen {_ci(sp['not_in_sources'])}")
        if b["invalid_labels"]:
            out.append(f"      etiquetas fuera de su lista: {len(b['invalid_labels'])} (cuentan como sin etiqueta)")
    return out


__all__ = [
    "BANKS",
    "BANK_VERSION",
    "CLAIMS",
    "CLAIM_LABELS",
    "CLAIM_TYPES",
    "QUOTA",
    "SENTENCES",
    "SENTENCE_LABELS",
    "SUPPORT_LABELS",
    "Candidate",
    "allocate",
    "claim_candidate",
    "cohen_kappa",
    "lines",
    "rank",
    "read_sheet",
    "sample",
    "score",
    "sentence_candidate",
    "sheet",
    "to_csv",
    "type_of",
]
