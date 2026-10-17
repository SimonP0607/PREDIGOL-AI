"""PrediGol's AI decision layer (``docs/ai/AI_DECISION_LAYER.md``).

    data -> features -> quantitative models -> shortlist -> CONTEXT (packet + evidence)
         -> REVIEW (rules engine, and a language model when configured) -> picks / parlays
         -> result -> post-mortem -> memory -> hypotheses -> experiments -> owner

What this package may do, and what it may not:

* It READS the platform (fixtures, prices, models, picks) and WRITES only into the ``ai`` schema,
  plus proposals into the evolution loop (``analytics.research_hypotheses``, status PROPOSED).
* A review can confirm, lower, reject or abstain. Nothing here raises a probability, creates a
  pick, edits a threshold or promotes a model.
* Its decisions reach users only in ``enforce`` mode, which needs BOTH the owner's switch
  (``FBI_AI_MODE=enforce``) and the AI's own shadow gate (``fbi.ai.shadow``). Until then every
  decision is recorded and shown to the owner only.
* An AI failure (no key, a timeout, a budget spent, an invalid answer) is an ABSTAIN with its
  reason; the quantitative pipeline never waits for it and never breaks because of it.
"""
