# Wai — AI Partner in Telegram

**Bot**: @waicomputer_bot | **Server**: 89.167.125.46 | **Domain**: telegram.waiwai.is

## What It Is

A personal AI partner in Telegram. Remembers conversations, summarizes voice messages, tracks commitments, searches by meaning, analyzes photos, extracts documents — all in 13 languages.

## Architecture

```
Telegram → Webhook → Intent Router → Model Router → Agent Loop (Claude)
                                                      ↓
                                              7 Tools (search, digest, entities,
                                                       commitments, web, etc.)
                                                      ↓
                                              Response → Telegram
```

**Stack**: Python 3.12, FastAPI, PostgreSQL+pgvector, Deepgram Nova-3, Claude API, Telethon, Celery+Redis

## Agent Modules (`app/services/agent/`)

| Module | Purpose |
|--------|---------|
| `router.py` | Intent classification (30+ patterns EN/RU + Haiku fallback) |
| `soul.py` | 5-layer personality prompt (11 native languages) |
| `loop.py` | Agent execution with 7 tools + Claude tool_use |
| `metrics.py` | Counters + histograms (/metrics endpoint) |
| `commitments.py` | Promise detection (EN+RU) + DB persistence |
| `entities.py` | People/amounts/dates/decisions extraction |
| `language.py` | 13-language detection without LLM |
| `voice_summary.py` | Transcript + AI summary + entities + commitments |
| `briefing.py` | Morning briefing with [no_message] pattern |
| `inline.py` | Viral inline search in any chat |
| `forward_processor.py` | Forward anything → remember |
| `user_resolver.py` | Telegram ID → internal user + auto-create |
| `status.py` | User stats + system health |
| `typing.py` | "Wai is typing..." UX indicator |
| `conversation.py` | Session memory (last 20 messages) |
| `media_processor.py` | Photo Vision + document text extraction |

## Commands

| Command | Description |
|---------|------------|
| `/start` `/help` | Welcome + commands (EN/RU) |
| `/search <q>` | Semantic search messages |
| `/web <q>` | Web search via Claude |
| `/digest` | Daily AI summary |
| `/commitments` | Open promises |
| `/entities <text>` | Extract entities |
| `/briefing` | Morning briefing |
| `/status` | Stats + health |
| `/clear` | Reset conversation |
| Voice | Transcript + summary + entities |
| Photo | Claude Vision + entities |
| Document | Text extraction |
| Forward | Remember anything |
| Inline | `@waicomputer_bot q` |

## Tests & CI

- 212+ agent tests, 480+ total, 61% coverage
- CI: GitHub Actions → lint → format → test → deploy
- Auto-deploy on push to main
