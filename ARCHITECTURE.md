# Quality Oracle — Final Architecture & Implementation Plan

## 1. IDEA (Short)

**Quality Oracle = active competency verification for AI agents, skills, and MCP servers.**

Every agent economy needs three layers: Identity (who is this agent?), Quality (is this agent competent?), Payment (how to pay?). Identity exists (SATI, ERC-8004). Payments exist (x402, AP2). Quality is missing. We fill that gap.

How: challenge-response benchmarking where Quality Oracle calls the agent/skill/server with calibrated test inputs, LLM-as-Judge evaluates responses, and results are published as W3C Verifiable Credentials portable across A2A, MCP, on-chain, and framework ecosystems.

First domain: MCP Servers (biggest pain point post-ClawHavoc, clearest test surface via JSON schemas, natural distribution as MCP Server itself).

---

## 2. ARCHITECTURE

### 2.1 System Overview

```
                    ┌──────────────────────────────────┐
                    │         CONSUMERS                │
                    │                                  │
                    │  IDE Users ──── MCP Server        │
                    │  Developers ─── REST API          │
                    │  Agents ─────── A2A Protocol      │
                    │  CI/CD ──────── GitHub Action      │
                    │  Marketplaces ─ Webhook/Badge API  │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────▼───────────────────────┐
                    │      QUALITY ORACLE SERVICE       │
                    │         (FastAPI, port 8002)      │
                    │                                  │
                    │  ┌─────────┐  ┌──────────────┐   │
                    │  │ REST API│  │ A2A Handler   │   │
                    │  │ /v1/*   │  │ JSON-RPC      │   │
                    │  └────┬────┘  └──────┬───────┘   │
                    │       │              │           │
                    │  ┌────▼──────────────▼───────┐   │
                    │  │    EVALUATION ENGINE       │   │
                    │  │                           │   │
                    │  │  ┌─────────────────────┐  │   │
                    │  │  │ Test Generator      │  │   │
                    │  │  │ (manifest → cases)  │  │   │
                    │  │  └─────────┬───────────┘  │   │
                    │  │            │              │   │
                    │  │  ┌─────────▼───────────┐  │   │
                    │  │  │ Challenge Runner    │  │   │
                    │  │  │ (MCP Client calls)  │  │   │
                    │  │  └─────────┬───────────┘  │   │
                    │  │            │              │   │
                    │  │  ┌─────────▼───────────┐  │   │
                    │  │  │ LLM Judge           │  │   │
                    │  │  │ (DeepSeek/Groq)     │  │   │
                    │  │  └─────────┬───────────┘  │   │
                    │  │            │              │   │
                    │  │  ┌─────────▼───────────┐  │   │
                    │  │  │ Scorer + Attestor   │  │   │
                    │  │  │ (UAQA / W3C VC)     │  │   │
                    │  │  └─────────────────────┘  │   │
                    │  └───────────────────────────┘   │
                    │                                  │
                    │  ┌───────────┐  ┌─────────────┐  │
                    │  │ MongoDB   │  │ Redis       │  │
                    │  │ quality__ │  │ (cache,     │  │
                    │  │ prefix    │  │  rate limit) │  │
                    │  └───────────┘  └─────────────┘  │
                    └──────────────────────────────────┘
                               │
                    ┌──────────▼───────────────────────┐
                    │    TARGETS BEING EVALUATED        │
                    │                                  │
                    │  MCP Servers (via MCP Client)     │
                    │  ClawHub Skills (65% are MCP)     │
                    │  REST API Agents (via HTTP)       │
                    │  A2A Agents (via A2A protocol)    │
                    └──────────────────────────────────┘
```

### 2.2 Directory Structure

```
quality-oracle/
├── src/
│   ├── main.py                     # FastAPI app entry, port 8002
│   ├── config.py                   # Env config (pydantic-settings)
│   │
│   ├── api/
│   │   ├── v1/
│   │   │   ├── evaluate.py         # POST /v1/evaluate
│   │   │   ├── scores.py           # GET /v1/score/{id}
│   │   │   ├── attestations.py     # GET /v1/attestation/{id}
│   │   │   ├── badges.py           # GET /v1/badge/{id}.svg
│   │   │   └── health.py           # GET /health
│   │   ├── a2a.py                  # POST /v1/a2a (A2A JSON-RPC)
│   │   ├── agent_card.py           # GET /.well-known/agent.json
│   │   └── webhooks.py             # Webhook delivery for async results
│   │
│   ├── core/
│   │   ├── evaluator.py            # Orchestrates full evaluation flow
│   │   ├── llm_judge.py            # Multi-provider LLM judging (from agent-poi)
│   │   ├── challenge_handler.py    # Challenge-response logic (from agent-poi)
│   │   ├── question_pools.py       # Domain question bank (from agent-poi)
│   │   ├── test_generator.py       # NEW: manifest → test cases auto-generation
│   │   ├── mcp_client.py           # NEW: MCP client to call target servers
│   │   ├── scoring.py              # Score aggregation, tiers, confidence
│   │   └── attestation.py          # UAQA format, W3C VC signing
│   │
│   ├── standards/
│   │   ├── a2a_extension.py        # A2A Agent Card quality extension
│   │   ├── mcp_server.py           # Quality Oracle as MCP Server (FastMCP)
│   │   ├── vc_issuer.py            # W3C Verifiable Credential issuance
│   │   └── badge_renderer.py       # SVG badge generation
│   │
│   ├── storage/
│   │   ├── mongodb.py              # quality__ collections
│   │   ├── cache.py                # Redis score cache + rate limiting
│   │   └── models.py               # Pydantic models for DB documents
│   │
│   └── auth/
│       ├── api_keys.py             # API key management (Redis-backed)
│       └── rate_limiter.py         # Per-key rate limiting
│
├── mcp-server/
│   ├── server.py                   # Standalone MCP Server (for PyPI)
│   └── pyproject.toml              # mcp-quality-oracle package
│
├── tests/
│   ├── test_evaluator.py
│   ├── test_llm_judge.py
│   ├── test_api.py
│   └── fixtures/                   # Mock MCP server responses
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt                # ~15 lean dependencies
├── openapi.yaml                    # OpenAPI 3.1 specification
├── .env.example
└── README.md
```

### 2.3 Key Dependencies (~15)

```
# Core
fastapi==0.115.*
uvicorn[standard]
pydantic==2.*
pydantic-settings

# LLM
openai                  # DeepSeek V3.2 via OpenAI-compatible API
groq                    # Fallback judge

# Storage
motor                   # Async MongoDB driver
redis[hiredis]          # Caching + rate limiting

# MCP Client
mcp                     # Official MCP SDK (to call target servers)

# Standards
PyJWT                   # VC signing (Ed25519)
cryptography            # Key management

# Utils
httpx                   # Async HTTP client
celery[redis]           # Async eval jobs (optional, can start with BackgroundTasks)
```

### 2.4 MongoDB Collections

```
quality__evaluations
  - _id, target_id, target_type (mcp_server|agent|skill)
  - target_url, target_manifest
  - status (pending|running|completed|failed)
  - level (1|2|3), questions_asked, questions_answered
  - scores: { overall, per_tool: { tool_name: score } }
  - llm_judge_model, llm_judge_responses
  - created_at, completed_at, duration_ms
  - attestation_id (ref to quality__attestations)

quality__scores
  - _id, target_id, target_type
  - current_score (0-100), tier (expert|proficient|basic|failed)
  - confidence, evaluation_count, trend (improving|stable|declining)
  - domain_scores: { domain: { score, questions, se } }
  - last_evaluated_at, next_evaluation_at
  - badge_url

quality__attestations
  - _id, evaluation_id, target_id
  - vc_document (full W3C VC JSON)
  - merkle_root, merkle_proof
  - issued_at, expires_at
  - revoked (bool), revoked_reason

quality__question_banks
  - _id, domain, difficulty, question_text
  - expected_behavior, scoring_rubric
  - source (manual|auto_generated), generator_model
  - irt_params: { discrimination, difficulty, se }
  - usage_count, exposure_count, last_used_at
  - variant_group_id

quality__api_keys
  - _id, key_hash, owner_email
  - tier (free|developer|team|marketplace)
  - rate_limit, monthly_quota, used_this_month
  - created_at, last_used_at, active (bool)
```

### 2.5 API Endpoints

```
# Core Evaluation
POST   /v1/evaluate              # Submit target for evaluation
  Body: { target_url, target_type, level?, domains[]?, webhook_url? }
  Returns: { evaluation_id, status: "pending", estimated_time_seconds }

GET    /v1/evaluate/{eval_id}    # Poll evaluation status
  Returns: { status, progress_pct, result? }

# Scores
GET    /v1/score/{target_id}     # Get quality score
  Returns: { score, tier, confidence, domains, last_evaluated, attestation_url }

GET    /v1/scores                # List/search scores
  Query: ?domain=&min_score=&tier=&sort=&limit=
  Returns: { items[], total, page }

# Attestations (W3C VC)
GET    /v1/attestation/{id}      # Get W3C Verifiable Credential
  Returns: Full UAQA VC document (JSON-LD)

GET    /v1/attestation/{id}/verify  # Verify attestation signature
  Returns: { valid, issuer, issued_at, expires_at }

# Badges
GET    /v1/badge/{target_id}.svg # SVG badge for README embedding
  Query: ?style=flat|flat-square|plastic
  Returns: SVG image

# A2A Protocol
POST   /v1/a2a                   # A2A JSON-RPC handler
  Methods: tasks/send, tasks/get, tasks/cancel
  Quality Oracle acts as A2A agent accepting evaluation tasks

# Agent Card (A2A Discovery)
GET    /.well-known/agent.json   # A2A Agent Card for Quality Oracle itself
  Returns: A2A-compliant agent card with capabilities

# MCP Server (separate process)
# Tools: check_quality, find_best, verify_attestation
# Resources: quality://scores/{id}, quality://attestations/{id}

# Admin
GET    /health                   # Health check
GET    /metrics                  # Prometheus metrics
```

### 2.6 Evaluation Flow (3 Levels)

```
Level 1: Manifest Validation (instant, free)
  ├── Fetch target manifest (MCP: server capabilities, Skill: SKILL.md)
  ├── Validate JSON schema completeness
  ├── Check: tool descriptions present? input/output schemas defined?
  ├── Check: error handling declared? security patterns?
  ├── Score: 0-100 on manifest quality
  └── Result: pass/fail + warnings

Level 2: Functional Testing (30-60s, paid)
  ├── Read manifest → extract tool definitions
  ├── Auto-generate test cases per tool:
  │   ├── Happy path (valid input → expected output type)
  │   ├── Edge case (boundary values, empty inputs)
  │   └── Error case (invalid input → graceful error)
  ├── Execute via MCP Client (connect → call tool → collect response)
  ├── For each response:
  │   ├── LLM Judge scores: relevance, correctness, completeness (0-10 each)
  │   ├── Measure latency
  │   └── Check error handling
  ├── Aggregate: per-tool scores → overall score
  └── Result: 0-100 score + per-tool breakdown

Level 3: Domain Expert Testing (2-5min, premium)
  ├── Identify domain from manifest (defi, code, data, etc.)
  ├── Pull calibrated questions from question bank
  ├── Challenge-response with domain-specific questions
  ├── LLM Judge with domain-specific rubric
  ├── IRT scoring (when enough data: adaptive termination)
  └── Result: Certification level (Expert/Proficient/Basic)
```

### 2.7 UAQA (Universal Agent Quality Attestation) Format

```json
{
  "@context": [
    "https://www.w3.org/2018/credentials/v1",
    "https://quality-oracle.assisterr.ai/schemas/v1"
  ],
  "type": ["VerifiableCredential", "AgentQualityAttestation"],
  "issuer": "did:web:quality-oracle.assisterr.ai",
  "issuanceDate": "2026-02-23T12:00:00Z",
  "expirationDate": "2026-03-25T12:00:00Z",
  "credentialSubject": {
    "id": "mcp://smithery.ai/servers/@example/my-server",
    "type": "mcp_server",
    "name": "My MCP Server",
    "qualityScore": 82,
    "tier": "proficient",
    "confidence": 0.91,
    "evaluationLevel": 2,
    "domains": ["code-generation"],
    "toolScores": {
      "generate_code": { "score": 87, "tests_passed": 8, "tests_total": 10 },
      "explain_code": { "score": 76, "tests_passed": 6, "tests_total": 8 }
    },
    "evaluationMethod": "challenge-response-v1",
    "questionsAsked": 18,
    "latencyP50ms": 340,
    "latencyP99ms": 1200,
    "evaluatedAt": "2026-02-23T12:00:00Z",
    "evaluationId": "eval_abc123"
  },
  "proof": {
    "type": "Ed25519Signature2020",
    "verificationMethod": "did:web:quality-oracle.assisterr.ai#key-1",
    "proofValue": "z..."
  }
}
```

**Maps into:**
- A2A Agent Card: `extensions.quality_oracle` field
- MCP Manifest: `quality` section in server info
- ERC-8004: `validationResponse()` payload
- SATI: Attestation schema data
- OpenAPI: `x-quality-attestation` extension
- ClawHub: Quality badge metadata

---

## 3. STANDARDS COMPATIBILITY

### 3.1 Integration Matrix

| Standard | How Quality Oracle Integrates | MVP? |
|----------|------------------------------|------|
| **Google A2A** | Quality Oracle IS an A2A agent; publishes Agent Card with quality extension | Yes |
| **Anthropic MCP** | Published as MCP Server on PyPI; evaluates MCP servers as primary target | Yes |
| **W3C VCs** | All attestations issued as Verifiable Credentials (UAQA format) | Yes |
| **OpenAPI 3.1** | Full API spec with x-quality extensions | Yes |
| **ERC-8004** | Implements ValidationRegistry interface (validationRequest/Response) | Week 5 |
| **SATI/Cascade** | Quality attestations as Token-2022 NFTs on Solana | Week 5 |
| **x402** | HTTP 402 payment gate for premium evaluations | Week 4 |
| **LangChain** | QualityOracleMiddleware package | Week 7 |
| **OpenClaw/ClawHub** | Evaluate skills (65% are MCP wrappers), quality badges | Week 3 |

### 3.2 Design Principles

1. **Extension-only** — never fork standards, use official extension mechanisms
2. **Protocol-agnostic evaluation** — same engine evaluates MCP servers, ClawHub skills, REST agents, A2A agents
3. **UAQA as canonical** — one internal format, multiple external projections
4. **Quality Oracle IS an A2A agent** — speaks A2A natively, not just extends it
5. **MCP-first distribution** — any IDE with MCP support gets instant access

---

## 4. IMPLEMENTATION PLAN (8 Weeks)

### Week 1: Core Service + Level 1 (Days 1-5)

**Day 1-2: Scaffold + Port**
- [ ] Create `quality-oracle/` directory in monorepo
- [ ] Setup FastAPI app with config, health endpoint
- [ ] Port from agent-poi: `llm_judge.py`, `challenge_handler.py`, `question_pools.py`
- [ ] Setup MongoDB connection (motor), create quality__ collections
- [ ] Setup Redis connection (cache + rate limiting)

**Day 3-4: Level 1 + MCP Client**
- [ ] Implement MCP Client wrapper (connect to target server, list tools)
- [ ] Level 1: manifest validation (schema check, description completeness)
- [ ] `POST /v1/evaluate` endpoint (async job queue)
- [ ] `GET /v1/evaluate/{id}` endpoint (poll status)
- [ ] `GET /v1/score/{id}` endpoint
- [ ] API key management (Redis-backed, simple hash)

**Day 5: Test + Evaluate**
- [ ] Evaluate 20 popular MCP servers from Smithery
- [ ] Collect Level 1 results
- [ ] Basic rate limiting
- [ ] Docker setup (Dockerfile + docker-compose.yml)

**Deliverable:** Working API that accepts MCP server URLs and returns manifest quality scores.

---

### Week 2: Level 2 + Badges (Days 6-10)

**Day 6-7: Test Auto-Generation**
- [ ] Test generator: read tool manifest → generate test cases (happy path, edge, error)
- [ ] Claude Sonnet for initial test case generation per domain ($0.05/domain)
- [ ] Challenge runner: connect to MCP server → call tools → collect responses

**Day 8-9: LLM Judging + Scoring**
- [ ] DeepSeek V3.2 as primary judge (relevance, correctness, completeness: 0-10 each)
- [ ] Groq Llama fallback
- [ ] Score aggregation: per-tool → per-domain → overall (0-100)
- [ ] Tier assignment: Expert (85+), Proficient (70-84), Basic (50-69), Failed (<50)
- [ ] SVG badge generation (`GET /v1/badge/{id}.svg`)

**Day 10: First X Post**
- [ ] Evaluate top 20 MCP servers with Level 2
- [ ] Deploy to Fargate
- [ ] Prepare results visualization
- [ ] **X thread: "We evaluated the top 20 MCP servers. Results inside."**

**Deliverable:** Full Level 1+2 evaluation with quality scores and badges. First public announcement.

---

### Week 3: MCP Server + ClawHub Scan (Days 11-15)

**Day 11-12: Quality Oracle as MCP Server**
- [ ] Implement FastMCP server with tools:
  - `check_quality(server_url)` → score + report
  - `find_best(domain, min_score)` → ranked list
  - `verify_attestation(attestation_id)` → validity
- [ ] `mcp-quality-oracle` PyPI package
- [ ] Publish on Smithery, Glama.ai, PulseMCP

**Day 13-14: Mass Scan**
- [ ] Scan all MCP servers on Smithery (1000+)
- [ ] Generate quality distribution report
- [ ] Identify worst offenders and best picks
- [ ] OpenClaw skill wrapper (evaluate ClawHub skills that are MCP wrappers)

**Day 15: Landing Page + Report**
- [ ] Landing page (Vercel): problem statement, live demo, "Get API Key"
- [ ] Full scan report with data visualizations
- [ ] **X thread: "We scanned 1,247 MCP servers. 23% fail basic tests."**

**Deliverable:** Quality Oracle available as MCP Server in IDE. Mass scan report published.

---

### Week 4: x402 + W3C VCs + A2A (Days 16-20)

**Day 16-17: W3C Verifiable Credentials**
- [ ] Ed25519 key pair generation and management
- [ ] UAQA VC issuance on evaluation completion
- [ ] `GET /v1/attestation/{id}` endpoint
- [ ] `GET /v1/attestation/{id}/verify` endpoint
- [ ] Attestation expiry (30 days default)

**Day 18-19: A2A Protocol Compliance**
- [ ] `GET /.well-known/agent.json` — Quality Oracle Agent Card
- [ ] `POST /v1/a2a` — JSON-RPC handler (tasks/send, tasks/get)
- [ ] Quality extension schema for other agents' Agent Cards
- [ ] A2A task flow: receive evaluation request → process → return result

**Day 20: x402 Integration**
- [ ] HTTP 402 payment gate for Level 2+ evaluations
- [ ] x402 facilitator integration for accepting payments
- [ ] Free tier: Level 1 only, 10 evals/month
- [ ] **X thread: "Quality Oracle + x402 = trust before you pay."**

**Deliverable:** Standards-compliant service with VCs, A2A, and x402.

---

### Week 5-6: On-Chain + Assisterr Integration (Days 21-30)

**Day 21-23: Solana On-Chain**
- [ ] SATI SDK integration for quality attestations
- [ ] Merkle audit trail (from hackathon code, 99.97% cost reduction)
- [ ] On-chain score lookup
- [ ] ERC-8004 compatibility layer

**Day 24-26: Assisterr Platform**
- [ ] Quality badges on SLM Store agents
- [ ] Add quality_score, quality_badges to incentive__slm_agents schema
- [ ] Dashboard endpoint for quality trends
- [ ] Webhook notifications on evaluation complete
- [ ] **X thread: "Quality Oracle goes on-chain via SATI."**

**Day 27-30: Level 3 + Question Bank**
- [ ] Domain-specific question banks (5 domains: code, defi, data, search, general)
- [ ] Auto-generation pipeline: domain description → Claude Sonnet → questions
- [ ] Level 3 certification flow
- [ ] 7-day per-agent re-evaluation cooldown
- [ ] **X thread: "Assisterr agents now verified by Quality Oracle."**

**Deliverable:** On-chain attestations, Assisterr integration, Level 3 certification.

---

### Week 7-8: Distribution + Frameworks (Days 31-40)

**Day 31-33: Framework SDKs**
- [ ] LangChain middleware: `pip install langchain-quality-oracle`
- [ ] OpenAI function calling tool definitions
- [ ] CrewAI guardrail function
- [ ] Code examples + tutorials

**Day 34-36: CI/CD + GitHub Action**
- [ ] GitHub Action: `quality-oracle/evaluate@v1`
- [ ] Quality gate: fail CI if score < threshold
- [ ] Publish on GitHub Marketplace

**Day 37-38: API Self-Service**
- [ ] API key signup on landing page (email + Stripe)
- [ ] Usage dashboard
- [ ] Documentation (API reference, tutorials, examples)

**Day 39-40: Partnerships**
- [ ] Smithery integration proposal (quality badges in registry)
- [ ] SendAI Agent Kit plugin
- [ ] Content: Show HN, r/LangChain, Dev.to tutorial
- [ ] **X thread: "Quality Oracle is now a GitHub Action."**

**Deliverable:** Framework SDKs, CI/CD integration, self-service API, partnership outreach.

---

## 5. COST MODEL

### 5.1 Infrastructure

| Component | Monthly Cost |
|-----------|-------------|
| Fargate (0.25 vCPU, 0.5GB) | $15-30 |
| MongoDB Atlas (shared with Assisterr) | $0 |
| Redis (shared with Assisterr) | $0 |
| Domain + SSL | ~$1 |
| **Infra Total** | **~$20-30/mo** |

### 5.2 LLM Costs (per evaluation)

| Level | Model | Cost/eval |
|-------|-------|-----------|
| Level 1 (manifest) | No LLM needed | $0.00 |
| Level 2 (functional, 10 tools avg) | DeepSeek V3.2 | $0.006 |
| Level 3 (domain, 30 questions) | DeepSeek V3.2 | $0.018 |
| Question generation (one-time/domain) | Claude Sonnet | $0.05 |

### 5.3 Projected Monthly Costs

| Phase | Evals/day | LLM/mo | Infra/mo | Total/mo |
|-------|-----------|--------|----------|----------|
| Week 1-4 (launch) | 20-50 | $4-9 | $25 | ~$30-35 |
| Month 2-3 (growth) | 100-300 | $18-54 | $30 | ~$50-85 |
| Month 6 (scale) | 1,000 | $180 | $50 | ~$230 |

---

## 6. SUCCESS METRICS

| Metric | Week 2 | Week 4 | Week 8 |
|--------|--------|--------|--------|
| Servers/skills evaluated | 50 | 500 | 2,000 |
| API calls/day | 100 | 500 | 2,000 |
| API keys issued | 20 | 100 | 500 |
| X followers | 200 | 1,000 | 3,000 |
| MCP Server installs | 50 | 200 | 1,000 |
| Quality badges displayed | 0 | 20 | 100 |
| Revenue | $0 | $0 | $290+ |

---

## 7. TECH DECISIONS LOG

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Separate FastAPI in monorepo | Independent deploy, lean deps, spin-off ready |
| Primary judge | DeepSeek V3.2 | Best cost/quality ratio ($0.006/eval) |
| Fallback judge | Groq Llama 3.3 70B | Fast, cheap ($0.002/eval), good enough |
| Question gen | Claude Sonnet (one-time) | Best quality for test case generation |
| DB | MongoDB (quality__ prefix) | Shared with Assisterr, consistent patterns |
| Cache | Redis | Shared with Assisterr, fast score lookup |
| VC signing | Ed25519 | Standard for W3C VCs, fast, secure |
| Async jobs | FastAPI BackgroundTasks → Celery | Start simple, scale when needed |
| MCP Client | Official mcp SDK | Standard, maintained by Anthropic |
| First domain | MCP Servers | Biggest pain, clearest test surface, natural distribution |
| On-chain | SATI/Cascade on Solana | Cheapest ($0.002/attestation), Solana ecosystem fit |
