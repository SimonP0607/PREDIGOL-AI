"""Walk-forward predictive backtesting against the market baseline.

Train, validation and test are separated in time. A hyper-parameter (the goal
models' time decay) is chosen on the validation season and frozen before the
test season is touched. Inside the test season the models are refitted every
few days on results known before each refit, and every prediction is compared
on the SAME fixtures with the de-vigged market - which is the baseline a model
has to beat to be worth anything.
"""
