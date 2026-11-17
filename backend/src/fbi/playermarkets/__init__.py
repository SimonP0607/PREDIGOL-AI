"""The player markets in PRIVATE evaluation (plan 2026, AD-E04, ``IA-130``): shots and shots on target of a player, only after the
line-up evaluation (E3) is reliable. OFF: nothing here reaches a reader, a published pick, a decision or a model.

* ``quotes``     the prices of a player's shots (bets 240, 241) and shots on target (269) read from a stored RAW ``/odds`` answer with
                 the readers of ``tax-v3`` (``fbi.odds.book``), grouped by player and line, with the number of houses behind each and
                 the mark «una sola casa». The provider's names are matched to the men of the match's sheet. Pure.
* ``settle``     the settlement rule of a player count (``player_count_ft@v1``): at least N, void when he did not play, nothing when
                 his figure is missing. Pure.
* ``admission``  the state of a player selection in the private evaluation: always waiting for the official line-up, never
                 confirmed without it, never confirmed by the price of fewer than three houses, and nothing at all while E3 is not
                 reliable (decision n.º 7). Pure.
* ``lab``        the read-only measurement over played matches: coverage of the prices, houses, names matched, settlement - the
                 sample registered for AD-K02.

It writes nothing and has no table: the prices stay in RAW (never deleted), the rule lives in code, and the families are ``off``.
"""
