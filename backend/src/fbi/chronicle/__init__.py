"""The chronicle of a match, outside PrediGol Intelligence: nothing of Intelligence imports it.

    review    the post-match review of the readers' chronicle (IA-022, ``chronicle-review-v1``): database only, no model, no cost
    job       the worker's ``chronicle_review`` job (IA-023)
    claims    the classes of claim and the facts that authorise them (IA-103, ``claim-classes-v1``)
    plan      the content plan made by code (IA-103, AD-F01, ``content-plan-v1``): pure
    verify    the verifier of the single chronicle, sentence by sentence (IA-104, ``chronicle-verify-v1``): pure
    writer    the prompt ``chronicle-v4`` and its closed contract (IA-104, AD-F02): pure
    inputs    what a plan is made from, read-only
    v4_job    the single chronicle in shadow (``FBI_CHRONICLE_V4``, off by default): plan, write, verify, keep in ``ai.chronicles``

None of it changes a model, a probability, a threshold or a pick, and nothing of the single chronicle reaches a reader.
"""
