# EuroMario

> **A personal, automated gaming-news radar that filters the noise, groups duplicate stories, uses AI to rank and summarize what matters, and publishes the result as a fast static website.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-265%20passed-2ea44f?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Lint](https://img.shields.io/badge/Ruff-clean-D7FF64?logo=ruff&logoColor=111111)](https://docs.astral.sh/ruff/)
[![GitHub Actions](https://img.shields.io/badge/automation-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/features/actions)
[![GitHub Pages](https://img.shields.io/badge/deployed-GitHub%20Pages-222222?logo=githubpages&logoColor=white)](https://pages.github.com/)

**Live site:** https://mariomunpeq.github.io/Euromario/

EuroMario is a zero-infrastructure gaming news digest built as a portfolio project. It continuously collects gaming news from specialist publications, Steam and Reddit, detects the game each story is about, groups related articles into stories, enriches the survivors with AI, and publishes the resulting dataset to a vanilla JavaScript frontend hosted on GitHub Pages.

The project deliberately avoids a traditional backend, database and paid infrastructure. The repository itself acts as the data store and GitHub Actions acts as the scheduler and deployment pipeline.

---

## ✦ What EuroMario does

EuroMario is designed around one simple question:

> **"What happened in the games I actually care about?"**

Instead of dumping every article from a collection of gaming sites onto a page, the pipeline progressively reduces the noise:

```text
RSS / Steam / Reddit
        │
        ▼
   Fetch & normalize
        │
        ▼
   Quality exclusions
        │
        ▼
   Game matching / detection
        │
        ▼
 Story clustering / deduplication
        │
        ▼
 Per-game pre-selection
        │
        ▼
   AI enrichment
   ├─ summary
   ├─ relevance 1–5
   └─ category
        │
        ▼
 Per-game ranking
        │
        ▼
 ~24-hour retention (daily)
 + 200-item cap
        │
        ▼
 Atomic JSON storage
        │
        ▼
 GitHub commit
        │
        ▼
 Static GitHub Pages site
```

### Core features

- **Multiple news sources** through RSS.
- **Official Steam news** through the Steam News API.
- **Reddit community coverage** through subreddit RSS.
- **Curated game tracking** with canonical names and aliases.
- **News from any game, no whitelist needed**: games outside `config/games.yaml` are still published (Steam app name, title detection or a generic label).
- **Blacklist support** for games that should never appear.
- **Robust matching** designed to avoid naive substring false positives.
- **Story clustering** to reduce duplicate coverage of the same event.
- **AI relevance scoring** from 1 to 5.
- **AI categorization** into release, update, rumor and analysis.
- **AI-generated short summaries**, instructed to be written in English.
- **Ollama local inference** with a Groq cloud fallback.
- **Graceful AI failure handling** so one bad response does not destroy the whole run.
- **Pre-AI per-game limiting** to avoid wasting inference calls on stories that cannot survive the final cap.
- **Cheap pre-ranking before AI** that cuts the workload to ~40-60 stories per run.
- **~24-hour rolling news retention** (daily digest window, with a 2-hour tolerance).
- **200-item global storage cap**.
- **Atomic JSON writes** for safer publication data.
- **Vanilla HTML/CSS/JavaScript frontend** with no framework or build step.
- **Responsive game/platform filter tiles**.
- **News / Rumors sections**.
- **URL-synchronized filters** so views can be shared or refreshed without losing state.
- **GitHub Actions daily automation** (a fresh digest every morning, ~09:00 Madrid time).
- **GitHub Pages hosting** with no server to maintain.

---

## 🧠 Why the pipeline is structured this way

A straightforward implementation would send every matched article to an LLM and then display whatever came back. That is expensive, slow and noisy.

EuroMario instead treats the pipeline as a series of increasingly selective stages.

### 1. Fetch

Configured sources are queried and normalized into a common `FetchedItem` representation.

Current source families:

| Source | Mechanism | Verification |
|---|---|---|
| IGN | RSS | Verified publication |
| Eurogamer | RSS | Verified publication |
| PC Gamer | RSS | Verified publication |
| Polygon | RSS | Verified publication |
| Rock Paper Shotgun | RSS | Verified publication |
| Steam | Steam News API | Official/verified |
| Reddit | Subreddit RSS | Community / unverified |

Sources are configured in [`config/sources.yaml`](config/sources.yaml).

### 2. Quality filtering

Configured title and URL patterns can reject known low-value or unwanted content before it reaches the game matcher.

Examples include hardware, humor, certain list-style pages and other patterns that are known to create noise for this particular digest.

### 3. Game matching

[`matcher.py`](src/gaming_news_digest/filtering/matcher.py) maps articles to canonical games using inclusion and exclusion rules.

Each followed game can define:

- a canonical name;
- aliases and abbreviations;
- an optional frontend logo;
- supported platforms.

The exclusion list has priority over inclusion.

The matcher also uses word boundaries and other heuristics so short aliases such as `GTA` do not accidentally match arbitrary substrings.

### 4. Story clustering

Several publications can cover exactly the same event. Showing all of them as separate stories makes the digest feel much larger than it really is.

The clustering stage groups related items and selects a representative before AI processing.

### 5. Pre-AI per-game limit

This is one of the pipeline's most important performance optimizations.

The final digest limits the number of stories per game. Applying that limit only after AI processing would mean paying the inference cost for stories that are going to be discarded anyway.

EuroMario therefore applies the per-game cap twice:

1. **Before AI** — keep the most recent candidates while relevance is not known yet.
2. **After AI** — rank survivors by AI relevance and then publication date, preserving the final cap.

This can drastically reduce AI calls during source-heavy news cycles.

### 5b. Pre-AI ranking (the cheap cut)

The per-game caps alone can still leave the full workload above the daily-digest budget.

EuroMario therefore applies one more filter immediately before AI, keeping **at most 60 stories** ordered by cheap signals collected without an LLM:

- **recency** — fresher stories win (a 48-hour decay);
- **news value** — headlines containing words like *update, patch, announcement, trailer* get a bonus;
- **featured games** — stories already in `config/games.yaml` get a bonus;
- **verified sources** — non-Reddit publications get a small bonus;
- **Reddit floor** — a minimum of 8 rumors survive so the rumors section is never empty.

This ranking never *drops* a game or source family by itself: it only picks the strongest candidates to spend AI inference on.

### 6. AI enrichment

Surviving stories are passed through a common AI interface.

The model is asked to return structured data containing:

```json
{
  "summary": "...",
  "relevance": 5,
  "category": "lanzamiento",
  "language": "en"
}
```

The response is validated before becoming a `NewsItem`.

### 7. Retention

The stored digest is deliberately short-lived.

Current policy:

- **~24 hours rolling window** (26 hours with tolerance, matching the daily schedule);
- **200 items maximum**;
- **per-game limit remains enforced**.

The 24-hour window is inclusive: an item at exactly the cutoff is retained, while an item older than the cutoff is removed.

### 8. Publication

The final data is written to `frontend/data/news.json` and the games metadata to `frontend/data/games.json`.

GitHub Actions commits changes back to the repository. Because the frontend lives inside the repository, GitHub Pages can publish it without a backend server.

---

## 🤖 AI architecture

EuroMario uses a provider-neutral AI interface:

```text
                    ┌──────────────┐
                    │  AIClient    │
                    │  interface   │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
      ┌──────────────┐          ┌──────────────┐
      │   Ollama     │          │     Groq     │
      │ local model  │          │  cloud API   │
      └──────────────┘          └──────────────┘
```

### Ollama

The primary local client uses Ollama's HTTP API.

Default model:

```text
llama3.2:3b
```

The GitHub Actions workflow installs Ollama and pulls the configured model on the runner.

### Groq

Groq provides the cloud fallback through an OpenAI-compatible chat-completions endpoint.

Default model configured by the client:

```text
openai/gpt-oss-20b
```

The API key is read from:

```text
GROQ_API_KEY
```

### Failure handling

The AI layer distinguishes between invalid model output and infrastructure failures.

- Invalid structured output can be retried.
- Repeated Ollama validation failures can trigger a provider switch.
- Ollama connection/timeouts can switch the pipeline to Groq and retry the item.
- A Groq infrastructure failure is treated as critical.
- A failed item can receive a safe fallback instead of killing the entire run.
- Reddit is deterministically categorized as a rumor regardless of what the model returns.

The shared contract lives in [`ai/base.py`](src/gaming_news_digest/ai/base.py).

---

## 📰 Categories

Internally, the project uses these category values:

| Value | Frontend label | Meaning |
|---|---|---|
| `lanzamiento` | Release | Releases, launches or major launch-related announcements |
| `actualizacion` | Update | Updates, patches, ongoing changes or similar news |
| `rumor` | Rumor | Rumors and unverified claims, including Reddit content |
| `analisis` | Analysis | Analysis and editorial coverage |

Reddit content is always treated as a rumor by the pipeline and is marked as unverified in the data model.

---

## 🎮 Followed games

The current configuration includes:

- Grand Theft Auto
- Call of Duty
- Persona
- The Legend of Zelda
- Baldur's Gate 3
- Elden Ring
- Hollow Knight
- Pokemon
- PUBG
- Rainbow Six
- Roblox
- Cyberpunk 2077
- Final Fantasy VII
- Helldivers 2
- Starfield

The configuration also contains an exclusion for **EA Sports FC / FIFA**.

This list is a **featured set, not a whitelist**. News about any game is published even without an entry; editing [`config/games.yaml`](config/games.yaml) adds canonical aliases (recognition priority), logos and platform info, while `excluir` removes games entirely.

---

## 🔎 Frontend

The frontend is intentionally lightweight:

- HTML
- CSS
- vanilla JavaScript
- no React
- no Vue
- no build tool
- no frontend package dependency required at runtime

The browser loads the generated JSON and renders the interface client-side.

### Current UI

The site provides:

- **News** and **Rumors** sections.
- **Game filters** with SVG logos where available.
- **Platform filters** for PC / Steam, PlayStation, Xbox and Nintendo.
- Multi-select platform filtering.
- Single-select game filtering.
- Category filtering within the news view.
- Responsive filter tiles with a mobile horizontal carousel.
- Loading, empty and error states.
- News cards with source, date, category, game, relevance and summary information.
- Image support with a visual fallback when a source image is unavailable.
- URL synchronization for active filters.
- Accessibility-oriented semantics such as ARIA labels, roles and visible interaction states.

The frontend is implemented in:

```text
frontend/
├── index.html
├── css/
│   └── style.css
├── js/
│   └── app.js
├── assets/
│   ├── games/
│   ├── icons/
│   └── platforms/
└── data/
    ├── games.json
    └── news.json
```

---

## ⚙️ Configuration

### `config/games.yaml`

Controls the **featured games** (logos, aliases, platforms) and the **blacklist**.

```yaml
incluir:
  - nombre: Grand Theft Auto
    aliases: [GTA]
    platform: [pc, playstation, xbox]

excluir:
  - nombre: EA Sports FC
    aliases: [FIFA]
```

News about any other game is still published (Steam app name, title detection or a generic label); it just doesn't get a logo or a dedicated filter tile until you add it below.

For each included game you can configure:

- `nombre`
- `aliases`
- `logo`
- `platform`

### `config/sources.yaml`

Controls:

- media RSS feeds;
- Steam app IDs;
- Reddit subreddits;
- per-source item limits;
- HTTP timeout;
- per-game story cap;
- title exclusion patterns;
- URL exclusion patterns.

Current limits include:

```yaml
limites:
  max_items_por_fuente: 20
  timeout_segundos: 15
  max_stories_por_juego: 8
```

The retention window is implemented in code as **48 hours**, with a **200-item global cap**.

---

## 🚀 Running locally

### Requirements

- Python 3.12+
- Git
- Ollama if you want local inference
- A Groq API key if the Groq client is instantiated or used by the pipeline

Clone the repository:

```bash
git clone https://github.com/MarioMunPeq/Euromario.git
cd Euromario
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Or on Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the test suite:

```bash
pytest
```

Run linting:

```bash
ruff check src tests
```

Check syntax:

```bash
python -m compileall -q src tests
```

Run the pipeline:

```bash
python -m gaming_news_digest
```

The pipeline reads configuration from `config/` and writes generated data to `frontend/data/`.

---

## 🔐 Groq configuration

Create a Groq API key in GroqCloud and expose it as an environment variable:

```text
GROQ_API_KEY=your-key-here
```

For GitHub Actions, add it as a repository secret named:

```text
GROQ_API_KEY
```

The workflow passes it to the pipeline with:

```yaml
env:
  GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

**Never commit the key to the repository.**

> **Implementation note:** the current `Pipeline` constructor instantiates `GroqClient` immediately, so a local run without `GROQ_API_KEY` can fail during startup even when Ollama is available. This is an implementation detail of the current version, not a reason to put the key in source control.

---

## 🦙 Ollama configuration

Install Ollama and make sure the service is running locally.

Then pull the default model:

```bash
ollama pull llama3.2:3b
```

The client talks to:

```text
http://localhost:11434/api/generate
```

The GitHub Actions workflow performs the installation and model pull automatically on its runner.

Because GitHub-hosted runners do not provide the local NVIDIA/AMD GPU environment available on a desktop, Ollama in CI may run in CPU-only mode. For that reason the Groq fallback is particularly useful for CI performance.

---

## 🤖 AI output contract

Every AI response is validated before it becomes part of the published dataset.

Required fields:

```json
{
  "summary": "string",
  "relevance": 1,
  "category": "lanzamiento",
  "language": "en"
}
```

Constraints:

- `summary` must be non-empty.
- `relevance` must be an integer from 1 to 5.
- `category` must be one of the supported enum values.
- `language` must be a supported language value.

The current AI prompts instruct the model to write summaries in **English**, regardless of the source language.

---

## 🗃️ Data model

The generated `frontend/data/news.json` contains metadata such as:

```json
{
  "generated_at": "2026-08-28T09:15:24Z",
  "total": 104,
  "news": [
    {
      "id": "1cabe9eddc7e3d75",
      "title": "...",
      "summary": "...",
      "url": "https://...",
      "source": "Polygon",
      "source_type": "media",
      "game": "Grand Theft Auto",
      "game_id": null,
      "language": "en",
      "published_at": "2026-08-28T01:02:10Z",
      "fetched_at": "2026-08-28T04:09:07Z",
      "relevance": 5,
      "category": "lanzamiento",
      "image": "https://...",
      "author": "...",
      "is_verified": true
    }
  ]
}
```

The storage layer also contains compatibility handling for older Reddit records whose source information used an older nested representation.

---

## ⏱️ Retention policy

EuroMario is a **rolling digest**, not a permanent archive.

### Time limit

A story is retained while:

```text
published_at >= now - 48 hours
```

Exactly 48 hours old is retained by the current inclusive boundary convention.

### Global limit

The storage layer also enforces:

```text
max_total = 200
```

The two policies work together: an item can disappear because it is too old or because it falls outside the global capacity after the newest items have been retained.

### Per-game limit

The configured per-game cap is currently:

```text
8 stories per game
```

This limit is also used before AI inference to reduce unnecessary model calls.

---

## 🔄 GitHub Actions automation

The project uses a single workflow.

### News pipeline and GitHub Pages deployment

`.github/workflows/digest.yml`

Runs:

```text
Every day at 07:00 UTC (09:00 in Madrid during summer, 08:00 in winter;
GitHub Actions schedules in UTC only, see the workflow comment)
plus manual triggers via workflow_dispatch
```

The workflow:

1. checks out the repository;
2. installs Python 3.12;
3. restores pip cache;
4. installs Python dependencies;
5. restores the cached Ollama model;
6. installs and starts Ollama;
7. pulls the configured model (from cache when available);
8. runs `python -m gaming_news_digest`;
9. commits updated frontend data;
10. pushes the generated data back to `master`;
11. deploys `frontend/` to GitHub Pages (`configure-pages` → `upload-pages-artifact` → `deploy-pages`), only when all previous steps succeeded.

A concurrency group prevents overlapping digest executions.

Manual frontend changes are deployed by triggering the workflow with `workflow_dispatch`.

---

## 🧪 Testing

The project has a substantial pytest suite covering the core pipeline.

Latest repository verification for this version:

```text
303 passed
Ruff: All checks passed
Python syntax: OK
```

The tests cover areas including:

- game matching;
- aliases and false-positive prevention;
- inclusion/exclusion precedence;
- story clustering;
- retention boundaries;
- 200-item cap;
- per-game limits;
- JSON storage;
- historical data compatibility;
- configuration parsing;
- RSS parsing;
- Reddit parsing;
- Steam parsing;
- AI response validation;
- Ollama behavior;
- Groq behavior;
- pipeline fallback behavior.

Run everything with:

```bash
pytest -q
```

Lint:

```bash
ruff check src tests
```

Syntax verification:

```bash
python -m compileall -q src tests
```

---

## 🧩 Project structure

```text
.
├── .github/
│   └── workflows/
│       └── digest.yml              # daily news pipeline (~09:00 Madrid) + GitHub Pages deployment
│
├── config/
│   ├── games.yaml                  # featured games & blacklist
│   └── sources.yaml                # feeds, Steam IDs, Reddit, limits
│
├── frontend/
│   ├── assets/                     # logos, icons and platform artwork
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── app.js
│   ├── data/
│   │   ├── games.json              # generated game metadata
│   │   └── news.json               # generated news digest
│   └── index.html
│
├── src/
│   └── gaming_news_digest/
│       ├── ai/
│       │   ├── base.py             # shared AI contract + validation
│       │   ├── groq_client.py      # Groq provider
│       │   └── ollama_client.py    # local Ollama provider
│       ├── clustering/
│       │   └── story_cluster.py    # story grouping / representatives
│       ├── fetchers/
│       │   ├── base.py
│       │   ├── reddit.py
│       │   ├── rss.py
│       │   └── steam.py
│       ├── filtering/
│       │   └── matcher.py          # inclusion / exclusion matching
│       ├── storage/
│       │   ├── json_store.py       # persistence + compatibility
│       │   └── retention.py        # 48h / 200-item retention
│       ├── config.py               # YAML loading and validation
│       ├── models.py               # domain models / enums
│       ├── pipeline.py             # orchestration
│       └── __main__.py             # CLI entry point
│
├── tests/
│   ├── fixtures/                   # offline fetcher fixtures
│   └── test_*.py
│
├── CONTRIBUTING.md                 # technical contribution guide
├── gaming-news-digest-spec.md      # original project specification
├── requirements.txt
└── README.md
```

---

## 🛡️ Reliability principles

The project intentionally treats external services as unreliable.

### Fetchers

A source failure should not prevent other sources from being processed.

### AI

Malformed model output is validated and isolated. Infrastructure errors can trigger provider fallback where appropriate.

### Storage

The final JSON is written through the storage layer rather than directly overwriting the live dataset in an unsafe way.

### Configuration

YAML files are validated before the pipeline begins, with explicit errors for malformed or incomplete configuration.

### Historical compatibility

The JSON store can handle older representations of source data, including Reddit records whose subreddit information was stored differently.

---

## 📈 Performance optimization

One of the most important lessons from the project is that **reducing AI work before inference is much more valuable than trying to make every inference faster**.

A representative live fetch run previously looked like:

```text
130 fetched
  ↓
74 filtered
  ↓
64 clustered stories
  ↓
13 stories after the per-game pre-limit
  ↓
13 AI calls instead of 64
```

That is an **80% reduction in AI calls** for that dataset.

This matters particularly in GitHub Actions, where the runner may execute Ollama in CPU-only mode.

---

## 💰 Cost model

The architecture is intentionally designed around free infrastructure:

| Component | Cost target |
|---|---:|
| GitHub repository | Free |
| GitHub Actions | Free-tier usage |
| GitHub Pages | Free |
| Ollama | Free / local |
| Groq | Free-tier API usage |
| Database | None |
| Dedicated backend | None |
| Dedicated server | None |

The project therefore has no permanent server to keep online.

Actual third-party service limits can change over time; the architecture does not assume unlimited API or CI usage.

---

## 🧭 Design decisions

### Why JSON instead of a database?

The dataset is small, short-lived and generated periodically. A database would add infrastructure without solving a meaningful problem for this project.

### Why vanilla JavaScript?

The frontend mostly needs to fetch one JSON document, filter it and render cards. A framework would add a build pipeline and dependency surface without providing much value for the current scope.

### Why configuration-driven games?

The followed games are personal editorial preferences, not application logic. Keeping them in YAML makes the digest easy to customize without touching Python.

### Why Reddit is always a rumor

Community posts are useful for discovering leaks and rumors, but they should never look equivalent to verified publication or official Steam information. The data model therefore explicitly tracks verification state and the pipeline enforces the rumor category for Reddit.

### Why retain only 48 hours?

EuroMario is intended as a current-news radar rather than an archival database. A short rolling window keeps the site focused on what is recent and prevents the generated JSON from growing indefinitely.

---

## 🧰 Useful commands

Run the complete test suite:

```bash
pytest -q
```

Lint:

```bash
ruff check src tests
```

Compile-check Python files:

```bash
python -m compileall -q src tests
```

Run the news pipeline:

```bash
PYTHONPATH=src python -m gaming_news_digest
```

Serve the static frontend locally:

```bash
cd frontend
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

---

## 🐛 Troubleshooting

### `GROQ_API_KEY no configurada`

The current pipeline constructs `GroqClient` during startup. Set `GROQ_API_KEY` in the environment before running the pipeline.

### Ollama is not available

Make sure Ollama is running and that the configured model exists:

```bash
ollama list
ollama pull llama3.2:3b
```

### GitHub Actions takes a long time

The CI workflow installs Ollama and downloads the model on the hosted runner. The runner may also run Ollama without a GPU. This setup is intentionally self-contained, but model startup and inference can dominate execution time.

The pipeline mitigates this by applying the per-game limit before AI inference and by supporting Groq fallback.

### The frontend shows no data locally

The frontend loads `data/news.json` relative to its own directory. Use a local HTTP server rather than opening `index.html` directly with `file://`.

```bash
cd frontend
python -m http.server 8000
```

### A Reddit story looks different

That is intentional. Reddit is treated as community / unverified content and is forced into the rumor category by the backend.

---

## 🔭 Possible future directions

The architecture leaves room for improvements without requiring a rewrite:

- More sources and language-specific feeds.
- More granular editorial categories.
- Better story clustering across differently worded headlines.
- More sophisticated relevance ranking.
- Additional AI providers implementing the same `AIClient` contract.
- More visual verification of the frontend in CI.
- Better observability and run statistics.
- Optional historical archives if the product direction changes from "news radar" to "news archive".

These are deliberately not required for the current core pipeline.

---

## 📜 Documentation

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — technical architecture, contracts, conventions and testing expectations.
- [`gaming-news-digest-spec.md`](gaming-news-digest-spec.md) — original project specification and design context.

---

## 📄 License

No explicit open-source license is currently declared in the repository. Unless a license is added, the source should be considered **all rights reserved by default**.

---

## 👤 Author

**Mario MunPeq**

EuroMario is a portfolio project focused on demonstrating:

- Python backend engineering;
- real-world scraping and data normalization;
- resilient external-service integration;
- AI-assisted processing;
- automated CI/CD;
- static web publishing;
- configuration-driven application design;
- testing and code quality.

---

<p align="center">
  <strong>EuroMario</strong><br>
  <sub>Less noise. More games. Fresh every day.</sub>
</p>
