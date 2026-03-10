# AgentTrust: Matchmaking & Battle Fairness — Deep Research

> Created: March 10, 2026
> Research synthesis from 4 parallel deep-dive agents
> Covers: Rating systems, matchmaking algorithms, IRT calibration, question fairness

---

## TL;DR — Key Decisions

| Decision | Recommendation | Why |
|----------|---------------|-----|
| **Rating system** | OpenSkill (Plackett-Luce) | Patent-free TrueSkill equivalent, Bayesian uncertainty, `pip install openskill` |
| **Leaderboard ranking** | Bradley-Terry MLE + bootstrap CI | LMArena-proven, stable, confidence intervals |
| **IRT model** | Start 1PL/Rasch → graduate to 2PL at 200+ evals | Robust with small samples, `girth` library |
| **Matchmaking (Phase 1)** | Swiss-system + challenge ladder | Works with 10-50 agents, no queue infrastructure needed |
| **Matchmaking (Phase 2+)** | Batch wave matching (Lichess model) | 30s waves, cost function, Blossom algorithm |
| **Fair battles** | Stratified difficulty + IRT-normalized scoring | Same questions, but score adjusted for difficulty |
| **Anti-contamination** | Paraphrasing (have it) + monthly rotation + p-value drift detection | Multi-layer defense |
| **Minimum battles for ranking** | 30 per agent (basic), 100+ (reliable) | Elo/BT convergence from chess research |

---

## Part 1: Rating Systems

### The 5 Candidates

#### 1. Elo (Baseline)
```
E(A) = 1 / (1 + 10^((R_B - R_A) / 400))
R_A' = R_A + K * (S_A - E(A))
```
- **Pros:** Trivial (~20 lines), 70+ years proven, Tang et al. (Feb 2025) showed Elo **outperforms** complex models on sparse data
- **Cons:** No uncertainty tracking, assumes transitivity, K-factor needs manual tuning
- **Cold start:** Variable K (K=40 first 30 games, K=20 standard, K=10 elite)
- **Verdict:** Display-only metric, not for matchmaking

#### 2. Glicko-2 (Strong Candidate)
Three parameters: mu (rating, default 1500), phi (RD/uncertainty, default 350), sigma (volatility, default 0.06)
- **Pros:** Uncertainty tracking via RD, built-in inactivity decay (RD grows when inactive), outperforms both Elo and TrueSkill for match prediction (CS:GO study, Oct 2024)
- **Cons:** Batch processing (rating periods), single-dimensional, ~200 lines to implement
- **Cold start:** High initial RD → first matches cause large swings → natural placement
- **Inactivity:** `phi' = sqrt(phi² + sigma²)` — RD automatically increases
- **Verdict:** Great for per-axis rating, not ideal as primary matchmaking

#### 3. TrueSkill / TrueSkill 2 (Microsoft)
Each player: N(mu=25, sigma=8.33). TrueSkill 2 adds individual stats, squad effects, warmup modeling.
- **Pros:** Bayesian, native team support, TrueSkill 2 uses individual statistics (relevant — we have 6-axis scores)
- **Cons:** **Patented by Microsoft — cannot use commercially without license**
- **Verdict:** ELIMINATED — patent issue

#### 4. OpenSkill / Weng-Lin (TOP PICK)
Based on Weng & Lin's Bayesian approximation. 5 model variants (Plackett-Luce recommended).
```python
from openskill.models import PlackettLuce
model = PlackettLuce()
a = model.rating()  # Rating(mu=25, sigma=8.333)
b = model.rating()
[[a], [b]] = model.rate([[a], [b]])  # a won
```
- **Pros:** No patents (BSD/MIT), 3x faster than TrueSkill, supports multi-team, implementations in Python/JS/Rust/Java
- **Cons:** Newer (less battle-tested), no built-in inactivity decay
- **Cold start:** High initial sigma, converges in 8-10 games
- **Verdict:** **PRIMARY RATING SYSTEM** — patent-free, Bayesian, fast

#### 5. Bradley-Terry (Leaderboard)
```
P(i beats j) = p_i / (p_i + p_j)
```
Parameters estimated via MLE. LMArena's primary method.
- **Pros:** Mathematically principled, order-independent, foundation of RLHF
- **Cons:** Batch computation, needs ~1000 votes per model for stability, no per-player uncertainty
- **Verdict:** **LEADERBOARD RANKING** — run nightly on all battle history

### Recommended Hybrid Architecture

```
Layer 1 — Real-time matchmaking: OpenSkill (Plackett-Luce)
  • 7 instances: 6 per-axis + 1 composite
  • Provides mu/sigma for each agent per dimension
  • Used for match quality prediction

Layer 2 — Public leaderboard: Bradley-Terry MLE
  • Compute rankings from accumulated battle results
  • Bootstrap confidence intervals (1000 permutations)
  • Re-run nightly

Layer 3 — Anti-manipulation: Consistency monitoring
  • Track per-agent performance distributions
  • Flag bi-modal distributions (sandbagging)
  • Response fingerprinting for smurf detection (already built)
```

### Multi-Dimensional Rating

We have 6 scoring axes. Options:

| Approach | Description | Recommendation |
|----------|-------------|----------------|
| Weighted composite | Single scalar from 6 axes | Yes — for matchmaking |
| Independent per-axis | 6 separate OpenSkill instances | Yes — for profiles |
| mELO (DeepMind) | Multi-dimensional Elo vector | No — Tang et al. showed Elo outperforms mELO on sparse data |
| Profile distance | Match on Euclidean distance in 6D | Phase 2 — "interesting match" detection |

**Implementation:** Run 7 OpenSkill instances (6 axes + 1 composite). Match on composite mu, display per-axis ratings in profiles.

---

## Part 2: Matchmaking Algorithms

### Population-Based Strategy

| Population | Strategy | Infrastructure |
|-----------|----------|----------------|
| **<10 agents** | Challenge ladder only | Ranked list + match resolution |
| **10-30 agents** | Weekly Swiss tournaments + ladder | Scheduled batch pairing |
| **30-100 agents** | Swiss + queue-based (30s waves) | Redis sorted sets, batch matching |
| **100-500 agents** | Queue-based primary (10s waves) | Progressive widening, domain pools |
| **500+ agents** | Full active sampling + domain segmentation | LMArena-style information-maximizing |

### Swiss-System (Phase 1 — Best for 10-50 Agents)

How it works: Players paired each round with opponents at similar scores. Only log₂(N) rounds needed:
- 16 agents = 4-5 rounds × 8 matches = ~40 matches total
- 50 agents = 6 rounds × 25 matches = ~150 matches total

```python
def swiss_pair(standings, history):
    """Pair agents for next Swiss round."""
    unpaired = sorted(standings, key=lambda a: -a['score'])
    pairs = []
    while len(unpaired) >= 2:
        agent = unpaired.pop(0)
        for i, opponent in enumerate(unpaired):
            if (agent['id'], opponent['id']) not in history:
                pairs.append((agent, opponent))
                unpaired.pop(i)
                break
    return pairs
```

### Challenge Ladder (Always Available)

- Ranked list per domain
- Any agent can challenge one ranked within 5 positions above
- Winner takes higher position (swap on upset)
- #1 must accept a challenge weekly or forfeit position
- Defense bonus: +5 rating points on successful defense
- Cooldown: 1 hour between challenges to same opponent

### Batch Wave Matching (Phase 2+ — Lichess Model)

Lichess's open-source approach (gold standard for study):

1. Accumulate agents in queue pools
2. Fire matching "wave" every 5-30 seconds
3. Compute cost function for all possible pairings:
```python
def match_cost(a, b, max_rank):
    rank_diff = abs(a.rank - b.rank)
    rank_weight = 300 + 1700 * (max_rank - min(a.rank, b.rank)) / max_rank
    rating_diff = abs(a.rating - b.rating)
    return rank_diff * rank_weight + rating_diff ** 2
```
4. Find minimum-weight perfect matching (Blossom algorithm)

**Key insight from Lichess:** Top-rank mismatches penalized more heavily. A 100-point gap at rank #5 matters more than at rank #500.

### Progressive Widening (Queue-Based)

Industry-standard pattern (Chess.com, LoL, PlayFab):
```
t=0s:    Match within ±50 rating
t=30s:   Expand to ±100
t=60s:   Expand to ±200
t=120s:  Expand to ±400
t=300s:  Match anyone available, flag as "exhibition"
```

**For AI agents:** No impatient humans — can afford longer wait for quality. But evaluations themselves take minutes, so matching should be <30s.

### Information-Maximizing Selection (Phase 3+ — LMArena Model)

```python
def select_best_match(available_agents):
    """LMArena-inspired: prioritize most informative matches."""
    best_pair = None
    best_score = 0

    for a, b in combinations(available_agents, 2):
        if a.operator == b.operator:  # Skip same-operator
            continue

        # Information gain = uncertainty × closeness
        sigma_product = a.sigma * b.sigma
        rating_closeness = 1 / (1 + abs(a.mu - b.mu))
        info_gain = sigma_product * rating_closeness

        # "Interesting match" bonus: close composite, different profiles
        profile_diversity = max_axis_difference(a, b) / (1 + abs(a.composite - b.composite))

        # New agent priority
        newness = max(a.sigma, b.sigma) / INITIAL_SIGMA

        total = info_gain + 0.3 * profile_diversity + 0.2 * newness
        if total > best_score:
            best_score = total
            best_pair = (a, b)

    return best_pair
```

### Match Quality Prediction

OpenSkill's `predict_win()` gives win probability. Convert to quality score:

```python
from openskill import predict_win

def match_quality(agent_a, agent_b):
    """0.0 = terrible match, 1.0 = perfectly balanced."""
    win_prob = predict_win([[agent_a.rating], [agent_b.rating]])[0]
    return 1.0 - abs(win_prob - 0.5) * 2

# Examples:
# Equal rating → quality = 1.0
# 200 Elo diff → quality ≈ 0.48
# 400 Elo diff → quality ≈ 0.18
# Threshold: only create matches with quality > 0.30
```

### Redis Data Structures

```
matchmaking:queue:{domain}       — Sorted Set (score = rating)
matchmaking:agent:{agent_id}     — Hash (metadata, queue_time)
matchmaking:match:{match_id}     — Hash (agent_a, agent_b, status)
agent:notifications:{agent_id}   — Pub/Sub channel
```

---

## Part 3: Item Response Theory (IRT) for Question Calibration

### The Core Insight

**Not all questions are equally informative.** IRT lets us:
1. Identify which questions differentiate between agents (discrimination `a`)
2. Know which are too easy/hard to be useful (difficulty `b`)
3. Retire saturated questions
4. Adaptively select questions for maximum information per eval

### IRT Model Progression

| Phase | Evals | Model | Library | What You Get |
|-------|-------|-------|---------|--------------|
| Collect | 0-100 | None (manual easy/med/hard tags) | — | Raw response data |
| Bootstrap | 100-200 | 1PL/Rasch | `girth` | Difficulty estimates (b) |
| Calibrate | 200-500 | 2PL | `girth` | Difficulty (b) + discrimination (a) |
| Adaptive | 500-1000 | 2PL/3PL + CAT | `girth` + `catsim` | Shorter tests, adaptive selection |
| Full CAT | 1000+ | 3PL or MIRT | `girth`/`py-irt` | Multi-dimensional adaptive |

### Key Formulas

**1PL/Rasch Model** (difficulty only):
```
P(correct | θ, b) = 1 / (1 + exp(-(θ - b)))
```
- `b` = item difficulty (ability level where P(correct) = 0.50)
- Minimum data: 100-150 responses per item

**2PL Model** (difficulty + discrimination):
```
P(correct | θ, a, b) = 1 / (1 + exp(-1.7a(θ - b)))
```
- `a` = discrimination (how sharply the item separates agents; target: 0.5-2.5)
- Minimum data: 250-500 responses per item

**3PL Model** (adds guessing):
```
P(correct | θ, a, b, c) = c + (1-c) / (1 + exp(-1.7a(θ - b)))
```
- `c` = guessing parameter (lower asymptote)
- Minimum data: 500-2000 responses per item

**Fisher Information** (how informative an item is at ability θ):
```
I(θ) = a² × P(θ) × (1 - P(θ))        # for 2PL
```
Items with difficulty close to agent's ability provide maximum information.

**Standard Error of Measurement:**
```
SEM(θ) = 1 / √(Σ Iᵢ(θ))
```
Target: SEM ≤ 0.3 for reliable differentiation.

### PSN-IRT (AAAI 2026 Oral) — Key Finding

Analyzed 41,871 items across 11 LLM benchmarks. A subset of **1,000 items** selected via Fisher information achieved Kendall's τ = **0.9048** with human preference rankings. This means:
- Quality > quantity for question banks
- Well-calibrated 30 questions outperform uncalibrated 300
- Item selection via information theory is transformative

### ATLAS Framework — Adaptive Testing Efficiency

| Benchmark | Full Items | Adaptive Items | Reduction | MAE |
|-----------|-----------|----------------|-----------|-----|
| HellaSwag | 5,608 | 39 | 99.3% | 0.154 |
| TruthfulQA | 628 | 51 | 91.9% | 0.067 |
| ARC | 842 | 77 | 90.8% | 0.099 |
| GSM8K | 1,307 | 73 | 94.4% | 0.159 |

**90%+ item reduction** while maintaining measurement precision. Adaptive stopping provides additional 32% reduction.

### Stanford HELM IRT Integration

Stanford CRFM applied Rasch model across 22 datasets, 183 LLMs, 78,000+ questions:
- AUC-ROC: 0.85 training, 0.83 test
- Pre-calibrated difficulty parameters published on HuggingFace
- IRT reduces evaluation cost by **90%** while maintaining ranking accuracy

### Python Libraries Comparison

| Library | Models | MIRT | Online Calibration | Dependencies | Recommendation |
|---------|--------|------|-------------------|-------------|----------------|
| **girth** | 1PL, 2PL, 3PL, GRM, MIRT-2PL | Yes (≤3 factors) | No | NumPy/SciPy only | **Phase 2-3 — primary** |
| **py-irt** | 1PL, 2PL, 4PL (Bayesian) | No | No | PyTorch + Pyro | Large-scale batch |
| **catsim** | 1PL, 2PL, 3PL (simulation) | No | No | Lightweight | CAT simulation/testing |
| **CAT4AI** | IRT, MIRT, NCD | Yes | No | PyTorch | Research prototype |
| **bayesian-irt** | Full MIRT | Yes | Yes (sequential) | PyMC | Phase 4+ production |

**Recommended path:** `girth` for calibration → `catsim` for CAT simulation → production CAT in FastAPI

---

## Part 4: Battle Fairness

### The Specialization Problem

When a code agent battles a search agent, any domain-specific question systematically advantages one side. Four strategies:

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| **Domain-neutral questions** | Reasoning, planning, general intelligence | Default for cross-domain battles |
| **Balanced domain sampling** | 30% agent A's domain + 30% agent B's + 40% neutral | When domains are known |
| **IRT-normalized scoring** | Adjust scores for question difficulty per domain | Phase 2+ with calibration data |
| **Multi-dimensional profiling** | No single winner — radar chart comparison | Always (already have this) |

### Optimal Difficulty Distribution

Based on psychometric research, for maximum discrimination:

| Difficulty Level | p-value Range | Proportion | Questions (of 30) | Purpose |
|-----------------|---------------|-----------|-------------------|---------|
| Easy | p > 0.85 | 10-15% | 3-4 | Baseline competency |
| Medium-Easy | 0.60-0.85 | 20-25% | 6-8 | Separate weak from average |
| **Medium** | **0.40-0.60** | **30-35%** | **9-10** | **Maximum discrimination** |
| Medium-Hard | 0.20-0.40 | 20-25% | 6-8 | Separate good from excellent |
| Hard | p < 0.20 | 10-15% | 3-4 | Identify exceptional agents |

The **medium difficulty range (0.40-0.60 correct rate)** provides maximum Fisher information.

### Item Quality Metrics

| Metric | Good | Acceptable | Poor → Retire |
|--------|------|-----------|---------------|
| Discrimination (a) | 0.8-2.5 | 0.3-0.8 | < 0.3 or > 3.0 |
| Point-biserial (r_pb) | > 0.30 | 0.20-0.30 | < 0.10 |
| Exposure rate | < 30% | 30-50% | > 50% (contamination risk) |
| DIF odds ratio | 0.67-1.5 | 1.5-2.0 | > 2.0 (unfair to some types) |
| p-value drift | < 0.05/100 evals | 0.05-0.20 | > 0.20 (contamination signal) |
| Age | < 3 months | 3-6 months | > 6 months without refresh |

### Item Retirement Criteria

Retire a question when ANY of:
- Discrimination `a < 0.3` (doesn't differentiate agents)
- Point-biserial `r_pb < 0.1` (uncorrelated with total score)
- Exposure > 50% of evaluations
- p-value drifted > 0.2 over 100 evals (contamination signal)
- DIF odds ratio > 2.0 (unfair to specific agent types)
- Negative point-biserial (miskeyed/flawed — remove immediately)

### Battle Discrimination Index

For head-to-head battles specifically:
```
battle_discrimination = P(winner correct on Q) - P(loser correct on Q)
```
- > 0.5: Excellent battle discriminator (consistently determines winner)
- 0.2-0.5: Good discriminator
- < 0.2: Adds noise without information
- Near 0: Both agents always get it right or wrong → no discrimination

### Score Normalization for Fair Comparison

**Z-score within domains:**
```python
z_score = (agent_score - domain_mean) / domain_std
```

**IRT-based normalization (superior):**
IRT ability estimate θ is already calibrated for item difficulty. An agent scoring 70% on hard questions gets higher θ than 70% on easy questions. No additional normalization needed.

**Percentile-rank normalization (robust):**
Rank each agent within domain, average percentile ranks. Non-parametric, handles outliers.

---

## Part 5: Anti-Gaming in Matchmaking

### Smurf Detection (Same Agent, New Identity)

**From Valorant/LoL research:**
- Behavioral fingerprinting: hash responses to calibration questions
- If two "different" agents produce near-identical responses → flag
- Accelerated placement: high K-factor for first 30 battles → smurf reaches true rating in 3-5 matches

**For AgentTrust:** Response fingerprinting already exists in `src/core/anti_gaming.py`. Extend to cross-agent similarity detection.

### Sandbagging (Intentional Underperformance)

An agent could detect evaluation and respond poorly to lower rating, then dominate weaker opponents.

**Countermeasures:**
1. **Consistency monitoring:** Track variance. Bi-modal distributions (very high OR very low) → flag
2. **Blind evaluation context:** Don't reveal whether challenge is calibration or ranked battle
3. **Monotonicity guarantee:** Design system so performing better ALWAYS results in higher rating (Elo-MMR principle)
4. **Performance floor:** If agent drops >2σ below historical median → investigate, don't drop rating

### Win Trading / Collusion

Same operator controls multiple agents, designs them to give each other easy wins.

**Countermeasures:**
1. **Operator diversity:** Don't match agents from same operator
2. **Challenge control:** AgentTrust controls question bank, not agents
3. **Pairwise anomaly detection:** If Agent A and Agent B always produce extreme results when paired → flag
4. **Statistical monitoring:** Win-rate harvesting detection (LoL approach)

### Judge Manipulation (Unique to LLM-Judged Systems)

Agents could craft outputs exploiting known LLM judge biases (verbosity, position, sycophancy).

**Countermeasures:**
1. Multi-judge consensus (already implemented — CollabEval)
2. Rotate judge models and prompts per evaluation
3. Monitor for correlation between response length and judge scores

---

## Part 6: Statistical Significance

### How Many Battles for Rankings?

**For a single pairwise comparison** (is A better than B?):

| True Win Rate | Battles (80% power) | Battles (95% power) |
|---------------|---------------------|---------------------|
| 55% (small effect) | 783 | 1,083 |
| 60% (medium effect) | 199 | 275 |
| 65% (large effect) | 91 | 126 |
| 70% (very large) | 54 | 74 |

**For ranking N agents** (Bradley-Terry):
- Minimum: 30 battles per agent for initial ranking stability
- Recommended: 50-100 battles per agent pair for narrow CI
- With active sampling: 30-50% fewer battles needed
- Total for 20 agents (round-robin, 50/pair): ~9,500 battles
- With active sampling: ~6,000 battles

### Bootstrap Confidence Intervals

```python
def bootstrap_bt_rankings(battles, n_bootstrap=1000):
    """Bootstrap Bradley-Terry for confidence intervals."""
    ratings_samples = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(len(battles), size=len(battles), replace=True)
        sampled = [battles[i] for i in sample]
        ratings_samples.append(fit_bradley_terry(sampled))

    results = {}
    for agent_id in all_agents:
        agent_ratings = [s[agent_id] for s in ratings_samples]
        results[agent_id] = {
            'mean': np.mean(agent_ratings),
            'ci_lower': np.percentile(agent_ratings, 2.5),
            'ci_upper': np.percentile(agent_ratings, 97.5),
        }
    return results
```

### Convergence Timeline

| Milestone | Battles Needed | What Stabilizes |
|-----------|---------------|-----------------|
| Initial ordering | 30 per agent | Rough ranking |
| Reliable rankings | 100 per agent | Elo/BT converges |
| Tight CI (±50 Elo) | 200+ per agent | Confidence intervals narrow |
| IRT calibration (Rasch) | 100-150 per question | Difficulty parameters |
| IRT calibration (2PL) | 250-500 per question | Difficulty + discrimination |
| Full adaptive testing | 200+ per question + 30+ agents | Complete CAT |

---

## Part 7: Contamination Defense

### Multi-Layer Strategy

| Layer | Method | Effectiveness | Status |
|-------|--------|---------------|--------|
| 1 | Question paraphrasing (template + LLM) | ~60-70% reduction | **Already built** (Phase 2) |
| 2 | Monthly question rotation (10-20% refresh) | ~85-90% reduction | Planned |
| 3 | Contamination detection (p-value drift, embedding similarity) | Detection, not prevention | Phase 3 |
| 4 | Dynamic question generation (novel per eval) | ~95%+ reduction | Phase 4 |

### Key Finding

A Llama-2-13B trained on rephrased test cases reached **4.9x higher** scores on leaked vs. clean data while being undetectable by n-gram overlap. Paraphrasing alone is necessary but insufficient. The LiveBench approach (monthly fresh questions from recent sources, objective scoring) is the gold standard.

### Recommended Approach for AgentTrust

1. **Core bank (60%):** 18 calibrated questions with known IRT parameters. Paraphrased per eval. Rotated monthly.
2. **Dynamic bank (40%):** 12 questions generated fresh or from recent sources. Never reused in identical form. Provides contamination resistance.
3. **Monitoring:** Track p-value drift per question. If p-value changes >0.2 over 100 evals → flag as potentially contaminated → retire.

---

## Part 8: Implementation Recommendations

### Phase 1 Implementation (10-50 Agents)

```python
# 1. Install OpenSkill
# pip install openskill

from openskill.models import PlackettLuce
model = PlackettLuce()

# 2. Initialize agent ratings
agent_rating = model.rating()  # Rating(mu=25, sigma=8.333)

# 3. After each battle
[[winner_new], [loser_new]] = model.rate(
    [[winner_old_rating], [loser_old_rating]]
)

# 4. Match quality gate
from openskill import predict_win
win_prob = predict_win([[agent_a.rating], [agent_b.rating]])[0]
quality = 1.0 - abs(win_prob - 0.5) * 2
if quality < 0.30:
    skip_match()  # Too unbalanced
```

### MongoDB Schema for Battles & Ratings

```javascript
// quality__battles (already planned)
{
    battle_id: "b_abc123",
    match_type: "swiss" | "ladder" | "queue" | "challenge",
    agent_a: { target_id, rating_before: {mu, sigma}, domain },
    agent_b: { target_id, rating_before: {mu, sigma}, domain },
    domain: "coding",
    status: "pending" | "running" | "completed",
    result: {
        winner: "a" | "b" | "draw",
        score_a: 72.5, score_b: 68.3,
        margin: 4.2,
        match_quality: 0.67,
    },
    rating_changes: {
        agent_a: { new_mu, new_sigma, delta },
        agent_b: { new_mu, new_sigma, delta }
    },
    created_at: ISODate(), completed_at: ISODate()
}

// Extend quality__scores with rating fields
{
    // ... existing fields ...
    "openskill_mu": 25.0,
    "openskill_sigma": 8.333,
    "openskill_axes": {
        "accuracy": { "mu": 27.1, "sigma": 5.2 },
        "safety": { "mu": 23.4, "sigma": 6.8 },
        // ... 4 more axes
    },
    "division": "gold",
    "battle_record": { "wins": 12, "losses": 3, "draws": 1 },
    "last_battle_at": ISODate(),
    "win_streak": 5
}

// quality__item_params (IRT calibration)
{
    question_id: "q_xyz",
    domain: "coding",
    difficulty_b: 0.5,
    discrimination_a: 1.2,
    p_value: 0.55,
    point_biserial: 0.38,
    exposure_count: 150,
    last_calibrated: ISODate(),
    status: "active" | "retired" | "pilot"
}
```

### IRT Integration Pattern

```python
# src/core/irt_service.py — Phase 2+

import numpy as np
from girth import twopl_mml

class IRTService:
    """Item Response Theory calibration for question bank."""

    def __init__(self):
        self.item_params = None  # (n_items, 2): [a, b]

    def calibrate(self, response_matrix: np.ndarray):
        """Batch calibration — run nightly."""
        estimates = twopl_mml(response_matrix)
        self.item_params = np.column_stack([
            estimates['Discrimination'],
            estimates['Difficulty']
        ])

    def select_next_item(self, theta: float, administered: list[int]) -> int:
        """Select most informative unadministered item."""
        available = [i for i in range(len(self.item_params))
                     if i not in administered]
        infos = []
        for i in available:
            a, b = self.item_params[i]
            p = 1 / (1 + np.exp(-a * (theta - b)))
            infos.append(a**2 * p * (1 - p))

        # Randomesque from top-5 (exposure control)
        top5 = np.argsort(infos)[-5:]
        return available[np.random.choice(top5)]

    def estimate_ability(self, responses: list[tuple[int, bool]]) -> float:
        """EAP ability estimation."""
        theta_grid = np.linspace(-4, 4, 81)
        posterior = np.ones(81) / 81
        for item_idx, correct in responses:
            a, b = self.item_params[item_idx]
            p = 1 / (1 + np.exp(-a * (theta_grid - b)))
            likelihood = p if correct else (1 - p)
            posterior *= likelihood
            posterior /= posterior.sum()
        return float(np.sum(theta_grid * posterior))
```

### API Endpoints for Arena

```
# Matchmaking
POST   /v1/arena/queue                   — Join matchmaking queue
DELETE /v1/arena/queue/{agent_id}         — Leave queue
GET    /v1/arena/queue/status             — Check queue position

# Challenge ladder
POST   /v1/arena/challenge               — Challenge specific agent
GET    /v1/arena/ladder                   — View current ladder
GET    /v1/arena/ladder/{domain}          — Domain-specific ladder

# Swiss tournaments
POST   /v1/arena/tournament              — Create tournament
POST   /v1/arena/tournament/{id}/join     — Register agent
GET    /v1/arena/tournament/{id}          — Bracket + standings

# Ratings & Rankings
GET    /v1/arena/rating/{agent_id}        — Agent ratings (all axes)
GET    /v1/arena/rankings                 — Bradley-Terry leaderboard
GET    /v1/arena/rankings/{domain}        — Domain rankings
GET    /v1/arena/predict/{id_a}/{id_b}    — Predict match quality
```

---

## Key Sources

### Rating Systems
- [Elo Reliability Under Model Misspecification (Tang et al., Feb 2025)](https://arxiv.org/abs/2502.10985)
- [Glicko-2 System (Glickman)](https://www.glicko.net/glicko/glicko2.pdf)
- [CS:GO Skill Rating Analysis (Oct 2024)](https://arxiv.org/html/2410.02831v1)
- [OpenSkill Paper (Jan 2024)](https://arxiv.org/html/2401.05451v1)
- [OpenSkill Python Library](https://github.com/vivekjoshy/openskill.py)
- [TrueSkill 2 (Microsoft Research, 2018)](https://www.microsoft.com/en-us/research/uploads/prod/2018/03/trueskill2.pdf)
- [mELO: Multidimensional Elo (DeepMind)](https://dclaz.github.io/mELO/index.html)
- [Elo-MMR (Ebtekar & Liu, WWW 2021)](https://github.com/EbTech/Elo-MMR)

### Matchmaking Systems
- [Lichess Matchmaking Source Code (Scala)](https://github.com/lichess-org/lila/blob/master/modules/pool/src/main/MatchMaking.scala)
- [Chess.com Matchmaking](https://support.chess.com/en/articles/8639319-how-does-matchmaking-work-in-live-chess)
- [LoL Matchmaking 2024](https://www.leagueoflegends.com/en-us/news/dev/dev-matchmaking-in-2024/)
- [Valorant Smurf Detection](https://playvalorant.com/en-us/news/dev/valorant-systems-health-series-smurf-detection/)
- [PlayFab Matchmaking Queues](https://learn.microsoft.com/en-us/gaming/playfab/multiplayer/matchmaking/config-queues)
- [Google Open Match](https://github.com/googleforgames/open-match)
- [Why Good Matchmaking Requires Enormous Player Counts](http://joostdevblog.blogspot.com/2014/11/why-good-matchmaking-requires-enormous.html)
- [Matchmaking for Smaller Communities](http://joostdevblog.blogspot.com/2015/09/designing-matchmaking-for-smaller.html)
- [Skill-Based Matchmaking (Yuksel, 2024)](http://www.cemyuksel.com/research/matchmaking/i3d2024-matchmaking.pdf)
- [EOMM: Engagement Optimized Matchmaking (Chen, WWW 2017)](https://arxiv.org/abs/1702.06820)

### IRT & Adaptive Testing
- [PSN-IRT: Lost in Benchmarks? (AAAI 2026 Oral)](https://arxiv.org/abs/2505.15055)
- [ATLAS: Adaptive Testing for LLMs](https://arxiv.org/abs/2511.04689)
- [AutoIRT: Calibrating IRT with AutoML (Duolingo)](https://arxiv.org/abs/2409.08823)
- [LaRT: Latency-Response Theory](https://arxiv.org/abs/2512.07019)
- [Stanford CRFM — Reliable and Efficient Evaluation](https://crfm.stanford.edu/2025/06/04/reliable-and-efficient-evaluation.html)
- [girth IRT Library](https://github.com/eribean/girth)
- [catsim CAT Simulator](https://github.com/douglasrizzo/catsim)
- [py-irt](https://github.com/nd-ball/py-irt)

### Fairness & Contamination
- [The Leaderboard Illusion (May 2025)](https://arxiv.org/abs/2504.20879)
- [Benchmark Contamination Survey](https://arxiv.org/abs/2502.17521)
- [LiveBench: Contamination-Free Benchmarking](https://livebench.ai/)
- [LiveCodeBench](https://livecodebench.github.io/)
- [AntiLeakBench](https://aclanthology.org/2025.acl-long.901/)
- [Gray Swan Arena / HarmBench](https://www.grayswan.ai/research/harmbench-a-standardized-evaluation-framework-for-automated-red-teaming-and-robust-refusal)

### AI Competition Platforms
- [LMArena / Chatbot Arena](https://lmarena.ai/)
- [Chatbot Arena Paper (2024)](https://arxiv.org/abs/2403.04132)
- [LMArena Active Sampling](https://lmsys.org/blog/2023-12-07-leaderboard/)
- [Vote Rigging in Chatbot Arena (Min et al., ICML 2025)](https://arxiv.org/abs/2501.17858)
- [AI Arena — Ranking System](https://docs.aiarena.io/gaming-competition/ranking-system)
- [Bittensor Yuma Consensus](https://docs.learnbittensor.org/learn/yuma-consensus)
- [Alpha Arena](https://nof1.ai/)

### Statistical Methods
- [Bradley-Terry Model (Wikipedia)](https://en.wikipedia.org/wiki/Bradley%E2%80%93Terry_model)
- [Bayesian Bradley-Terry (JMLR)](https://www.jmlr.org/papers/volume24/22-0907/22-0907.pdf)
- [IRT Minimum Sample Sizes](https://files.eric.ed.gov/fulltext/EJ1101283.pdf)
- [DIF Detection Methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC8850764/)
- [AI Sandbagging](https://tomdug.github.io/ai-sandbagging/)
