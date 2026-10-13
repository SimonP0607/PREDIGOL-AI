"""PrediGol Intelligence: the per-market calibration (CAPA 2's last step) and the decision layer (CAPA 4), with what
lets them learn without overfitting - outcomes and closing-line value, post-mortems that separate the decision from
the result, longitudinal memory, the daily learning report, the market discovery engine, champion/challenger with
criteria fixed in advance, and an automatic data-leakage audit.

Architecture, contracts and the daily cycle: ``docs/intelligence/PREDIGOL_INTELLIGENCE.md``.

Everything here is SHADOW: it reads the data (CAPA 1), the models' probabilities (CAPA 2) and PrediGol Intelligence's
context (CAPA 3, ``fbi.ai``) and writes only to the ``intel`` schema. It never writes a pick, a model probability, a
rule users see, and never publishes or stakes anything.
"""
