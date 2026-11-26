"""When an experiment of the plan is due, and how it is run and leaves its verdict (plan RP-8.3, findings H24 and H26). Nothing here decides a model, a probability,
a pick or a threshold.

An experiment (``fbi.research.exp_protocol``, EXP-E1 ... EXP-E8) used to be launched by hand, so the last one was of 4 October. Here each one has the CONDITION that
launches it, checked by arithmetic and never by a person's memory:

* SAMPLE REACHED. The experiment looks at its data ONCE, when the sample fixed in its protocol is there: before that nothing is computed and nothing is declared
  (no peeking). A sample is counted only from matches played after the protocol was signed.
* MODEL CODE CHANGED. A verdict of «insufficient» (the sample was there and the interval still held both answers) is looked at again when the code of the models
  changed since it was computed, so a new model gets its own verdict.
* FOUR WEEKS. The same, when four weeks have passed and the sample has grown since.
* NEW PROTOCOL. A decided verdict stands on one protocol (its fingerprint): a new version of the protocol makes the experiment due again.
* A verdict of success or abandonment on the current protocol is final: the experiment is not due again.

An experiment says how it counts its sample and how it runs by REGISTERING itself (``register``): until it does, it is reported as «no counter» and is never launched,
which is how the pieces RP-9.1 to RP-9.7 plug in one at a time. ``run`` calls the runner and writes the verdict only through ``fbi.research.verdicts.record``, i.e. only
if the protocol was registered before the result. The worker is not involved: the launcher of RP-1.6 asks ``due_now`` as its gate and runs ``scripts.exp_run`` outside the
worker, one experiment at a time, with its row in the book of runs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.core.version import model_code_version
from fbi.research import exp_protocol, verdicts
from fbi.research.exp_protocol import EXPERIMENTS, Judgement
from fbi.research.protocol import fingerprint

VERSION: Final = "exp-conditions-v1"
FOUR_WEEKS: Final = timedelta(days=28)
SIGNED_ON: Final = date.fromisoformat(exp_protocol.SIGNATURE)

Counter = Callable[[psycopg.Connection[Any], date], int]
"""How many eligible matches (or cases) there are, played from the given day on (the signature of the protocol)."""
Runner = Callable[[psycopg.Connection[Any], datetime], tuple[Judgement, dict[str, Any]]]
"""Runs the experiment on its data and returns the judgement and the population it was judged on."""


class NotRegisteredError(LookupError):
    """The experiment has not said how it counts its sample or how it runs."""


@dataclass(frozen=True, slots=True)
class Spec:
    experiment: str
    count: Counter
    required: int
    run: Runner | None = None


_SPECS: dict[str, Spec] = {}


def register(experiment: str, *, count: Counter, required: int | None = None, run: Runner | None = None) -> Spec:
    """An experiment says how it counts its sample and (optionally) how it runs. ``required`` defaults to the audit's fixed sample (``exp_protocol.THRESHOLDS``)."""
    if experiment not in EXPERIMENTS:
        raise NotRegisteredError(f"{experiment} no tiene protocolo registrado")
    n = required if required is not None else exp_protocol.THRESHOLDS.get(experiment, {}).get("n_required")
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"{experiment}: falta la muestra fijada (required)")
    spec = Spec(experiment, count, n, run)
    _SPECS[experiment] = spec
    return spec


PLUGINS: Final[tuple[str, ...]] = ("fbi.research.exp_e1", "fbi.research.exp_e3", "fbi.families.exp_e7")
"""The modules that say how an experiment counts and runs (each has a ``register()`` that calls ``register``). The pieces RP-9.1 to RP-9.7 add themselves here, one each;
they are imported by name when asked (``load_plugins``), so this module imports none of them."""


def load_plugins() -> None:
    """Import and register every plugin that is not registered yet: what the launcher's gate and ``scripts.exp_run`` do before asking anything."""
    import importlib

    for name in PLUGINS:
        module = importlib.import_module(name)
        if module.KEY not in _SPECS:
            module.register()


def unregister(experiment: str) -> None:
    _SPECS.pop(experiment, None)


def registered() -> Mapping[str, Spec]:
    return dict(_SPECS)


@dataclass(frozen=True, slots=True)
class Due:
    """The state of one experiment: whether it is due, why (a stable code and a sentence in Spanish) and the figures behind it."""

    experiment: str
    due: bool
    code: str
    why: str
    sample: int | None = None
    required: int | None = None


def check(conn: psycopg.Connection[Any], experiment: str, *, at: datetime, model_code: str | None = None) -> Due:
    """Is ``experiment`` due at ``at``? Pure reading."""
    protocol = EXPERIMENTS.get(experiment)
    if protocol is None:
        return Due(experiment, False, "unknown", "no es un experimento del plan")
    spec = _SPECS.get(experiment)
    if spec is None:
        return Due(experiment, False, "no_counter", "todavía no dice cómo cuenta su muestra: no se lanza")
    last = next(iter(verdicts.history(conn, experiment)), None)
    fp = fingerprint(protocol)
    if last is not None and last.verdict != "insuficiente" and last.protocol_fingerprint == fp:
        return Due(experiment, False, "decided", f"ya tiene veredicto de {last.verdict} con este protocolo", spec.count(conn, SIGNED_ON), spec.required)
    sample = spec.count(conn, SIGNED_ON)
    if sample < spec.required:
        return Due(experiment, False, "sample", f"muestra {sample} de {spec.required}: no se mira antes de llegar", sample, spec.required)
    if last is None:
        return Due(experiment, True, "sample_reached", f"llegó a la muestra fijada ({sample} de {spec.required})", sample, spec.required)
    if last.protocol_fingerprint != fp:
        return Due(experiment, True, "new_protocol", "el protocolo tiene una versión nueva", sample, spec.required)
    if last.n < spec.required:
        return Due(experiment, True, "sample_reached", f"el último intento tenía {last.n}; ahora llegó a {sample}", sample, spec.required)
    code = model_code if model_code is not None else model_code_version()
    if last.population.get("model_code") not in (None, code):
        return Due(experiment, True, "model_code_changed", "cambió el código de los modelos desde el último veredicto", sample, spec.required)
    if at - last.computed_at >= FOUR_WEEKS and sample > last.n:
        return Due(experiment, True, "four_weeks", f"pasaron cuatro semanas y la muestra creció de {last.n} a {sample}", sample, spec.required)
    return Due(experiment, False, "waiting", "ya se miró con esta muestra; se vuelve a mirar con más partidos y cuatro semanas, o si cambia el código de modelos", sample, spec.required)


def survey(conn: psycopg.Connection[Any], *, at: datetime, model_code: str | None = None) -> list[Due]:
    """Every experiment of the plan, in order, with whether it is due."""
    return [check(conn, key, at=at, model_code=model_code) for key in EXPERIMENTS]


def due_now(conn: psycopg.Connection[Any], *, at: datetime, model_code: str | None = None) -> list[Due]:
    return [d for d in survey(conn, at=at, model_code=model_code) if d.due and _SPECS[d.experiment].run is not None]


def run(conn: psycopg.Connection[Any], experiment: str, *, at: datetime, due: Due | None = None, model_code: str | None = None,
        recorded_by: verdicts.Recorder = "system") -> verdicts.Stored:
    """Run one experiment that is due and write its verdict. Refuses one that is not due, one without a runner, and (through ``verdicts.record``) a result that does
    not stand on the protocol registered before it. The sample and the model code are kept in the population the verdict was judged on."""
    spec = _SPECS.get(experiment)
    if spec is None or spec.run is None:
        raise NotRegisteredError(f"{experiment} no tiene corredor")
    state = due or check(conn, experiment, at=at, model_code=model_code)
    if not state.due:
        raise exp_protocol.ProtocolRefusedError(f"{experiment} no toca: {state.why}")
    judgement, population = spec.run(conn, at)
    code = model_code if model_code is not None else model_code_version()
    population = {**population, "model_code": code, "sample": state.sample, "required": state.required, "trigger": state.code, "conditions": VERSION}
    return verdicts.record(conn, experiment, judgement, claimed_fingerprint=fingerprint(EXPERIMENTS[experiment]), computed_at=at, population=population,
                           recorded_by=recorded_by)


__all__ = ["FOUR_WEEKS", "PLUGINS", "VERSION", "Due", "NotRegisteredError", "Spec", "check", "due_now", "load_plugins", "register", "registered", "run", "survey", "unregister"]
