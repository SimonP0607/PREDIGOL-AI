"""The budget by value of information (``voi-v1``, IA-018, architecture layer 5), in SHADOW: it computes and reports, and nothing that spends,
decides or publishes imports it (``tests/unit/test_budgeting_isolation.py`` holds the door shut).

    tiers        pure: a selection's inputs (expected value, potential stake, probability of being published, the model's interval, the hours to
                 the kick-off, the open contradictions) -> a depth D0-D3 and the score it came from
    allocation   pure: a day's candidates as of a moment and budget v3's figures -> each selection's budget, the reserve for the line-up checkpoint
                 and the one for the escalations; never above budget v3's caps, and budget v3's states are hard rails on the depth
    replay       read-only: what the policy would have spent on a Bogota day against what the orchestrator spent, per selection, and the cost of a
                 useful signal by depth once the attribution exists (``scripts/ia_voi.py``)

``fbi.ai.budget_v3`` keeps deciding: this package changes nothing it spends."""
