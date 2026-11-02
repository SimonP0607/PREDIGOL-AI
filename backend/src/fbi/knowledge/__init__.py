"""Match Knowledge (plan F7): what a finished match leaves behind, read once, in layers, with the moment each layer was known.

* ``fbi.knowledge.events``  - what each line of the provider's list of events IS (a goal, an own goal, a penalty, a kick of a shoot-out, a second yellow,
  a VAR decision...) and in which period of the match it happened (``events-v1``). Pure.
* ``fbi.knowledge.layers``  - the nine layers of a match (result, team figures, events, players, tactics, market, context, picks, post-mortem) built by
  rules from what was read, each saying what it is made of, how fresh it is and how far it can be trusted (``mk-v1``). Pure: no database, no clock.
* ``fbi.knowledge.reader``  - what the layers are made of, read from the tables that hold the facts of a match in batches, and the fingerprint of it that
  says whether a match has to be built again.
* ``fbi.knowledge.builder`` - the only writer: puts a match together once it is over and settled (``layers.SETTLE``), as a chain of rows in
  ``intel.match_knowledge``, and rewrites the lines of its events in ``core.fixture_event_kinds`` in the same transaction.

Everything here concerns a match that is OVER. No pre-match reader (the dossier, the AI packet, the models, the forecast, the decision layer) may import it
or name its tables, the package imports nothing of ours but ``fbi.people.sides``, the builder writes its own two tables and no fact of a match, and the
page of a match reaches only the pure layers (``tests/unit/test_knowledge_isolation.py`` holds all four).
"""
