"""Parlays built only from selections that each carry value on their own.

A parlay is shown when every leg passes the value gate and the legs are independent
enough to multiply. When there are not enough such legs, the answer is "no valid
parlay" - never a parlay padded with legs that do not pass.
"""
