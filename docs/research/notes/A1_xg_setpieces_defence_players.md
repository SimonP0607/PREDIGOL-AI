# A1: xG, set pieces, defence and player evaluation (literature review and fit to our data)

*Reviewed 25 Sep 2026.*

**Data.**
- API-Football v3: fixtures, minute-stamped events, team and player match stats, lineups with grid positions, injuries, standings, and odds kept for 7 days.
- Football-Data.co.uk: results, shots, shots on target (SoT), corners, fouls, cards and closing odds.
- We have no coordinates, tracking or freeze frames.

**Labels.** AVAILABLE_NOW; APPROXIMABLE (proxy, loss stated); REQUIRES_EVENT_PROVIDER (x/y events; "+360" = freeze frames too); REQUIRES_TRACKING_PROVIDER.

**Priority.** P0 before going live, P1 after historical backfill, P2 improvement, P3 research. Product value: H, M or L.

**Rule.** Score models with proper scoring rules and calibration, on splits blocked by match or season. Judge indicators by their reliability and validity (Davis et al. 2024).

## 1. Expected goals, post-shot models and goalkeeping

### State of the art (2024–2026)

**Features.**
- xG models the chance that a shot is scored. Inputs are:
  - location and angle, body part, pattern of play;
  - the previous action (through ball, cross, cutback);
  - goalkeeper and defender context.
- Opta uses more than 20 variables, including keeper position, pressure and assist type. It fixes penalties at 0.79 (Opta Analyst 2023).
- Extra signal comes from:
  - blockers seen in freeze frames (Vatvani 2022);
  - tracking data (Anzer & Bauer 2021);
  - 3D skeletons, which capture body orientation (Xu et al. 2025).

**Diminishing returns.**
- Boosted-tree models need at most about 5 seasons of data. Pooling leagues is fine; mixing data providers is not (Robberechts & Davis 2020).
- A Bayesian mixed model with seven variables reaches AUC 0.781, against 0.801 for StatsBomb's model (Iapteff et al. 2025).
- Refinements: monotonic constraints and augmentation of rare shot types (Gallagher et al. 2026); modelling whether a shot happens at all, "xG+" (Pipping-Gamón et al. 2025); sequence models, whose under-sampled training needs recalibration (Bandara et al. 2024).

**Game state.**
- Score, red cards and the minute shift shot and corner volume (Skripnikov et al. 2025, accepted in JQAS).
- Goals cluster and become more frequent late in matches (Ayana et al. 2025).
- xG predicts future results better than shots or goals do (Mead et al. 2023).

**Post-shot models and skill.**
- PSxG and xGOT add where the shot ended (Goodman 2018; Opta Analyst 2021).
- Stats Perform (2025) adds keeper position, deflection, and a penalty model trained on more than 20,000 kicks.
- Goals prevented = xGOT faced − goals conceded.
- Goals above xG (GAX) is noisy and biased toward zero; it understates Messi's by 17% (Davis & Robberechts 2024).
- Residualised GAX gives valid intervals, for keepers too (Bajons & Kook 2025).
- Player effects persist after controlling for shot quality (Scholtes & Karakuş 2024). Off-target shots also carry signal (Baron et al. 2024).
- Team strength helps prediction but is a bad control for player evaluation (Bajons & Harringer 2025).

**Validation.**
- Use log loss, Brier score and calibration within subgroups. AUC is secondary.
- Accuracy is useless. StatsBomb's xG scores 0.911 accuracy against 0.904 for a constant prediction, yet its log loss is 0.254 against 0.316 (Bajons & Harringer 2025).
- Split data by match or season (Davis et al. 2024).
- Compute match probabilities exactly with a Poisson-binomial, not Monte Carlo (Davis, Robberechts & Van Haaren 2025).
- Prefer the log score to the ranked probability score, RPS (Wheatcroft 2021b).

### What we can build with our data

We cannot build shot-level xG, PSxG, finishing skill or shot-stopping skill. We lack shot location, body part, assist type, defender positions and end location.

What we can build:
- Team shot ratings from Football-Data shots and SoT. These carry information beyond the odds (Wheatcroft 2021a).
- An "xG-lite" from API-Football's inside-box, outside-box and blocked shot counts.
- API-Football's `expected_goals` and `goals_prevented`, used as black-box features after we check their calibration.
- An in-play goal-hazard model from goal and red-card minutes plus odds. This is the core of Robberechts et al. (2021).

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Evaluation harness | Are forecasts calibrated? Do they beat the market? | Forecasts; Football-Data closing odds (we must archive API odds ourselves) | AVAILABLE_NOW | Closing odds with the margin removed | Log loss, Brier, ECE; CV blocked by season | **P0** · H: gates every model |
| Team shot ratings | How well does a team create chances, beyond goals? | Football-Data shots, SoT | AVAILABLE_NOW | Goals-only Dixon–Coles or Elo | Out-of-season log loss | **P0** · H |
| Box-split "xG-lite" | How dangerous were a team's shots? | API shot splits; non-penalty goals | APPROXIMABLE: count GLM; loses location, body part, assist, pressure | Shots × conversion rate | Deviance on future goals; calibration | **P1** · H |
| Provider xG / goals prevented | Can we reuse API-Football's values? | API stats (some leagues only) | AVAILABLE_NOW (black box) | xG-lite | Summed xG vs goals; log-loss gain | **P1** · M–H |
| Penalty model | What is a penalty worth? Taker and keeper effects? | Penalty events; player fields | AVAILABLE_NOW | Constant 0.79 | Log loss; beta-binomial checks | **P0** · M |
| Game-state adjustment | Were shots inflated by trailing? | Goal and red-card minutes; shot totals | APPROXIMABLE: minutes in each state as exposure; no shot timing; reverse causality | Raw totals | Deviance on future shots | **P2** · M |
| In-play goal hazard | Win/draw/loss chances at minute *t* | Goal and red-card minutes; odds | AVAILABLE_NOW | Static pre-match odds | Log loss by minute | **P1** · H: live product, plus-minus |
| Shot-level and context xG | How good was each chance? | x/y events; 360; pose data | REQUIRES_EVENT_PROVIDER (+360); pose: REQUIRES_TRACKING_PROVIDER | Logistic model on distance and angle | Log loss; calibration by subgroup | **P3** (P1 if bought) · H |
| PSxG; finishing and keeper skill | Who finishes or saves above expectation? | End location; keeper position | REQUIRES_EVENT_PROVIDER. Saves vs shot-mix proxy: APPROXIMABLE (weak) | Raw conversion or save % | Split-half reliability; rGAX intervals | **P3** (proxy P2) · M |

### Sources
- Anzer, G., & Bauer, P. (2021). A goal scoring probability model for shots based on synchronized positional and event data in football (soccer). Frontiers in Sports and Active Living, 3, 624475. https://doi.org/10.3389/fspor.2021.624475
- Ayana, G., Ehlert, A., Ehlert, J., Santagata, L., Torricelli, M., & Klein, B. (2025). Temporal dynamics of goal scoring in soccer. arXiv:2501.18606. https://arxiv.org/abs/2501.18606
- Bajons, R., & Harringer, T. (2025). One xG model to rule them all? Challenging the most accurate xG model. Hudl Performance Insights 2025. https://static.hudl.com/craft/performance-insights-research-stage/2025/One-xG-model-to-rule-them-all_-Robert-Bajons-Tobias-Harringer.pdf
- Bajons, R., & Kook, L. (2025). Rethinking player evaluation in sports: Goals above expectation and beyond. arXiv:2509.20083. https://arxiv.org/abs/2509.20083
- Bandara, I., Shelyag, S., Rajasegarar, S., Dwyer, D., Kim, E.-J., & Angelova, M. (2024). Predicting goal probabilities with improved xG models using event sequences in association football. PLOS ONE, 19(10), e0312278. https://doi.org/10.1371/journal.pone.0312278
- Baron, E., Sandholtz, N., Pleuler, D., & Chan, T. C. Y. (2024). Miss it like Messi: Extracting value from off-target shots in soccer. JQAS, 20(1), 37–50. https://doi.org/10.1515/jqas-2022-0107
- Davis, J., & Robberechts, P. (2024). Biases in expected goals models confound finishing ability. arXiv:2401.09940. https://arxiv.org/abs/2401.09940
- Davis, J., Bransen, L., Devos, L., Jaspers, A., Meert, W., Robberechts, P., Van Haaren, J., & Van Roy, M. (2024). Methodology and evaluation in sports analytics: challenges, approaches, and lessons learned. Machine Learning, 113(9), 6977–7010. https://doi.org/10.1007/s10994-024-06585-0
- Davis, J., Robberechts, P., & Van Haaren, J. (2025). Expected goals and the Monte Carlo trap. KU Leuven DTAI Sports Analytics Lab. https://dtai.cs.kuleuven.be/sports/blog/expected-goals-and-the-monte-carlo-trap/
- Gallagher, J., Dinsdale, D., Murali, A., Mackay, N., Foroni, D., & Lucey, P. (2026). Addressing last mile issues in sports analytics: A case study in expected goals in soccer. Sports Analytics (ISACE 2026), LNCS 16610, 475–483. https://doi.org/10.1007/978-3-032-27272-0_30
- Goodman, M. (2018). A new way to measure keepers' shot stopping: Post-shot expected goals. StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/a-new-way-to-measure-keepers-shot-stopping-post-shot-expected-goals/
- Iapteff, L., Le Coz, S., Rioland, M., Houde, T., Carling, C., & Imbach, F. (2025). Toward interpretable expected goals modeling using Bayesian mixed models. Frontiers in Sports and Active Living, 7, 1504362. https://doi.org/10.3389/fspor.2025.1504362
- Mead, J., O'Hare, A., & McMenemy, P. (2023). Expected goals in football: Improving model performance and demonstrating value. PLOS ONE, 18(4), e0282295. https://doi.org/10.1371/journal.pone.0282295
- Opta Analyst (2021). What are expected goals on target (xGOT)? https://theanalyst.com/articles/what-are-expected-goals-on-target-xgot
- Opta Analyst (2023). What is expected goals (xG)? https://theanalyst.com/articles/what-is-expected-goals-xg
- Pipping-Gamón, J., Feng, T., & Sabin, R. P. (2025). Beyond expected goals: A probabilistic framework for shot occurrences in soccer. arXiv:2512.00203. https://arxiv.org/abs/2512.00203
- Robberechts, P., & Davis, J. (2020). How data availability affects the ability to learn good xG models. MLSA 2020, CCIS 1324, 17–27. https://doi.org/10.1007/978-3-030-64912-8_2
- Robberechts, P., Van Haaren, J., & Davis, J. (2021). A Bayesian approach to in-game win probability in soccer. KDD '21, 3512–3521. https://doi.org/10.1145/3447548.3467194
- Scholtes, A., & Karakuş, O. (2024). Bayes-xG: Player and position correction on expected goals (xG) using Bayesian hierarchical approach. Frontiers in Sports and Active Living, 6, 1348983. https://doi.org/10.3389/fspor.2024.1348983
- Skripnikov, A., Cemek, A., & Gillman, D. (2025). Leveraging minute-by-minute soccer match event data to adjust team's offensive production for game context. arXiv:2508.04008 (accepted, JQAS). https://arxiv.org/abs/2508.04008
- Stats Perform (2025). Enhancing expected goals on target: Deeper insights into shot execution, goalkeeper performance, and a dedicated model for women's football. https://www.statsperform.com/insights/enhancing-expected-goals-on-target/
- Vatvani, D. (2022). Upgrading expected goals. StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/upgrading-expected-goals/
- Wheatcroft, E. (2021a). Forecasting football matches by predicting match statistics. Journal of Sports Analytics, 7(2), 77–97. https://doi.org/10.3233/JSA-200462
- Wheatcroft, E. (2021b). Evaluating probabilistic forecasts of football matches: the case against the ranked probability score. JQAS, 17(4), 273–287. https://doi.org/10.1515/jqas-2019-0089
- Xu, Y., Bretzner, L., Wang, T., & Maki, A. (2025). Skor-xG: SKeleton-ORiented expected goal estimation in soccer. CVPR 2025 Workshops (CVsports). https://openaccess.thecvf.com/content/CVPR2025W/CVSPORTS/papers/Xu_Skor-xG_SKeleton-ORiented_Expected_Goal_Estimation_in_Soccer_CVPRW_2025_paper.pdf

## 2. Set pieces

### State of the art (2024–2026)

**Tracking-based work leads.**
- TacticAI was trained on 7,176 Premier League corners (Wang et al. 2024). It predicts the receiver with 0.782 top-3 accuracy and a shot with F1 0.71. Liverpool experts preferred its suggested set-ups 90% of the time.
- Graph reinforcement learning chooses player positions that maximise the shot probability of the first contact (Groom et al. 2026).
- Other tracking work clusters attacking runs and classifies man versus zonal marking (Shaw & Gopaladesikan 2020). Another model classifies seven defensive roles at 89.3% accuracy (Bauer, Anzer & Smith 2022).

**Base rates.**
- Corners:
  - 20.7–31.2% produce a shot and 2.2–4.43% a goal.
  - First contact goes to the keeper 16–24% of the time, a defender 28–44%, an attacker 31–48% (Plakias et al. 2025).
- Direct free kicks: 9 goals from 264 attempts in the 2023/24 Premier League, 0.06 xG per shot (Ridge 2024).
- Throw-ins:
  - 83% win first contact, 54% keep possession and 8.8% lead to a shot.
  - Backward or lateral throws do best (Stone et al. 2021; Casal et al. 2023).
  - StatsBomb values throw-ins with OBV over the next 5 seconds (Monte 2024).
  - Long throws have been studied with 360 data (Greenhalgh et al. 2025).

**Penalties.**
- Takers and keepers randomise as game theory predicts (minimax; Palacios-Huerta 2003).
- Opta's penalty xG is 0.79, and Stats Perform (2025) built a dedicated penalty xGOT.
- Keeper dive policies have been simulated (Bransen et al. 2025).
- Takers avoid placements that risk missing more than is optimal (Uribe et al. 2025).

**Counts and timing.**
- Corner counts: compound Poisson models using odds (Yip et al. 2024).
- Corner timing: event-history models (Peng et al. 2024; Isaacs et al. 2026).
- Corner counts help match forecasts (Wheatcroft 2021a).

**Second balls.** We found no peer-reviewed model.

### What we can build with our data

What we can build:
- Corner-count models: negative binomial or compound Poisson, with team strength taken from the odds.
- Corners as an input to the match model.
- Penalty rates, shrunk toward league averages.

What we cannot build: our goal events carry no pattern-of-play tag, only a penalty or own-goal flag (to be confirmed). That rules out set-piece xG, delivery zones, first contact, second balls, free-kick analysis and throw-in analysis. Multiplying corners by a 2–4% conversion rate is too crude to publish.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Corner count model | How many corners will each team win? | Corner counts; odds | AVAILABLE_NOW | Season means; plain Poisson | Log predictive density; over/under calibration | **P1** · M–H: corner markets |
| Corners and fouls in team strength | Do they add predictive signal? | Match counts | AVAILABLE_NOW | Shots + goals model | Log-loss gain vs closing odds | **P1** · M |
| Penalty award and conversion | How often does a team win penalties? Taker and keeper effects? | Penalty events; player fields; referee (where recorded) | AVAILABLE_NOW | League rates; 0.79 | Log loss; posterior checks | **P1** · M |
| Set-piece goals and xG | How dependent is a team on set pieces? | x/y shots tagged by pattern of play | REQUIRES_EVENT_PROVIDER | Corners × conversion rate | Calibration by set-piece type | **P3** (P2 with events) · H |
| Delivery zones, first contact, second balls | Where do deliveries land, and who wins them? | Delivery x/y; aerial duels; 360 or tracking | REQUIRES_EVENT_PROVIDER / REQUIRES_TRACKING_PROVIDER | Base rates per zone | Log loss by zone | **P3** · M |
| Routine and marking detection; generated set-ups | Which routine is used? What is the best set-up? | Tracking of all 22 players | REQUIRES_TRACKING_PROVIDER | Event-based corner xG | Top-k receiver accuracy; expert review | **P3** · L |
| Corner timing | When do corners come? | Corner timestamps (not in our feeds) | REQUIRES_EVENT_PROVIDER (timestamps only) | Homogeneous Poisson | Likelihood-ratio tests | **P3** · M |
| Free-kick xG; throw-in value | What are these routines worth? | x/y events; 360 | REQUIRES_EVENT_PROVIDER (+360) | League base rates | Log loss; value over the next 5 s | **P3** · L–M |
| Penalty placement and keeper policy | Where should takers aim and keepers dive? | Annotated penalties | REQUIRES_EVENT_PROVIDER (+video annotation) | Uniform dive | Simulated gain in saves | **P3** · L |

### Sources
- Bauer, P., Anzer, G., & Smith, J. W. (2022). Individual role classification for players defending corners in football (soccer). JQAS, 18(2), 147–160. https://doi.org/10.1515/jqas-2022-0003
- Bransen, L., Janssen, T., & Davis, J. (2025). Stop guessing: Optimizing goalkeeper policies for soccer penalty kicks. arXiv:2505.24629. https://arxiv.org/abs/2505.24629
- Casal, C. A., Armatas, V., Losada, J. L., & Mitrotasios, M. (2023). Effects of tactical dimension and situational variables in throw-ins on the offensive performance in football. PLOS ONE, 18(11), e0294317. https://doi.org/10.1371/journal.pone.0294317
- Greenhalgh, S., Anghel, D., Kutibashvili, S., Arsénio, H., & Pascual, R. (2025). Defending the long throw: A dual-model framework for minimising defensive risk. Hudl Performance Insights 2025. https://static.hudl.com/craft/performance-insights-research-stage/2025/Defending-the-Long-Throw_-A-Dual-Model-Framework-for-Minimising-Defensive-Risk-Sebastian-Greenhalgh-Dan-Anghel.pdf
- Groom, S., Groom, M., Belo, F., Rice, A., Anderson, L., Darvariu, V.-A., & Wang, S. (2026). Maximising the set-piece return: Optimising football corner tactics with graph reinforcement learning. arXiv:2606.06353. https://arxiv.org/abs/2606.06353
- Isaacs, R. L., Hu, X. J., Peng, K. K., & Swartz, T. (2026). Learning about corner kicks in soccer by analysis of event times using a frailty model. arXiv:2602.22684 (also Sports Analytics, ISACE 2026, LNCS 16610). https://arxiv.org/abs/2602.22684
- Monte, J. (2024). Measuring throw-in success. Hudl StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/measuring-throw-in-success/
- Opta Analyst (2023). What is expected goals (xG)? (penalty xG = 0.79). https://theanalyst.com/articles/what-is-expected-goals-xg
- Palacios-Huerta, I. (2003). Professionals play minimax. Review of Economic Studies, 70(2), 395–415. https://doi.org/10.1111/1467-937X.00249
- Peng, K. K., Hu, X. J., & Swartz, T. B. (2024). On the time of corner kicks in soccer: an analysis of event history data. Computational Statistics, 40(4), 2067–2083 (online 2024). https://doi.org/10.1007/s00180-024-01567-1
- Plakias, S., Armatas, V., & Giakas, G. (2025). Technical–tactical analysis of corner kicks in male soccer: A systematic review. Applied Sciences, 15(9), 4984. https://doi.org/10.3390/app15094984
- Ridge, P. (2024). What's happened to the Premier League's direct free-kick goals? Opta Analyst. https://theanalyst.com/2024/05/whats-happened-to-goals-from-premier-league-free-kicks/
- Shaw, L., & Gopaladesikan, S. (2020). Routine inspection: A playbook for corner kicks. MLSA 2020, CCIS 1324, 3–16. https://doi.org/10.1007/978-3-030-64912-8_1
- Stats Perform (2025). Enhancing expected goals on target (dedicated penalty model). https://www.statsperform.com/insights/enhancing-expected-goals-on-target/
- Stone, J. A., Smith, A., & Barry, A. (2021). The undervalued set piece: Analysis of soccer throw-ins during the English Premier League 2018–2019 season. International Journal of Sports Science & Coaching, 16(3), 830–839. https://doi.org/10.1177/1747954121991447
- Uribe, A., Sanders, S., Ehrlich, J., Reade, J. J., & Singleton, C. (2025). Do behavioral considerations cloud penalty-kick location optimization in professional soccer? MIT Sloan Sports Analytics Conference. https://www.sloansportsconference.com/research-papers/do-behavioral-considerations-cloud-penalty-kick-location-optimization-in-professional-soccer-game-theory-empirical-testing-using-polynomial-regression-and-ml-gradient-boosting
- Wang, Z., Veličković, P., Hennes, D., Tomašev, N., et al. (2024). TacticAI: an AI assistant for football tactics. Nature Communications, 15, 1906. https://doi.org/10.1038/s41467-024-45965-x
- Wheatcroft, E. (2021a). Forecasting football matches by predicting match statistics. Journal of Sports Analytics, 7(2), 77–97. https://doi.org/10.3233/JSA-200462
- Yip, S., Zou, Y., Hung, R. T. H., & Yiu, K. F. C. (2024). Forecasting number of corner kicks taken in association football using compound Poisson distribution. Journal of the Operational Research Society, 75(11), 2127–2137. https://doi.org/10.1080/01605682.2024.2306170

## 3. Defensive analytics

### State of the art (2024–2026)

**PPDA and territory.**
- PPDA (passes allowed per defensive action) is opponent passes ÷ tackles, interceptions, challenges and fouls beyond Opta's x = 40 line (Trainor 2014).
- It measures pressing intensity and style, not quality, and territorial dominance partly confounds it (Stats Perform n.d.).
- Field tilt is a team's share of final-third passes or possession (Stats Perform n.d.; Tweedale 2024).

**Why raw counts fail.**
- Raw tackles and interceptions did not correlate with shots against, goals against or points; possession-adjusted versions explained about 40% of the variation (Knutson 2014, blog evidence).
- DAxT values each defensive action by the threat it ended (Merhej et al. 2021).
- VDEP predicts frequent events (ball recoveries, "being attacked") instead of goals, from 25 Hz tracking: F1 > 0.483 against < 0.201 for goal-based classifiers, and r = 0.397 with season outcomes (Toda et al. 2022). A counterfactual variant uses StatsBomb 360 (Umemoto & Fujii 2023).

**Pressing and compactness (all from tracking).**
- Pressure can be quantified from player and ball positions (Andrienko et al. 2017).
- Counterpressing detection reaches AUC 0.874 over more than 4,100 Bundesliga matches. Regaining the ball within 5 s raises the chance of a shot (Bauer & Anzer 2021).
- Pressure averages 14.5% in successful defensive plays against 12.9% in failed ones (Forcher et al. 2024a).
- Compactness of the five defenders nearest the ball separates success from failure; whole-team compactness does not (Forcher et al. 2024b).
- Also: expected ball gain versus possession value in transitions (Forcher et al. 2025); frame-level pressing intensity (Bekkers 2025); individual pressing value, AUC 0.731 (Lee et al. 2026); a review of team-shape metrics (Low et al. 2020).

### What we can build with our data

What we can build:
- Opponent-adjusted defence ratings.
- Territory proxies: shares of shots, box shots, corners and possession. These are not field tilt.
- Tackles and interceptions adjusted for possession.
- A whole-match "PPDA-lite", which is Trainor's original form.
- Opponent pass completion compared with what we would expect.
- Defensive plus-minus, our only individual defensive measure that is not a raw count.

What we cannot build: zone PPDA, field tilt, turnovers, regains, progression prevented, compactness, VDEP or defensive responsibility.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Opponent-adjusted defence ratings | How well does a team suppress chances? | Goals, shots, SoT and box shots against | AVAILABLE_NOW | Raw goals against | Deviance on future goals against | **P0** · H |
| Territory proxies | Who controls games? | Shares of shots, box shots, corners, possession | AVAILABLE_NOW (not field tilt) | Possession alone | Split-half stability; future goal difference | **P0** · M–H |
| Possession-adjusted tackles and interceptions | How active is a defender, given his opportunities? | Player stats; possession | AVAILABLE_NOW | Raw per-90 | Split-half reliability | **P1** · M: activity, not quality |
| PPDA-lite | How intensely does a team press? | Opponent passes; tackles, interceptions, fouls | APPROXIMABLE: whole match; loses the x > 40 zone and failed challenges | Possession % | Stability; residual after possession | **P1** · M: style tag |
| Opponent pass completion vs expected | Does a team disrupt opponents' passing? | Opponent pass accuracy; opponent norms | AVAILABLE_NOW | Raw opponent pass % | Stability; link to opponent shots | **P2** · M |
| Defensive / two-way RAPM | Whose presence cuts goals conceded? | Lineups, subs, red cards, goal minutes | AVAILABLE_NOW (noisy) | Raw on/off | Reliability; forecast validity (Hvattum & Gelade 2021) | **P2** · M–H |
| Field tilt, zone PPDA, turnovers, regains, progression prevented, DAxT | Where and how fast is the ball won? What was prevented? | x/y events with timestamps | REQUIRES_EVENT_PROVIDER | Our proxies | Added predictive value | **P3** (P2 with events) · H |
| VDEP | Does the defence cause recoveries and prevent attacks? | Tracking, or events + 360 | REQUIRES_TRACKING_PROVIDER (or EVENT_PROVIDER +360) | Goal-based evaluation | F1 or log loss; correlation with season results | **P3** · M |
| Compactness, pressing intensity, counterpressing, responsibility | What is the off-ball shape? Who is responsible? | Tracking at 25 Hz | REQUIRES_TRACKING_PROVIDER | Event-based proxies | AUC for ball gains; expert labels | **P3** · M |

### Sources
- Andrienko, G., Andrienko, N., Budziak, G., Dykes, J., Fuchs, G., von Landesberger, T., & Weber, H. (2017). Visual analysis of pressure in football. Data Mining and Knowledge Discovery, 31(6), 1793–1839. https://doi.org/10.1007/s10618-017-0513-2
- Bauer, P., & Anzer, G. (2021). Data-driven detection of counterpressing in professional football. Data Mining and Knowledge Discovery, 35(5), 2009–2049. https://doi.org/10.1007/s10618-021-00763-7
- Bekkers, J. (2025). Pressing intensity: An intuitive measure for pressing in soccer. arXiv:2501.04712. https://arxiv.org/abs/2501.04712
- Forcher, L., Forcher, L., Altmann, S., Jekauc, D., & Kempe, M. (2024a). The keys of pressing to gain the ball: Characteristics of defensive pressure in elite soccer using tracking data. Science and Medicine in Football, 8(2), 161–169. https://doi.org/10.1080/24733938.2022.2158213
- Forcher, L., Forcher, L., Altmann, S., Jekauc, D., & Kempe, M. (2024b). Is a compact organization important for defensive success in elite soccer? Analysis based on player tracking data. International Journal of Sports Science & Coaching, 19(2), 757–768. https://doi.org/10.1177/17479541231172695
- Forcher, L., Forcher, L., Altmann, S., & Woll, A. (2025). The strategy tradeoff between risk and reward in soccer: Expected ball gain and expected possession value in Bundesliga. International Journal of Sports Science & Coaching (online first). https://doi.org/10.1177/17479541251389831
- Hvattum, L. M., & Gelade, G. A. (2021). Comparing bottom-up and top-down ratings for individual soccer players. International Journal of Computer Science in Sport, 20(1), 23–42. https://doi.org/10.2478/ijcss-2021-0002
- Knutson, T. (2014). More discussion about possession adjusted defensive stats. StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/more-discussion-about-possession-adjusted-defensive-stats/
- Lee, M., Jo, G., Hong, M., Bauer, P., & Ko, S.-K. (2026). Contextual evaluation of individual contributions from pressing situations in football. MLSA 2025, CCIS 2833, 35–47. https://doi.org/10.1007/978-3-032-15165-0_3
- Low, B., Coutinho, D., Gonçalves, B., Rein, R., Memmert, D., & Sampaio, J. (2020). A systematic review of collective tactical behaviours in football using positional data. Sports Medicine, 50(2), 343–385. https://doi.org/10.1007/s40279-019-01194-7
- Merhej, C., Beal, R., Matthews, T., & Ramchurn, S. (2021). What happened next? Using deep learning to value defensive actions in football event-data. KDD '21. https://doi.org/10.1145/3447548.3467090
- Stats Perform (n.d.). How we measure pressure. https://www.statsperform.com/insights/how-we-measure-pressure/
- Toda, K., Teranishi, M., Kushiro, K., & Fujii, K. (2022). Evaluation of soccer team defense based on prediction models of ball recovery and being attacked: A pilot study. PLOS ONE, 17(1), e0263051. https://doi.org/10.1371/journal.pone.0263051
- Trainor, C. (2014). Defensive metrics: Measuring the intensity of a high press. StatsBomb (Hudl blog). https://www.hudl.com/blog/defensive-metrics-measuring-the-intensity-of-a-high-press
- Tweedale, A. (2024). Possession and territory, but too few chances created: Tottenham's final-third problems analysed. Opta Analyst. https://theanalyst.com/articles/tottenham-problems-chances-created
- Umemoto, R., & Fujii, K. (2023). Evaluation of team defense positioning by computing counterfactuals using StatsBomb 360 data. StatsBomb Conference 2023. https://blogarchive.statsbomb.com/uploads/2023/10/Evaluation-of-Team-Defense-Positioning-by-Computing-Counterfactuals-Using-StatsBomb-360-Data.pdf

## 4. Player evaluation

### State of the art (2024–2026)

**Action values.**
- Main models: VAEP (Decroos et al. 2019), xT (Singh n.d.), OBV (Hudl StatsBomb 2025), and EPV from tracking (Fernández et al. 2021).
- Design choices matter, for example the xT grid size (van Arem et al. 2025b).
- Validate an indicator separately from its model: face validity, split-half robustness (VAEP is only moderately robust, mostly because of shots), divergent validity and usefulness (Davis, Robberechts & Van Roy 2025).

**Plus-minus.**
- Reviewed by Hvattum (2019). Versions exist based on goals, xG and expected points (Kharrat et al. 2020).
- Plus-minus beat a VAEP-based rating on both reliability and forecast validity (Hvattum & Gelade 2021).
- Elo plus plus-minus forecasts better than either one alone (Arntzen & Hvattum 2021).
- RAPM has also been fitted on possession sequences (Bajons & Hornik 2024).

**Context.**
- Team strength confounds individual output; the Soccer Factor Model separates the two and defines skill and performance above replacement (Andorra & Göbel 2024).
- League strength:
  - a hierarchical Elo weighted 80% on the score and 20% on xG (Whitmore et al. 2026);
  - a Glicko rating that accounts for league strength (Shelopugin & Sirotkin 2026).
- Too few players change leagues to translate numbers directly between leagues (McIntosh & Beckmann 2025).

**Embeddings.**
- Role-aware ratings come from PlayeRank (Pappalardo et al. 2019), and style profiles from player vectors (Decroos & Davis 2020).
- A transformer that treats players as tokens, trained on per-match stats, beats the last-5-match mean at predicting next-match stats (Adjileye 2024).
- Large event models and next-event models support "what if he moved" transfer analysis (Mendes-Neves et al. 2024a, 2024b; Hong et al. 2025).

**Ageing.**
- Players peak at about 25–27; forwards peak earliest and keepers by about 27 (Dendir 2016; Säfvenberg et al. 2024).
- Forecasts can include uncertainty estimates (van Arem et al. 2025a).

### What we can build with our data

Our strongest method is **stint-based RAPM** from lineups, substitutions, red cards and goal minutes.
- Fit it on goals first, then on expected points from the in-play model.
- Use role priors and at least three seasons of data.
- Feed the ratings into a lineup-aware match model (Arntzen & Hvattum 2021).

We can also build:
- role-adjusted per-90 stats with shrinkage;
- the API-Football rating, once validated (Dendir 2016 used a similar composite rating);
- cross-league Elo;
- replacement level, age curves and player similarity.

We cannot build VAEP, xT, OBV, EPV, off-ball value or embeddings learned from event sequences.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Role-adjusted per-90 with shrinkage | How does a player compare with peers in his role? | Player stats, minutes, lineup grid | AVAILABLE_NOW | Raw per-90 | Split-half and season-to-season reliability | **P0** · H: player pages |
| API-Football rating | Is the rating informative? | Player ratings | AVAILABLE_NOW (black box) | Share of minutes | Reliability; gain in lineup model | **P1** · M |
| Goal RAPM from stints | What is a player's net goal impact? | Lineups, subs, red cards, goal minutes; 3+ seasons | AVAILABLE_NOW | Raw plus-minus; on/off | Reliability; forecast validity; ridge tuned by CV | **P1** · H |
| Expected-points and xG plus-minus | What is a player's impact on win probability or chances? | In-play model; match-level provider xG | xPoints: AVAILABLE_NOW. xG: APPROXIMABLE (match xG spread over minutes) | Goal RAPM | As for goal RAPM | **P2** · M–H |
| Lineup-aware match model | How do absences change the forecast? | Lineups, injuries, ratings | AVAILABLE_NOW | Team Elo; closing odds | Log loss on held-out seasons | **P1** · H |
| League and opponent normalisation | Is 0.4 per 90 worth the same in every league? | All fixtures, including European cups | AVAILABLE_NOW for teams; APPROXIMABLE for players (few movers) | Elo (Hvattum & Arntzen 2010); raw per-90 | Cross-league log loss; back-tests on movers | **P1** · H |
| Replacement level | How much better is he than a free alternative? | Ratings or RAPM; minutes | AVAILABLE_NOW | League average | Stability | **P2** · M |
| Age curves | What trajectory should we expect? | Birth dates (to confirm), minutes, ratings | AVAILABLE_NOW | Cross-sectional means (survivorship bias) | Error on next season | **P2** · M |
| Player similarity | Who plays like player X? | Role-adjusted per-90 vectors | AVAILABLE_NOW. Learned embeddings: APPROXIMABLE (about 20 stats) | Same-position neighbours | Self-retrieval across split seasons | **P2** (learned: P3) · M |
| VAEP, xT, OBV, EPV; sequence RAPM; EventGPT | What is each action worth? How would a player fit elsewhere? | x/y events (EPV needs tracking) | REQUIRES_EVENT_PROVIDER (EPV: REQUIRES_TRACKING_PROVIDER) | Box-score composites; RAPM | Face validity, robustness, divergent validity | **P3** (P2 with events) · H |

### Sources
- Adjileye, A. A. (2024). RisingBALLER: A player is a token, a match is a sentence. A path towards a foundational model for football players data analytics. StatsBomb Conference 2024; arXiv:2410.00943. https://arxiv.org/abs/2410.00943
- Andorra, A., & Göbel, M. (2024). Unveiling true talent: The Soccer Factor Model for skill evaluation. arXiv:2412.05911. https://arxiv.org/abs/2412.05911
- Arntzen, H., & Hvattum, L. M. (2021). Predicting match outcomes in association football using team ratings and player ratings. Statistical Modelling, 21(5), 449–470. https://doi.org/10.1177/1471082X20929881
- Bajons, R., & Hornik, K. (2024). Regularized adjusted plus-minus models for evaluating and scouting football (soccer) players using possession sequences. arXiv:2407.17832. https://arxiv.org/abs/2407.17832
- Davis, J., Robberechts, P., & Van Roy, M. (2025). How do we know a metric is good? A case study on VAEP. KU Leuven DTAI Sports Analytics Lab. https://dtai.cs.kuleuven.be/sports/blog/how-do-we-know-a-metric-is-good-a-case-study-on-vaep/
- Decroos, T., Bransen, L., Van Haaren, J., & Davis, J. (2019). Actions speak louder than goals: Valuing player actions in soccer. KDD '19, 1851–1861. https://doi.org/10.1145/3292500.3330758
- Decroos, T., & Davis, J. (2020). Player vectors: Characterizing soccer players' playing style from match event streams. ECML PKDD 2019, LNCS, 569–584. https://doi.org/10.1007/978-3-030-46133-1_34
- Dendir, S. (2016). When do soccer players peak? A note. Journal of Sports Analytics, 2(2), 89–105. https://doi.org/10.3233/JSA-160021
- Fernández, J., Bornn, L., & Cervone, D. (2021). A framework for the fine-grained evaluation of the instantaneous expected value of soccer possessions. Machine Learning, 110(6), 1389–1427. https://doi.org/10.1007/s10994-021-05989-6
- Hong, M., Lee, M., Jo, G., So, J.-H., Bauer, P., & Ko, S.-K. (2025). EventGPT: Capturing player impact from team action sequences using GPT-based framework. arXiv:2512.17266 (Hudl Performance Insights 2025). https://arxiv.org/abs/2512.17266
- Hudl StatsBomb (2025). On-Ball Value (OBV): Valuing player actions in football. https://www.hudl.com/blog/statsbomb-on-ball-value
- Hvattum, L. M. (2019). A comprehensive review of plus-minus ratings for evaluating individual players in team sports. International Journal of Computer Science in Sport, 18(1), 1–23. https://doi.org/10.2478/ijcss-2019-0001
- Hvattum, L. M., & Arntzen, H. (2010). Using ELO ratings for match result prediction in association football. International Journal of Forecasting, 26(3), 460–470. https://doi.org/10.1016/j.ijforecast.2009.10.002
- Hvattum, L. M., & Gelade, G. A. (2021). Comparing bottom-up and top-down ratings for individual soccer players. International Journal of Computer Science in Sport, 20(1), 23–42. https://doi.org/10.2478/ijcss-2021-0002
- Kharrat, T., McHale, I. G., & Peña, J. L. (2020). Plus–minus player ratings for soccer. European Journal of Operational Research, 283(2), 726–736. https://doi.org/10.1016/j.ejor.2019.11.026
- McIntosh, R., & Beckmann, T. (2025). Modelling player performance after potential transfers between leagues. Hudl Performance Insights 2025. https://static.hudl.com/craft/performance-insights-research-stage/2025/Modelling-player-performance-after-potential-transfers-between-leagues-Richard-McIntosh-Tobias-Beckmann.docx.pdf
- Mendes-Neves, T., Meireles, L., & Mendes-Moreira, J. (2024a). Estimating player performance in different contexts using fine-tuned large events models. arXiv:2402.06815. https://arxiv.org/abs/2402.06815
- Mendes-Neves, T., Meireles, L., & Mendes-Moreira, J. (2024b). Towards a foundation large events model for soccer. Machine Learning, 113(11–12), 8687–8709. https://doi.org/10.1007/s10994-024-06606-y
- Pappalardo, L., Cintia, P., Ferragina, P., Massucco, E., Pedreschi, D., & Giannotti, F. (2019). PlayeRank: Data-driven performance evaluation and player ranking in soccer via a machine learning approach. ACM TIST, 10(5). https://doi.org/10.1145/3343172
- Säfvenberg, R., Nordgaard, A., Lidmark Eriksson, O., Carlsson, N., & Lambrix, P. (2024). Age of peak performance among soccer players in Sweden. Sports Analytics (ISACE 2024), LNCS, 278–290. https://doi.org/10.1007/978-3-031-69073-0_24
- Shelopugin, A., & Sirotkin, A. (2026). Constructing football club ratings with league strength awareness using a modified Glicko model. Sports Analytics (ISACE 2026), LNCS 16610. https://doi.org/10.1007/978-3-032-27272-0_4
- Singh, K. (n.d.). Introducing Expected Threat (xT). https://karun.in/blog/expected-threat.html
- van Arem, K. W., Goes-Smit, F., & Söhl, J. (2025a). Forecasting the future development in quality and value of professional football players. Applied Sciences, 15, 8916. https://doi.org/10.3390/app15168916
- van Arem, K. W., Söhl, J., Bruinsma, M., & Jongbloed, G. (2025b). The trade-off between model flexibility and accuracy of the Expected Threat model in football. MathSport International 2025; arXiv:2511.09457. https://arxiv.org/abs/2511.09457
- Whitmore, J., et al. (2026). Opta Power Rankings explained: How our global football rating system works. Opta Analyst. https://theanalyst.com/articles/power-rankings-your-club-ranked
