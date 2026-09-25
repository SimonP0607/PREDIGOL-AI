# A3: Team strength, match prediction, uncertainty and causal inference (review, 25 Sep 2026)

**Scope.** Research from 2024–2026, plus the foundational papers it builds on, read against our stack. That stack is API-Football plus Football-Data.co.uk (FD); Elo V2 + ordered logit, Maher Poisson and Dixon–Coles (DC); a walk-forward (WF) backtest against de-vigged Pinnacle closing odds. All three models trail the market by ΔLL ≈ +0.027 to +0.030, and the confidence intervals exclude zero.

**How claims were checked.** Every cited item was opened and each claim checked against its abstract or text. Where only metadata could be read, the claim goes no further than the title, or is marked (unverified). Some lookups failed, so Collet (2013), Lago (2009) and Mackenzie & Cushion (2013) are left out.

**Abbreviations.** ΔLL = log-loss difference against the baseline; MB = moving-block bootstrap over matchdays.

## Bottom line for our gap

1. **No verified public-data model beats the market on a proper score.** Profit claims are typically against historical, average, Bet365 or best-available prices, over a few seasons. Two reference points:
   - Goal-margin Elo trailed max and average odds by 0.0085 and 0.0078 bits (≈0.006 and 0.005 nats; Hvattum & Arntzen 2010).
   - An adaptive Glicko-2 trailed market probabilities by 1.35% in log loss (Nguyen & Tran 2026).

   Our ≈0.028 nats is larger. Part of that is the sharper benchmark, and part is team news priced in after our forecast time.
2. **Most likely to narrow the gap:**
   1. Measure against, and anchor to, the **Pinnacle pre-closing** 1X2 and Asian handicap price.
   2. Add **lineup/injury-aware player ratings**.
   3. Add **shot/SoT ratings and rolling xG difference (xGD)**.
   4. Add **pi-ratings + gradient boosting**, stacked with calibrated pooling.
   5. Model **home advantage (HA) per league and over time**, with priors for promoted teams.
3. **Unlikely to help:** deep networks on goals-only data; swapping Elo for Glicko-2; richer score dependence for 1X2; manager-bounce features; choosing models by ROI.

## 1. Team strength

### State of the art (2024–2026)

- **Elo.** Our Elo V2 design follows Hvattum & Arntzen (2010): Elo covariates in an ordered logit.
  - It beat six non-market benchmarks but was significantly worse than market odds.
  - Goal-margin Elo beat result-only Elo. Informational loss was 1.4995 vs 1.4910 for max odds, in bits (the uniform forecast scores log₂3 = 1.5850).
  - For national teams, an Elo variant beat the other ranking systems compared, FIFA's included (Lasek et al. 2013). World Football Elo (eloratings.net) is the public reference; its method page could not be read (unverified).
- **Glicko / Glicko-2.**
  - Glicko adds a rating-deviation term (Glickman 1999). Glickman (2001) lets the state variance change over time.
  - Football evidence is thin. An adaptive Glicko-2 improved Brier by 4.04% over standard Glicko-2 (EPL 2008–16, rolling-origin evaluation), yet still trailed the market (Nguyen & Tran 2026, arXiv).
  - A league-aware Glicko reportedly beat DC (conference abstract; Shelopugin & Sirotkin 2026).
- **pi-ratings.** They "substantially outperform" Elo and were profitable over five EPL seasons (Constantinou & Fenton 2013). They are the default feature in both prediction challenges (Hubáček et al. 2019a; Yeung et al. 2024).
- **Goal models.**
  - Poisson attack/defence strengths, where a bivariate Poisson with correlation ≈0.2 fits better (Maher 1982). DC showed positive betting returns (Dixon & Coles 1997).
  - Bivariate Poisson and diagonal inflation correct under-predicted draws (Karlis & Ntzoufras 2003). Skellam models the goal difference (Karlis & Ntzoufras 2009).
  - With time decay, bivariate and independent Poisson were the best of ten likelihood models on RPS (Ley et al. 2019).
  - Bradley–Terry and hierarchical Poisson are comparable (Tsokos et al. 2019). Goal-based vs result-based comparisons are inconclusive (Egidi & Torelli 2021).
  - DC's dependence assumptions are "not always based on solid arguments" (Petretta et al. 2025).
- **Dynamic Bayesian / state-space models.**
  - A dynamic GLM fitted by MCMC (Rue & Salvesen 2000).
  - Dynamic beats static, with the drift variance estimated (Owen 2011).
  - A state-space bivariate Poisson with a significant positive return (Koopman & Lit 2015).
  - Score-driven panels across six leagues: pairwise counts gave the most precise forecasts, goal difference was best for betting (Koopman & Lit 2019).
  - Priors that weight each period differently improved RPS (Macrì-Demartino et al. 2025, arXiv; no market comparison).
- **Ratings from markets, crowds and players.**
  - Odds-updated Elo beats goal-based Elo, which beats result-based Elo, but the odds themselves stay significantly better (Wunderlich & Memmert 2018).
  - A bookmaker consensus beat Elo and FIFA at EURO 2008 (Leitner et al. 2010). Transfermarkt valuations beat FIFA and Elo for internationals (Peeters 2018). Lopez et al. (2017) build state-space strengths from betting lines (US sports).
  - Team Elo plus player plus-minus beats either alone (Arntzen & Hvattum 2021).
  - A WhoScored-rating model scored Brier 0.5955 against Bet365's 0.5877, yet produced positive Kelly returns (Holmes & McHale 2024).
- **Shots and xG.**
  - Generalised Attacking Performance (GAP) ratings are built from shots, SoT and corners (Wheatcroft 2020).
  - Predicted statistics add information beyond the maximum odds, with "a downturn in profit in recent seasons" (Wheatcroft 2021a).
  - xG predicts the next six matches better than goals or shots (Mead et al. 2023; needs shot coordinates).
  - A 3-match rolling-xG Skellam model with isotonic calibration (WF, Bundesliga 2014/15–2024/25) lost to the market on per-outcome log loss and Brier. Its ROI against average odds is called "an upper bound" (Wilkens 2026).
- **The Sciety-listed review, verified with caveats.** Lee, Mohamad & Asirvatham (2026) covers 74 studies on Preprints.org. It is not peer-reviewed and has zero evaluations on Sciety. It states: "Rolling expected goal difference was the most transferable team-level signal".
  - Its main support, Brechot & Flepp (2020), presents xG as a tool for performance evaluation, not a forecasting benchmark.
  - **Treat the claim as a hypothesis to test.**

**Which ratings forecast best, and against what:** against FIFA and plain Elo, market, crowd and goal-margin ratings win. Among models, pi-ratings beat Elo, Poisson and Bradley–Terry are about even, and dynamic beats static. Against the market, none win.

### What we can build with our data

- Goal-margin Elo with league-specific, time-varying HA.
- pi-ratings, and GAP ratings from FD's HS/AS/HST/AST/HC/AC columns.
- Rolling xGD where API-Football supplies `expected_goals` (coverage unknown).
- Market-implied strengths from FD's Pinnacle pre-closing odds, collected "Friday afternoons … Tuesday afternoons", and the Asian handicap columns (PAHH/PAHA).
- Player ratings from lineups (about 20–60 minutes before kick-off) and injuries (from April 2021 only; internal A5 inventory).

### Techniques table

| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Goal-margin Elo + time-varying HA per league | Current strength | Results, venue | AVAILABLE_NOW | Elo V2 | WF ΔLL, MB | P0 (cheap; fixes HA drift) |
| pi-ratings | Strength from goal difference | Results | AVAILABLE_NOW | Elo V2 | WF ΔLL, MB | P1 (best goals-only feature) |
| Glicko / Glicko-2 | Rating uncertainty | Results | AVAILABLE_NOW | Elo V2 | ΔLL; calibration by rating deviation | P2 (mostly for display) |
| Bivariate / diagonal-inflated / Skellam | Draws, score dependence | Results | AVAILABLE_NOW | DC | ΔLL; draw reliability | P3 (small gain) |
| Dynamic Bayesian state-space | Evolving attack/defence + posteriors | Results (+ shots) | AVAILABLE_NOW | Time-decay Maher | Same folds; posterior predictive checks | P2 (adaptivity; honest intervals) |
| GAP / SoT ratings | Process strength | FD shots, SoT, corners | AVAILABLE_NOW | Goals-only Poisson | ΔLL; value given pre-closing odds | P1 (less noisy than goals) |
| Rolling xGD | Strength from chance quality | API-Football xG (partial) | APPROXIMABLE | GAP | Covered leagues; provider drift | P1 (tests Lee et al.) |
| Market-derived ratings | Strength the market implies | Pinnacle 1X2/AH pre-closing | AVAILABLE_NOW | Elo V2; the market | Δ vs pre-closing and closing | P1 (largest gap reduction) |
| Player ratings from lineups | Today's XI given absences | Lineups, minutes, injuries | APPROXIMABLE | Team-only rating | Timestamped WF | P1 (the team news the closing price has) |
| Priors for promoted teams | Starting ratings | Lower-division results | APPROXIMABLE | Default prior | Early-season ΔLL | P1 (better early-season forecasts) |
| Own xG; pressing / structure metrics | Chance quality; tactical strength | Shot coordinates; tracking | REQUIRES_EVENT_PROVIDER; REQUIRES_TRACKING_PROVIDER | Provider xG; shot ratings | Held-out seasons | P3 (research) |

### Sources

- Arntzen, H., Hvattum, L.M. (2021). Predicting match outcomes in association football using team ratings and player ratings. Statistical Modelling 21(5), 449–470. https://doi.org/10.1177/1471082X20929881
- Brechot, M., Flepp, R. (2020). Dealing with randomness in match outcomes: how to rethink performance evaluation in European club football using expected goals. Journal of Sports Economics 21(4), 335–362. https://doi.org/10.1177/1527002519897962
- Constantinou, A.C., Fenton, N.E. (2013). Determining the level of ability of football teams by dynamic ratings based on the relative discrepancies in scores between adversaries. JQAS 9(1), 37–50. https://doi.org/10.1515/jqas-2012-0036
- Dixon, M.J., Coles, S.G. (1997). Modelling association football scores and inefficiencies in the football betting market. JRSS C 46(2), 265–280. https://doi.org/10.1111/1467-9876.00065
- Egidi, L., Torelli, N. (2021). Comparing goal-based and result-based approaches in modelling football outcomes. Social Indicators Research 156, 801–813. https://doi.org/10.1007/s11205-020-02293-z
- Football-Data.co.uk (n.d.). Notes (column definitions and odds collection times). https://www.football-data.co.uk/notes.txt
- Glickman, M.E. (1999). Parameter estimation in large dynamic paired comparison experiments. JRSS C 48(3), 377–394. https://doi.org/10.1111/1467-9876.00159
- Glickman, M.E. (2001). Dynamic paired comparison models with stochastic variances. Journal of Applied Statistics 28(6), 673–689. https://www.glicko.net/research/dpcmsv.pdf
- Holmes, B., McHale, I.G. (2024). Forecasting football match results using a player rating based model. IJF 40(1), 302–312. https://doi.org/10.1016/j.ijforecast.2023.03.002
- Hvattum, L.M., Arntzen, H. (2010). Using ELO ratings for match result prediction in association football. IJF 26(3), 460–470. https://econpapers.repec.org/RePEc:eee:intfor:v:26:y::i:3:p:460-470
- Karlis, D., Ntzoufras, I. (2003). Analysis of sports data by using bivariate Poisson models. JRSS D 52(3), 381–393. https://doi.org/10.1111/1467-9884.00366
- Karlis, D., Ntzoufras, I. (2009). Bayesian modelling of football outcomes: using the Skellam's distribution for the goal difference. IMA J. Management Mathematics 20(2), 133–145. https://doi.org/10.1093/imaman/dpn026
- Koopman, S.J., Lit, R. (2015). A dynamic bivariate Poisson model for analysing and forecasting match results in the English Premier League. JRSS A 178(1), 167–186. https://doi.org/10.1111/rssa.12042
- Koopman, S.J., Lit, R. (2019). Forecasting football match results in national league competitions using score-driven time series models. IJF 35(2), 797–809. https://doi.org/10.1016/j.ijforecast.2018.10.011
- Lasek, J., Szlávik, Z., Bhulai, S. (2013). The predictive power of ranking systems in association football. Int. J. Applied Pattern Recognition 1(1), 27–46. https://doi.org/10.1504/IJAPR.2013.052339
- Lee, C.H., Mohamad, A.H., Asirvatham, D. (2026). Data-driven football performance measurement: a measure-first systematic review of action-centric, individual, team, and financial analytics (2018–2024). Preprints.org (not peer-reviewed; on Sciety). https://doi.org/10.20944/preprints202607.0281.v1
- Leitner, C., Zeileis, A., Hornik, K. (2010). Forecasting sports tournaments by ratings of (prob)abilities: a comparison for the EURO 2008. IJF 26(3), 471–481. https://ideas.repec.org/a/eee/intfor/v26yi3p471-481.html
- Ley, C., Van de Wiele, T., Van Eetvelde, H. (2019). Ranking soccer teams on the basis of their current strength: a comparison of maximum likelihood approaches. Statistical Modelling 19(1), 55–73. https://doi.org/10.1177/1471082X18817650
- Lopez, M.J., Matthews, G.J., Baumer, B.S. (2017). How often does the best team win? A unified approach to understanding randomness in North American sport. arXiv:1701.05976. https://arxiv.org/abs/1701.05976
- Macrì-Demartino, R., Egidi, L., Torelli, N. (2025). Bayesian weighted discrete-time dynamic models for association football prediction. arXiv:2508.05891. https://arxiv.org/abs/2508.05891
- Maher, M.J. (1982). Modelling association football scores. Statistica Neerlandica 36(3), 109–118. https://doi.org/10.1111/j.1467-9574.1982.tb00782.x
- Mead, J., O'Hare, A., McMenemy, P. (2023). Expected goals in football: improving model performance and demonstrating value. PLOS ONE 18, e0282295. https://doi.org/10.1371/journal.pone.0282295
- Nguyen, B.V., Tran, N.A. (2026). An adaptive Glicko-2 rating framework for probabilistic football forecasting and season simulation. arXiv:2607.01722. https://arxiv.org/abs/2607.01722
- Owen, A. (2011). Dynamic Bayesian forecasting models of football match outcomes with estimation of the evolution variance parameter. IMA J. Management Mathematics 22(2), 99–113. https://doi.org/10.1093/imaman/dpq018
- Peeters, T. (2018). Testing the Wisdom of Crowds in the field: Transfermarkt valuations and international soccer results. IJF 34(1), 17–29. https://doi.org/10.1016/j.ijforecast.2017.08.002
- Petretta, M., Schiavon, L., Diquigiovanni, J. (2025). Modelling dependence in football match outcomes: traditional assumptions and an alternative proposal. Statistical Modelling 25(3), 255–269. https://doi.org/10.1177/1471082X241238802
- Rue, H., Salvesen, Ø. (2000). Prediction and retrospective analysis of soccer matches in a league. JRSS D 49(3), 399–418. https://doi.org/10.1111/1467-9884.00243
- Shelopugin, A., Sirotkin, A. (2026). Constructing football club ratings with league strength awareness using a modified Glicko model. ISACE 2026, Springer. https://doi.org/10.1007/978-3-032-27272-0_4
- Tsokos, A. et al. (2019). Modeling outcomes of soccer matches. Machine Learning 108, 77–95. https://doi.org/10.1007/s10994-018-5741-1
- Wheatcroft, E. (2020). A profitable model for predicting the over/under market in football. IJF 36(3), 916–932. https://doi.org/10.1016/j.ijforecast.2019.11.001
- Wheatcroft, E. (2021a). Forecasting football matches by predicting match statistics. Journal of Sports Analytics 7(2), 77–97. https://doi.org/10.3233/JSA-200462
- Wilkens, S. (2026). Can simple models predict football — and beat the odds? Lessons from the German Bundesliga. Journal of Sports Analytics 12. https://doi.org/10.1177/22150218261416681
- Wunderlich, F., Memmert, D. (2018). The Betting Odds Rating System: using soccer forecasts to forecast soccer. PLOS ONE 13(6), e0198668. https://doi.org/10.1371/journal.pone.0198668


## 2. Match prediction

### State of the art (2024–2026)

- **Challenges.**
  - 2017 (206 test matches, RPS). Hubáček et al. won with hand-built features and gradient-boosted trees, having also explored pi-ratings and a PageRank rating. Constantinou's *Dolores* (dynamic ratings + hybrid Bayesian networks) was second, with "0.94% higher" error (Berrar et al. 2019a). The organisers' own k-NN on learned ratings was "the top-ranking model" (Berrar et al. 2019b).
  - 2023 (736 matches). "Relatively simple learning algorithms perform remarkably well" (Berrar et al. 2024).
  - CatBoost + pi-ratings scored RPS 0.1991–0.2145 on three held-out seasons, with a deep model about the same. The entry ranked 16th (0.2195), and the bookmaker consensus beat it by 6.42% (Yeung et al. 2024).
  - Gradient-boosted trees on pi-ratings are best on goals-only data, and bookmakers beat the top 2017 entries (Bunker et al. 2024).
- **Other comparisons.** Gradient boosting scored RPS 0.2156 against bookmakers' 0.2012 (Baboota & Kaur 2019). A hybrid random forest beat the odds, but over only 64 World Cup matches (Groll et al. 2019).
- **The market.**
  - Bookmaker accuracy varies and has improved over time (Štrumbelj & Robnik-Šikonja 2010).
  - Shin's method beats normalisation, less so in large markets (Štrumbelj 2014).
  - 1X2 odds show a strong favourite–longshot bias, while Asian handicap odds give efficient forecasts (Hegarty & Whelan 2025).
  - Apparent inefficiencies appear in single seasons but are not "persistent or systematic across leagues" (Winkelmann et al. 2024).
  - Returns can be positive without superior accuracy (Wunderlich & Memmert 2020).
  - Exploiting price dispersion across bookmakers worked until accounts were restricted (Kaunitz et al. 2017).
  - Decorrelating a model from the bookmaker aids profit (NBA; Hubáček et al. 2019b).
- **Scoring rules.**
  - The log score is the only proper local scoring rule (Gneiting & Raftery 2007).
  - Constantinou & Fenton (2012) argued for RPS because the outcomes are ordered.
  - In simulations the ignorance (log) score beat RPS and Brier (Wheatcroft 2021b), and Hubáček et al. (2019a) question RPS's monotonicity assumption.
- **Calibration.**
  - Modern classifiers are often miscalibrated, and temperature scaling is a simple fix (Guo et al. 2017).
  - Improved estimators of expected calibration error (ECE) beat plug-in ones (Kumar et al. 2019).
  - CORP reliability diagrams come with uncertainty bands (Dimitriadis et al. 2021).
  - Selecting by calibration beat selecting by accuracy in NBA betting, though after a 2025 corrigendum Kelly staking lost money under both (Walsh & Joshi 2024).
- **Validation and ensembles.**
  - Under non-stationarity, out-of-sample evaluation that keeps time order is most accurate (Cerqueira et al. 2020).
  - Temporal leakage is part of the leakage taxonomy (Kapoor & Narayanan 2023).
  - Linear pools come out miscalibrated, which a beta-transformed pool fixes (Ranjan & Gneiting 2010).
  - Egidi et al. (2018) blend historical and odds-implied scoring rates.

### What we can build with our data

- **Metrics.** Keep log loss primary, add RPS for comparability with the literature, and use CORP with debiased ECE.
- **Benchmarks.** Report Δ against Pinnacle **pre-closing** (a fair benchmark for a forecast issued on Friday) and against closing (an upper bound), plus Asian-handicap-derived probabilities. The difference between the two gaps estimates how much of our gap is information arriving late.
- **Stacking.** Stack Elo-ologit, DC, pi-rating GBT, GAP and pre-closing log-odds on the validation season, then temperature-scale. If the stacker weights the market heavily, that is the honest answer.

### Techniques table

| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Log loss primary; RPS and Brier secondary | Which forecast is better? | Predictions, outcomes | AVAILABLE_NOW | Market | WF, same matches | P0 (credible evaluation) |
| CORP + debiased ECE; temperature / isotonic recalibration | Are the probabilities honest? | Validation and test seasons | AVAILABLE_NOW | Raw model; market reliability | Fit on validation, score on test; bands | P0 (trustworthy probabilities) |
| Pinnacle pre-closing + closing (Shin/power), AH-derived | What did the market know at forecast time? | FD odds | AVAILABLE_NOW | Not applicable | Match forecast timestamps to odds snapshots | P0 (fair benchmark) |
| Market-anchored prior / blend | Improve on the market by adjusting it | Pre-closing odds + model | AVAILABLE_NOW | Pinnacle pre-closing | Δ vs pre-closing, then closing | P1 (biggest gain) |
| CatBoost on pi-ratings + shot/xG features | Non-linear feature use | Results, stats, xG | AVAILABLE_NOW / APPROXIMABLE | Elo-ologit, DC | Tune on validation season only | P2 (modest gain likely) |
| Stacking with calibrated pooling | Combine correlated models | Model outputs | AVAILABLE_NOW | Best single model | Same folds; model confidence set | P2 (robustness) |
| Deep sequence models | Richer temporal patterns | Results / events | AVAILABLE_NOW / REQUIRES_EVENT_PROVIDER | CatBoost + pi-ratings | Same | P3 (no evidence of gain) |
| Closing-line value / ROI | Could a user profit? | Odds | AVAILABLE_NOW | Zero after margin | Pre-registered, multi-season | P3 (secondary metric) |

### Sources

- Baboota, R., Kaur, H. (2019). Predictive analysis and modelling football results using machine learning approach for English Premier League. IJF 35(2), 741–755. https://doi.org/10.1016/j.ijforecast.2018.01.003
- Berrar, D., Lopes, P., Davis, J., Dubitzky, W. (2019a). Guest editorial: special issue on machine learning for soccer. Machine Learning 108, 1–7. https://doi.org/10.1007/s10994-018-5763-8
- Berrar, D., Lopes, P., Dubitzky, W. (2019b). Incorporating domain knowledge in machine learning for soccer outcome prediction. Machine Learning 108, 97–126. https://doi.org/10.1007/s10994-018-5747-8
- Berrar, D., Lopes, P., Dubitzky, W. (2024). A data- and knowledge-driven framework for developing machine learning models to predict soccer match outcomes. Machine Learning 113, 8165–8204. https://doi.org/10.1007/s10994-024-06625-9
- Bunker, R., Yeung, C., Fujii, K. (2024). Machine learning for soccer match result prediction (book chapter). arXiv:2403.07669. https://arxiv.org/abs/2403.07669
- Cerqueira, V., Torgo, L., Mozetič, I. (2020). Evaluating time series forecasting models: an empirical study on performance estimation methods. Machine Learning 109, 1997–2028. https://arxiv.org/abs/1905.11744
- Constantinou, A.C. (2019). Dolores: a model that predicts football match outcomes from all over the world. Machine Learning 108, 49–75. https://doi.org/10.1007/s10994-018-5703-7
- Constantinou, A.C., Fenton, N.E. (2012). Solving the problem of inadequate scoring rules for assessing probabilistic football forecast models. JQAS 8(1). https://doi.org/10.1515/1559-0410.1418
- Dimitriadis, T., Gneiting, T., Jordan, A.I. (2021). Stable reliability diagrams for probabilistic classifiers. PNAS 118, e2016191118. https://doi.org/10.1073/pnas.2016191118
- Egidi, L., Pauli, F., Torelli, N. (2018). Combining historical data and bookmakers' odds in modelling football scores. Statistical Modelling 18(5–6), 436–459. https://doi.org/10.1177/1471082X18798414
- Gneiting, T., Raftery, A.E. (2007). Strictly proper scoring rules, prediction, and estimation. JASA 102(477), 359–378. https://doi.org/10.1198/016214506000001437
- Groll, A., Ley, C., Schauberger, G., Van Eetvelde, H. (2019). A hybrid random forest to predict soccer matches in international tournaments. JQAS 15(4), 271–287. https://doi.org/10.1515/jqas-2018-0060
- Guo, C., Pleiss, G., Sun, Y., Weinberger, K.Q. (2017). On calibration of modern neural networks. ICML, PMLR 70, 1321–1330. https://proceedings.mlr.press/v70/guo17a.html
- Hegarty, T., Whelan, K. (2025). Forecasting soccer matches with betting odds: a tale of two markets. IJF 41(2), 803–820. https://doi.org/10.1016/j.ijforecast.2024.06.013
- Hubáček, O., Šourek, G., Železný, F. (2019a). Learning to predict soccer results from relational data with gradient boosted trees. Machine Learning 108, 29–47. https://doi.org/10.1007/s10994-018-5704-6
- Hubáček, O., Šourek, G., Železný, F. (2019b). Exploiting sports-betting market using machine learning. IJF 35(2), 783–796. https://doi.org/10.1016/j.ijforecast.2019.01.001
- Kapoor, S., Narayanan, A. (2023). Leakage and the reproducibility crisis in machine-learning-based science. Patterns 4, 100804 (preprint arXiv:2207.07048). https://arxiv.org/abs/2207.07048
- Kaunitz, L., Zhong, S., Kreiner, J. (2017). Beating the bookies with their own numbers – and how the online sports betting market is rigged. arXiv:1710.02824. https://arxiv.org/abs/1710.02824
- Kumar, A., Liang, P., Ma, T. (2019). Verified uncertainty calibration. NeurIPS 2019. https://arxiv.org/abs/1909.10155
- Ranjan, R., Gneiting, T. (2010). Combining probability forecasts. JRSS B 72(1), 71–91. https://doi.org/10.1111/j.1467-9868.2009.00726.x
- Štrumbelj, E. (2014). On determining probability forecasts from betting odds. IJF 30(4), 934–943. https://doi.org/10.1016/j.ijforecast.2014.02.008
- Štrumbelj, E., Robnik-Šikonja, M. (2010). Online bookmakers' odds as forecasts: the case of European soccer leagues. IJF 26(3), 482–488. https://ideas.repec.org/a/eee/intfor/v26yi3p482-488.html
- Walsh, C., Joshi, A. (2024). Machine learning for sports betting: should model selection be based on accuracy or calibration? Machine Learning with Applications 16, 100539 (corrigendum 2025). https://doi.org/10.1016/j.mlwa.2024.100539
- Wheatcroft, E. (2021b). Evaluating probabilistic forecasts of football matches: the case against the ranked probability score. JQAS 17(4), 273–287. https://doi.org/10.1515/jqas-2019-0089
- Winkelmann, D., Ötting, M., Deutscher, C., Makarewicz, T. (2024). Are betting markets inefficient? Evidence from simulations and real data. Journal of Sports Economics 25(1), 54–97. https://doi.org/10.1177/15270025231204997
- Wunderlich, F., Memmert, D. (2020). Are betting returns a useful measure of accuracy in (sports) forecasting? IJF 36(2), 713–722. https://doi.org/10.1016/j.ijforecast.2019.08.009
- Yeung, C., Bunker, R., Umemoto, R., Fujii, K. (2024). Evaluating soccer match prediction models: a deep learning approach and feature optimization for gradient-boosted trees. Machine Learning 113(10), 7541–7564. https://doi.org/10.1007/s10994-024-06608-w


## 3. Uncertainty

### State of the art (2024–2026)

- **Comparing forecasts.**
  - The Diebold–Mariano (DM) test works for any loss and allows for serially correlated errors (Diebold & Mariano 1995). It is for comparing forecasts, not models (Diebold 2015).
  - Harvey, Leybourne & Newbold (HLN; 1997) give a modified version (R `forecast::dm.test`).
  - Giacomini & White (2006) test conditional predictive ability.
  - The model confidence set (MCS) grows when the data are uninformative, which makes it a formal "insufficient evidence" output (Hansen et al. 2011).
- **Dependence.** Block and stationary bootstraps handle dependence (Künsch 1989; Politis & Romano 1994). The plain paired bootstrap assumes independent matches.
- **Small samples.** A single-season "edge" can appear under full efficiency (Winkelmann et al. 2024). Groll et al. (2019)'s claim of beating the odds rests on 64 matches.
- **Sources of uncertainty.**
  - Dynamic Bayesian models give posterior predictive distributions (Rue & Salvesen 2000; Owen 2011), and Glicko gives a rating deviation.
  - Keep epistemic (reducible) and aleatoric (irreducible) uncertainty apart (Hüllermeier & Waegeman 2021).
  - Deep ensembles give well-calibrated uncertainty that rises on unfamiliar inputs (Lakshminarayanan et al. 2017). We use model disagreement as a practical epistemic signal.
- **Abstaining.** Selective classification trades coverage for guaranteed risk (Geifman & El-Yaniv 2017). Conformal sets (e.g. {home, draw}) give distribution-free coverage (Angelopoulos & Bates 2021).

### What we can build with our data

- **Replace the iid paired bootstrap with MB**, and add DM-HLN with a variance estimate robust to autocorrelation (HAC) and an MCS per league-season.
- **Minimum detectable difference:** n ≈ (1.96·sd_d/h)².
  - Illustration with an assumed sd_d = 0.10 nats: h = 0.01 needs ~384 matches and h = 0.005 needs ~1,537.
  - One 380-match season therefore resolves only about ±0.010. Plug in our measured sd_d.
  - Our +0.028 gap is real. A claimed edge of 0.005 would need several league-seasons.
- **Proposed "insufficient evidence" rule (our proposal).** Flag a match when any of these hold:
  - a team has played fewer than N matches since promotion;
  - the 80% interval for P(home win) is wider than about 15 percentage points;
  - the models disagree by more than about 10 percentage points;
  - lineups, xG or odds are missing;
  - the model departs from pre-closing odds without a news reason.

  When flagged, show a range next to the market or base rate and suppress "value" labels. Tune the thresholds with risk–coverage curves.

### Techniques table

| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| MB / stationary bootstrap + DM-HLN (HAC) on ΔLL | Is the gap real, allowing for dependence? | Per-match losses | AVAILABLE_NOW | iid paired bootstrap | Simulated coverage | P0 (honest confidence intervals) |
| Minimum detectable difference | Can our sample detect h? | sd of ΔLL | AVAILABLE_NOW | Not applicable | Not applicable | P0 (stops over-claiming) |
| Model confidence set | Which models are tied with the best? | Loss matrix | AVAILABLE_NOW | Pairwise tests | Per league-season | P1 (honest model ranking) |
| Giacomini–White conditional tests | Where or when does a model win? | Losses + conditioning variables | AVAILABLE_NOW | Unconditional DM | Out-of-sample | P2 (targeted model use) |
| Rating-deviation / posterior-SD gating | Is this team's rating reliable yet? | Results | AVAILABLE_NOW | No gating | Risk–coverage curves | P0 (avoids overconfident early-season calls) |
| Disagreement and data-completeness flags | Is this forecast fragile? | Model outputs, feed flags | AVAILABLE_NOW | No flags | Log loss on flagged vs unflagged | P0 (user-facing warning) |
| Posterior / parametric-bootstrap intervals | How wide is P(home win)? | Model | AVAILABLE_NOW | Point forecast | Interval coverage (PIT) | P1 (ranges instead of false precision) |
| Selective prediction / conformal sets | Abstain with guarantees | Calibration split | AVAILABLE_NOW | Always forecast | Empirical coverage | P2 (formal abstention) |

### Sources

- Angelopoulos, A.N., Bates, S. (2021). A gentle introduction to conformal prediction and distribution-free uncertainty quantification. arXiv:2107.07511. https://arxiv.org/abs/2107.07511
- Diebold, F.X. (2015). Comparing predictive accuracy, twenty years later: a personal perspective on the use and abuse of Diebold–Mariano tests. JBES 33(1). https://doi.org/10.1080/07350015.2014.983236
- Diebold, F.X., Mariano, R.S. (1995). Comparing predictive accuracy. JBES 13(3), 253–263. https://ideas.repec.org/a/bes/jnlbes/v13y1995i3p253-63.html
- Geifman, Y., El-Yaniv, R. (2017). Selective classification for deep neural networks. NeurIPS 30. https://papers.nips.cc/paper/7073-selective-classification-for-deep-neural-networks
- Giacomini, R., White, H. (2006). Tests of conditional predictive ability. Econometrica 74(6), 1545–1578. https://doi.org/10.1111/j.1468-0262.2006.00718.x
- Hansen, P.R., Lunde, A., Nason, J.M. (2011). The model confidence set. Econometrica 79(2), 453–497. https://doi.org/10.3982/ECTA5771
- Harvey, D., Leybourne, S., Newbold, P. (1997). Testing the equality of prediction mean squared errors. IJF 13(2), 281–291. https://doi.org/10.1016/S0169-2070(96)00719-4
- Hüllermeier, E., Waegeman, W. (2021). Aleatoric and epistemic uncertainty in machine learning: an introduction to concepts and methods. Machine Learning 110, 457–506. https://doi.org/10.1007/s10994-021-05946-3
- Künsch, H.R. (1989). The jackknife and the bootstrap for general stationary observations. Annals of Statistics 17(3), 1217–1241. https://doi.org/10.1214/aos/1176347265
- Lakshminarayanan, B., Pritzel, A., Blundell, C. (2017). Simple and scalable predictive uncertainty estimation using deep ensembles. NeurIPS 2017. https://arxiv.org/abs/1612.01474
- Politis, D.N., Romano, J.P. (1994). The stationary bootstrap. JASA 89(428), 1303–1313. https://doi.org/10.1080/01621459.1994.10476870
- Also cited here (full entries in §1–2): Winkelmann et al. (2024), Groll et al. (2019), Rue & Salvesen (2000), Owen (2011), Glickman (1999).


## 4. Causal inference in football

### State of the art (2024–2026)

- **Predicting vs explaining.** Explanatory and predictive modelling differ at every step (Shmueli 2010). Counterfactual prediction needs a research design and expert knowledge (Hernán et al. 2019). A feature's importance in our models is not an effect.
- **Manager changes.** A mid-season sacking "has basically no effect". The apparent recovery is regression to the mean, and matched controls improve just as much (Heuer et al. 2011). Dutch data with bookmaker odds show a comparable control group improving similarly (van Ours & van Tuijl 2016).
- **Red cards.**
  - Ridder et al. (1994) estimated the effect of a red card.
  - A red card raises the scoring rate of the team *not* penalised, and home teams attack less when leading (Titman et al. 2015).
  - There is no "ten do it better" effect in World Cups (Caliendo & Radic 2006), though a late dismissal can help an away team (Mechtel et al. 2011).
- **Home advantage without crowds** (natural experiments, difference-in-differences (DiD), mediation).
  - Absent crowds meant fewer yellow cards for away teams (Bryson et al. 2021).
  - HA fell in the Bundesliga's top division only (Fischer & Haucap 2021).
  - A DiD on 6,120 matches: home performance fell and then recovered, and odds mispriced it in the short run (Fischer & Haucap 2022; Winkelmann et al. 2021).
  - Referee bias vanished, but points and goals showed only a "non-significant decrease" (Wunderlich et al. 2021).
  - Across 17 leagues, HA fell in 11 and rose in 6 (Benz & Lopez 2023).
  - Mediation: roughly 80% of the drop ran through team performance and 20% through referees (Bilalić et al. 2021).
  - Historical empty stadiums reduced away cautions, but "cannot statistically reject no effect" on results (Reade et al. 2022).
  - Pre-COVID designs: empty Italian stadiums (Pettersson-Lidbom & Priks 2010) and derbies between teams sharing a stadium (Ponzo & Scoppa 2018).
- **Luck as a natural experiment.** Comparing shots that hit the post with goals shows that evaluators over-reward luck (Gauriot & Page 2019).
- **Tactics and pressing.**
  - The evidence is mostly correlational: 68 studies analysed mainly by regression or discriminant analysis (Lepschy et al. 2018), and 58% of data-provider studies are descriptive (Otero-Saborido et al. 2021).
  - Pitfalls: confounding by team quality, dependence on the score (game state), reverse causality, and judging by outcomes.
  - No verified quasi-experimental estimate of pressing's effect was found.
- **Methods.** Natural experiments, DiD, matched controls, mediation, and synthetic control (Abadie 2021 sets out when it is reliable and when it fails; no verified football application). No verified football study used instrumental variables (IV).

### What we can build with our data

- **Use causal findings to shape model structure:**
  - home advantage that varies over time and by league, with a flag for ghost-game periods, and separate reporting for 2019/20–2020/21;
  - no manager-bounce feature;
  - down-weighting goals scored after an early red card.
- **A feasible internal study:** a DiD on coach changes with matched controls (API-Football `/coachs` lists career history; internal A5 inventory).
- **Label any tactical correlation as associational.**

### Techniques table

| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Time-varying HA + ghost-game indicator | Did crowds change HA, and do we price it? | Results, crowd-status flags | APPROXIMABLE | Constant HA | ΔLL for 2020/21; pre-trends | P1 (fixes a known bias) |
| "No bounce" rule + matched-control event study | Does sacking cause improvement? | Results, odds, coach dates | APPROXIMABLE | Naive before/after | Placebo dates | P1 rule (avoids a spurious feature) / P3 study |
| Red-card-adjusted updates | Remove the effect of playing a man down | Card minutes | APPROXIMABLE | Unadjusted ratings | ΔLL | P2 (cleaner ratings) |
| Mediation (referee vs performance) | Channels behind HA | Cards, shots, results | AVAILABLE_NOW | Total effect only | Sensitivity analysis | P3 (explanatory only) |
| Matching for tactical style | Effect of possession style | Event data | REQUIRES_EVENT_PROVIDER | Correlational regression | Balance checks | P3 (explanatory content) |
| Pressing effect | Does pressing cause turnovers or goals? | Tracking | REQUIRES_TRACKING_PROVIDER | Correlation | Quasi-experiment | P3 (research) |
| Synthetic control; instrumental variables | Effect for one unit; effect under confounding | Long panel; a valid instrument | APPROXIMABLE (instrument unclear) | DiD; OLS | Placebo-in-space; exclusion argument | P3 (research) |

### Sources

- Abadie, A. (2021). Using synthetic controls: feasibility, data requirements, and methodological aspects. Journal of Economic Literature 59(2), 391–425. https://doi.org/10.1257/jel.20191450
- Benz, L.S., Lopez, M.J. (2023). Estimating the change in soccer's home advantage during the Covid-19 pandemic using bivariate Poisson regression. AStA Advances in Statistical Analysis 107, 205–232. https://doi.org/10.1007/s10182-021-00413-9
- Bilalić, M., Gula, B., Vaci, N. (2021). Home advantage mediated (HAM) by referee bias and team performance during covid. Scientific Reports 11, 21558. https://doi.org/10.1038/s41598-021-00784-8
- Bryson, A., Dolton, P., Reade, J.J., Schreyer, D., Singleton, C. (2021). Causal effects of an absent crowd on performances and refereeing decisions during Covid-19. Economics Letters 198, 109664. https://doi.org/10.1016/j.econlet.2020.109664
- Caliendo, M., Radic, D. (2006). Ten do it better, do they? An empirical analysis of an old football myth. IZA DP 2158. https://ideas.repec.org/p/iza/izadps/dp2158.html
- Fischer, K., Haucap, J. (2021). Does crowd support drive the home advantage in professional football? Evidence from German ghost games during the COVID-19 pandemic. Journal of Sports Economics 22(8), 982–1008. https://doi.org/10.1177/15270025211026552
- Fischer, K., Haucap, J. (2022). Home advantage in professional soccer and betting market efficiency: the role of spectator crowds. Kyklos 75(2), 294–316. https://doi.org/10.1111/kykl.12291
- Gauriot, R., Page, L. (2019). Fooled by performance randomness: overrewarding luck. Review of Economics and Statistics 101(4), 658–666. https://doi.org/10.1162/rest_a_00783
- Hernán, M.A., Hsu, J., Healy, B. (2019). Data science is science's second chance to get causal inference right: a classification of data science tasks. CHANCE 32(1), 42–49. https://doi.org/10.1080/09332480.2019.1579578
- Heuer, A., Müller, C., Rubner, O., Hagemann, N., Strauss, B. (2011). Usefulness of dismissing and changing the coach in professional soccer. PLOS ONE 6(3), e17664. https://doi.org/10.1371/journal.pone.0017664
- Lepschy, H., Wäsche, H., Woll, A. (2018). How to be successful in football: a systematic review. Open Sports Sciences Journal 11, 3–23. https://doi.org/10.2174/1875399X01811010003
- Mechtel, M., Bäker, A., Brändle, T., Vetter, K. (2011). Red cards: not such bad news for penalized guest teams. Journal of Sports Economics 12(6), 621–646. https://doi.org/10.1177/1527002510388478
- Otero-Saborido, F.M., Aguado-Méndez, R.D., Torreblanca-Martínez, V.M., González-Jurado, J.A. (2021). Technical-tactical performance from data providers: a systematic review in regular football leagues. Sustainability 13(18), 10167. https://doi.org/10.3390/su131810167
- Pettersson-Lidbom, P., Priks, M. (2010). Behavior under social pressure: empty Italian stadiums and referee bias. Economics Letters 108(2), 212–214. https://ideas.repec.org/a/eee/ecolet/v108y2010i2p212-214.html
- Ponzo, M., Scoppa, V. (2018). Does the home advantage depend on crowd support? Evidence from same-stadium derbies. Journal of Sports Economics 19(4), 562–582. https://doi.org/10.1177/1527002516665794
- Reade, J.J., Schreyer, D., Singleton, C. (2022). Eliminating supportive crowds reduces referee bias. Economic Inquiry 60(3), 1416–1436. https://doi.org/10.1111/ecin.13063
- Ridder, G., Cramer, J.S., Hopstaken, P. (1994). Down to ten: estimating the effect of a red card in soccer. JASA 89, 1124–1127. https://doi.org/10.1080/01621459.1994.10476850
- Shmueli, G. (2010). To explain or to predict? Statistical Science 25(3), 289–310. https://doi.org/10.1214/10-STS330
- Titman, A.C., Costain, D.A., Ridall, P.G., Gregory, K. (2015). Joint modelling of goals and bookings in association football. JRSS A 178(3), 659–683. https://ideas.repec.org/a/bla/jorssa/v178y2015i3p659-683.html
- van Ours, J.C., van Tuijl, M.A. (2016). In-season head-coach dismissals and the performance of professional football teams. Economic Inquiry 54(1), 591–604. https://ideas.repec.org/a/bla/ecinqu/v54y2016i1p591-604.html
- Winkelmann, D., Deutscher, C., Ötting, M. (2021). Bookmakers' mispricing of the disappeared home advantage in the German Bundesliga after the COVID-19 break. Applied Economics 53(26), 3054–3064. https://doi.org/10.1080/00036846.2021.1873234
- Wunderlich, F., Weigelt, M., Rein, R., Memmert, D. (2021). How does spectator presence affect football? Home advantage remains in European top-class football matches played without spectators during the COVID-19 pandemic. PLOS ONE 16(3), e0248590. https://doi.org/10.1371/journal.pone.0248590
