"""Pydantic response contracts: the public shape of every endpoint.

Every probability-like field is named for what it is (``implied_probability``
is 1/odds with the margin still in it; ``p_fair`` is de-vigged) and every
metric that can be absent is Optional - absent is reported as null with a
reason, never as 0.
"""
