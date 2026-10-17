"""Outcome models: Elo ordered-logit, Poisson (Maher) and Dixon-Coles.

Each is fitted by maximum likelihood on results strictly before the moment it
predicts, and every parameter that is chosen rather than fitted (time decay)
is chosen on a validation window that precedes the test window. Probabilities
for 1X2, Over/Under and BTTS come from the model's score distribution by
summation - never from a heuristic mapping.
"""
