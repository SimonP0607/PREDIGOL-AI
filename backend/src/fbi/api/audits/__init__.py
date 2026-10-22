"""Audits of what the product itself shows (players, team records), against the provider.

They read the API's own SQL and services - "through the product's own code, not a copy of it" - so they sit in
the API layer, above ``fbi.truth``, not inside it: the domain must not import the layer that serves it.
"""
