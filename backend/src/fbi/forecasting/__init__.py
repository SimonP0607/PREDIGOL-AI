"""PrediGol's forecast of a match (plan F5), kept apart from the models and from the decision layer.

This package is deliberately NOT one of ``fbi.core.version.MODEL_PACKAGES``. Those packages are the code that decides what a model
predicts, and a change anywhere in them renews the version of every model (a full re-forecast, a new prospective record, a research run
that becomes due). The forecast derives from what the models say - it picks the model, applies a calibrator, writes a table - and decides
nothing about what any of them predicts. It sat in ``fbi.predictions`` for the first release of F5 (23 Oct 2026, 02:45 UTC) and that is
what happened: 92,937 forecasts were written again under new model versions. A test pins the fingerprint, so it cannot happen unnoticed.
"""
