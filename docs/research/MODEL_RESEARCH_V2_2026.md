# Model research V2 (2026): pre-match football outcome models

*Research pass of 4 October 2026 (web search over papers, competition results and reputable
practitioner sources; every claim carries its source, listed at the end). Scope: pre-match
1X2, Over/Under, BTTS, Asian Handicap and Double Chance for about 120 competitions, compared
against de-vigged bookmaker prices. Thresholds marked "proposal" are ours, not the literature's.
This document drives GATE F (model research) and GATE G (backtest V2, champion/challenger).*

## 1. Bottom line

1. **The betting market is the strongest forecaster we can access.** Bookmaker odds scored
   better than every top entry of the 2017 Soccer Prediction Challenge [1]; Elo-based models do
   worse than market odds [3]; odds-setters beat a statistical model with many variables [4]; a
   2026 preprint finds a tuned Dixon-Coles adds nothing to the closing price over 19 Serie A
   seasons [2]. Our own numbers agree. Beating the close will be rare, and is most plausible in
   thin markets rather than top leagues.
2. **Model families perform about the same** [5][6]. New *information* (shots/xG, line-ups) is
   more likely to help than a new algorithm.
3. **Roles.** Where liquid odds exist, the de-vigged market is the default forecast (the
   champion). Our models (a) cover fixtures without reliable odds, (b) produce consistent O/U,
   BTTS, AH and DC probabilities from one score distribution, and (c) act as challengers that
   must prove they add information *beyond* the market.
4. **Qualify picks on expected value after uncertainty plus closing-line value (CLV), never on
   realised ROI**, which needs thousands of bets to separate skill from luck [7][8].

## 2. Our measured state (internal, not literature)

Walk-forward backtest, 5 leagues, test season 2024/25, 2,224 fixtures
(`docs/rebuild/CRITICAL_REBUILD_BASELINE.md`):

| Forecast | Log loss | Gap vs de-vigged Pinnacle close (Shin) |
|---|---|---|
| League base rates | 1.0765 | +0.119 (worse), n = 1,751 |
| Multinomial logit (Elo + form) | 0.9948 | +0.025 (worse), n = 1,684 |
| Shadow picks | ROI −22.2 % on 923 settled | n/a |

Two things to fix before any new model is judged:

* **The two gaps are not on the same fixtures.** They imply a market log loss of 0.9575 and
  0.9698; on identical fixtures these would be equal. The comparisons ran on different subsets
  (1,751 vs 1,684 matched fixtures). Every comparison from now on is **paired** on one fixture
  set.
* **−22 % is very unlikely to be bad luck.** With level stakes and no edge, the standard error
  of ROI at decimal odds *o* over *n* bets is about √(o−1)/√n: for 923 picks, 3.3 pp at odds 2
  and 6.6 pp at odds 5 — so −22 % is 3–7 standard errors below break-even. The likely cause is a
  model less sharp than the market "finding value" on longshots, where 1X2 prices carry the
  strongest favourite-longshot bias [9]; blindly backing prices above 5.00 historically returned
  80 % or less of stakes [10]. Next step: split pick ROI by odds bucket into price-vs-close,
  EV implied by the close, and luck.

## 3. The model ladder

| Model | What the evidence says | For us |
|---|---|---|
| **De-vigged market** | Shin beat normalisation and regression, with less advantage in big markets [11]; the power method beat proportional and matched Shin [12]; odds-ratio and additive are in the `implied` package [13]. Across 84,230 matches 1X2 odds show strong favourite-longshot bias while AH odds give unbiased probabilities [9][14]. On the 2017 challenge test set odds scored RPS 0.2020 vs 0.2054–0.2083 for the top entries [1]; in Serie A the close beat Dixon-Coles in all 7 test seasons (RPS 0.1905 vs 0.1972) [2]. | **Champion.** Choose the de-vig method per market and tier on our data; test AH-derived 1X2. |
| **Elo** | Beats historical frequencies, trails odds; nothing profitable on average [3]. Modelling home advantage and draws explicitly helps [15]. Ordered logit on Elo: RPS 0.2035 after the 2017 challenge [1], best for the 2002–14 World Cups [16]. | Keep; tune K and home advantage walk-forward. |
| **Pi-ratings** | Beat Elo considerably and were profitable over 5 EPL seasons 2007–12 [17]; generally ahead of Elo [1]. | Feature (the profit result is old and small). |
| **Poisson → Dixon-Coles** | Maher [18]; Dixon-Coles adds the low-score correction and time decay, ξ = 0.0065 per half-week ≈ 0.0019/day, half-life ≈ 1 year [19][20]. | Tune ξ per tier. |
| **Bivariate Poisson** | Models the correlation between the teams' goals, with a draw-inflated variant [21]; with independent Poisson the best of 10 team-strength models, with time and importance weights [22]. | One score matrix → O/U, BTTS, AH, DC. |
| **Bayesian hierarchical** | Shrinks strengths to a common mean (mixture priors avoid over-shrinking) [23]; odds can feed the priors [24]. | Sparse competitions; posterior intervals. |
| **Ordered probit/logit on ratings** | Goals- and results-based models differ little; a hybrid is best [25]; Bradley-Terry ≈ hierarchical Poisson [26]. | Baseline. |
| **Gradient boosting / ML** | GBT on pi-rating and PageRank features won the 2017 challenge (RPS 0.2063) [27][1]; k-NN on ratings top-ranked in the organisers' report [28]. 2023 challenge (714 matches): CatBoost + pi-ratings + deep learning finished 16th (RPS 0.2195), ~6 % behind a bookmaker-consensus-type model [29]; simple k-NN/NN placed 4th–7th [30]. Later scores on the public 2017 test set (0.1925 [1]) should be discounted; the top score-based models make nearly identical predictions [5]. | Little gain from the algorithm alone. |
| **xG and shots** | xG predicts future success better than goals or shots [31]; shot-based GAP ratings beat goal-based ones for O/U (~0.8 % profit per bet over 12 years) [32]; a simple xG model was less calibrated than odds but reported ~10 % ROI in the Bundesliga [33]; single-league profits are fragile [34]. In Serie A a SoT model added information to a goals model but got zero weight against the market [2]. | Build shots/SoT ratings (we hold the data). |
| **Line-ups / player ratings** | A player-rating model produced significant positive 1X2 returns [36]. | Promising, costly, usable ~1 h before kick-off. |
| **Ensembles / stacking** | A random forest using statistical-model ratings beat each part [37]; a model trained to disagree with the market can profit even as a worse predictor [38]. | Stack **with the market as an input**. |

## 4. How to evaluate

* **Scores.** Log loss is the primary metric: strictly proper, it depends only on the
  probability given to the outcome [39]; in simulations it outperforms RPS [40] (RPS is argued
  for because outcomes are ordered [41]). Report RPS (for comparison with the literature) and
  Brier as secondary metrics.
* **Calibration.** Reliability diagrams, ECE per outcome class, calibration slope and
  intercept per outcome [42][43]; report sharpness too.
* **Validation.** Walk-forward (rolling origin) [44][45][26].
* **Leakage** [46]. Features frozen at a fixed time before kick-off; ratings updated only from
  earlier matches; no closing odds or later line moves as features for earlier picks; de-vig
  settings, calibration and hyper-parameters fitted on the past only; 90-minute settlement
  (no extra time or penalties) [47].
* **Against the market.** Per-match loss differences on the **same fixtures**, a
  Diebold-Mariano test [48][49] and a 95 % bootstrap interval resampled by matchday; and the
  weight *w* our model gets when blended with the market in a logarithmic opinion pool [2]
  (w ≈ 0: the model adds nothing).
* **Sample size.** n ≈ (1.96·σ/δ)², σ the SD of per-match loss differences (measure it), δ the
  improvement to detect; σ = 0.10, δ = 0.005 → ~1,540 matches. Efficient markets produce
  "significant" anomalies in single seasons [34]. A +2 % ROI edge at odds 2.0 needs ~9,600
  level-stake bets; CLV shows skill within 50–100 bets [7].

## 5. Market efficiency: what to expect

* Odds became better forecasters over time [4]; betting returns are a poor measure of
  accuracy [8].
* Inefficiencies are narrow and temporary: best odds across 41 bookmakers made 3 of 11 leagues
  exploitable [50]; bookmakers were slow to price the loss of home advantage in ghost games [51];
  ML beat BTTS odds "in some scenarios" [35]; none of these patterns persisted across 14 seasons
  [34].
* Sharp vs soft: individual books do not fully use competitors' prices [52]; betting soft books
  when above the cross-market average was profitable — and the bettors were restricted [53];
  selections priced against Pinnacle (26,960 bets, ≥ 2 % value) returned 4.90 % vs 2.88 %
  expected from Pinnacle closing odds [54], so the close is an excellent but not perfect
  benchmark; sharp AH books "do not ban serial winners" [14].
* **CLV as an early signal**: among 1,525 tipsters, first-half CLV explained half the variance
  of second-half CLV; its link to profit was weak but significant (R² = 6 %); ~1 % looked
  reliably profitable [7].
* Thinner markets: books differ more and Shin helps more [11]; English tiers 1–4 showed no
  overall bias [52]; softer markets come with low limits and restrictions [7]. **No
  peer-reviewed study of market efficiency in women's football was found** — a hypothesis to
  test, not a premise.
* **Data risk:** Pinnacle closed its public API on 23 Jul 2025; football-data.co.uk calls its
  Pinnacle odds since then "systematically out of date" [55]. Our 2024/25 benchmark predates
  that; any later Pinnacle-based benchmark must be checked (see
  `ODDS_PROVIDER_GAP_ANALYSIS_2026.md`).

## 6. Uncertainty, calibration and "qualified" picks

* Recalibrate on rolling past windows: temperature or Dirichlet scaling for 1X2 [42][43], beta
  calibration for two-way markets [56], isotonic only with large samples [57]. (In NBA data
  selecting models by calibration instead of accuracy turned ROI from −35 % to +35 % [58] —
  another sport; directional only.)
* Intervals: Bayesian posteriors from hierarchical Poisson/DC [23][59], a parametric bootstrap,
  Venn-Abers [60][61] (its guarantees assume i.i.d. matches, which seasons are not: a warning
  flag, not a guarantee).
* **Qualification rule (proposal)** — all four: (1) in that segment the market-blend weight
  *w* > 0 with its interval excluding 0; (2) edge at the lower-bound probability
  p_low × odds − 1 ≥ *m*, *m* starting at 2–3 % [54]; (3) the price is available at a bookmaker
  that accepts the bet; (4) rolling CLV in the segment is positive.
* Staking: Kelly shrunk for parameter uncertainty [62]; adaptive fractional Kelly held up best
  across sports [63]; cap exposure per fixture.

## 7. Segmentation

* **Home advantage is not stable**: it fell in ghost games across 15 leagues [64], mixed across
  17 [65]; Bundesliga near pre-COVID by 2020/21 [66]; lower German divisions showed no drop [67];
  EPL home/away-win ratio back to ~1.68 by 2022/23 [68] yet only 39.0 % home wins by January 2025
  vs 45.8 % across the era [69]; long-run decline [70]. **Replace the fixed +65 with a
  per-competition, time-varying home advantage shrunk to a shared mean; 0 at neutral venues.**
* **Women's football**: home advantage 54.2 % vs 60.0 % for men across 26 countries [71]; fewer
  0-0s, more 2-0/3-0, negatively related scores; a negative-binomial Sarmanov model beat
  Dixon-Coles [72]. **Separate model family.**
* **National teams**: World Football Elo uses K = 60/50/40/30/20 by match type, +100 home, goal
  multiplier [73]; FIFA importance weights run 5 (friendlies) to 60 [74] — but importance
  weighting made FIFA-ranking predictions worse while home advantage and draws helped [15];
  time and importance weights did work in Poisson models [22]. **Test on our data, do not copy.**
* **Cups**: model the 90-minute result [47]; update ratings on the score, never on shoot-outs.
* **Friendlies and youth**: rating systems weight friendlies less [73][74]; little evidence on
  their predictability. **Default: wide intervals and no picks until our own backtest shows
  value.** Integrity risk: 618 suspicious matches flagged in 2025, no breakdown by tier [75].

## 8. Experiment plan (champion vs challenger, highest expected value first)

| # | Challenger | Why | Promote only if |
|---|---|---|---|
| E0 | Harness: one paired fixture set, timestamped odds snapshots, a 90-minute settlement audit, ROI split by odds bucket | Current numbers are not comparable; −22 % looks systematic | The market's log loss is identical across models on the same fixtures |
| E1 | Market champion: de-vig methods (proportional, Shin, power, odds-ratio, additive); Pinnacle-like single sharp book vs the multi-book consensus; 1X2 from AH [9] | Best forecast available, cheap | Lowest log loss per market and tier |
| E2 | Market-anchored blend: market price at pick time + Elo, pi-ratings, Dixon-Coles, shots; *w* per segment | The only route to qualified picks | *w* > 0 out of sample, interval excluding 0 |
| E3 | Structural: DC with tuned ξ, time-varying home advantage, bivariate / NB-Sarmanov, one score matrix for all markets | Coverage without odds, consistent markets | Beats current DC on log loss and calibration |
| E4 | Shots/SoT (GAP-style) ratings [32] | Best evidence for totals and BTTS | Log loss below E3, interval excluding 0 |
| E5 | CatBoost/LightGBM on ratings + market, calibrated | Small expected gain [5] | Log loss below E2 |
| E6 | Line-up and player-strength features [36] | Possible edge, high cost | Lower log loss and positive CLV |

Report for every experiment: paired fixtures; log loss, RPS, Brier; difference vs champion and
vs market with bootstrap interval and DM p-value; per-season/league direction; calibration
error, slope and reliability plot; *w*; for picks: count, mean claimed edge, mean CLV with
t-statistic, EV implied by the close, realised ROI with its standard error.

**Do not promote (proposal) if any holds:** (1) the 95 % interval of the log-loss difference
vs the champion includes 0; (2) for picks: not better than the de-vigged close (interval
excluding 0) and the interval for *w* includes 0; (3) calibration slope outside 0.9–1.1 for any
outcome, or ECE worse than the champion's; (4) the gain appears in fewer than half the
seasons/leagues or in one league only; (5) shadow-pick CLV ≤ 0 or t < 2 after ≥ 300 picks —
realised ROI alone never qualifies a model; (6) any leakage check fails, the model was tuned
on the test season, or the result flips under another de-vig method.

## Sources

1. Bunker, Yeung, Fujii (2024). Machine Learning for Soccer Match Result Prediction. https://arxiv.org/abs/2403.07669
2. Pitcan (2026, preprint). Does a Structural Model Add Anything to the Closing Price? https://arxiv.org/abs/2608.11505
3. Hvattum, Arntzen (2010). Using ELO ratings for match result prediction in association football. IJF. https://doi.org/10.1016/j.ijforecast.2009.10.002
4. Forrest, Goddard, Simmons (2005). Odds-setters as forecasters. IJF. https://salford-repository.worktribe.com/output/1472154/odd-setters-as-forecasters-the-case-of-english-football
5. Hubáček, Šourek, Železný (2022). Forty years of score-based soccer match outcome prediction. https://academic.oup.com/imaman/article-abstract/33/1/1/6342916
6. Fischer, Heuer (2025). Match Predictions in Soccer: Machine Learning vs. Poisson Approaches. https://www.researchgate.net/publication/393885760_Match_Predictions_in_Soccer_Machine_Learning_vs_Poisson_Approaches
7. Buchdahl. All Monkeys Are Throwing Darts (closing-line value). https://www.football-data.co.uk/blog/monkeys_throwing_darts.php
8. Wunderlich, Memmert (2020). Are betting returns a useful measure of accuracy? IJF. https://ideas.repec.org/a/eee/intfor/v36y2020i2p713-722.html
9. Hegarty, Whelan (2025). Forecasting soccer matches with betting odds: A tale of two markets. IJF. https://www.sciencedirect.com/science/article/pii/S0169207024000670
10. football-data.co.uk (2015). Revisiting the Favourite-Longshot Bias. https://www.football-data.co.uk/blog/favourite_longshot_bias_revisited.php
11. Štrumbelj (2014). On determining probability forecasts from betting odds. IJF. https://www.sciencedirect.com/science/article/abs/pii/S0169207014000533
12. Clarke, Kovalchik, Ingram (2017). Adjusting bookmaker's odds to allow for overround. https://www.sciencepublishinggroup.com/article/10.11648/j.ajss.20170506.12
13. `implied` R package vignette. https://rdrr.io/cran/implied/f/vignettes/introduction.Rmd
14. Hegarty, Whelan. VoxEU column. https://cepr.org/voxeu/columns/forecasting-soccer-matches-betting-odds-tale-two-markets
15. Szczecinski, Roatis (2022). FIFA ranking: Evaluation and path forward. https://arxiv.org/abs/2201.00691
16. Robberechts, Davis (2019). Forecasting the FIFA World Cup. https://www.researchgate.net/publication/332257439_Forecasting_the_FIFA_World_Cup_-_Combining_Result-_and_Goal-Based_Team_Ability_Parameters
17. Constantinou, Fenton (2013). Pi-ratings. JQAS. https://qmro.qmul.ac.uk/xmlui/bitstream/123456789/10776/5/CONSTANTINOU%20Determing%20the%20Level%20of%20Ability%202012%20Accepted.pdf
18. Maher (1982). Modelling association football scores. https://doi.org/10.1111/j.1467-9574.1982.tb00782.x
19. Dixon, Coles (1997). Modelling association football scores and inefficiencies in the football betting market. https://doi.org/10.1111/1467-9876.00065
20. opisthokonta. Dixon-Coles time weighting. https://opisthokonta.net/?p=1013
21. Karlis, Ntzoufras (2003). Bivariate Poisson models. https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/1467-9884.00366
22. Ley, Van de Wiele, Van Eetvelde (2019). Ranking soccer teams on the basis of their current strength. https://arxiv.org/abs/1705.09575
23. Baio, Blangiardo (2010). Bayesian hierarchical model for football results. https://discovery.ucl.ac.uk/id/eprint/16040/
24. Egidi, Pauli, Torelli (2018). Combining historical data and bookmakers' odds. https://arxiv.org/abs/1802.08848
25. Goddard (2005). Regression models for forecasting goals and match results. IJF. https://www.sciencedirect.com/science/article/abs/pii/S0169207004000676
26. Tsokos et al. (2019). Modeling outcomes of soccer matches. https://doi.org/10.1007/s10994-018-5741-1
27. Hubáček, Šourek, Železný (2019). Learning to predict soccer results with gradient boosted trees. https://ida.fel.cvut.cz/papers/hubacek2019learning.html
28. Berrar, Lopes, Dubitzky (2019). Incorporating domain knowledge in ML for soccer outcome prediction. https://oro.open.ac.uk/96634
29. Yeung, Bunker, Umemoto, Fujii (2024). Evaluating soccer match prediction models. https://link.springer.com/article/10.1007/s10994-024-06608-w
30. Berrar, Lopes, Dubitzky (2024). A data- and knowledge-driven framework. https://link.springer.com/article/10.1007/s10994-024-06625-9
31. Mead, O'Hare, McMenemy (2023). Expected goals in football. PLOS ONE. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0282295
32. Wheatcroft (2020). A profitable model for predicting the over/under market. IJF. https://ideas.repec.org/a/eee/intfor/v36y2020i3p916-932.html
33. Wilkens (2026). Can simple models predict football and beat the odds? JSA. https://journals.sagepub.com/doi/10.1177/22150218261416681
34. Winkelmann, Ötting, Deutscher, Makarewicz (2024). Are betting markets inefficient? https://ideas.repec.org/a/sae/jospec/v25y2024i1p54-97.html
35. da Costa, Marinho, Pires (2022). The case of "both teams to score". IJF. https://ideas.repec.org/a/eee/intfor/v38y2022i3p895-909.html
36. Holmes, McHale (2024). Player rating based model. IJF. https://livrepository.liverpool.ac.uk/id/eprint/3170651
37. Groll, Ley, Schauberger, Van Eetvelde (2018/2019). Hybrid random forest. https://arxiv.org/abs/1806.03208
38. Hubáček, Šír (2023). Beating the market with a bad predictive model. IJF. https://arxiv.org/abs/2010.12508
39. Gneiting, Raftery (2007). Strictly proper scoring rules. JASA. https://doi.org/10.1198/016214506000001437
40. Wheatcroft (2021). The case against the Ranked Probability Score. JQAS. https://arxiv.org/abs/1908.08980
41. Constantinou, Fenton (2012). Inadequate scoring rules. JQAS. https://ideas.repec.org/a/bpj/jqsprt/v8y2012i1n12.html
42. Guo et al. (2017). On calibration of modern neural networks. https://arxiv.org/abs/1706.04599
43. Kull et al. (2019). Dirichlet calibration. https://arxiv.org/abs/1910.12656
44. Tashman (2000). Out-of-sample tests of forecasting accuracy. IJF. https://ideas.repec.org/a/eee/intfor/v16y2000i4p437-450.html
45. Hyndman, Athanasopoulos. FPP3 §5.10, time series cross-validation. https://otexts.com/fpp3/tscv.html
46. Kaufman, Rosset, Perlich (2012). Leakage in data mining. https://doi.org/10.1145/2382577.2382579
47. Pinnacle betting rules (soccer). https://www.pinnacle.com/en/future/betting-rules
48. Diebold, Mariano (1995). Comparing predictive accuracy. https://doi.org/10.1080/07350015.1995.10524599
49. Diebold (2015). Comparing predictive accuracy, twenty years later. https://www.nber.org/papers/w18391
50. Angelini, De Angelis (2019). Efficiency of online football betting markets. IJF. https://ideas.repec.org/a/eee/intfor/v35y2019i2p712-721.html
51. Winkelmann, Deutscher, Ötting (2021). Bookmakers' mispricing of the disappeared home advantage. https://ideas.repec.org/a/taf/applec/v53y2021i26p3054-3064.html
52. Elaad, Reade, Singleton (2020). Information, prices and efficiency in an online betting market. https://ideas.repec.org/a/eee/finlet/v35y2020ics1544612319306440.html
53. Kaunitz, Zhong, Kreiner (2017). Beating the bookies with their own numbers. https://arxiv.org/abs/1710.02824
54. Buchdahl. Wisdom of the Crowd: true expected profit (closing odds). https://www.football-data.co.uk/blog/wisdom_of_crowd_betting_system_closing_odds.php
55. football-data.co.uk. Wisdom of Crowd selections (Pinnacle API note). https://www.football-data.co.uk/wisdom_of_crowd_bets
56. Kull, Silva Filho, Flach (2017). Beta calibration. https://proceedings.mlr.press/v54/kull17a.html
57. Niculescu-Mizil, Caruana (2005). Predicting good probabilities with supervised learning. https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting
58. Walsh, Joshi (2024). Model selection: accuracy or calibration? https://researchportal.bath.ac.uk/en/publications/machine-learning-for-sports-betting-should-model-selection-be-bas/
59. penaltyblog documentation (goal models, including Bayesian). https://penaltyblog.readthedocs.io/en/latest/models/overview.html
60. Vovk, Petej (2014). Venn-Abers predictors. https://arxiv.org/abs/1211.0025
61. van der Laan, Alaa (2025). Generalized Venn and Venn-Abers calibration. https://arxiv.org/abs/2502.05676
62. Baker, McHale (2013). Optimal betting under parameter uncertainty. https://ideas.repec.org/a/inm/ordeca/v10y2013i3p189-199.html
63. Uhrín, Šourek, Hubáček, Železný (2021). Optimal sports betting strategies in practice. https://arxiv.org/abs/2107.08827
64. McCarrick et al. (2021). Home advantage during the COVID-19 pandemic. https://researchportal.northumbria.ac.uk/en/publications/home-advantage-during-the-covid-19-pandemic-analyses-of-european-/
65. Benz, Lopez (2023). Home advantage change during COVID, bivariate Poisson. https://arxiv.org/abs/2012.14949
66. Schank, Voigt, Orthey (2024). During and after COVID-19: Bundesliga home advantage. https://arxiv.org/abs/2411.12509
67. Fischer, Haucap (2020/21). Crowd support and home advantage (German ghost games). https://econpapers.repec.org/RePEc:zbw:dicedp:344
68. Jackson (2025). Home advantage: what's changed since Covid? Significance. https://significancemagazine.com/home-advantage-whats-changed-since-covid/
69. Opta Analyst (20 Jan 2025). Premier League home wins at COVID-era levels. https://theanalyst.com/articles/premier-league-home-wins-covid-levels
70. Maimone, Yasseri (2021). Football is becoming more predictable. https://arxiv.org/abs/1908.08991
71. Pollard, Gómez (2014). Home advantage in men's and women's leagues. https://doi.org/10.1080/17461391.2011.651490
72. Michels, Ötting, Karlis (2025). Extending the Dixon and Coles model: women's football. https://arxiv.org/abs/2307.02139
73. World Football Elo Ratings: methodology. https://www.eloratings.net/about
74. FIFA. Men's ranking procedure (SUM). https://digitalhub.fifa.com/m/f99da4f73212220/original/edbm045h0udbwkqew35a-pdf.pdf
75. Inside World Football (2026). Sportradar 2025 integrity report. https://www.insideworldfootball.com/2026/02/12/sportradar-reports-1-drop-suspicious-match-identification-2025/
