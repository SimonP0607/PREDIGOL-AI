"""A user's own records: the picks they saved and the parlays they built, and their history.

The API's connections are read-only; this package and ``fbi.auth`` are the only two that
write, each to its own tables, and every statement here is scoped to the signed-in user's id.
"""
