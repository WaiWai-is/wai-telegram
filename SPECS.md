# Wai — AI Partner in Telegram

**Bot**: @waicomputer_bot | **Server**: 89.167.125.46 | **Domain**: telegram.waiwai.is

## What It Is

A personal AI partner in Telegram that generates websites, presentations, tables, and documents; creates autonomous AI agents; searches 106K+ synced messages by meaning; transcribes voice; tracks commitments — in 13 languages.

## Architecture

```
Telegram → Webhook → Intent Router → Model Router → Agent Loop (Claude)
                                                      ↓
                                              Tools (search, web, digest,
                                                     entities, commitments)
                                                      ↓
                                              Response → Telegram

Content Generation:
  /build → Claude Sonnet 4 → HTML (Tailwind+Alpine) → Cloudflare Pages → Screenshot → Telegram
  /slides → Claude Sonnet 4 → reveal.js HTML → Cloudflare Pages
  /table → Claude Sonnet 4 → AG Grid HTML → Cloudflare Pages
  /doc → Claude Sonnet 4 → Print CSS HTML → Cloudflare Pages

Agent System:
  /agent create → Claude Haiku parses → DB → Celery Beat (cron) → Execute → Telegram
```

**Stack**: Python 3.12, FastAPI, PostgreSQL+pgvector, Celery+Redis, Claude API (Sonnet 4 + Haiku), Deepgram Nova-3, Cloudflare Pages (wrangler CLI), Microlink (screenshots)

## Commands

### Content Generation
| Command | Description |
|---------|------------|
| `/build <desc>` | Generate website (Tailwind+Alpine+Lucide, 8 themes) |
| `/build --theme <name> <desc>` | Build with specific theme |
| `/edit <changes>` | Edit last built site |
| _"make it darker"_ | Conversational edit (no slash command needed) |
| `/slides <topic>` | Generate reveal.js presentation |
| `/table <desc>` | Generate AG Grid interactive table |
| `/doc <desc>` | Generate print-ready document (A4 CSS) |
| `/doc-edit <changes>` | Edit last document |
| `/sites` | List all deployments |

### AI Agents
| Command | Description |
|---------|------------|
| `/agent create <desc>` | Create autonomous agent with cron schedule |
| `/agent list` | Show your agents |
| `/agent run <id>` | Trigger manually |
| `/agent delete <id>` | Remove agent |

### Memory & Search
| Command | Description |
|---------|------------|
| `/search <q>` | Semantic search across 106K+ messages |
| `/briefing` | Morning digest |
| `/commitments` | Open promises |

### Other
| Command | Description |
|---------|------------|
| `/start` `/help` | Welcome + commands (EN/RU) |
| `/status` | Stats + health |
| `/summarize <text>` | AI summary |
| `/web <q>` | Web search |
| `/entities <text>` | Extract entities |
| `/clear` | Reset conversation |
| Voice message | Transcript + summary + entities |
| Photo | Claude Vision description |
| Document | Text extraction |
| Forward | Remember anything |

## Agent Modules (`app/services/agent/`)

| Module | Purpose |
|--------|---------|
| `router.py` | Intent classification (30+ patterns EN/RU, 8 intents including EDIT) |
| `soul.py` | 5-layer personality prompt with recalled memories |
| `loop.py` | Agent execution with tools + Claude tool_use |
| `site_builder.py` | Website generation + themes + Redis persistence |
| `presentation_builder.py` | reveal.js slide generation |
| `table_builder.py` | AG Grid table generation |
| `document_builder.py` | Print-ready document generation |
| `digital_agents.py` | Autonomous agent CRUD + cron scheduling |
| `html_validator.py` | Pre-deploy quality validation |
| `screenshot_service.py` | Microlink screenshot API |
| `web_search.py` | DuckDuckGo search for agents |
| `cloudflare_deploy.py` | Wrangler CLI deployment |
| `voice_summary.py` | Transcript + AI summary + entities |
| `commitments.py` | Promise detection + DB persistence |
| `entities.py` | People/amounts/dates extraction |
| `language.py` | 13-language detection |
| `conversation.py` | Session memory (last 20 messages) |
| `media_processor.py` | Photo/document processing |

## Themes

8 presets: `default`, `dark-corporate`, `warm-organic`, `neon-startup`, `clean-minimal`, `luxury-gold`, `fresh-modern`, `retro-vintage`

## Tests & CI

- 768+ tests, CI green
- Pre-push hook: ruff check + format
- Auto-deploy on push to main via GitHub Actions
