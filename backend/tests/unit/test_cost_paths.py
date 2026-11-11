"""The cost by path of decision (IA-034): every row of the ledger in exactly one path, the total equal to the ledger's to the cent, every call to
Opus with the rule the code recorded for it - and the report decides nothing."""

from __future__ import annotations

import inspect
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.ai import cost_paths as cp
from fbi.ai import cost_paths_readers as readers
from fbi.ai.config import SHADOW_ENGINES
from fbi.ai.pricing import token_cost

AT = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
KICK = AT + timedelta(hours=6)
_ids = iter(range(1, 100_000))


def call(prompt: str | None, model: str = "claude-sonnet-5-5", *, cost: str = "0.010000", purpose: str = "pick_review", tier: str = "analysis",
         fixture: int | None = 1, batch: bool = False, status: str = "ok", cid: int | None = None, kickoff: datetime | None = KICK,
         at: datetime = AT, **tokens: int) -> cp.Call:
    provider = "exa" if tier == "search" else "anthropic"
    return cp.Call(next(_ids) if cid is None else cid, at, purpose, tier, provider, model, prompt, status, Decimal(cost), fixture,
                   kickoff if fixture is not None else None, batch, tokens.get("inp", 0), tokens.get("out", 0), tokens.get("cached", 0),
                   tokens.get("write", 0), tokens.get("write_1h", 0))


def link(c: cp.Call, *, engine: str = "llm", selection: str = "Home", role: str | None = "candidate", tier: str | None = "analysis",
         fixture: int = 1) -> cp.Link:
    return cp.Link(c.id, engine, fixture, "1X2", selection, Decimal("0"), role, tier)


def test_every_prompt_has_one_path_and_part() -> None:
    cases = {
        ("review-v2", "pick_review"): ("production", "review"), ("brief-v8", "match_brief"): ("production", "brief"),
        ("match-context-v4", "match_analysis"): ("deliberation", "match_agent"), ("match-assess-v3", "other"): ("deliberation", "match_agent"),
        ("stats-assess-v3", "other"): ("deliberation", "stats_agent"), ("player-assess-v1", "match_analysis"): ("deliberation", "player_agent"),
        ("council-v1", "other"): ("deliberation", "council"), ("council-opus-v1", "pick_review"): ("deliberation", "escalation"),
        ("extract-v3", "evidence_extraction"): ("research", "extraction"), (None, "web_search"): ("research", "search"),
        ("user-narrative-v3", "other"): ("chronicles", "chronicle"), ("learning-v2", "learning"): ("rest", "learning"),
        ("patterns-v1", "pattern_review"): ("rest", "learning"), ("pick-postmortem-v4", "postmortem"): ("rest", "postmortem"),
        ("pmr-v1", "postmortem"): ("rest", "postmortem"), ("battery-v3", "other"): ("rest", "lab"), ("equiv-v1", "other"): ("rest", "lab"),
        ("something-new-v1", "other"): ("rest", "other"), (None, "match_brief"): ("production", "brief"),
    }
    for (prompt, purpose), want in cases.items():
        tier = "search" if purpose == "web_search" else "analysis"
        assert cp.path_of(call(prompt, purpose=purpose, tier=tier)) == want, (prompt, purpose)
    assert {p for p, _ in cases.values()} == set(cp.PATHS)
    a_batch_of_the_council = cp.Call(1, AT, "other", "analysis", "anthropic", "claude-sonnet-5-5", None, "ok", Decimal(0), agent="council")
    assert cp.path_of(a_batch_of_the_council) == ("deliberation", "council"), "without a prompt the agent still says whose it is"


def test_the_paths_add_up_to_the_total_and_the_total_to_the_ledger() -> None:
    rnd = random.Random(7)
    prompts = ["review-v2", "brief-v8", "council-v1", "council-opus-v1", "match-assess-v3", "extract-v1", None, "learning-v2", "battery-v3",
               "pick-postmortem-v4", "unknown-v9"]
    rows = []
    for _ in range(400):
        p = rnd.choice(prompts)
        tier = "search" if p is None else "analysis"
        rows.append(call(p, purpose="web_search" if p is None else "other", tier=tier, cost=f"{rnd.randint(0, 99_999) / 1_000_000:.6f}"))
    total = sum((c.cost for c in rows), Decimal(0))
    rep = cp.report(rows, ledger=cp.Ledger(len(rows), total))
    t = rep["total"]
    assert t["usd_exact"] == str(total.quantize(Decimal("0.000001"))) and t["difference_usd"] == "0.000000" and t["reconciles"] is True
    assert sum(Decimal(p["usd_exact"]) for p in rep["paths"].values()) == total, "each row in exactly one path"
    assert sum(p["calls"] for p in rep["paths"].values()) == len(rows)
    for name, p in rep["paths"].items():
        assert sum(Decimal(q["usd_exact"]) for q in p["parts"].values()) == Decimal(p["usd_exact"]), f"the parts of {name} add up to it"
        assert sum(q["calls"] for q in p["parts"].values()) == p["calls"]
    off = cp.report(rows, ledger=cp.Ledger(len(rows), total + Decimal("0.02")))["total"]
    assert off["reconciles"] is False and off["difference_usd"] == "0.020000"
    missing_row = cp.report(rows, ledger=cp.Ledger(len(rows) + 1, total))["total"]
    assert missing_row["reconciles"] is False, "the same sum over another number of rows is not the ledger"
    assert cp.report(rows)["total"]["reconciles"] is None, "without the ledger's sum the report does not claim it reconciles"


def test_candidates_and_matches_per_path_with_their_n() -> None:
    r1, r2, r3 = call("review-v2", cost="0.040000", fixture=1), call("review-v2", cost="0.020000", fixture=1), call("review-v2", cost="0.030000", fixture=2)
    brief = call("brief-v8", "claude-haiku-5-5", cost="0.010000", purpose="match_brief", tier="bulk", fixture=3)
    council = call("council-v1", cost="0.050000", fixture=2)
    links = [link(r1, selection="Home"), link(r2, selection="Home"), link(r3, selection="Over", fixture=2),
             link(council, engine="ma-v1", selection="Over", fixture=2), link(council, engine="ma-v1", selection="Under", fixture=2),
             link(council, engine="llm", selection="Draw", fixture=2)]
    rep = cp.report([r1, r2, r3, brief, council], links)
    prod, delib = rep["paths"]["production"], rep["paths"]["deliberation"]
    assert (prod["fixtures"], prod["candidates"], prod["usd"]) == (3, 2, "0.10")
    assert prod["usd_per_fixture"] == "0.0333" and prod["usd_per_candidate"] == "0.0500"
    review, brief_part = prod["parts"]["review"], prod["parts"]["brief"]
    assert (review["fixtures"], review["candidates"], review["usd_per_candidate"]) == (2, 2, "0.0450")
    assert (brief_part["candidates"], brief_part["usd_per_candidate"], brief_part["usd_per_fixture"]) == (0, None, "0.0100")
    assert (delib["candidates"], delib["fixtures"]) == (2, 1), "a call of the shadow serves every candidate of its pass; a link of llm is not its"


def test_every_call_to_opus_with_its_rule() -> None:
    opus = "claude-opus-5-5"
    pick, contra, material = (call("review-v2", opus, tier="final", cost="0.090000") for _ in range(3))
    no_role = call("review-v2", opus, tier="final", cost="0.080000")
    not_final = call("review-v2", opus, tier="final", cost="0.070000")
    e6 = call("council-opus-v1", opus, tier="final", cost="0.060000")
    skipped = call("council-opus-v1", opus, tier="final", cost="0.050000")
    battery = call("battery-v3", opus, purpose="other", tier="final", cost="0.040000", batch=True)
    loose = call("something-v1", opus, purpose="other", tier="final", cost="0.030000")
    links = [link(pick, role="pick", tier="final"), link(contra, role="contradiction", tier="final"), link(material, role="candidate", tier="final"),
             link(not_final, role="pick", tier="analysis")]
    routes = [cp.Route(e6.id, "escalation", "CALL", "E6", ("E6",)), cp.Route(skipped.id, "escalation", "SKIP", None)]
    items = [cp.LabItem(battery.id, "battery", "council", "k_escalated")]
    rep = cp.report([pick, contra, material, no_role, not_final, e6, skipped, battery, loose], links, routes, items)
    o = rep["opus"]
    by: dict[tuple[str, str], tuple[int, bool, str]] = {}
    for r in o["by_rule"]:
        n, _, where = by.get((r["path"], r["rule"]), (0, r["registered"], r["where"]))
        by[(r["path"], r["rule"])] = (n + r["calls"], r["registered"], where if n else r["where"])
    assert by[("production", "L3_pick")] == (1, True, "ai.pick_reviews.output")
    assert by[("production", "L3_contradiction")] == (1, True, "ai.pick_reviews.output")
    assert by[("production", "L3_material")] == (1, True, "ai.pick_reviews.output")
    assert by[("deliberation", "E6")] == (1, True, "ai.agent_tasks.route")
    assert by[("rest", "lab_battery")] == (1, True, "ai.batch_items.context")
    assert by[("production", "unregistered")][:2] == (2, False), "no review row, or a row that is not at the final tier, is no rule"
    assert by[("deliberation", "unregistered")][:2] == (1, False), "a route that did not CALL is no rule"
    assert by[("rest", "unregistered")][:2] == (1, False)
    assert (o["calls"], o["registered"], o["unregistered"], o["all_registered"]) == (9, 5, 4, False)
    assert sorted(o["unregistered_ids"]) == sorted([no_role.id, not_final.id, skipped.id, loose.id]) and o["unregistered_usd"] == "0.23"
    assert cp.report([pick], links)["opus"]["all_registered"] is True
    assert cp.report([call("review-v2")])["opus"] == {"calls": 0, "usd": "0.00", "registered": 0, "unregistered": 0, "unregistered_usd": "0.00",
                                                       "all_registered": True, "unregistered_ids": [], "by_rule": []}


def test_batch_cache_and_what_could_have_waited() -> None:
    sonnet = "claude-sonnet-5-5"

    def priced(cached: int = 0, batch: bool = False) -> str:  # what the ledger would have billed, with the verified price table
        return str(token_cost("anthropic", sonnet, input_tokens=10_000, output_tokens=500, cached_tokens=cached, batch=batch, at=AT))

    live_far = call("review-v2", sonnet, cost=priced(cached=8_000), inp=10_000, out=500, cached=8_000)
    live_far_pick = call("review-v2", sonnet, cost=priced(), inp=10_000, out=500)
    batched = call("review-v2", sonnet, cost=priced(batch=True), batch=True, inp=10_000, out=500)
    near = call("review-v2", sonnet, cost=priced(), kickoff=AT + timedelta(hours=2), inp=10_000, out=500)
    arbitration = call("review-v2", sonnet, cost=priced(), inp=10_000, out=500)
    search = call(None, "exa", cost="0.015000", purpose="web_search", tier="search")
    links = [link(live_far), link(live_far_pick, role="pick"), link(batched), link(near), link(arbitration, role="contradiction")]
    rep = cp.report([live_far, live_far_pick, batched, near, arbitration, search], links)
    review = rep["paths"]["production"]["parts"]["review"]
    waited = live_far.cost + live_far_pick.cost
    assert review["could_wait"]["calls"] == 2, "real time, a candidate's or a pick's, 4 h or more before the kick-off"
    assert Decimal(review["could_wait"]["usd"]) == waited.quantize(Decimal("0.01"))
    assert (review["batch"]["calls"], review["batch"]["share_of_calls_pct"]) == (1, "20.0")
    cache = review["cache"]
    assert (cache["model_calls"], cache["calls_reading_cache"], cache["input_tokens"], cache["cached_tokens"]) == (5, 1, 50_000, 8_000)
    assert cache["read_share_pct"] == "16.0"
    assert rep["paths"]["research"]["cache"]["model_calls"] == 0, "a search has no tokens to cache"
    fresh = token_cost("anthropic", sonnet, input_tokens=10_000, output_tokens=500, at=AT)
    assert Decimal(review["saved"]["cache_usd"]) == (fresh - live_far.cost).quantize(Decimal("0.01")) > 0
    assert Decimal(review["saved"]["batch_usd"]) == (fresh - batched.cost).quantize(Decimal("0.01")) > 0
    assert not cp.could_wait(near, link(near)) and not cp.could_wait(batched, link(batched)) and not cp.could_wait(live_far, None)
    assert review["could_wait"]["models"] == [{"model": sonnet, "calls": 2, "usd": str(waited.quantize(Decimal("0.01")))}]
    assert review["calls_linked_to_a_review"] == 5


def test_a_saving_is_priced_call_by_call_never_over_a_sum_of_prompts() -> None:
    """Haiku costs five times more above 100k input tokens IN ONE PROMPT: three prompts of 60k are three cheap prompts, not one of 180k."""
    haiku = "claude-haiku-5-5"
    one = token_cost("anthropic", haiku, input_tokens=60_000, output_tokens=800, at=AT)
    briefs = [call("brief-v8", haiku, cost=str(one), purpose="match_brief", tier="bulk", inp=60_000, out=800) for _ in range(3)]
    saved = cp.report(briefs)["paths"]["production"]["parts"]["brief"]["saved"]
    assert saved == {"cache_usd": "0.00", "batch_usd": "0.00", "calls_unpriced": 0}, "no cache, no batch: nothing saved"
    summed = token_cost("anthropic", haiku, input_tokens=180_000, output_tokens=2_400, at=AT)
    assert summed > 3 * one, "what a sum of the prompts would have invented"
    unknown = call("review-v2", "some-new-model", cost="0.010000", inp=1_000, out=100)
    assert cp.report([unknown])["paths"]["production"]["saved"]["calls_unpriced"] == 1


def test_the_chronicles_ledger_is_beside_the_total_never_in_it() -> None:
    rows = [call("review-v2", cost="1.000000")]
    rep = cp.report(rows, user_ledger=[{"prompt_version": "user-narrative-v3", "model": "claude-haiku-5-5", "calls": 12, "usd": Decimal("0.036")}],
                    ledger=cp.Ledger(1, Decimal("1")))
    u = rep["chronicles_user_ledger"]
    assert (u["calls"], u["usd"], u["in_total"]) == (12, "0.04", False)
    assert rep["total"]["usd"] == "1.00" and rep["total"]["reconciles"] is True
    assert rep["paths"]["chronicles"]["calls"] == 0, "the chronicle writes to its own ledger"


def test_an_empty_window_decides_nothing_and_reads_in_spanish() -> None:
    rep = cp.report([], ledger=cp.Ledger(0, Decimal(0)), since=AT - timedelta(days=14), until=AT)
    assert rep["version"] == cp.VERSION == "cost-paths-v1" and rep["decides"] is False and rep["total"]["reconciles"] is True
    assert all(p["usd_per_fixture"] is None and p["usd_per_candidate"] is None for p in rep["paths"].values())
    text = cp.lines(rep)
    assert text[0].startswith("Coste por camino cost-paths-v1 (informa, no decide)") and "cuadra: sí" in text[1]
    rows = [call("review-v2", "claude-opus-5-5", tier="final")]
    assert any("sin regla 1" in t for t in cp.lines(cp.report(rows)))


def test_the_rows_of_the_readers_become_the_reports_rows() -> None:
    c = readers.call_of({"id": 5, "at": AT, "purpose": "pick_review", "tier": "final", "provider": "anthropic", "model": "claude-opus-5-5",
                         "prompt_version": "review-v2", "status": "ok", "cost_usd": Decimal("0.081234"), "fixture_id": 9, "kickoff_at": KICK,
                         "batch": False, "input_tokens": 100, "output_tokens": 10, "cached_tokens": None, "cache_write_tokens": 0,
                         "cache_write_1h_tokens": 0, "agent": None, "workspace": "PREDIGOL"})
    assert (c.cost, c.fixture_id, c.cached_tokens, c.opus, c.lead_minutes) == (Decimal("0.081234"), 9, 0, True, 360.0)
    lk = readers.link_of({"usage_id": 5, "engine": "llm", "fixture_id": 9, "market_key": "OU", "selection": "Over", "line": Decimal("2.50"),
                          "role": "pick", "tier": "final"})
    assert lk.key == (9, "OU", "Over", "2.5")
    rt = readers.route_of({"usage_id": 5, "task_kind": "escalation", "action": "CALL", "escalation": "E7", "fired": ["E6", "E7"]})
    assert rt.fired == ("E6", "E7")
    assert readers.item_of({"usage_id": 5, "lab": "battery", "target": "council", "base": "k_escalated"}).base == "k_escalated"


def test_the_readers_read_only_and_name_their_engines() -> None:
    assert "r.engine = 'llm'" in readers.PRODUCTION_LINKS_SQL and "ma-v1" not in readers.PRODUCTION_LINKS_SQL
    assert "r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')" in readers.SHADOW_LINKS_SQL and "'llm'" not in readers.SHADOW_LINKS_SQL
    assert tuple(cp.SHADOW_ENGINES) == tuple(SHADOW_ENGINES), "the shadow's engines are config's one list"
    for sql in readers.STATEMENTS:
        assert not any(w in sql.upper() for w in ("INSERT", "UPDATE ", "DELETE", "CREATE", "ALTER", "TRUNCATE")), "it reads only"
    assert "FROM ai.usage u" in readers.CALLS_SQL and "FROM ai.usage WHERE at >= %(since)s AND at < %(until)s" in readers.LEDGER_SQL
    assert "ai.user_usage" in readers.USER_LEDGER_SQL


def test_the_script_opens_the_database_read_only_in_one_snapshot() -> None:
    from scripts import ia_cost_paths as script

    source = inspect.getsource(script)
    assert "default_transaction_read_only=on" in source and "conn.read_only = True" in source and ".commit(" not in source
    assert "REPEATABLE_READ" in source
    start, end = script.window(14, None, None, now=AT)
    assert (start, end) == (AT - timedelta(days=14), AT)
    s, e = script.window(14, AT.date() - timedelta(days=3), AT.date(), now=AT)
    assert (s, e) == (datetime(2026, 11, 6, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC))
    with pytest.raises(ValueError):
        script.window(0, None, None, now=AT)
    with pytest.raises(ValueError):
        script.window(14, AT.date(), AT.date(), now=AT)
    assert script.main(["--since", "2026-11-10", "--until", "2026-11-09"]) == script.CANNOT
