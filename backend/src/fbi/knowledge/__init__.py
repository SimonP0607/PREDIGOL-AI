"""Match Knowledge (plan F7): what a finished match leaves behind, read once, in layers, with the moment each layer was known.

* ``fbi.knowledge.events``  - what each line of the provider's list of events IS (a goal, an own goal, a penalty, a kick of a shoot-out, a second yellow,
  a VAR decision...) and in which period of the match it happened.

Everything here concerns a match that is OVER. No pre-match reader (the dossier, the AI packet, the models) may import it
(``tests/unit/test_knowledge_isolation.py``).
"""
