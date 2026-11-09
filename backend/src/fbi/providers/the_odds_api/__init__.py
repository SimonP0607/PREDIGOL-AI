"""The Odds API as a SHARP REFERENCE price (BE-012, plan «Herramientas gratuitas y Open Source», tool 7).

What this package is: the prepared, switched-off connection to https://the-odds-api.com. It reads the 1X2 prices (``h2h``) the European
region lists, takes Pinnacle's as the efficient reference, removes the margin with the Shin estimator the rest of the platform uses and
maps the event onto a fixture we already know. Nothing here is scheduled, nothing writes to the database and nothing makes a request
unless a key is configured: without ``FBI_THEODDSAPI_KEY`` the client refuses to be built.

What it is NOT: a bookmaker feed for users and a place to send them. The price is an internal yardstick (closing-line value, edge
sanity checks); no operator is named or linked to in the product from it (Circular MinTIC 0017/2025, Coljuegos: legal review first).

Cost: the free plan is 500 credits a month and a call costs ``markets x regions`` credits, so a month of ``h2h`` for ``eu`` is 1 credit a
call. The budget defaults to 90 % of the plan and the client refuses the call that would pass it. A PAID plan is the owner's decision,
never a configuration default: ``plan`` only accepts ``free`` until the owner decides otherwise (guide: docs/proyecto/GUIA_THE_ODDS_API.md).
"""
