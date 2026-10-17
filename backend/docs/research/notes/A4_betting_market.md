## Betting market intelligence

Scope: margin removal, consensus, efficiency, price discovery, EV and staking, and evaluation, for a platform that treats the market as the baseline to beat and never bets. Every source below was opened and checked in September 2026. Where no source was found, the text says so and does not fill the gap.

**Bottom line.** Pinnacle's de-vigged closing price is the right baseline. Testing it for leftover favourite–longshot bias (FLB) matters more than which de-vig method we use. We found no verified 2024–2026 study in which a public model beats a sharp closing price on a proper scoring rule. Our near-close snapshot comes from an in-play feed and must pass explicit tests before we call it a close.

### State of the art (2024–2026)

**Removing the margin.** The standard methods, with r_i = 1/odds (Clarke et al. 2017; Lindstrøm 2023):
- proportional (r_i/Σr);
- additive;
- Shin, which assumes a share z of insiders and loads the margin onto longshots (Shin 1991, 1993);
- power (r_i^k);
- odds-ratio.

Shin beat basic normalisation in 217 of 412 bookmaker–competition pairs across five sports, soccer included, and the gain shrank in larger markets (Štrumbelj 2014). Normalisation is biased enough to flip conclusions (Štrumbelj 2016). Power matched or beat Shin and never leaves [0,1]. Additive can go negative and equals Shin for two outcomes. That comparison used tennis and racing, not football (Clarke et al. 2017).

Two newer football methods beat these classics, but neither has been replicated:
- an equal-profitability odds-only method, on 90,014 matches from five bookmakers (Goto et al. 2026, preprint);
- pooling 1X2, totals, BTTS and handicap prices under a Dixon–Coles constraint, on 359,035 matches from one bookmaker (Karimov et al. 2025).

Shin's z correlates 0.99 with the overround in soccer, so it measures margin, not insider activity (Whelan 2025b). Disagreement among bettors is enough on its own to produce FLB (Whelan 2025a).

**How FLB interacts with de-vigging.** Hegarty & Whelan (2025a) normalised average closing 1X2 odds proportionally on 84,230 Football-Data matches:
- longshots returned 0.83 per unit staked, favourites 0.98;
- draws returned slightly more than predicted;
- Asian handicap (AH) prices were unbiased.

Realised loss rates exceed the margin implied by the overround (8.7% vs 7.1%), Pinnacle included (Hegarty & Whelan 2025b). The authors attribute FLB to imperfect competition (Hegarty & Whelan 2026), matching the longshot bias seen in multi-outcome markets since Cain et al. (2000) (review: Newall & Cortis 2021).

So proportional de-vig leaves FLB in, and Shin, power and odds-ratio remove part of it by construction. Bias inside the price itself needs a recalibration per outcome, since FLB is weaker for draws (Goto et al. 2026). Normalised Betfair last-traded prices before kickoff were unbiased, with a back overround of about 100.7–101%, close to our 1.006 (Whelan 2026).

**Gap:** we found no peer-reviewed head-to-head of Shin, power and odds-ratio on Pinnacle closing odds for football 1X2 or totals. At a 2.8% margin we expect the differences to be small. Totals are two-way, so Shin and additive give the same result, and we found no strong evidence of FLB in totals.

**Consensus, sharp vs soft.** Sharp books such as Pinnacle run low margins and accept informed money. Soft books take higher margins and limit winning customers (Hegarty & Whelan 2025a, 2026). "Position-takers" rarely move their odds and restrict informed bettors. About half of 545 arbitrage portfolios needed a bet with a position-taker and could not be exploited in practice (Grant et al. 2018). Bookmakers differ in accuracy and have improved over time (Štrumbelj & Šikonja 2010; Forrest et al. 2005). An exchange out-forecast bookmakers. Backing wherever a bookmaker's probability sat below the exchange's earned above-average returns (Franck et al. 2010). When exchange liquidity is thin, the exchange loses that edge (Flepp et al. 2017; Whelan 2026). Betting when the maximum price disagreed with the consensus returned 3.5% over 479,440 simulated games and 8.5% on 265 real bets, until the bookmakers limited the accounts (Kaunitz et al. 2017).

**Efficiency, the close and closing line value (CLV).** Using best prices, 8 of 11 leagues were weak-form efficient (Angelini & De Angelis 2019). Significant single-season inefficiencies appear even in efficient markets, and none persisted over 14 seasons (Winkelmann et al. 2024). Semi-strong evidence is mixed. Prices overrated home teams early in the ghost games (matches without spectators) (Meier et al. 2021), yet markets adjusted promptly to the reduced home advantage (Hegarty & Whelan 2023).

The close is the best benchmark, not an oracle. Exchange closes look unbiased (Whelan 2026). In US sports, about half of the move from opening to closing price reverses, but not by enough to profit after costs (Moskowitz 2021). We found no peer-reviewed validation of CLV itself. The case for it rests on the close being efficient and on returns being a noisy measure of accuracy (Wunderlich & Memmert 2020).

Recent model-versus-market results fit this picture:
- +11.96% on 556 Kelly bets at Bet365 prices, from a model whose Brier score was worse than Bet365's (0.5955 vs 0.5877; Holmes & McHale 2024);
- about 10% at average odds from an xG model the bookmakers out-calibrated, varying by season (Wilkens 2026);
- about 0.8% per bet on over/under 2.5 (Wheatcroft 2020);
- a +34.69% ROI corrected to −9.77% after code bugs were found (Walsh & Joshi 2024, 2025).

A 2024 review finds odds "have proven difficult to beat" (Bunker et al. 2024). None of these results beats a sharp close on a proper scoring rule.

**Line movement.** In-play, goal news is priced "swiftly and fully" (Croxson & Reade 2014). Structural news is absorbed more slowly (Meier et al. 2021). Insiders force odds down and can collapse a market once they are more than a small share (Whelan 2025a). This fits bookmakers limiting sharp accounts. **Gap:** we found no verified football study on the timing of pre-match steam moves. Studying it needs tick-level line history, which we lack.

**EV and staking.** Kelly (1956) maximises long-run growth, but bad runs can destroy most of a bankroll (MacLean et al. 2010). When probabilities are estimated, stakes should be shrunk (Baker & McHale 2013). Formal Kelly was "infeasible in almost all practical scenarios with uncertain probability estimates" and often led to ruin, while fractional Kelly worked (Uhrín et al. 2021). Staking all three 1X2 outcomes jointly is more aggressive than per-outcome Kelly, and loses more when the odds are accurate (Whelan 2025c). At equal EV, strategies heavy in longshots carry a higher risk of ruin (Whelan 2025d).

**Honest evaluation.**
- Use strictly proper scoring rules (Gneiting & Raftery 2007). For football, prefer log loss to the ranked probability score (RPS) (Wheatcroft 2021; cf. Constantinou & Fenton 2012).
- Test on a rolling origin (Tashman 2000), never with shuffled cross-validation (Bunker et al. 2024).
- Compare forecasts with paired tests (Diebold & Mariano 1995) and a bootstrap that respects dependence (Politis & Romano 1994).
- Control for data snooping (White 2000; Hansen 2005; Bailey et al. 2016).

Our own arithmetic: a flat stake at odds O and win probability p has a standard deviation of O√(p(1−p)), about 1.0 at evens and 2.2 at odds of 6.0. So 1,000 bets give a 95% ROI interval of about ±6–9 points, and narrowing it to ±2 points needs about 9,600–21,600 bets. Our −8% ROI therefore says little. The +0.027 to +0.030 log-loss gap is the informative number.

### What we can build with our data
- **Baseline audit (P0).** Football-Data has Pinnacle closing 1X2 from 2012/13. From 2019/20 it also has pre-closing (Friday/Tuesday afternoon) and closing sets for Pinnacle, Bet365, the average, the maximum, Betfair and totals. Run every de-vig method plus a per-outcome recalibration, walk-forward, by league and outcome. Football-Data's notes do not say whether the Betfair columns are best back prices or last-traded prices.
- **Is the close better? (P0).** Compare pre-closing with closing prices (Pinnacle, average), and the Pinnacle close with the Betfair close. CLV only makes sense if the close wins.
- **Historical CLV (P0).** Treat the pre-closing price as the decision price and grade it against the Shin-de-vigged Pinnacle close. Check whether CLV tracks realised ROI.
- **Market-anchored modelling (P1).** Stack model and market out-of-sample. The weight the model earns, not ROI, measures what it adds. Test residual signals against the close as an offset (cf. Egidi et al. 2018): shots and corners now, xG later, since xG needs an event provider.
- **Uncertainty-adjusted EV gate (P0).** Apply it before any "value" label is shown. Kelly stays hypothetical and shrunk (P2).
- **Out of reach.** Steam-move timing, exchange depth and bookmaker limits all need a richer odds feed (REQUIRES_ODDS_PROVIDER). Nothing here needs tracking data.

### Techniques table
Abbreviations: FD = Football-Data. PS/PSC = Pinnacle pre-closing/closing. Avg/AvgC = market-average pre-closing/closing. B365C = Bet365 closing. BFEC = Betfair Exchange closing. DM = Diebold–Mariano test. ECE = expected calibration error. The text after each priority states the product value.

| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Proportional normalisation | Fair probabilities if the margin is proportional | FD PSC, AvgC, B365C, BFEC; live snapshots | AVAILABLE_NOW | — (reference) | Walk-forward log loss, ECE, calibration by bin and by home/draw/away | P0 — transparent reference; leaves FLB in |
| Shin | Fair probabilities with the margin loaded on longshots | As above | AVAILABLE_NOW | Proportional | Paired Δ log loss with season-block bootstrap CI; report z only as a margin proxy | P0 — current primary baseline, re-justified |
| Power / odds-ratio / additive | Does another way of allocating the margin calibrate better? | As above | AVAILABLE_NOW | Shin on PSC | As above; flag negative additive probabilities | P0 power, P1 others — robustness of the baseline |
| Per-outcome recalibration of the close | Is there leftover FLB or draw mispricing in Pinnacle's close? | PSC, 2012/13 onward | AVAILABLE_NOW | Best de-vig | Fit on past seasons only; reliability diagrams; separate home/draw/away intercepts | P1 — a sharper, fairer target |
| Two-way totals de-vig | Fair P(over 2.5) | FD PC>2.5, AvgC>2.5 (over/under 2.5 closing); live over/under | AVAILABLE_NOW | Proportional | Calibration by price bucket | P1 — a baseline for totals |
| Exchange-implied probabilities, net of commission | Is the Betfair close a better "truth" than Pinnacle's? | FD BFEC; our commission rate | AVAILABLE_NOW | PSC Shin | Paired Δ log loss on common matches (no volume data) | P1 — a near-zero-margin cross-check |
| AH-implied 1X2 | Does the unbiased AH market give better 1X2 probabilities? | FD AH lines and prices; historical refund rates | APPROXIMABLE | PSC Shin | Walk-forward log loss using the Hegarty & Whelan (2025a) mapping | P2 — possible baseline upgrade |
| Multi-book consensus | Does pooling bookmakers beat Pinnacle alone? | FD PSC, B365C, AvgC, BFEC; API-Football bookmakers | AVAILABLE_NOW | PSC Shin | Stacked weights fitted walk-forward | P1 — fallback when Pinnacle is missing live |
| Disagreement signal (soft vs sharp, bookmaker vs exchange) | Does the gap predict outcomes, or the move to the close, beyond PSC? | FD pre-closing and closing | AVAILABLE_NOW | PSC Shin (as offset) | Logistic regression with offset; predict the PS→PSC move; never ROI at maximum odds | P2 — explains disagreement, flags stale prices |
| Close vs pre-close test | Is the close the better forecast in our leagues? | FD PS vs PSC, Avg vs AvgC | AVAILABLE_NOW | Pre-closing price | Paired Δ log loss; DM test by league and season | P0 — the premise of CLV |
| Price-path (drift) features | Does the path to the close carry information the close lacks? | FD's two snapshots; live T−24h to T−3h (3-hour refresh) | APPROXIMABLE | PSC Shin | Movement coefficient ≈ 0 if the close is sufficient | P1 — detects over- or under-reaction |
| Tick-level history: steam timing, depth, limits | When do sharp moves happen? What stake could actually be placed? | Timestamped multi-book ticks; Betfair order book; limit data | REQUIRES_ODDS_PROVIDER | Snapshot drift features | Event study around moves; placeable vs displayed price | P3 — alerts, execution realism |
| Semi-strong event studies | Do prices absorb public news (coach changes, empty stadiums)? | Event dates + FD odds | APPROXIMABLE | PSC Shin | Pre-registered event windows; placebo dates | P3 — research, feature ideas |
| Residual-signal tests | Does a non-price feature predict beyond the close? | FD shots and corners; xG needs event data | APPROXIMABLE | PSC Shin | Walk-forward with the close as offset; placebo tests | P2 — the only honest route to a model edge |
| Model–market stacking | What weight does our model earn once the market is known? | Model probabilities + PSC | AVAILABLE_NOW | PSC Shin alone | Out-of-sample weight and Δ log loss | P1 — quantifies what the model adds |
| Uncertainty-adjusted EV | Is the edge bigger than our estimation error? | Bootstrap or posterior spread of p; offered odds | AVAILABLE_NOW | Raw EV / price edge | Realised vs predicted edge by EV decile; interval coverage | P0 — prevents inflated "value" labels |
| Shrunk Kelly + bankroll simulation | What risk would disciplined staking carry? | p, its uncertainty, odds, shadow bets | AVAILABLE_NOW | Flat 1-unit shadow stakes | Monte Carlo with outcomes drawn from closing probabilities | P2 — risk education; never automated |
| Walk-forward harness | How does the model perform out-of-sample, without leakage? | FD, 5 leagues; timestamps | AVAILABLE_NOW | PSC Shin | Rolling origin by matchday; frozen configurations | P0 — credibility of every number |
| Paired Δ log loss vs market | Is the model's gap real, and where is it? | Model and baseline probabilities | AVAILABLE_NOW | PSC Shin | DM test; matchday block bootstrap; per league | P0 — primary KPI |
| CLV | Did the decision price beat the close? | Decision price (FD pre-closing or live snapshot); PSC Shin | AVAILABLE_NOW | CLV = 0 | Mean of O_d·p_close − 1 (O_d = decision odds) with block-bootstrap CI; CLV–ROI link; live CLV provisional | P0 — low-noise leading indicator |
| ROI CIs and sample size | Can ROI be told apart from 0 or from −margin? | Shadow bets | AVAILABLE_NOW | 0 and −margin | Block bootstrap; required-sample-size calculation | P0 — stops over-reading of ROI |
| Multiple-testing control | How much of any "edge" is selection? | Registry of every model and rule tried | AVAILABLE_NOW | Best of N under the null | White reality check / Hansen superior-predictive-ability test; probability of backtest overfitting; placebo that treats the market as truth | P0 — guards against spurious edges |

### What our near-close snapshot needs before it may be called a closing line
API-Football's own guide (API-SPORTS 2026) says the following. The formal documentation was unreachable, so treat these as vendor-reported:
- Fixtures appear on `/odds/live` only 5–15 minutes before kickoff.
- The live endpoint keeps no history.
- Live bet-type IDs are a separate system from pre-match IDs; mixing them silently returns wrong data.
- The `finished` flag is true both before kickoff and after the match ends.
- Pre-match `/odds` refreshes every 3 hours and keeps only 7 days.

Before the snapshot may be called a closing line:
1. **Provenance.** Record which bookmaker the quote comes from. If it is not Pinnacle, benchmark it against that bookmaker's Football-Data (FD) close or the market-average close (AvgC).
2. **Pre-match integrity.** Confirm the match has not started (status, minute, score) and the market is not blocked or stopped. Ignore `finished`. Map live bet IDs to 1X2 and over/under explicitly.
3. **Timing.** Store both our fetch time and the provider's update time, and measure the offset to actual kickoff. A single poll at T−12 misses fixtures that enter the feed later, so poll repeatedly (e.g. T−15 to T−1) and keep the last valid quote before kickoff.
4. **Coverage.** Report the share of fixtures with a valid quote per league. Missing quotes must be unrelated to price or price movement.
5. **Agreement with the FD close.** The gaps in de-vigged probabilities (mean and 95th percentile) should show no favourite/longshot pattern. The overround should be similar. The paired Δ log loss should be about zero, with a CI. Pre-register tolerances; our proposal is a median |Δp| of at most 0.5 percentage points and |Δ log loss| below 0.002.
6. **Movement capture.** The snapshot should sit closer to the FD close than our T−3h capture does: regressing (close − T−3h) on (snapshot − T−3h) should give a slope of about 1.
7. **Stability.** It must pass in all five leagues over a pre-set horizon (our proposal: at least 500 matches over at least 2 months). Re-validate after any provider change, and version the definition.
8. **Archival.** Store the raw payloads ourselves, with a hash and timestamps.

Until all eight pass, call it a "near-close snapshot (unvalidated)" and treat any CLV measured against it as provisional. The FD Pinnacle close remains the official close. Betfair commission varies by account (see Betfair's help page; Whelan 2026 models 2%), so keep it as a parameter.

### Sources
- API-SPORTS (2026). How to get started with API-Football: the complete beginner's guide. API-Football blog, 13 Mar 2026. https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
- Angelini, G., & De Angelis, L. (2019). Efficiency of online football betting markets. International Journal of Forecasting 35(2), 712–721. https://doi.org/10.1016/j.ijforecast.2018.07.008
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2016). The probability of backtest overfitting. Journal of Computational Finance 20(4), 39–69. https://doi.org/10.21314/JCF.2016.322
- Baker, R. D., & McHale, I. G. (2013). Optimal betting under parameter uncertainty: Improving the Kelly criterion. Decision Analysis 10(3), 189–199. https://doi.org/10.1287/deca.2013.0271
- Betfair (n.d.). Exchange: What is the Market Base Rate? Betfair Support. https://support.betfair.com/app/answers/detail/412-exchange-what-is-the-market-base-rate/
- Bunker, R., Yeung, C., & Fujii, K. (2024). Machine learning for soccer match result prediction. arXiv:2403.07669. https://arxiv.org/abs/2403.07669
- Cain, M., Law, D., & Peel, D. A. (2000). The favourite-longshot bias and market efficiency in UK football betting. Scottish Journal of Political Economy 47(1), 25–36. https://doi.org/10.1111/1467-9485.00151
- Clarke, S., Kovalchik, S., & Ingram, M. (2017). Adjusting bookmaker's odds to allow for overround. American Journal of Sports Science 5(6), 45–49. https://doi.org/10.11648/j.ajss.20170506.12
- Constantinou, A. C., & Fenton, N. E. (2012). Solving the problem of inadequate scoring rules for assessing probabilistic football forecast models. Journal of Quantitative Analysis in Sports 8(1). https://doi.org/10.1515/1559-0410.1418
- Croxson, K., & Reade, J. J. (2014). Information and efficiency: Goal arrival in soccer betting. Economic Journal 124(575), 62–91. https://ideas.repec.org/a/wly/econjl/v124y2014i575p62-91.html
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. Journal of Business & Economic Statistics 13(3), 253–263. https://ideas.repec.org/a/bes/jnlbes/v13y1995i3p253-63.html
- Egidi, L., Pauli, F., & Torelli, N. (2018). Combining historical data and bookmakers' odds in modelling football scores. arXiv:1802.08848. https://arxiv.org/abs/1802.08848
- Flepp, R., Nüesch, S., & Franck, E. (2017). The liquidity advantage of the quote-driven market: Evidence from the betting industry. Quarterly Review of Economics and Finance 64, 306–317. https://doi.org/10.1016/j.qref.2016.07.016
- Football-Data.co.uk (n.d.). Notes for football data; Data files page. https://www.football-data.co.uk/notes.txt ; https://www.football-data.co.uk/data.php
- Forrest, D., Goddard, J., & Simmons, R. (2005). Odds-setters as forecasters: The case of English football. International Journal of Forecasting 21(3), 551–564. https://doi.org/10.1016/j.ijforecast.2005.03.003
- Franck, E., Verbeek, E., & Nüesch, S. (2010). Prediction accuracy of different market structures — bookmakers versus a betting exchange. International Journal of Forecasting 26(3), 448–459. https://doi.org/10.1016/j.ijforecast.2010.01.004
- Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. Journal of the American Statistical Association 102, 359–378. https://ideas.repec.org/a/bes/jnlasa/v102y2007p359-378.html
- Goto, K., Takeishi, N., & Yairi, T. (2026). Forecast sports outcomes under efficient market hypothesis: Theoretical and experimental analysis of odds-only and generalised linear models. arXiv:2604.17194. https://arxiv.org/abs/2604.17194
- Grant, A., Oikonomidis, A., Bruce, A. C., & Johnson, J. E. V. (2018). New entry, strategic diversity and efficiency in soccer betting markets: the creation and suppression of arbitrage opportunities. European Journal of Finance 24(18), 1799–1816. https://doi.org/10.1080/1351847X.2018.1443148
- Hansen, P. R. (2005). A test for superior predictive ability. Journal of Business & Economic Statistics 23(4), 365–380. https://ideas.repec.org/a/bes/jnlbes/v23y2005p365-380.html
- Hegarty, T., & Whelan, K. (2023). The wisdom of no crowds: The reaction of betting markets to lockdown soccer games. Journal of Prediction Markets. https://ubplj.org/index.php/jpm/article/view/2089
- Hegarty, T., & Whelan, K. (2025a). Forecasting soccer matches with betting odds: A tale of two markets. International Journal of Forecasting 41(2), 803–820. https://doi.org/10.1016/j.ijforecast.2024.06.013
- Hegarty, T., & Whelan, K. (2025b). Estimating expected loss rates in betting markets: Theory and evidence. Applied Economics (online). https://doi.org/10.1080/00036846.2025.2507979
- Hegarty, T., & Whelan, K. (2026). Market structure and prices in online betting markets: theory and evidence. Oxford Economic Papers 78(1), 90–113. https://doi.org/10.1093/oep/gpaf023
- Holmes, B., & McHale, I. G. (2024). Forecasting football match results using a player rating based model. International Journal of Forecasting 40(1), 302–312. https://doi.org/10.1016/j.ijforecast.2023.03.002
- Karimov, A., Koshkin, A., Kaplun, D., & Butusov, D. (2025). Domain-driven identification of football probabilities. Mathematics 13(24), 3976. https://doi.org/10.3390/math13243976
- Kaunitz, L., Zhong, S., & Kreiner, J. (2017). Beating the bookies with their own numbers — and how the online sports betting market is rigged. arXiv:1710.02824. https://arxiv.org/abs/1710.02824
- Kelly, J. L. (1956). A new interpretation of information rate. Bell System Technical Journal 35(4), 917–926. https://archive.org/details/bstj35-4-917
- Lindstrøm, J. C. (2023). implied: Convert between bookmaker odds and probabilities (R package 0.5). CRAN. https://cran.r-project.org/web/packages/implied/vignettes/introduction.html
- MacLean, L. C., Thorp, E. O., & Ziemba, W. T. (2010). Long-term capital growth: the good and bad properties of the Kelly and fractional Kelly capital growth criteria. Quantitative Finance 10(7), 681–687. https://doi.org/10.1080/14697688.2010.506108
- Meier, P. F., Flepp, R., & Franck, E. (2021). Are sports betting markets semi-strong efficient? Evidence from the COVID-19 pandemic. International Journal of Sport Finance 16(3), 111–126. https://doi.org/10.32731/IJSF.163.082021.01
- Moskowitz, T. J. (2021). Asset pricing and sports betting. Journal of Finance 76(6), 3153–3209. https://doi.org/10.1111/jofi.13082
- Newall, P. W. S., & Cortis, D. (2021). Are sports bettors biased toward longshots, favorites, or both? A literature review. Risks 9(1), 22. https://doi.org/10.3390/risks9010022
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. Journal of the American Statistical Association 89(428), 1303–1313. https://doi.org/10.1080/01621459.1994.10476870
- Shin, H. S. (1991). Optimal betting odds against insider traders. Economic Journal 101(408), 1179–1185. https://ideas.repec.org/a/ecj/econjl/v101y1991i408p1179-85.html
- Shin, H. S. (1993). Measuring the incidence of insider trading in a market for state-contingent claims. Economic Journal 103(420), 1141–1153. https://doi.org/10.2307/2234240
- Štrumbelj, E. (2014). On determining probability forecasts from betting odds. International Journal of Forecasting 30(4), 934–943. https://doi.org/10.1016/j.ijforecast.2014.02.008
- Štrumbelj, E. (2016). A comment on the bias of probabilities derived from betting odds and their use in measuring outcome uncertainty. Journal of Sports Economics 17(1), 12–26. https://doi.org/10.1177/1527002513519329
- Štrumbelj, E., & Robnik Šikonja, M. (2010). Online bookmakers' odds as forecasts: The case of European soccer leagues. International Journal of Forecasting 26(3), 482–488. https://doi.org/10.1016/j.ijforecast.2009.10.005
- Tashman, L. J. (2000). Out-of-sample tests of forecasting accuracy: an analysis and review. International Journal of Forecasting 16(4), 437–450. https://ideas.repec.org/a/eee/intfor/v16y2000i4p437-450.html
- Uhrín, M., Šourek, G., Hubáček, O., & Železný, F. (2021). Optimal sports betting strategies in practice: an experimental review. IMA Journal of Management Mathematics 32(4), 465–489. https://doi.org/10.1093/imaman/dpaa029
- Walsh, C., & Joshi, A. (2024). Machine learning for sports betting: Should model selection be based on accuracy or calibration? Machine Learning with Applications 16, 100539. https://doi.org/10.1016/j.mlwa.2024.100539
- Walsh, C., & Joshi, A. (2025). Corrigendum to "Machine learning for sports betting: Should model selection be based on accuracy or calibration?". Machine Learning with Applications 19, 100627. https://doi.org/10.1016/j.mlwa.2025.100627
- Wheatcroft, E. (2020). A profitable model for predicting the over/under market in football. International Journal of Forecasting 36(3), 916–932. https://doi.org/10.1016/j.ijforecast.2019.11.001
- Wheatcroft, E. (2021). Evaluating probabilistic forecasts of football matches: the case against the ranked probability score. Journal of Quantitative Analysis in Sports 17(4), 273–287. https://doi.org/10.1515/jqas-2019-0089
- Whelan, K. (2025a). How does inside information affect sports betting odds? Scottish Journal of Political Economy. https://doi.org/10.1111/sjpe.70017
- Whelan, K. (2025b). On estimates of insider trading in sports betting. The Manchester School. https://doi.org/10.1111/manc.12505
- Whelan, K. (2025c). On optimal betting strategies with multiple mutually exclusive outcomes. Bulletin of Economic Research 77(1), 67–85. https://doi.org/10.1111/boer.12474
- Whelan, K. (2025d). Ruin probabilities for strategies with asymmetric risk. Working paper, University College Dublin. http://www.karlwhelan.com/Papers/Ruin.pdf
- Whelan, K. (2026). Agreeing to disagree: The economics of betting exchanges. Working paper, University College Dublin (draft 26 Jan 2026). http://www.karlwhelan.com/Papers/Betfair.pdf
- White, H. (2000). A reality check for data snooping. Econometrica 68(5), 1097–1126. https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html
- Wilkens, S. (2026). Can simple models predict football — and beat the odds? Lessons from the German Bundesliga. Journal of Sports Analytics. https://doi.org/10.1177/22150218261416681
- Winkelmann, D., Ötting, M., Deutscher, C., & Makarewicz, T. (2024). Are betting markets inefficient? Evidence from simulations and real data. Journal of Sports Economics 25(1), 54–97. https://doi.org/10.1177/15270025231204997
- Wunderlich, F., & Memmert, D. (2020). Are betting returns a useful measure of accuracy in (sports) forecasting? International Journal of Forecasting 36(2), 713–722. https://doi.org/10.1016/j.ijforecast.2019.08.009
