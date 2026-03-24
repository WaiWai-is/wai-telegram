# Wai — AI Partner in Telegram: Memory + Build + Chief of Staff

## Context

After 37+ research agents, 3 deep research reports, and analysis of 5 existing projects (wai-telegram, wai-rocks, wai-computer, wai-uni, wai-agents), we identified the product:

> **7-9.5 billion voice messages sent daily. Zero are searchable. Nobody owns the knowledge layer on top of messaging.**

This is the Steinberger moment: STT APIs + Telegram + Knowledge Graph = obvious connection nobody made as a consumer product.

**We already have 90% of the infrastructure** in wai-telegram (deployed, working, production-grade). The plan is to turn it into a beautiful, global, lovable product.

**Market**: Global-first (English + multi-language). Russia via VPN as bonus market (Telegram blocked to 19% availability as of March 22, 2026). Target: 900M+ Telegram users worldwide.

---

## What We're Building

**One sentence**: An AI partner in Telegram that remembers your entire conversation history, builds sites/bots/apps from your context, and proactively manages your professional life.

**Tagline**: "Memory. Build. Manage. From Telegram."

### Three Core Superpowers:

1. **MEMORY** — Knows your ENTIRE Telegram history. Searchable by meaning. Voice messages transcribed. Knowledge graph of people, topics, decisions, commitments.

2. **BUILD** — "Wai, build me a landing page from my conversation with the designer." → deployed site in minutes. Creates bots, apps, infrastructure — all from chat context.

3. **CHIEF OF STAFF** — Meeting prep from your real conversations. Project tracking from chat. Commitment tracking. Daily briefs. Email/calendar management.

---

## Five Existing Projects → One Product

| Project | What it contributes | Status |
|---------|-------------------|--------|
| **wai-telegram** | Core: Telethon sync, Deepgram transcription, pgvector search, Claude digests, MCP server | **Deployed, production** |
| **wai-rocks** | Telegram Mini App, 12 languages, subscriptions/payments, ElevenLabs TTS, Cohere reranking, hybrid RAG | **Live with users** |
| **wai-computer** | Knowledge graph, entity extraction (people/topics/projects), action items, highlights, search API | **Deployed, production** |
| **wai-uni** | Teaching/coaching system, skill levels (1-6), best practices library, bilingual prompts | **Deployed** |
| **wai-agents** | Agent loop, MCP tools, memory system (decay, consolidation), proactive system, BullMQ jobs | **Code ready** |

---

## Architecture

```
Telegram User
  ↓
Telethon Userbot (wai-telegram — already working)
  ↓ syncs ALL messages in realtime
PostgreSQL + pgvector (already working)
  ↓ embeddings (OpenAI text-embedding-3-small)
  ↓ voice transcription (Deepgram Nova-3)
  ↓ entity extraction (Claude — ADD from wai-computer)
  ↓
Three interfaces:
  1. Telegram Bot (@wai_bot) — chat, ask questions, get answers
  2. Telegram Mini App — beautiful search, digests, entity graph, timeline
  3. MCP Server — Claude integration (already working)
```

---

## Implementation: Three Levels

### Level 1: "Telegram, But Searchable" (Week 1)

**Goal**: Beautiful Mini App + polished bot on top of existing wai-telegram infrastructure.

**What already works (just needs polish):**
- Message sync (Telethon) ✅
- Voice transcription (Deepgram Nova-3) ✅
- Semantic search (pgvector + HNSW) ✅
- Daily AI digest (Claude Sonnet) ✅
- MCP server ✅

**What to build:**

1. **Beautiful Telegram Mini App** (React, opens inside Telegram)
   - Semantic search bar — "What did Alex say about pricing?"
   - Daily digest view — beautiful cards, not raw text
   - Chat list with AI summaries
   - Voice message player with transcripts inline
   - Dark mode, minimal, fast

2. **Polish the bot** (@wai_bot)
   - Natural language questions → search results from your messages
   - Forward anything → it processes and remembers
   - `/digest` — today's summary
   - `/search query` — find anything

3. **Onboarding flow**
   - Connect Telegram account (phone number → code → synced)
   - Instant value: "You have 14,237 messages. 892 voice messages transcribed. Try searching!"
   - First "wow" in under 60 seconds

4. **Monetization from day 1** (Telegram Stars)
   - Free: 50 searches/month, 7-day digest history
   - Pro ($12/mo via Stars): unlimited search, full history, entity graph, proactive features

**Files to modify:**
- `wai-telegram/packages/frontend/` — rebuild as Telegram Mini App
- `wai-telegram/packages/backend/app/api/` — add Mini App auth endpoints
- `wai-telegram/packages/backend/app/services/search_service.py` — polish search UX

**Files to create:**
- Mini App components (search, digest, chat view, onboarding)
- Bot command handlers for natural language questions
- Telegram Stars payment integration

### Level 2: "Knowledge Graph" (Month 1)

**Goal**: Extract entities, track commitments, cross-conversation intelligence.

1. **Entity extraction pipeline** (port from wai-computer)
   - After each message batch: extract people, topics, decisions, commitments
   - Schema: `entities` (name, type, embedding) + `entity_relations` (source, target, type)
   - Store in PostgreSQL (same DB)

2. **Commitment tracking**
   - Detect "I'll send...", "Let's meet on...", "You promised..."
   - Both directions: what YOU promised, what OTHERS promised
   - Proactive reminders: "Alex said he'd send the contract by Friday. It's Saturday."

3. **Cross-conversation intelligence**
   - "You discussed budget with 3 different people this week. Here are all the numbers mentioned."
   - Connect entities across chats automatically

4. **Mini App: Entity pages**
   - Person page: all conversations with them, topics discussed, commitments
   - Topic page: every mention across all chats, timeline of how it evolved
   - Decision log: what was decided, when, by whom

**Files to create:**
- `packages/backend/app/services/entity_service.py` (port from wai-computer)
- `packages/backend/app/tasks/entity_extraction_tasks.py`
- `packages/backend/app/models/entity.py`
- Mini App entity views

### Level 3: "AI Partner" (Month 2-3)

**Goal**: Actions, teaching, voice responses, group memory.

1. **Actions** (from wai-agents)
   - Email (Gmail/Outlook OAuth): read, send, reply
   - Calendar (Google): view, create, update events
   - "Based on this conversation, I created a calendar event for Tuesday at 3pm"

2. **Teaching layer** (from wai-uni)
   - Coach mode: analyze user's prompting patterns
   - Best practices injected contextually
   - "Here's a prompt to ask Claude Code about this — and here's why it works"

3. **Voice responses** (from wai-rocks)
   - ElevenLabs TTS: Wai responds with voice in Telegram
   - Full voice conversation: you speak → Wai speaks back

4. **Group chat memory mode**
   - Add @wai_bot to a group → becomes the group's memory
   - Anyone can ask "What did we decide about X?"
   - Daily group digest

5. **Proactive intelligence**
   - Morning briefing: today's meetings, unresolved commitments, important messages overnight
   - Meeting prep: 15 min before calendar event → everything you discussed with attendees
   - Weekly review: decisions made, commitments status, topics trending

---

## Viral Mechanics

1. **Inline mode**: `@wai_bot what did we discuss about pricing` in ANY chat → paste result → everyone sees → "How does it know that?"
2. **Shareable digest cards**: Beautiful weekly summary → share to social media
3. **Group memory demo**: Add bot to group → ask question about past discussion → wow moment for entire group
4. **"60 seconds to wow"**: Connect Telegram → instantly see all your voice messages transcribed → search → magic

---

## Monetization

| Tier | Price | What |
|------|-------|------|
| Free | $0 | 50 searches/mo, 7-day digests, basic transcription |
| Pro | $12/mo (Telegram Stars) | Unlimited search, full history, entity graph, proactive, actions |
| Team | $20/user/mo | Group memory, shared knowledge, admin controls |

Credits via Stars: 14% free-to-paid conversion (proven in AI Telegram bots).

---

## Key Technical Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Base infrastructure | **wai-telegram** (as-is) | Already deployed, Telethon sync working, pgvector, digests |
| Mini App framework | **React** (from wai-rocks pattern) | Already have Mini App experience |
| Bot framework | **Telethon** (already in wai-telegram) | Userbot access, not limited by Bot API |
| Entity extraction | **Port from wai-computer** | Already has models, pipeline, proven |
| Teaching | **Port from wai-uni** | Coach mode, best practices, skill levels |
| Voice I/O | **Deepgram (STT) + ElevenLabs (TTS)** from wai-rocks | Already integrated |
| Payments | **Telegram Stars** | Zero friction, native, no Stripe needed |
| Market | **Global-first** (English + multi-language) | Russia blocked (19% availability), 900M+ global users |
| Repo | **wai-telegram** (evolve existing) | Already deployed, production-grade |

---

## Critical Files

| File | Role | Action |
|------|------|--------|
| `wai-telegram/packages/backend/app/services/search_service.py` | Semantic search | Polish, add natural language queries |
| `wai-telegram/packages/backend/app/services/digest_service.py` | Daily digest | Add entity extraction, commitment tracking |
| `wai-telegram/packages/backend/app/listener/main.py` | Realtime message capture | Add entity extraction trigger |
| `wai-telegram/packages/backend/app/tasks/sync_tasks.py` | Batch sync | Add voice transcription for old messages |
| `wai-telegram/packages/frontend/` | Web UI | Rebuild as Telegram Mini App |
| `wai-telegram/packages/mcp-server/` | MCP tools | Keep as-is, extend with entity tools |
| `wai-computer/backend/app/core/summarizer.py` | Entity extraction | Port to wai-telegram |
| `wai-computer/backend/app/models/entity.py` | Entity schema | Port to wai-telegram |
| `wai-rocks/app.py` | Voice I/O, payments, Mini App | Reference patterns |
| `wai-uni/backend/app/agent/coach.py` | Teaching/coaching | Port to wai-telegram |

---

---

## Overnight Build Loop Strategy

Work in wai-telegram repo (`/Users/mikwiseman/Documents/Code/wai-telegram`). Each cycle = 1 feature, fully tested.

### Cycle 1: Foundation (Tests + Metrics + Logging)
- Set up pytest with 100% coverage target
- Add structured logging (structlog) across all services
- Add Prometheus metrics endpoint (/metrics)
- Key metrics: messages_synced, searches_performed, voice_transcribed, digest_generated, api_latency
- Verify existing tests pass, add missing coverage

### Cycle 2: Bot Polish
- Natural language questions to @wai_bot → search results
- Forward any message → processed + stored
- `/search query` → semantic search results
- `/digest` → today's AI summary
- Tests for all bot commands

### Cycle 3: Mini App Foundation
- Telegram Mini App (React) with auth via Telegram WebApp API
- Search page: semantic search bar + results
- Digest page: beautiful daily summary cards
- Tests for Mini App API endpoints

### Cycle 4: Entity Extraction
- Port entity extraction from wai-computer
- After message sync: extract people, topics, decisions, commitments
- Entity pages in Mini App: person → conversations + commitments
- Tests for extraction pipeline

### Cycle 5: Commitment Tracking
- Detect promises in messages ("I'll send...", "Let me...")
- Bi-directional: what you promised, what others promised
- Proactive reminders via bot
- Tests for detection + reminder logic

### Cycle 6: Voice Summary
- Forward voice message → instant summary + key points + action items
- Voice messages > 60s get auto-summarized
- Tests for summary pipeline

### Cycle 7: Deploy/Build from Chat
- "Wai, deploy a site with this content" → creates + deploys static site
- "Wai, create a Telegram bot that does X" → generates + deploys bot
- Integration with E2B or similar sandbox for code execution
- Tests for deploy pipeline

### Cycle 8: Proactive Intelligence
- Morning briefing (daily, configurable hour)
- Meeting prep (from Google Calendar integration)
- Weekly review digest
- Tests for scheduling + delivery

### Cycle 9: Inline Oracle
- @wai_bot query in any chat → search results from your memory
- Inline mode registration + handler
- Tests for inline queries

### Cycle 10: Contact Pages + Relationship Intelligence
- Auto-generated pages per contact
- Conversation history, topics, commitments, shared files
- Communication patterns + ghost detection
- Tests for entity aggregation

---

## Quality Requirements (Every Cycle)

- **Tests**: 100% coverage for new code, pytest + pytest-asyncio
- **Logging**: Every significant action logged with structlog
- **Metrics**: Prometheus counters/histograms for all operations
- **Type checking**: mypy strict mode
- **Linting**: ruff check + format
- **CI**: All checks must pass before deploying
- **Deploy**: Auto-deploy on push to main (existing GitHub Actions)

---

## Verification

After Level 1:
1. Connect Telegram account → messages sync within 5 minutes
2. Search "what did [name] say about [topic]" → get relevant results including from voice messages
3. Open Mini App → see beautiful digest + search
4. Telegram Stars payment → Pro tier activates
5. Forward voice message → transcribed + searchable

After Level 2:
6. Entity page for a person → all conversations, topics, commitments
7. "What did others promise me this week?" → commitment list with status
8. Cross-conversation search finds connections user didn't see

After Level 3:
9. "Send Alex an email about the meeting" → email sent
10. Morning briefing arrives proactively
11. Ask question in group → bot answers from group history
