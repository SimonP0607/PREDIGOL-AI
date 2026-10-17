"""The match narrative of PrediGol Intelligence - ``narrative-v1``: how each team arrives, what is at stake, the
tactical keys, the important players, the risks, the interesting markets and the conclusion, in Spanish.

Written by the economical model in the brief (``fbi.ai.brief``, brief-v4: every number in it must be in the packet,
a paragraph that cites one that is not is replaced) or, when no model may answer, by these rules from the same packet:
only what the data says, with its sample size, and "sin datos suficientes" where it says nothing. It never states a
probability of its own, a stake or a pick.
"""

from __future__ import annotations

from typing import Any

VERSION = "narrative-v1"
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


def markets(content: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    parts = []
    for c in cards[:3]:
        if c.get("p_model") is None or c.get("p_market") is None:
            continue
        parts.append(f"{c.get('market')} {c.get('selection')}" + (f" {c.get('line')}" if str(c.get('line')) not in
                                                                   ("0", "0.00", "None") else "")
                     + f": modelo {_pct(c['p_model'])} frente a mercado {_pct(c['p_market'])}.")
    return " ".join(parts) or "Ningún mercado destaca frente al precio."


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
