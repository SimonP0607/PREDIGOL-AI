"""The chronicle of a match, outside PrediGol Intelligence: nothing of Intelligence imports it.

    review    the post-match review of the readers' chronicle (IA-022, ``chronicle-review-v1``): database only, no model, no cost
    job       the worker's ``chronicle_review`` job (IA-023)
    claims    the classes of claim and the facts that authorise them (IA-103, ``claim-classes-v1``)
    plan      the content plan made by code (IA-103, AD-F01, ``content-plan-v1``): pure
    verify    the verifier of the single chronicle, sentence by sentence (IA-104, ``chronicle-verify-v1``): pure
    writer    the prompt ``chronicle-v4`` and its closed contract (IA-104, AD-F02): pure
    inputs    what a plan is made from, read-only
    v4_job    the single chronicle in shadow (``FBI_CHRONICLE_V4``, off by default): plan, write, verify, keep in ``ai.chronicles``
    repetition  stock phrases and repetitions, a rule of the verifier (IA-117, AD-F04, ``repeat-check-v1``, ``FBI_CHRONICLE_REPEAT``): pure
    update    the paragraph after the official line-up and the why of each selection, by template (IA-116, AD-F03): pure
    update_job  their new version of the chronicle in shadow (``FBI_CHRONICLE_LINEUP``, off by default), after each E3
    review_v2 the factual review of the single chronicle on its cited facts (IA-118, AD-F06, ``chronicle-review-v2``, ``FBI_CHRONICLE_REVIEW_V2``)
    protocol  the preregistered, unsigned protocol of the human review by sample (IA-118, ``chronicle-protocol-v1``): pure
    retire    the preregistered comparison and the steps of the retirement of the duplicated texts (IA-119, AD-F05, ``retire-compare-v1``)

None of it changes a model, a probability, a threshold or a pick, and nothing of the single chronicle reaches a reader.
"""
