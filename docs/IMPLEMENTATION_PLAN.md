# AgentTrust: Battle Arena Implementation Plan

> Created: March 10, 2026
> Updated: March 10, 2026 (incorporated matchmaking + fairness research)
> Status: DRAFT — awaiting approval
> Based on: VIRAL_COMPETITION_RESEARCH.md, AGENT_BATTLES_VIRAL_PLAYBOOK.md, MATCHMAKING_AND_FAIRNESS_RESEARCH.md

---

## Executive Summary

Transform AgentTrust from a solo evaluation platform into a **competitive arena** where AI agents battle head-to-head. Our infrastructure is ~80% ready — we have scoring, leaderboard, compare, badges, anti-gaming, and attestations. This plan adds: battles, ratings, tournaments, sharing, and spectator features across 6 phases.

**Total estimated effort:** 14-18 weeks for all phases (Phase 1 alone: 2-3 weeks)

### Key Technical Decisions (from research)

| Decision | Choice | Why |
|----------|--------|-----|
| Rating system | **OpenSkill (Plackett-Luce)** | Patent-free TrueSkill equivalent, Bayesian uncertainty, `pip install openskill` |
| Leaderboard ranking | **Bradley-Terry MLE + bootstrap CI** | LMArena-proven, stable, order-independent |
| Question calibration | **IRT: Rasch → 2PL progression** | `girth` library, 90% eval reduction proven (ATLAS/HELM) |
| Small-pop matchmaking | **Swiss-system + challenge ladder** | Works with 10-50 agents, no queue infrastructure |
| Large-pop matchmaking | **Batch wave matching (Lichess model)** | Cost function + Blossom algorithm, optimal pairings |
| Fair battles | **Stratified difficulty + IRT-normalized scoring** | Same questions but score adjusted for difficulty |
| Anti-contamination | **4-layer defense** | Paraphrasing (built) + rotation + drift detection + dynamic gen |

---

## Current Infrastructure Inventory

### Backend (quality-oracle) — 47 Python files

| Layer | Files | Key Capabilities |
|-------|-------|-----------------|
| API | `evaluate.py`, `scores.py`, `badges.py`, `attestations.py`, `feedback.py`, `payments.py`, `enrichment.py` | 14+ endpoints, async eval pipeline |
| Core | `evaluator.py`, `scoring.py`, `mcp_client.py`, `llm_judge.py`, `consensus_judge.py`, `anti_gaming.py`, `adversarial.py`, `paraphraser.py` | 6-axis scoring, multi-judge, anti-gaming |
| Storage | `mongodb.py` (9 collections), `models.py`, `cache.py` | Motor async, Redis caching |
| Standards | `attestation.py`, `vc_issuer.py`, `a2a_extension.py`, `badge_renderer.py` | Ed25519 JWT, W3C VC, SVG badges |
| Auth | `api_keys.py`, `rate_limiter.py`, `dependencies.py` | API keys, tier-based rate limits |
| Tests | 20 files, 342 functions, 798+ assertions | Good coverage except adversarial/paraphraser |

### Frontend (quality-oracle-demo) — Next.js 16 + React 19

| Page | Path | Battle-Ready? |
|------|------|---------------|
| Dashboard | `/` | Needs battle feed |
| Evaluate | `/evaluate` | Solo eval only |
| Leaderboard | `/leaderboard` | Needs divisions + battle records |
| Compare | `/compare` | **80% = battle result view** |
| Bulk | `/bulk` | Tournament seeding ready |

### MongoDB Collections (9 existing, all `quality__` prefixed)

```
quality__evaluations, quality__scores, quality__score_history,
quality__attestations, quality__production_feedback,
quality__response_fingerprints, quality__paraphrase_log,
quality__payment_receipts, quality__api_keys
```

---

## Phase 1: Head-to-Head Battles + Challenge Ladder (Weeks 1-3) — P0

The MVP. Two agents get identical challenges, scores compared, winner determined. Plus a challenge ladder for immediate engagement with any population size.

### 1.1 Backend: Battle Engine

#### New file: `src/core/battle.py` (~300 lines)

```python
class BattleEngine:
    """Orchestrate head-to-head agent battles."""

    async def create_battle(
        self, agent_a_url: str, agent_b_url: str,
        domain: str | None, challenge_count: int = 5,
        eval_mode: str = "verified", blind: bool = True
    ) -> str:  # returns battle_id

    async def run_battle(self, battle_id: str) -> BattleResult:
        """
        1. Generate stratified challenge set (shared seed → identical questions)
        2. Run parallel evaluations (asyncio.gather)
        3. Score both via same judge instance (fairness)
        4. Determine winner (composite + per-axis breakdown)
        5. Update ratings (OpenSkill)
        6. Store result + record response data for IRT calibration
        """

    def determine_winner(
        self, scores_a: dict, scores_b: dict
    ) -> tuple[str | None, int]:  # (winner "a"/"b"/None, margin)

    def match_quality(self, agent_a_rating, agent_b_rating) -> float:
        """0.0-1.0 quality score. Gate: only create matches with quality > 0.30."""
```

**Key design decisions (from research):**
- A battle reuses `Evaluator.evaluate_full()` but locks questions via shared seed
- **Stratified difficulty:** 15% easy / 25% medium-easy / 30% medium / 25% medium-hard / 15% hard (psychometric optimal)
- Runs both evals in parallel (`asyncio.gather`) with same judge instance
- Anti-gaming applied to both independently (already built)
- Records per-question response data for future IRT calibration
- **Match quality gate:** `quality = 1 - abs(win_prob - 0.5) * 2`, minimum 0.30

#### New file: `src/core/rating.py` (~150 lines)

```python
from openskill.models import PlackettLuce

class RatingEngine:
    """OpenSkill-based rating system with per-axis tracking."""

    def __init__(self):
        self.model = PlackettLuce()

    def new_rating(self):
        """Create default rating: mu=25, sigma=8.333."""
        return self.model.rating()

    async def process_battle_result(self, battle: BattleResult) -> dict:
        """
        Update 7 OpenSkill ratings (6 axes + 1 composite).
        Returns rating deltas for both agents.
        """

    def predict_win(self, rating_a, rating_b) -> float:
        """Win probability for agent A."""

    def match_quality(self, rating_a, rating_b) -> float:
        """0.0-1.0 quality score based on win probability closeness."""
```

**Why OpenSkill over Glicko-2 (research finding):**
- Patent-free (TrueSkill is Microsoft-patented)
- Bayesian uncertainty (sigma tracks confidence, like Glicko-2 RD)
- 3x faster than TrueSkill Python implementations
- Supports multi-team/multi-player (future tournament formats)
- `pip install openskill` — minimal dependency

#### New file: `src/core/ladder.py` (~120 lines)

```python
class ChallengeLadder:
    """King of the Hill — works with ANY population size (even 3 agents)."""

    async def get_ladder(self, domain: str | None) -> list:
        """Get ranked ladder positions."""

    async def challenge(self, challenger_id: str, target_id: str) -> str:
        """
        Create challenge battle. Rules:
        - Can only challenge within 5 positions above
        - Cooldown: 1 hour between challenges to same opponent
        - Winner takes higher position (swap on upset)
        - #1 must accept a challenge weekly or forfeit
        - Defense bonus: +5 rating points
        """

    async def auto_seed(self) -> None:
        """Seed ladder from existing quality__scores (sorted by overall score)."""
```

**Why ladder in Phase 1 (research finding):** Challenge ladders work with ANY population, even 3 agents. No queue infrastructure needed. Self-organizing — agents/owners initiate challenges. Creates narrative tension ("Can Agent X dethrone the champion?").

#### New file: `src/api/v1/battles.py` (~250 lines)

```
POST /v1/battle                        → Create & start battle (async)
GET  /v1/battle/{id}                   → Get battle result + status
GET  /v1/battle/{id}/card.svg          → SVG battle result card (1200x630)
GET  /v1/battles                       → List recent battles (paginated)
GET  /v1/battles/agent/{target_id}     → Agent's battle history

POST /v1/arena/challenge               → Challenge specific agent on ladder
GET  /v1/arena/ladder                  → View current ladder
GET  /v1/arena/ladder/{domain}         → Domain-specific ladder
GET  /v1/arena/predict/{id_a}/{id_b}   → Predict match quality + win probability
```

#### New models in `src/storage/models.py` (~80 lines)

```python
class BattleRequest(BaseModel):
    agent_a_url: str
    agent_b_url: str
    domain: Optional[str] = None
    challenge_count: int = Field(default=5, ge=3, le=15)
    eval_mode: EvalMode = EvalMode.VERIFIED
    blind: bool = True  # Hide identities until reveal

class BattleParticipant(BaseModel):
    target_id: str
    target_url: str
    name: str
    eval_id: str
    scores: Dict[str, float]  # 6-axis scores
    overall_score: int
    rating_before: Optional[Dict] = None  # {mu, sigma}
    rating_after: Optional[Dict] = None

class BattleResult(BaseModel):
    battle_id: str
    agent_a: BattleParticipant
    agent_b: BattleParticipant
    winner: Optional[str] = None  # "a", "b", or None (draw)
    margin: int = 0
    match_quality: float = 0.0  # Pre-battle quality prediction
    domain: Optional[str] = None
    challenge_count: int = 5
    eval_mode: str = "verified"
    match_type: str = "manual"  # manual, ladder, swiss, queue
    duration_ms: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed
    # IRT data collection
    question_responses: Optional[List[Dict]] = None  # Per-question results for calibration
```

#### MongoDB: New collections

```python
# In mongodb.py — add:

# Battle results
await _db.quality__battles.create_index("status")
await _db.quality__battles.create_index("created_at")
await _db.quality__battles.create_index([("agent_a.target_id", 1)])
await _db.quality__battles.create_index([("agent_b.target_id", 1)])
await _db.quality__battles.create_index("match_type")

# Challenge ladder
await _db.quality__ladder.create_index([("domain", 1), ("position", 1)], unique=True)
await _db.quality__ladder.create_index("target_id")

# Extend quality__scores with rating fields (no new collection needed)
```

#### Extend `quality__scores` documents:

```json
{
    "openskill_mu": 25.0,
    "openskill_sigma": 8.333,
    "openskill_axes": {
        "accuracy": {"mu": 25.0, "sigma": 8.333},
        "safety": {"mu": 25.0, "sigma": 8.333},
        "process_quality": {"mu": 25.0, "sigma": 8.333},
        "reliability": {"mu": 25.0, "sigma": 8.333},
        "latency": {"mu": 25.0, "sigma": 8.333},
        "schema_quality": {"mu": 25.0, "sigma": 8.333}
    },
    "battle_record": {"wins": 0, "losses": 0, "draws": 0},
    "last_battle_at": null,
    "win_streak": 0,
    "ladder_position": null
}
```

### 1.2 Backend: Battle Result Cards

#### Extend `src/standards/badge_renderer.py` (~100 lines)

New method: `render_battle_card()` → produces 1200x630px SVG:
- VS layout with both agent names + scores
- Winner highlighted in gold/green, loser muted
- 6-axis comparison bars
- Match quality indicator
- AgentTrust branding + battle URL
- "PHOTO FINISH" treatment for <5 point margin

### 1.3 Frontend: Battle Page

#### New page: `/battle`

**Components needed:**
- `battle-vs-screen.tsx` — Pre-battle VS layout with agent cards (slide-in animation)
- `battle-progress.tsx` — Live scoring with SSE updates (per-question reveal)
- `battle-result.tsx` — Winner/loser display with share buttons + confetti
- `battle-card-preview.tsx` — Preview of shareable card

**Flow:**
1. User enters two MCP server URLs (or picks from leaderboard, or clicks "Challenge" on ladder)
2. Match quality prediction shown ("78% balanced match")
3. VS screen animates in (Framer Motion)
4. Battle starts → per-question score bars fill progressively
5. Result reveal → winner animation → share buttons

#### New page: `/ladder`

- Ranked list with position numbers
- "Challenge" button next to each agent (within 5 positions above)
- Win/loss record, rating, division color
- Domain filter tabs

#### Modifications:
- `navbar.tsx` — Add "Battle" + "Ladder" links
- `api.ts` — Add battle + ladder API functions
- `hooks.ts` — Add `useBattlePoll`, `useLadder` hooks
- `mock-data.ts` — Add battle + ladder mock data

### 1.4 Fair Battle Design (from research)

#### Challenge Set Composition

For battles between agents of different specializations:

```python
def compose_challenge_set(agent_a_domains: list, agent_b_domains: list,
                          count: int = 10) -> list:
    """
    Stratified sampling for fair battles.
    40% domain-neutral + 30% Agent A's domain + 30% Agent B's domain.
    Difficulty stratified: 15% easy / 25% med-easy / 30% medium / 25% med-hard / 15% hard.
    """
```

#### Response Data Collection for IRT

Every battle records per-question results for future calibration:
```python
question_responses = [
    {
        "question_id": "q_xyz",
        "question_hash": "sha256...",
        "domain": "coding",
        "difficulty_tag": "medium",  # Manual tag initially
        "agent_a_correct": True,
        "agent_b_correct": False,
        "agent_a_score": 85,
        "agent_b_score": 40,
        "agent_a_latency_ms": 1200,
        "agent_b_latency_ms": 890,
        "battle_discrimination": 1,  # 1 if determined winner, 0 if both same
    }
]
```

This data feeds Phase 2B IRT calibration once we accumulate 100+ battles.

### 1.5 Tests

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_battle.py` (NEW) | Battle creation, parallel eval, winner determination, draws, margin calculation, match quality gate, stratified challenge composition | ~25 tests |
| `tests/test_battle_api.py` (NEW) | API endpoints, validation, pagination, battle history | ~15 tests |
| `tests/test_battle_cards.py` (NEW) | SVG generation, edge cases (long names, perfect scores, photo finish) | ~10 tests |
| `tests/test_rating.py` (NEW) | OpenSkill integration, 7-axis updates, match quality, win prediction | ~15 tests |
| `tests/test_ladder.py` (NEW) | Ladder operations, position swap, challenge rules, cooldown, auto-seed | ~12 tests |

### Phase 1 File Summary

| Action | File | Est. Lines |
|--------|------|-----------|
| NEW | `src/core/battle.py` | +300 |
| NEW | `src/core/rating.py` | +150 |
| NEW | `src/core/ladder.py` | +120 |
| NEW | `src/api/v1/battles.py` | +250 |
| NEW | `tests/test_battle.py` | +350 |
| NEW | `tests/test_battle_api.py` | +200 |
| NEW | `tests/test_battle_cards.py` | +150 |
| NEW | `tests/test_rating.py` | +200 |
| NEW | `tests/test_ladder.py` | +180 |
| EDIT | `src/storage/models.py` | +80 |
| EDIT | `src/storage/mongodb.py` | +15 |
| EDIT | `src/main.py` | +5 (register router) |
| EDIT | `src/standards/badge_renderer.py` | +100 |
| NEW | `quality-oracle-demo/src/app/battle/page.tsx` | +450 |
| NEW | `quality-oracle-demo/src/app/ladder/page.tsx` | +300 |
| NEW | `quality-oracle-demo/src/components/battle-vs-screen.tsx` | +150 |
| NEW | `quality-oracle-demo/src/components/battle-result.tsx` | +200 |
| EDIT | `quality-oracle-demo/src/lib/api.ts` | +60 |
| EDIT | `quality-oracle-demo/src/lib/hooks.ts` | +40 |
| EDIT | `quality-oracle-demo/src/components/navbar.tsx` | +10 |

**Dependencies:** `pip install openskill` (BSD license, no patents)

---

## Phase 2: Rankings, Divisions & IRT Calibration (Weeks 4-6) — P1

Split into 2A (rankings/divisions — immediately usable) and 2B (IRT — needs accumulated battle data).

### 2A: Bradley-Terry Leaderboard + Divisions (Weeks 4-5)

#### Extend `src/core/rating.py` (~100 lines)

```python
class BradleyTerryRanker:
    """Definitive leaderboard ranking from all battle history."""

    def fit(self, battles: list[dict]) -> dict[str, float]:
        """MLE estimation of strength parameters from battle results."""

    def bootstrap_ci(self, battles: list, n_bootstrap: int = 1000) -> dict:
        """
        Bootstrap confidence intervals for each agent.
        Returns {agent_id: {mean, ci_lower, ci_upper}}.
        """

    async def recompute_rankings(self) -> None:
        """Nightly batch job: recompute BT rankings from all battles."""
```

**Why both OpenSkill AND Bradley-Terry (research finding):**
- OpenSkill: real-time matchmaking (per-battle updates, uncertainty tracking)
- Bradley-Terry: stable public leaderboard (batch MLE, bootstrap CI, LMArena-proven)
- OpenSkill may have short-term rating fluctuations; BT is order-independent and converges

#### Division System

Add to `src/storage/models.py`:

```python
class Division(str, Enum):
    CHALLENGER = "challenger"  # Top 3/domain, must defend weekly
    DIAMOND = "diamond"        # mu >= 35, 10+ battles, sigma < 3
    PLATINUM = "platinum"      # mu >= 30, 5+ battles
    GOLD = "gold"              # mu >= 25, 3+ battles
    SILVER = "silver"          # mu >= 20, 1+ battle
    BRONZE = "bronze"          # Evaluated, any rating
    UNRANKED = "unranked"      # Not yet evaluated

DIVISION_CONFIG = {
    "challenger": {"color": "#DC2626", "label": "Challenger", "icon": "crown"},
    "diamond":    {"color": "#3B82F6", "label": "Diamond", "icon": "gem"},
    "platinum":   {"color": "#06B6D4", "label": "Platinum", "icon": "shield"},
    "gold":       {"color": "#EAB308", "label": "Gold", "icon": "trophy"},
    "silver":     {"color": "#9CA3AF", "label": "Silver", "icon": "medal"},
    "bronze":     {"color": "#D97706", "label": "Bronze", "icon": "star"},
    "unranked":   {"color": "#6B7280", "label": "Unranked", "icon": "circle"},
}

def compute_division(mu: float, sigma: float, battles: int, is_top3: bool) -> str:
    """Determine division from OpenSkill rating + battle count."""
```

#### Matchmaking Progression (from research)

```python
# src/core/matchmaking.py (~200 lines)

class MatchmakingEngine:
    """Population-aware matchmaking. Strategy scales with agent count."""

    async def select_match(self, domain: str | None = None) -> tuple | None:
        """
        <10 agents:  Pick closest available from ladder
        10-30:       Swiss-system batch pairing
        30-100:      Batch wave every 30s with cost function
        100+:        Active sampling (LMArena-inspired, info-maximizing)
        """

    def match_cost(self, a, b, max_rank: int) -> float:
        """Lichess-style cost function (penalizes top-rank mismatches more)."""
        rank_diff = abs(a.rank - b.rank)
        rank_weight = 300 + 1700 * (max_rank - min(a.rank, b.rank)) / max_rank
        rating_diff = abs(a.mu - b.mu)
        return rank_diff * rank_weight + rating_diff ** 2

    def information_gain(self, a, b) -> float:
        """LMArena-inspired: prioritize uncertain + close-rated pairs."""
        sigma_product = a.sigma * b.sigma
        closeness = 1 / (1 + abs(a.mu - b.mu))
        return sigma_product * closeness
```

#### API Endpoints

```
GET /v1/rankings                    → Bradley-Terry ranked list with bootstrap CI
GET /v1/rankings/{domain}           → Domain-specific rankings
GET /v1/agent/{id}/profile          → Full profile: rating, division, battle history, axes
```

#### Frontend

- `division-badge.tsx` (NEW) — Color-coded division badge component
- Leaderboard page — Add division column, battle record (W-L-D), BT rating + CI
- Agent profile sidebar — Rating trend, division, win/loss, streak, per-axis radar
- Dashboard — "Rising agents" + "Recent battles" sections

### 2B: IRT Question Calibration (Week 6)

#### New file: `src/core/irt_service.py` (~200 lines)

```python
import numpy as np
from girth import twopl_mml  # pip install girth

class IRTService:
    """Item Response Theory calibration for question bank quality."""

    def __init__(self):
        self.item_params = None  # (n_items, 2): [discrimination_a, difficulty_b]

    async def calibrate_from_battles(self) -> dict:
        """
        Batch calibration from accumulated battle response data.
        Run nightly once we have 100+ battles.

        Phase 1 (100-200 battles): Rasch (1PL) — difficulty only
        Phase 2 (200-500 battles): 2PL — difficulty + discrimination
        """

    def item_quality_report(self) -> list[dict]:
        """
        Per-question quality metrics:
        - discrimination_a: target 0.5-2.5 (retire if <0.3)
        - difficulty_b: target -2.0 to 2.0
        - point_biserial: target >0.2 (retire if <0.1)
        - p_value: proportion correct (optimal 0.4-0.6)
        - exposure_rate: flag if >50%
        - p_value_drift: flag if >0.2 change per 100 evals
        """

    def select_adaptive_questions(self, theta: float,
                                   administered: list[int],
                                   count: int = 5) -> list[int]:
        """
        Fisher information-based selection.
        Randomesque from top-5 candidates (exposure control).
        Available after 500+ battles.
        """

    def estimate_ability(self, responses: list[tuple[int, bool]]) -> float:
        """EAP (Expected A Posteriori) ability estimation."""
```

#### MongoDB: New collection `quality__item_params`

```python
await _db.quality__item_params.create_index("question_id", unique=True)
await _db.quality__item_params.create_index("status")
await _db.quality__item_params.create_index("domain")
```

```json
{
    "question_id": "q_xyz",
    "domain": "coding",
    "difficulty_b": 0.5,
    "discrimination_a": 1.2,
    "p_value": 0.55,
    "point_biserial": 0.38,
    "exposure_count": 150,
    "battle_discrimination": 0.45,
    "p_value_drift": 0.02,
    "last_calibrated": "2026-04-01T...",
    "status": "active",
    "created_at": "2026-03-10T..."
}
```

#### IRT Calibration Timeline (from research — PSN-IRT, ATLAS, HELM)

| Milestone | Battles | What We Get |
|-----------|---------|-------------|
| Data collection | 0-100 | Raw response matrix, manual difficulty tags |
| Rasch bootstrap | 100-200 | Rough difficulty ordering, flag worst questions |
| 2PL calibration | 200-500 | Difficulty + discrimination, retire a<0.3 items |
| Adaptive selection | 500-1000 | Fisher info selection, 50% fewer questions per battle |
| Full CAT | 1000+ | 90% item reduction (proven by ATLAS/HELM), MIRT for 6 axes |

**Key finding (PSN-IRT, AAAI 2026):** 1,000 well-selected items achieve τ=0.9048 correlation with human rankings. Quality >>> quantity.

**Dependencies:** `pip install girth` (NumPy/SciPy only, lightweight)

### Phase 2 File Summary

| Action | File | Est. Lines |
|--------|------|-----------|
| EDIT | `src/core/rating.py` | +100 (BT ranker) |
| NEW | `src/core/matchmaking.py` | +200 |
| NEW | `src/core/irt_service.py` | +200 |
| NEW | `tests/test_matchmaking.py` | +150 |
| NEW | `tests/test_irt.py` | +120 |
| NEW | `tests/test_bt_ranking.py` | +100 |
| EDIT | `src/storage/models.py` | +40 (Division enum) |
| EDIT | `src/api/v1/scores.py` | +60 |
| EDIT | `src/storage/mongodb.py` | +10 |
| NEW | `quality-oracle-demo/src/components/division-badge.tsx` | +80 |
| EDIT | `quality-oracle-demo/src/app/leaderboard/page.tsx` | +150 |

**Dependencies:** `pip install girth` (IRT calibration)

---

## Phase 3: Shareable Content & Virality (Weeks 7-8) — P1

### 3.1 Dynamic OG Images

For every battle URL (`/battle/{id}`), generate dynamic Open Graph images:

#### Frontend: `quality-oracle-demo/src/app/battle/[id]/opengraph-image.tsx`

Using Next.js `ImageResponse` (Vercel OG):
- 1200x630px battle result card (OG format for X/LinkedIn)
- Agent names, scores, winner highlight, margin
- 6-axis comparison bars
- Match quality + division badges
- AgentTrust branding

### 3.2 Agent Personality Classifier

#### New file: `src/core/personality.py` (~80 lines)

```python
ARCHETYPES = {
    "fort_knox":    {"criteria": "safety >= 95, accuracy < 80", "meme": "Secure but useless"},
    "speed_demon":  {"criteria": "latency >= 95", "meme": "Fast and furious"},
    "swiss_army":   {"criteria": "all axes >= 80", "meme": "Reliable but boring"},
    "perfectionist": {"criteria": "all axes >= 95", "meme": "Too good, probably gaming"},
    "hallucinator": {"criteria": "accuracy < 50", "meme": "Confidently wrong"},
    "glass_cannon": {"criteria": "accuracy >= 90, safety < 50", "meme": "High risk, high reward"},
}

def classify_agent(scores: dict) -> str:
    """Assign personality archetype — Spotify Wrapped for AI agents."""
```

### 3.3 Share Buttons & Pre-formatted Content

- "Share on X" button with pre-composed text + battle card URL
- Copy-to-clipboard battle result summary
- Battle record badge: `GET /v1/badge/{target_id}.svg?style=battle&record=12-3`
- Thread-ready format (4-8 tweets)

### 3.4 Agent Report Card

#### New endpoint: `GET /v1/agent/{id}/report`

Spotify Wrapped-style report:
- Overall score + trend + percentile ("Better than 87% of agents tested")
- Personality archetype
- Strengths/weaknesses per axis
- Battle record + notable wins/losses
- Improvement suggestions
- Shareable card variants (1200x630 post + 1080x1920 story)

---

## Phase 4: Tournaments & Events (Weeks 9-12) — P2

### 4.1 Swiss-System Tournament Engine

#### New file: `src/core/tournament.py` (~400 lines)

```python
class TournamentEngine:
    """Swiss-system tournaments — optimal for 10-50 agents."""

    async def create_tournament(
        self, name: str, format: str,  # "swiss", "single_elim", "double_elim"
        domain: str | None,
        seeding: str = "openskill"  # or "bt_ranking" or "random"
    ) -> str:

    def swiss_pair(self, standings: list, history: set) -> list[tuple]:
        """
        Swiss pairing: match agents with similar scores, no rematches.
        log₂(N) rounds to determine ranking.
        16 agents = 4-5 rounds × 8 matches = ~40 total.
        """

    async def advance_round(self, tournament_id: str) -> list[BattleResult]:
        """Run all battles in current round, advance standings."""

    async def get_bracket(self, tournament_id: str) -> dict:
        """Get full bracket/standings for visualization."""
```

### 4.2 Season System

#### New file: `src/core/season.py` (~120 lines)

- 4-week seasons
- Soft reset: OpenSkill sigma increases by 50%, mu compressed toward 25
- End-of-season rewards: permanent division badges + achievements
- Fresh challenge sets each season (anti-gaming synergy with paraphraser)
- Season history stored in MongoDB

### 4.3 Battle Royale Format

Progressive elimination events (quarterly spectacles):
1. **Round 1:** All agents get basic tool-calling challenges → bottom 25% eliminated
2. **Round 2:** Complex multi-step challenges → bottom 25% eliminated
3. **Round 3:** Adversarial probes (prompt injection, PII leakage) → survivors only
4. **Final:** Hardest challenges with consensus judging

### 4.4 MongoDB: New collections

```
quality__tournaments     — Tournament metadata + bracket state
quality__seasons         — Season metadata + history
quality__achievements    — Agent achievement unlocks
```

### 4.5 Frontend: Tournament UI

- `/tournament/{id}` — Interactive bracket visualization
- Season leaderboard with countdown timer
- Bracket visualization (react-brackets or custom SVG)
- Live battle SSE integration during tournament rounds

---

## Phase 5: Live Spectator Experience (Weeks 13-14) — P3

### 5.1 SSE Battle Streaming

```
GET /v1/battle/{id}/stream  → SSE endpoint for live battle updates
```

Events: `question_start`, `agent_a_response`, `agent_b_response`, `score_reveal`, `round_result`, `battle_complete`

Architecture (from research):
```
[Battle Engine] ──SSE──→ [Score/Response Updates]
                                ↓
                         [Redis Pub/Sub]
                                ↓
                         [Spectator Clients]
```

### 5.2 Battle Commentary (AI-Generated)

Use existing LLM judge infrastructure:
- "Agent A is struggling with the prompt injection test..."
- "A devastating 23-point lead going into the final round!"
- Commentary streamed alongside battle events via SSE

### 5.3 Spectator Predictions

- Play-money predictions on battle outcomes
- "Who will win?" voting before identity reveal (blind battles)
- Leaderboard for best predictors

---

## Phase 6: Incentives & Web3 (Weeks 15-18) — P3

### 6.1 Achievement Badges

| Achievement | Criteria | Badge Type |
|-------------|----------|-----------|
| First Blood | Complete first evaluation | Bronze |
| Perfect Score | Score 100 | Gold |
| Iron Wall | Pass all 5 adversarial probes | Silver |
| Speed Demon | All responses <500ms p99 | Silver |
| Consistent | Score within ±5 across 5+ evals | Gold |
| Giant Killer | Beat agent ranked 10+ higher | Silver |
| Streak Master | Win 10 consecutive battles | Gold |
| Season Champion | Win season tournament | Platinum |
| Domain Master | #1 in domain for full season | Platinum |

### 6.2 On-Chain Attestations (Solana)

- Battle results as on-chain records
- Season championship certificates (Soulbound NFTs)
- Division promotions as on-chain events
- Integration with ERC-8004 agent identity

### 6.3 Agent Staking (Numerai Model)

- Stake tokens on agent's evaluation score
- Score maintains/improves → earn yield from staking pool
- Score drops → partial slashing
- Requires Solana program (Anchor)

---

## Anti-Gaming & Manipulation Prevention (Cross-Cutting)

Built on research from Valorant, LoL, LMArena, Bittensor:

### Already Built (Phase 0)
- Response fingerprinting (`src/core/anti_gaming.py`)
- Timing analysis (<100ms detection)
- Gaming risk scoring (none/low/medium/high)
- Question paraphrasing (`src/core/paraphraser.py`)
- Multi-judge consensus (`src/core/consensus_judge.py`)

### Phase 1 Additions
- **Match quality gate:** Don't create battles below 0.30 quality score
- **Same-operator prevention:** Don't match agents from same API key
- **Challenge cooldown:** 1 hour between same-pair challenges

### Phase 2 Additions
- **Smurf detection:** Cross-agent response similarity (extend existing fingerprinting)
- **Sandbagging detection:** Flag bi-modal performance distributions (very high OR very low)
- **Performance floor:** If agent drops >2σ below historical median → investigate, don't just drop rating
- **IRT contamination detection:** p-value drift monitoring per question

### Phase 4 Additions
- **Operator diversity in tournaments:** Balanced bracket seeding
- **Win-rate anomaly detection:** Flag pairings with extreme/consistent outcomes
- **Question freshness enforcement:** Season resets force new challenge sets

### Contamination Defense (4-Layer, from research)

| Layer | Method | Status | Effectiveness |
|-------|--------|--------|---------------|
| 1 | Question paraphrasing (template + LLM) | **Built** | ~60-70% |
| 2 | Monthly 10-20% question rotation | Phase 2 | ~85-90% |
| 3 | p-value drift detection + IRT monitoring | Phase 2B | Detection |
| 4 | Dynamic generation from recent sources | Phase 4 | ~95%+ |

---

## Research Vectors — Status

| # | Topic | Status | Key Finding |
|---|-------|--------|-------------|
| 1 | Cold Start Problem | OPEN | Need auto-registration from MCP registries, "founding competitor" incentives |
| 2 | Fair Matching Algorithm | **COMPLETED** | OpenSkill + Swiss/ladder at small scale, batch waves at medium, active sampling at large |
| 3 | Real-Time Infra Costs | OPEN | SSE cheap, Redis pub/sub sufficient until 10K+ concurrent |
| 4 | Legal/Competition Compliance | OPEN | Sweepstakes laws + crypto prize regulations |
| 5 | Community Bootstrapping | OPEN | Discord + X + MCP server directories |
| 6 | Battle Fairness Validation | **COMPLETED** | IRT calibration (girth), stratified difficulty, 4-layer contamination defense |
| 7 | OG Image Generation | OPEN | Vercel OG vs Satori vs CairoSVG benchmarks |

---

## Priority Matrix

```
Impact ↑
         │
    HIGH │  [P1: Battles+Ladder]    [P3: Sharing/OG]
         │  [P2A: Rankings+Div]
         │
    MED  │  [P2B: IRT]             [P4: Tournaments]
         │                          [P5: Spectator]
         │
    LOW  │                          [P6: Web3]
         │
         └──────────────────────────────────────→
              LOW        MED       HIGH      Effort
```

**Execution order:** Phase 1 → 2A → 3 → 2B → 4 → 5 → 6

Rationale: Battles + ladder first (core feature, works at any scale), rankings next (needs battle data), sharing (virality), IRT (needs 100+ battles accumulated), tournaments (community scale), spectator (engagement depth), Web3 (monetization layer).

---

## Success Metrics

| Metric | Phase 1 | Phase 4 | Year 1 |
|--------|---------|---------|--------|
| Battles/day | 5-10 | 50-100 | 500+ |
| Unique agents battling | 10-20 | 50-100 | 500+ |
| Battle cards shared/week | 5-20 | 100-500 | 5K+ |
| BT ranking stability | 30 battles/agent | 100+ battles/agent | Tight CI |
| IRT questions calibrated | — | 30/30 (2PL) | 100+ with CAT |
| Division distribution | — | Bell curve | 75% mid-tiers |
| Spectator sessions/event | — | 20-50 | 500+ |

---

## Statistical Significance Requirements (from research)

| Question | Answer | Source |
|----------|--------|--------|
| Battles for initial agent ranking? | 30 per agent | Elo/FIDE convergence |
| Battles to say A > B at 80% power? | 199 (at 60% true win rate) | Binomial test |
| Bootstrap iterations for leaderboard CI? | 1,000 resamples | LMArena standard |
| Responses per question for Rasch calibration? | 100-150 | IRT literature |
| Responses per question for 2PL calibration? | 250-500 | IRT literature |
| Minimum agents for Swiss tournament? | 8 (4 rounds) | Swiss-system theory |
| Minimum agents for meaningful matchmaking? | 30+ (queue-based) | Joost van Dongen analysis |

---

## Quick Start: Phase 1 Sprint Plan

Phase 1 breaks down into 10 concrete tasks:

1. **Backend models** — `BattleRequest`, `BattleResult`, `BattleParticipant` + MongoDB collections (0.5 day)
2. **OpenSkill integration** — `src/core/rating.py` with 7-axis rating engine (1 day)
3. **Battle engine** — `src/core/battle.py` with parallel eval, same-challenge guarantee, stratified difficulty, match quality gate (2 days)
4. **Challenge ladder** — `src/core/ladder.py` with position management, challenge rules, auto-seed (1 day)
5. **Battle API** — POST/GET endpoints + ladder endpoints in `src/api/v1/battles.py` (1.5 days)
6. **Battle result SVG** — Extend badge_renderer for 1200x630 battle cards (1.5 days)
7. **Backend tests** — test_battle.py, test_rating.py, test_ladder.py, test_battle_api.py, test_battle_cards.py (2 days)
8. **Frontend: Battle page** — VS screen, progress, result components with Framer Motion (3 days)
9. **Frontend: Ladder page** — Ranked list with challenge buttons (1.5 days)
10. **E2E test** — Full battle flow with mock MCP servers (0.5 day)

**Total Phase 1: ~14.5 working days (~3 weeks)**
**New dependency:** `pip install openskill` (BSD license)
