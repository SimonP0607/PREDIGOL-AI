# A2: Possession value, phases, tracking, graphs, sequence and decision models

*Literature review, 25 Sep 2026. Every technique is classified against our data: API-Football v3 and Football-Data.co.uk, with no x/y event coordinates and no tracking data.*

**Legend.** Classifications: AVAILABLE_NOW, APPROXIMABLE (the table says how, and what is lost), REQUIRES_EVENT_PROVIDER, REQUIRES_TRACKING_PROVIDER. Priorities: P0 = before live, P1 = after backfill, P2 = important improvement, P3 = research/future. Value = product value (H/M/L).

**Bottom line.** None of the state of the art runs on our feeds. What we can build now is match-level: game-state timelines, in-game goal-hazard models, lineup plus-minus and box-score threat proxies. Each must beat Elo or Dixon–Coles and closing odds. All four requested papers exist and were verified; all are research-grade.

---

## 1. Possession value

### State of the art (2024–2026)

**Foundations.**
- **xT** values zones of a 16×12 grid by shoot/move probabilities (Singh 2019).
- **VAEP** values an action by its change in P(score) minus P(concede) over the next 10 actions (Decroos et al. 2019).
- **EPV** decomposes possession value from tracking data (Fernández et al. 2021).
- **OBV** fits separate goal-for and goal-against models on xG, with no possession history, so it does not absorb team strength (StatsBomb 2021).
- **Opta PV** is P(score in the next 10 s) (Whitmore 2021).
- **xT vs VAEP:** split-half stability is ρ 0.89 for xT vs 0.25 for VAEP (Van Roy et al. 2020).

**(a) Verified: Le Coz, Boustila & Imbach (2026), *Scientific Reports*.**
- **Model:** states are action type × zone. Durations use accelerated-failure-time models conditioned on distance and angle to goal, with the distribution family chosen per transition (the families differ). Temporal xT = P(goal within T s), computed by backward induction.
- **Data:** 537 StatsBomb open-data matches (Ligue 1, Euro 2020/2024).
- **Results:** Brier beats a fixed-mean-delay baseline at every horizon (0.0190 vs 0.0568 at 300 s). AUC is better only at 120–300 s. Standard xT keeps the better 300 s Brier (0.0152), so the authors reserve temporal xT for late-game decisions.
- **Limits:** no match-state or opponent covariates.

**(b) Verified: van Arem, Söhl, Bruinsma & Jongbloed (2026), arXiv:2604.21087.**
- **Error:** worst-case error across zones, bootstrapped from the Markov chain, is about lognormal in training size N and zone count M.
- **Tolerance:** experts set 0.0192 as the maximum acceptable error. At that level, fewer than 10% of players change scouting quartile, with probability 0.9.
- **Rule of thumb:** choose the finest grid meeting it. 2.48 M events support 10×8; 16×12 needs about 3.35 M events (~5.4 seasons). It builds on the error bound in van Arem et al. (2025).

**Risk and validation.**
- Overmeer et al. (2025) could not replicate EPV. They propose a state-pair benchmark and a split of passes into reward and risk.
- Forcher et al. (2025a) pair EPV with expected ball gain on tracking data.
- Davis et al. (2024, 2025) test whether an indicator is valid, not just whether the model fits: face validity, robustness, novelty, usefulness.
- On 918 Bundesliga matches, pre-match RPS was 0.194 for EPV, 0.199 for xG and 0.202 for Elo (Forcher et al. 2025b). The gain is small, and it needed tracking.

### What we can build with our data
Nothing at action level. We can build team threat features (box shots, shots on target, corners, and xG where offered) and a descriptive player box-score model. If event data is licensed: xT sized by van Arem's rule, then VAEP.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| xT | Threat added by moving the ball | x/y passes, carries, shots | REQUIRES_EVENT_PROVIDER | progressive-pass counts | error < 0.0192 (p = 0.9); split-half ρ | P3 (P2 if licensed) · M |
| VAEP | Value of every action | x/y event stream | REQUIRES_EVENT_PROVIDER | xT | calibration; robustness | P3 · M |
| OBV / Opta PV | Provider-computed action value | licence | REQUIRES_EVENT_PROVIDER | in-house xT | stability only (black box) | P3 · M |
| EPV; pass risk/reward (Power et al. 2017) | Value of the current state, including options not taken; pass risk vs gain | tracking (360 freeze frames partial) | REQUIRES_TRACKING_PROVIDER | VAEP; completion % × xT | calibration; pairwise benchmark | P3 · M |
| Temporal (semi-Markov) xT | P(goal within T seconds) | timestamped x/y events | REQUIRES_EVENT_PROVIDER | fixed-delay xT; standard xT | AUC and Brier per horizon | P3 · L–M |
| Team threat proxy | Which team created more danger | API-Football team stats (+xG); Football-Data shots, shots on target, corners | APPROXIMABLE: Poisson regression of goals on these stats. Lost: action credit, location, sequence | raw shots; Elo; closing odds | time-ordered RPS and log-loss | P0 · H |
| Player box-score contribution | Which per-90 actions track goal difference | API-Football player stats + minutes | APPROXIMABLE: ridge regression. Lost: context and quality; confounded by team and role | API rating; plus-minus (§6) | split-half reliability | P1 · M |

### Sources
- Singh, K. (2019). Introducing Expected Threat (xT). Blog. https://karun.in/blog/expected-threat.html
- Decroos, T. et al. (2019). Actions Speak Louder than Goals: Valuing Player Actions in Soccer. KDD. https://doi.org/10.1145/3292500.3330758
- Van Roy, M. et al. (2020). Valuing On-the-Ball Actions in Soccer: A Critical Comparison of xT and VAEP. AAAI-20 Workshop on AI in Team Sports. https://tomdecroos.github.io/reports/xt_vs_vaep.pdf
- Fernández, J., Bornn, L., Cervone, D. (2021). A framework for the fine-grained evaluation of the instantaneous expected value of soccer possessions. Machine Learning 110. https://doi.org/10.1007/s10994-021-05989-6
- StatsBomb (2021). Introducing On-Ball Value (OBV). https://statsbomb.com/articles/soccer/introducing-on-ball-value-obv/
- Whitmore, J. (2021). What Is Possession Value (PV)? Opta Analyst. https://theanalyst.com/articles/what-is-possession-value
- Le Coz, S., Boustila, F., Imbach, F. (2026). A Semi-Markov framework for modeling football possessions and temporal expected threat. Scientific Reports 16:22590. https://doi.org/10.1038/s41598-026-52938-1
- van Arem, K., Söhl, J., Bruinsma, M., Jongbloed, G. (2026). Model quality in football: Quantifying the quality of an Expected Threat model. arXiv. https://arxiv.org/abs/2604.21087
- van Arem, K. W. et al. (2025). The trade-off between model flexibility and accuracy of the Expected Threat model in football. MathSport International. https://arxiv.org/abs/2511.09457
- Overmeer, T., Janssen, T., Nuijten, W. (2025). Revisiting Expected Possession Value in Football: Introducing a Benchmark, U-Net Architecture, and Reward and Risk for Passes. arXiv. https://arxiv.org/abs/2502.02565
- Power, P. et al. (2017). "Not All Passes Are Created Equal": Objectively Measuring the Risk and Reward of Passes in Soccer from Tracking Data. KDD. https://doi.org/10.1145/3097983.3098051
- Forcher, L. et al. (2025a). The strategy tradeoff between risk and reward in soccer: Expected ball gain and expected possession value in Bundesliga. Int. J. Sports Sci. & Coaching. https://doi.org/10.1177/17479541251389831
- Forcher, L. et al. (2025b). AI in Bundesliga match analysis—EPV vs. xG to predict match outcomes. Frontiers in Sports and Active Living 7. https://doi.org/10.3389/fspor.2025.1713852
- Davis, J. et al. (2024). Methodology and evaluation in sports analytics: challenges, approaches, and lessons learned. Machine Learning 113. https://doi.org/10.1007/s10994-024-06585-0
- Davis, J., Robberechts, P., Van Roy, M. (2025). How Do We Know a Metric Is Good? A Case Study on VAEP. KU Leuven DTAI blog. https://dtai.cs.kuleuven.be/sports/blog/how-do-we-know-a-metric-is-good-a-case-study-on-vaep/

---

## 2. Tactical phases

### State of the art (2024–2026)

**The graph + Transformer paper. Verified: Li & Link (2026), arXiv:2606.09289 (TU Munich, v3).**
- **Labels:** three intentions (Invade Opponent Space, Keep Possession, Scoring) divided into six phases (Build Up, Progression, Counter Attack, Maintenance, Sustained Threat, Finishing).
- **Model (T-GAN):** a per-frame player-interaction graph, then a Transformer over time.
- **Data:** 7 Bundesliga TRACAB matches, one annotator, leave-one-match-out.
- **Results:** frame F1 0.87 for intentions and 0.76–0.79 for phases; tIoU (segment overlap) 0.67 and 0.57.
- **Findings:** a Transformer alone nearly matches on intentions; the graph helps mainly Counter Attack. Main confusions: Build Up vs Progression, and Counter Attack vs Progression.

**Earlier work.**
- FeatGRU: 80% agreement with experts (Biermann et al. 2025).
- CNN segmentation: F1 0.76 (Bauer, Anzer & Shaw 2023).
- Counterpressing detection: AUC 0.874 (Bauer & Anzer 2021).
- Few-label counterattack detection: AUC 0.912 on 2 matches (Fassmeyer et al. 2021).

**Provider rules.**
- SkillCorner (2025) builds phases from tracking plus Wyscout events. Build up requires the ball in the team's own third, with the carrier under pressure or opponents positioned high. Finish requires the opponent's back line near the box. Direct is a long ball of 32 m or more. Quick Break is a regain in the opponent's half followed by fast progress. Chaotic is fewer than 3 passes and under 5 s.
- Opta's sequences and direct attacks are event-only (Whitmore 2021).

**Event-only vs tracking.**
- **x/y events can approximate:** possession segmentation; Build Up vs Progression (zone, forward progress); Counter Attack (regain location, speed to the final third); Finishing (shots, box entries); Sustained Threat (repeated final-third entries); Maintenance (many passes, little progress).
- **They cannot capture:** pressure on the carrier, defensive-line height, compactness, opponent disorganisation (the graph's Counter Attack signal), off-ball runs, precise phase boundaries.
- **Inference:** event rules would do worst at separating Counter Attack from Progression.

### What we can build with our data
Phases are impossible without possession sequences. Two things are possible: game-state segmentation from goal and red-card minutes, which enables context adjustment (Skripnikov et al. 2025), and season-level style indices.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Tracking phase and counterpress models (T-GAN, FeatGRU, XGBoost) | Which phase is active, frame by frame | tracking + events + expert labels | REQUIRES_TRACKING_PROVIDER | rules (zone + ball direction); Random Forest; Transformer alone | multi-annotator agreement; match hold-out; tIoU | P3 · M |
| Provider phases (SkillCorner) | Same, supplied by provider | licence | REQUIRES_TRACKING_PROVIDER | event rules | video spot-checks | P3 (P2 if licensed) · M |
| Event-rule phases (Opta style) | How each possession is played | x/y events | REQUIRES_EVENT_PROVIDER | possession % | agreement with tracking labels | P3 · M |
| Game-state segmentation | Minutes leading, level or trailing, and at 11 v 10 | API-Football goal and card minutes | AVAILABLE_NOW | final score only | reconcile with half-time and full-time scores | P0 · H |
| Team style indices | Possession-based vs direct | possession, passes, accuracy, inside/outside-box shots, corners | APPROXIMABLE: z-scores adjusted for game state. Lost: phases, timing, location | league means | season-to-season stability | P1 · M |

### Sources
- Li, Y., Link, D. (2026). Intention Driven Identification of In-Possession Match Phases in Association Football through Temporal Graph Learning. arXiv. https://arxiv.org/abs/2606.09289
- Biermann, H. et al. (2025). Contextualization of soccer analysis with tactical periodization and machine learning. Data Mining and Knowledge Discovery 39. https://doi.org/10.1007/s10618-025-01092-9
- Bauer, P., Anzer, G., Shaw, L. (2023). Putting team formations in association football into context. Journal of Sports Analytics 9. https://doi.org/10.3233/JSA-220620
- Bauer, P., Anzer, G. (2021). Data-driven detection of counterpressing in professional football. Data Mining and Knowledge Discovery 35. https://doi.org/10.1007/s10618-021-00763-7
- Fassmeyer, D. et al. (2021). Toward Automatically Labeling Situations in Soccer. Frontiers in Sports and Active Living 3. https://doi.org/10.3389/fspor.2021.725431
- SkillCorner (2025). Phases of Play – CSV Specifications. https://26560301.fs1.hubspotusercontent-eu1.net/hubfs/26560301/Guides/Phases%20of%20Play/20250216%20-%20Phases%20of%20Play%20CSV%20Specifications.pdf
- Whitmore, J. (2021). Sequences and Possessions in Football. Opta Analyst. https://theanalyst.com/articles/possessions-and-sequences-in-football
- Skripnikov, A. V., Cemek, A., Gillman, D. (2025). Leveraging minute-by-minute soccer match event data to adjust team's offensive production for game context. JQAS. https://doi.org/10.1515/jqas-2024-0162

---

## 3. Spatial and tracking analytics

### State of the art (2024–2026)
- **Pitch control** (Spearman et al. 2017): time-to-intercept plus a control rate. It predicts the receiving team 81% of the time and the actual receiver 68%. Extensions:
  - Off-ball scoring opportunity (OBSO; Spearman 2018)
  - Space creation (Fernández & Bornn 2018)
  - Player-specific top speeds (da Silva et al. 2025)
  - Transition space value (Ogawa et al. 2025)
- **Pressure:**
  - Pressing intensity (Bekkers 2025)
  - Minimum arrival time (Narizuka et al. 2026): higher pressure means less progress and more losses.
- **Passing lanes:**
  - xPass completion model, AUC 93.4% (Anzer & Bauer 2022)
  - Temporal graph networks for reception probability (Rahimian et al. 2026)
  - MPNN picks the receiver 75.8% of the time vs 27.6% for "nearest teammate", but trained on completed passes only (Masella et al. 2026)
- **Packing:**
  - Defenders bypassed relate to goals and wins (Rein et al. 2017)
  - Line Bypass Score (Karakuş & Arkadaş 2026)
- **Shape:**
  - 27 collective variables (Low et al. 2020)
  - Shape graphs, 69% agreement with provider labels (Brandes et al. 2025)
- **Movement:**
  - SkillCorner's 10 off-ball run types (May 2023)
  - Body orientation (Arbués-Sangüesa et al. 2020)
- **Open data:** IDSSE (Bassek et al. 2025)

### What we can build with our data
Only declared formations and grid roles, plus location-free defensive-activity ratios.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Pitch/space control, OBSO | Who controls which space, and its value | tracking | REQUIRES_TRACKING_PROVIDER | Voronoi; nearest player | receiver accuracy; calibration | P3 · M |
| Pressure / pressing intensity | Pressure on the ball carrier | tracking (StatsBomb "Pressure" events are coarse) | REQUIRES_TRACKING_PROVIDER | distance to nearest defender | predicts ball losses | P3 · M |
| Pass difficulty, receiver availability | Which passes were on, and how risky | tracking | REQUIRES_TRACKING_PROVIDER | nearest teammate; logistic regression | top-k accuracy, AUC; include failed passes | P3 · M |
| Packing / line breaks | Defenders bypassed per pass | tracking or freeze frames | REQUIRES_TRACKING_PROVIDER | progressive passes | link to box entries and goals | P3 · M |
| Compactness, width/depth, line height | Team shape | tracking | REQUIRES_TRACKING_PROVIDER | declared formation | reliability; xG conceded | P3 · M |
| Runs, orientation, velocity/acceleration | Movement quality and load | tracking/pose | REQUIRES_TRACKING_PROVIDER | none | provider validation | P3 · M |
| Declared formation and grid roles | Nominal shape | API-Football lineups | AVAILABLE_NOW | none | consistency checks | P1 · M |
| Location-free PPDA | How much a team disrupts opponent passing | opponent passes ÷ (tackles + interceptions + fouls) | APPROXIMABLE: from match stats. Lost: pitch zone, the core of pressing | possession % | season-to-season stability | P2 · L |

### Sources
- Spearman, W. et al. (2017). Physics-Based Modeling of Pass Probabilities in Soccer. MIT SSAC. https://static.hudl.com/craft/downloads/SSAC17-Physics-Based-Modeling-of-Pass-Probabilities-in-Soccer.pdf
- Spearman, W. (2018). Beyond Expected Goals. MIT SSAC. (Verified via citing work, e.g. https://arxiv.org/abs/2206.01899)
- Fernández, J., Bornn, L. (2018). Wide Open Spaces: A statistical technique for measuring space creation in professional soccer. MIT SSAC. https://www.sloansportsconference.com/research-papers/wide-open-spaces-a-statistical-technique-for-measuring-space-creation-in-professional-soccer
- da Silva, M. F. et al. (2025). The interplay between pitch control and top speed in soccer considering the stamina factor. Scientific Reports 15:38799. https://doi.org/10.1038/s41598-025-22778-6
- Ogawa, Y., Umemoto, R., Fujii, K. (2025). Space evaluation at the starting point of soccer transitions. arXiv. https://arxiv.org/abs/2505.14711
- Bekkers, J. (2025). Pressing Intensity: An Intuitive Measure for Pressing in Soccer. arXiv. https://arxiv.org/abs/2501.04712
- Narizuka, T. et al. (2026). Quantifying defensive pressure on the ball carrier in soccer based on minimum arrival time. arXiv. https://arxiv.org/abs/2606.09452
- Anzer, G., Bauer, P. (2022). Expected passes. Data Mining and Knowledge Discovery 36. https://doi.org/10.1007/s10618-021-00810-3
- Rahimian, P., Davis, J., Toka, L. (2026). Temporal Graph Network Framework for Quantifying Pass Reception Probabilities Against Defensive Structures. Machine Learning 115. https://doi.org/10.1007/s10994-025-06935-6
- Masella, G. et al. (2026). Evaluating passing decision-making in professional football: An enhanced MPNN approach to Receiver Selection. arXiv. https://arxiv.org/abs/2605.25696
- Rein, R., Raabe, D., Memmert, D. (2017). "Which pass is better?" Novel approaches to assess passing effectiveness in elite soccer. Human Movement Science 55. https://doi.org/10.1016/j.humov.2017.07.010
- Karakuş, O., Arkadaş, H. (2026). Structural Pass Analysis in Football: Learning Pass Archetypes and Tactical Impact from Spatio-Temporal Tracking Data. arXiv. https://arxiv.org/abs/2603.28916
- Low, B. et al. (2020). A Systematic Review of Collective Tactical Behaviours in Football Using Positional Data. Sports Medicine 50. https://doi.org/10.1007/s40279-019-01194-7
- Brandes, U. et al. (2025). Shape graphs and the instantaneous inference of tactical positions in soccer. npj Complexity 2:25. https://doi.org/10.1038/s44260-025-00047-x
- May, E. (2023). Game Intelligence: Off-Ball Run Types. SkillCorner. https://skillcorner.com/articles/game-intelligence-off-ball-run-types
- Arbués-Sangüesa, A. et al. (2020). Using Player's Body-Orientation to Model Pass Feasibility in Soccer. CVPR Workshops. https://arxiv.org/abs/2004.07209
- Bassek, M. et al. (2025). An integrated dataset of spatiotemporal and event data in elite soccer. Scientific Data 12:195. https://doi.org/10.1038/s41597-025-04505-y

---

## 4. Graph Neural Networks

### What a GNN solves better than simple baselines, and with what data
A GNN earns its place when three things hold:
- the input is an unordered set of interacting agents (22 players plus the ball);
- the answer depends on where they stand relative to each other (who can receive, which lane is blocked);
- the output is per player or per situation.

That requires every player's position, from tracking or freeze frames.

**Evidence.**
- TacticAI receiver prediction, top-3 accuracy (random split): CNN 0.364, MPNN 0.723, GATv2 0.748, symmetry-aware GATv2 0.782.
- An MPNN beats a LambdaMART ranker at receiver prediction, 75.8% vs 44.6% top-1.
- In phase detection, the graph mainly helps Counter Attack.

Our data has no positions and no player-to-player interactions, so a GNN has nothing relational to learn.

### State of the art (2024–2026)
**TacticAI (Wang et al. 2024).** Trained on 7,176 tracked Liverpool corners. It predicts the receiver and whether a shot follows, and generates better player placements. Experts preferred its suggestions in 45 of 50 cases.

**Verified: Lin, Chen & Liu (2026), *Scientific Reports* (GIRL-GNN).**
- **Graph:** player, ball and zone nodes per decision moment. Edges are passing lanes, carrying options and pressure.
- **Policy:** a hierarchy of intent then action, plus a feasibility check (timing, visibility, pressure, offside).
- **Scoring:** ΔEPV − xG against + cohesion + log P(feasible).
- **Learning:** risk-averse offline RL, kept close to observed behaviour.
- **Evaluation:** 7 IDSSE matches, leave-one-match-out.
- **Results:** ΔxT +0.04 to +0.08 over baselines, but the paper's own models estimate these for actions never played. Analysts preferred the model's choice 61% of the time (κ = 0.51).
- **Availability:** data on request.
- This is also the §6 paper.

**Others.**
- A counterattack-success GNN with open code (Bekkers & Sahasrabudhe 2024).
- HIGFormer (Wang et al. 2025): 52.2% outcome accuracy, with no odds baseline and no probabilistic score.
- Passing networks (Buldú et al. 2018).

### What we can build with our data
No passing networks: we have no passer→receiver pairs. A lineup-grid graph is possible, but it is unlikely to beat gradient boosting with Elo and odds.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Passing-network metrics | Who links play | passer→receiver pairs | REQUIRES_EVENT_PROVIDER | pass counts | stability; value beyond totals | P3 · L–M |
| GNN receiver / pass models (MPNN, TGN) | Probability of each passing option | tracking | REQUIRES_TRACKING_PROVIDER | nearest teammate; XGBoost; pitch control | top-k accuracy, AUC, calibration | P3 · M |
| Symmetry-aware set-piece GNN (TacticAI) | Receiver, shot, better set-ups | tracking | REQUIRES_TRACKING_PROVIDER | non-equivariant GNN; XGBoost | time-based split; blind expert review | P3 · M |
| Player/ball/zone graph + RL (GIRL-GNN) | Best feasible, risk-aware action | tracking + events | REQUIRES_TRACKING_PROVIDER | observed action; greedy ΔEPV; rules | off-policy evaluation; other competitions | P3 · M |
| Lineup graph for outcomes | Match result | lineups, grid, player stats | APPROXIMABLE: grid neighbours as edges. Lost: in-match interactions | closing odds; Elo / Dixon–Coles | RPS vs de-margined closing odds | P3 · L |

### Sources
- Wang, Z. et al. (2024). TacticAI: an AI assistant for football tactics. Nature Communications 15:1906. https://doi.org/10.1038/s41467-024-45965-x
- Lin, J., Chen, F., Liu, J. (2026). A graph-integrated reinforcement learning framework with graph neural networks for tactical decision modeling in professional football. Scientific Reports 16:26974. https://doi.org/10.1038/s41598-026-50061-9
- Bekkers, J., Sahasrabudhe, A. (2024). A Graph Neural Network deep-dive into successful counterattacks. arXiv (MIT SSAC 2023). https://arxiv.org/abs/2411.17450
- Wang, L. et al. (2025). Player-Team Heterogeneous Interaction Graph Transformer for Soccer Outcome Prediction. KDD. https://arxiv.org/abs/2507.10626
- Buldú, J. M. et al. (2018). Using Network Science to Analyse Football Passing Networks: Dynamics, Space, Time, and the Multilayer Nature of the Game. Frontiers in Psychology 9:1900. https://doi.org/10.3389/fpsyg.2018.01900
- Also cited: Masella et al. and Rahimian et al. (2026) (§3); Li & Link (2026) (§2).

---

## 5. Transformers and sequence models

### State of the art (2024–2026)
- **Event sequences:**
  - Seq2Event (Transformer or RNN; Simpson et al. 2022).
  - Large Events Model, which simulates matches (Mendes-Neves et al. 2024).
  - GPT-style player-conditioned transfer simulation (Hong et al. 2025, 2026).
  - Cheaper path signatures beat a Transformer benchmark (Hirnschall & Bajons 2025).
- **Tracking:** TranSPORTmer (Capellera et al. 2024).
- **At scale:** Stats Perform's axial Transformer (58,501 training games) forecasts per-player in-game totals. It is validated only by calibration, "given the unavailability of existing baseline models" (Horton & Lucey 2025).
- **Match-level timing (our data):**
  - Goals become likelier as a match goes on and tend to cluster (Ayana et al. 2025).
  - A calibrated Bayesian win-probability model (Robberechts et al. 2021).
  - A Markov model for substitution timing (Hirotsu & Wright 2002).

**Model families compared.**

| Family | Data needs (indicative) | Interpretability | Validation |
|---|---|---|---|
| RNN | hundreds to thousands of matches | low | next-event log-loss; expert agreement |
| Transformer | largest (many seasons) | low; attention ≠ explanation | must beat Markov and path-signature baselines on time-ordered splits; counterfactuals unverifiable |
| Temporal Graph Network | timestamped interactions between players (tracking or passes) | low to medium | per-edge calibration; match hold-out |
| Semi-Markov / hazard | timestamps plus a small state space; fine on sparse data | high | Brier and AUC per horizon; per-minute calibration |

### What we can build with our data
A match has only about 10–20 timestamped events (goals, cards, substitutions, VAR). That is too few for Transformers. We can build a goal-hazard or semi-Markov model over score states (the match-level analogue of temporal xT) and match-history models. Both must beat Dixon–Coles, Elo and closing odds.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Next-event Transformer / Large Events Model | What happens next | x/y events | REQUIRES_EVENT_PROVIDER | Markov chain; path signatures | held-out-season log-loss | P3 · M |
| GPT-style transfer simulation | Performance at another club | multi-season events | REQUIRES_EVENT_PROVIDER | context-adjusted per-90 stats | backtest on real transfers | P3 · M |
| Trajectory Transformer / TGN | Future movement; pass probabilities | tracking | REQUIRES_TRACKING_PROVIDER | constant velocity; static GNN | displacement error; calibration | P3 · L |
| In-game goal hazard / score-state model | P(next goal) and P(result) as the match unfolds | event minutes, results, pre-match odds | AVAILABLE_NOW | constant-rate Poisson from odds; Dixon–Coles | per-minute Brier and log-loss | P1 (P0 if in-play) · H |
| Pre-match player action counts | Expected shots and tackles per player | player stats, minutes, lineups | APPROXIMABLE: Poisson / negative-binomial on player history. Lost: in-game updating, interactions | rolling per-90 × expected minutes | Poisson deviance, time-ordered | P2 · M |
| Sequence model over match histories | Changing team strength | results, team stats, odds | AVAILABLE_NOW | Elo; Dixon–Coles; closing odds | RPS vs closing odds | P2 · M |

### Sources
- Simpson, I. et al. (2022). Seq2Event: Learning the Language of Soccer Using Transformer-based Match Event Prediction. KDD. https://doi.org/10.1145/3534678.3539138
- Mendes-Neves, T., Meireles, L., Mendes-Moreira, J. (2024). Towards a foundation large events model for soccer. Machine Learning 113. https://doi.org/10.1007/s10994-024-06606-y
- Hong, M. et al. (2025). EventGPT: Capturing Player Impact from Team Action Sequences Using GPT-Based Framework. arXiv. https://arxiv.org/abs/2512.17266
- Hong, M. et al. (2026). Modeling Matches as Language: A Generative Transformer Approach for Counterfactual Player Valuation in Football. ECML-PKDD (accepted). https://arxiv.org/abs/2603.15212
- Hirnschall, D., Bajons, R. (2025). The path to a goal: Understanding soccer possessions via path signatures. arXiv. https://arxiv.org/abs/2508.12930
- Capellera, G. et al. (2024). TranSPORTmer: A Holistic Approach to Trajectory Understanding in Multi-Agent Sports. ACCV. https://arxiv.org/abs/2410.17785
- Horton, M., Lucey, P. (2025). Large-Scale In-Game Outcome Forecasting for Match, Team and Players in Football using an Axial Transformer Neural Network. arXiv. https://arxiv.org/abs/2511.18730
- Ayana, G. et al. (2025). Temporal dynamics of goal scoring in soccer. arXiv. https://arxiv.org/abs/2501.18606
- Robberechts, P., Van Haaren, J., Davis, J. (2021). A Bayesian Approach to In-Game Win Probability in Soccer. KDD. https://doi.org/10.1145/3447548.3467194
- Dixon, M. J., Coles, S. G. (1997). Modelling Association Football Scores and Inefficiencies in the Football Betting Market. JRSS C 46. https://doi.org/10.1111/1467-9876.00065
- Hirotsu, N., Wright, M. (2002). Using a Markov process model of an association football match to determine the optimal timing of substitution and tactical decisions. JORS 53. https://doi.org/10.1057/palgrave/jors/2601254
- Also cited: Le Coz et al. (2026) (§1); Biermann et al. (2025) and Li & Link (2026) (§2).

---

## 6. Counterfactual and decision models

### State of the art (2024–2026)
**Event data.**
- A team model of decisions (an MDP) learned from events answers "what-if" questions. It suggests teams should shoot more from a few spots outside the box (Van Roy et al. 2021, 2023).
- un-xPass rewards valuable but atypical passes, using StatsBomb 360 data (Robberechts et al. 2023).
- Hierarchical Bayesian xG reallocates shots between players (Mahmudlu et al. 2025).

**Tracking data.**
- EPV scores the options a player did not choose.
- Multi-agent RL values off-ball players (Nakahara et al. 2023).
- Graph RL for corners (Groom et al. 2026) raises expected first-contact shot probability by +0.068 per test corner over the observed set-up. The score comes from a frozen GNN (3,223 Premier League corners), and the policy beats random search in 94.2% of corners at matched compute. Defenders do not react, and nothing was tested on the pitch.
- The RL + GNN model of value, risk and feasibility is GIRL-GNN (§4).

**Shared limitation.** A counterfactual outcome is never observed. Evaluation is therefore model-on-model or expert preference. Classified as research/future.

### What we can build with our data
- **Lineup counterfactuals** via regularised plus-minus, from lineups and minutes of substitutions, goals and red cards (Kharrat et al. 2020; Hvattum 2019).
- **Substitution-timing analysis.**

Both are observational, not causal. Closing odds are usually set after lineups are announced, so they are the baseline to beat.

### Techniques table
| Technique | Question answered | Data required | Classification | Baseline to beat | Validation | Priority |
|---|---|---|---|---|---|---|
| Shoot-vs-pass decision model | Would shooting more pay? | x/y events | REQUIRES_EVENT_PROVIDER | xG-threshold rule | sensitivity; out-of-season test | P3 · M |
| Alternative passes (un-xPass) | Was a better pass available? | x/y events + 360 freeze frames, or tracking | REQUIRES_EVENT_PROVIDER / REQUIRES_TRACKING_PROVIDER | completion %; xT gain | per-component calibration | P3 · M |
| Offline / graph RL (GIRL-GNN, corner RL) | Best feasible action given value and risk | tracking + events | REQUIRES_TRACKING_PROVIDER | observed action; greedy ΔEPV; random search | off-policy evaluation; blind expert review | P3 · M |
| Player-swap shot counterfactual | Player B's output on player A's chances | shot-level x/y | REQUIRES_EVENT_PROVIDER | league-average xG | posterior checks | P3 · L–M |
| Lineup counterfactual (plus-minus) | Effect of starting X instead of Y | lineups, substitutions, goal/card minutes, odds | AVAILABLE_NOW (goal difference, expected points). xG version APPROXIMABLE: match xG spread over stints. Lost: when chances occurred | no-lineup team model; closing odds | out-of-sample goal difference per stint | P1 · H |
| Substitution timing | When does a change raise P(win) | event minutes + hazard model | AVAILABLE_NOW (descriptive); effects confounded | current practice | backtest by game state | P2 · M |

### Sources
- Van Roy, M. et al. (2021). Leaving Goals on the Pitch: Evaluating Decision Making in Soccer. MIT SSAC. https://arxiv.org/abs/2104.03252
- Van Roy, M. et al. (2023). A Markov Framework for Learning and Reasoning About Strategies in Professional Soccer. JAIR 77. https://doi.org/10.1613/jair.1.13934
- Robberechts, P., Van Roy, M., Davis, J. (2023). un-xPass: Measuring Soccer Player's Creativity. KDD. https://doi.org/10.1145/3580305.3599924
- Mahmudlu, M., Karakuş, O., Arkadaş, H. (2025). What If They Took the Shot? A Hierarchical Bayesian Framework for Counterfactual Expected Goals. arXiv. https://arxiv.org/abs/2511.23072
- Nakahara, H. et al. (2023). Action valuation of on- and off-ball soccer players based on multi-agent deep reinforcement learning. IEEE Access. https://doi.org/10.1109/ACCESS.2023.3336425
- Groom, S. et al. (2026). Maximising the Set-Piece Return: Optimising Football Corner Tactics with Graph Reinforcement Learning. arXiv. https://arxiv.org/abs/2606.06353
- Kharrat, T., McHale, I. G., López Peña, J. (2020). Plus–minus player ratings for soccer. European Journal of Operational Research 283. https://doi.org/10.1016/j.ejor.2019.11.026
- Hvattum, L. M. (2019). A comprehensive review of plus-minus ratings for evaluating individual players in team sports. IJCSS 18. https://doi.org/10.2478/ijcss-2019-0001
- Also cited: Lin et al. (2026) and Wang et al. (2024) (§4); Hirotsu & Wright (2002) (§5).

---

## Verification notes
All sources were opened at the publisher, on arXiv, or via PubMed, Crossref or ML Anthology. Exceptions:
- Rahimian et al. (2026): checked on ML Anthology (Springer rate-limited).
- Spearman (2018): confirmed via papers that cite it.
- Hirotsu & Wright (2002): bibliographic record only.
- API-Football documentation: behind Cloudflare, so our data description follows the brief.
- Football-Data columns, including closing odds: checked at https://www.football-data.co.uk/notes.txt.
