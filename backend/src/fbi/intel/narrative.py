"""The match narrative of PrediGol Intelligence - ``narrative-v3``: how each team arrives, what is at stake, the
tactical keys, the important players, the risks, the interesting markets and the conclusion, in Spanish.

Written by the economical model in the brief (``fbi.ai.brief``, brief-v4: every number in it must be in the packet,
a paragraph that cites one that is not is replaced) or, when no model may answer, by these rules from the same packet:
only what the data says, with its sample size, and "sin datos suficientes" where it says nothing. It never states a
probability of its own, a stake or a pick.
"""

from __future__ import annotations

from typing import Any

VERSION = "narrative-v3"
"""v2 (plan F2): a second leg says what the first 90 minutes do to the aggregate (``tie_scenarios``).
v3 (plan F5): «mercados interesantes» starts with what PrediGol expects (the packet's ``forecast``: the likely outcome of each
market with its probability, «sin calibrar» where no champion calibrator exists) and then the cards - a probability apart from a
price: the likely outcome is not said to be well paid."""
SECTIONS = ("como_llega_local", "como_llega_visitante", "que_esta_en_juego", "claves_tacticas",
            "jugadores_importantes", "riesgos", "mercados_interesantes", "conclusion")
TITLES = {"como_llega_local": "Cómo llega el local", "como_llega_visitante": "Cómo llega el visitante",
          "que_esta_en_juego": "Qué está en juego", "claves_tacticas": "Claves tácticas",
          "jugadores_importantes": "Jugadores importantes", "riesgos": "Riesgos",
          "mercados_interesantes": "Mercados interesantes", "conclusion": "Conclusión PrediGol Intelligence"}
NO_DATA = "Sin datos suficientes."
PRESSURE = {"title": "pelea el título", "europe": "pelea plazas internacionales", "relegation": "pelea por no descender",
            "promotion": "pelea el ascenso", "settled": "ya no se juega nada en la tabla", "playoff": "pelea el playoff"}
ZONE = {"title": "título", "europe": "plazas internacionales", "relegation": "descenso", "promotion": "ascenso"}
"""The zones by name (stakes-v2 gives the kind of the zone above and below): the facts - rank and gaps - before the
inference ("pressure", only the nearest boundary within two wins)."""


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.1f} %"
    except (TypeError, ValueError):
        return "?"


def _num(x: Any, places: int = 1) -> str:
    try:
        return f"{float(x):.{places}f}"
    except (TypeError, ValueError):
        return "?"


def _team(content: dict[str, Any], side: str) -> str:
    fx = content.get("fixture") or {}
    return str((fx.get(side) or {}).get("name") or ("el local" if side == "home" else "el visitante"))


def arrives(content: dict[str, Any], side: str) -> str:
    name = _team(content, side)
    d = ((content.get("dossier") or {}).get("teams") or {}).get(side) or {}
    form = (content.get("form") or {}).get(side) or {}
    if not d.get("n") and not form.get("n"):
        return NO_DATA
    parts = []
    if d.get("n"):
        a = d.get("all") or {}
        venue = d.get(side) or {}
        parts.append(f"{name} llega con {d.get('results', '')[:5] or '—'} en sus últimos partidos "
                     f"({a.get('wins', 0)} victorias, {a.get('draws', 0)} empates y {a.get('losses', 0)} derrotas en "
                     f"{a.get('n', 0)}), {_num(a.get('goals_for'))} goles a favor y {_num(a.get('goals_against'))} en "
                     f"contra por partido.")
        if a.get("xg_for") is not None:
            parts.append(f"Genera {_num(a.get('xg_for'), 2)} xG y concede {_num(a.get('xg_against'), 2)} "
                         f"(en {a.get('n_stats', 0)} partidos con estadísticas).")
        if venue.get("n"):
            where = "en casa" if side == "home" else "fuera"
            parts.append(f"{where.capitalize()}: {venue.get('wins', 0)}G {venue.get('draws', 0)}E "
                         f"{venue.get('losses', 0)}P en {venue.get('n')}.")
        st = d.get("streaks") or {}
        if (st.get("unbeaten") or 0) >= 4:
            parts.append(f"Suma {st['unbeaten']} partidos sin perder.")
        elif (st.get("winless") or 0) >= 4:
            parts.append(f"Lleva {st['winless']} partidos sin ganar.")
        opp = d.get("opponents") or {}
        if opp.get("mean_elo"):
            parts.append(f"Rivales recientes con Elo medio {opp['mean_elo']:.0f}.")
    else:
        parts.append(f"{name}: forma {form.get('sequence', '—')} ({form.get('ppg', '?')} puntos por partido).")
    return " ".join(parts)


def _goals(n: int) -> str:
    return "1 gol" if n == 1 else f"{n} goles"


def tie_scenarios(content: dict[str, Any]) -> str | None:
    """What the first 90 minutes of a second leg do to the aggregate, in words, from the packet's ``phase.tie.outlook`` (plain
    arithmetic on the legs already played). What a level aggregate leads to is the competition's own rule: it is said, not
    assumed. None when the packet has no such outlook (a packet before packet-v4, a first leg, an aggregate not known)."""
    outlook = (((content.get("phase") or {}).get("tie")) or {}).get("outlook") or {}
    if outlook.get("kind") != "second_leg" or "level_if_home_margin_is" not in outlook:
        return None
    ahead = int(outlook["home_side_ahead_if_home_margin_at_least"])
    level = int(outlook["level_if_home_margin_is"])
    if ahead >= 2:
        ahead_text = f"gana por {ahead} goles o más"
    elif ahead == 1:
        ahead_text = "gana"
    elif ahead == 0:
        ahead_text = "empata o gana"
    else:
        ahead_text = f"no pierde por más de {_goals(-ahead)}"
    level_text = f"gana por {_goals(level)}" if level > 0 else "empata" if level == 0 else f"pierde por {_goals(-level)}"
    return (f"En el global, tras los 90 minutos {_team(content, 'home')} va por delante si {ahead_text}; queda igualado si "
            f"{level_text}; en otro caso va por delante {_team(content, 'away')}. Si queda igualado, deciden las reglas de "
            f"la competición.")


def stakes(content: dict[str, Any]) -> str:
    st = content.get("stakes") or {}
    ctx = (content.get("dossier") or {}).get("context") or {}
    parts = []
    for side in ("home", "away"):
        s = st.get(side) or {}
        p = s.get("pressure")
        where = []
        if s.get("zone") in ZONE:
            where.append(f"está en zona de {ZONE[s['zone']]}")
        if s.get("gap_up") is not None and s.get("zone_above") in ZONE:
            where.append(f"a {s['gap_up']} puntos de la zona de {ZONE[s['zone_above']]}")
        if s.get("gap_down") is not None and s.get("zone_below") in ZONE:
            where.append(f"{s['gap_down']} por encima de la zona de {ZONE[s['zone_below']]}")
        rank = f" ({s['rank']}.º)" if s.get("rank") else ""
        if where:
            parts.append(f"{_team(content, side)}{rank} " + ", ".join(where) + ".")
        if p and p in PRESSURE:
            parts.append(f"{_team(content, side)} {PRESSURE[str(p)]}.")
    if ctx.get("final"):
        parts.append("Es una final.")
    elif ctx.get("knockout"):
        parts.append("Es una eliminatoria.")
    if ctx.get("second_leg"):
        sl = ctx["second_leg"]
        parts.append(f"Partido de vuelta: la ida terminó {sl.get('first_leg_score_home_side')}-"
                     f"{sl.get('first_leg_score_away_side')} ({sl.get('aggregate_need')}).")
    scenario = tie_scenarios(content)
    if scenario:
        parts.append(scenario)
    if ctx.get("derby"):
        parts.append("Es un derbi (misma ciudad): la historia emocional no cambia las probabilidades.")
    if ctx.get("friendly"):
        parts.append("Es un amistoso: rotaciones probables y poco en juego.")
    return " ".join(parts) or NO_DATA


def tactics(content: dict[str, Any]) -> str:
    teams = (content.get("dossier") or {}).get("teams") or {}
    parts = []
    for side in ("home", "away"):
        c = (teams.get(side) or {}).get("coach") or {}
        if c.get("main_formation"):
            alt = [f for f in (c.get("formations") or {}) if f != c["main_formation"]]
            parts.append(f"{_team(content, side)}" + (f" ({c['name']})" if c.get("name") else "")
                         + f" suele formar {c['main_formation']}" + (f", alternativa {alt[0]}" if alt else "")
                         + (f"; cambia de media {c['rotation_avg_changes']} titulares entre partidos"
                            if c.get("rotation_avg_changes") is not None else "") + ".")
        a = (teams.get(side) or {}).get("all") or {}
        if a.get("possession") is not None:
            parts.append(f"Posesión media {a['possession']} %, {_num(a.get('shots'))} tiros y "
                         f"{_num(a.get('corners'))} córners por partido.")
    lu = content.get("lineups") or {}
    if lu.get("confirmed"):
        parts.append("Alineaciones confirmadas.")
    return " ".join(parts) or NO_DATA


def players(content: dict[str, Any]) -> str:
    ps = (content.get("dossier") or {}).get("players") or {}
    parts = []
    for side in ("home", "away"):
        top = (ps.get(side) or [])[:3]
        if top:
            parts.append(f"{_team(content, side)}: " + "; ".join(
                f"{p['name']} ({p['minutes']} min, {p['goals']} goles, {p['assists']} asist."
                + (", reportado baja" if p.get("reported_out") else "") + ")" for p in top) + ".")
    absences = content.get("absences") or {}
    for side in ("home", "away"):
        key = [p["name"] for p in (absences.get(side) or {}).get("players", []) if p.get("key")][:3]
        if key:
            parts.append(f"Bajas importantes de {_team(content, side)}: {', '.join(key)}.")
    return " ".join(parts) or NO_DATA


def risks(content: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    parts = []
    ref = (content.get("dossier") or {}).get("referee") or {}
    if ref.get("with_stats"):
        parts.append(f"Árbitro {ref['name']}: {ref.get('cards_per_match')} tarjetas por partido en "
                     f"{ref['with_stats']} partidos.")
    sched = content.get("schedule") or {}
    for flag in sched.get("flags") or []:
        if flag.endswith("short_rest"):
            parts.append(f"{_team(content, flag.split('_')[0])} llega con poco descanso.")
    ev = content.get("evidence") or []
    rumors = sum(1 for e in ev if e.get("status") == "RUMOR")
    contra = sum(1 for e in ev if e.get("status") == "CONTRADICTORY")
    if contra:
        parts.append(f"{contra} informaciones contradictorias.")
    if rumors:
        parts.append(f"{rumors} rumores sin confirmar (no cuentan como hechos).")
    if not ev:
        parts.append("CONTEXTO EXTERNO LIMITADO: no hay información externa del partido.")
    h2h = (content.get("dossier") or {}).get("h2h") or {}
    if h2h.get("relevance") in ("nula", "baja"):
        parts.append("El historial directo dice poco.")
    return " ".join(parts) or NO_DATA


FORECAST_WORDS = {("1X2", "Home"): "gana {home}", ("1X2", "Draw"): "empate", ("1X2", "Away"): "gana {away}",
                  ("OU", "Over"): "más de {line} goles", ("OU", "Under"): "menos de {line} goles",
                  ("BTTS", "Yes"): "ambos marcan", ("BTTS", "No"): "no marcan los dos"}
"""The likely outcome of a market in words: nothing else is said about a forecast here but its probability."""


def expected(content: dict[str, Any]) -> str:
    """What PrediGol expects of the match (the packet's ``forecast``): the likely outcome of each market with the probability
    the packet states, and «sin calibrar» where it is the model's own number. A probability, not a price: it is never said to
    be well paid. Empty when the packet has no forecast."""
    parts: list[str] = []
    for m in (content.get("forecast") or {}).get("markets") or []:
        words = FORECAST_WORDS.get((m.get("market"), m.get("likely")))
        likely = next((o for o in m.get("outcomes") or [] if o.get("selection") == m.get("likely")), None)
        if words is None or likely is None or likely.get("p") is None:
            continue
        try:
            line = f"{float(m.get('line')):g}"
        except (TypeError, ValueError):
            line = str(m.get("line"))
        label = words.format(home=_team(content, "home"), away=_team(content, "away"), line=line)
        parts.append(f"{label} ({_pct(likely['p'])}" + (", sin calibrar" if m.get("calibration") == "UNCALIBRATED" else "") + ")")
    return ("PrediGol espera: " + "; ".join(parts) + ". Es una probabilidad, no un precio.") if parts else ""


def markets(content: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    parts = []
    for c in cards[:3]:
        if c.get("p_model") is None or c.get("p_market") is None:
            continue
        parts.append(f"{c.get('market')} {c.get('selection')}" + (f" {c.get('line')}" if str(c.get('line')) not in
                                                                   ("0", "0.00", "None") else "")
                     + f": modelo {_pct(c['p_model'])} frente a mercado {_pct(c['p_market'])}.")
    first = expected(content)
    return " ".join([first, *parts] if first else parts) or "Ningún mercado destaca frente al precio."


def conclusion(content: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    q = ((content.get("quality") or {}).get("competition_score") or {}).get("class")
    base = "La decisión la toman los filtros de PrediGol Intelligence con la probabilidad calibrada frente al precio; " \
           "este texto describe el partido, no lo apuesta."
    if q in ("PRODUCT_ONLY", "INSUFFICIENT"):
        return "Los datos de esta competición no son aptos para modelos: solo descripción. " + base
    return base


def rules_narrative(content: dict[str, Any], cards: list[dict[str, Any]] | None = None) -> dict[str, str]:
    cards = cards or []
    return {"como_llega_local": arrives(content, "home"), "como_llega_visitante": arrives(content, "away"),
            "que_esta_en_juego": stakes(content), "claves_tacticas": tactics(content),
            "jugadores_importantes": players(content), "riesgos": risks(content, cards),
            "mercados_interesantes": markets(content, cards), "conclusion": conclusion(content, cards)}
