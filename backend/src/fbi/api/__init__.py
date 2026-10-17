"""The product API: router -> service -> repository -> database.

Routers parse and validate a request and return a contract. Services decide
what the honest answer is - including "there is not enough data to answer" -
and assemble contracts. Repositories run SQL and return plain rows. No router
contains SQL; no repository decides what a number means.

Every connection is opened read-only. Nothing reachable from an HTTP request
can write to the database.
"""
