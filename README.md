# Universal AI Residential Construction Planner

A working multi-agent system that converts natural-language house requirements
into a validated preliminary floor plan (SVG), a construction budget estimate,
and engineering recommendations.

## Architecture

```
User Requirements
      │
      ▼
Planning Agent      (backend/planning_agent.py)  — parses NL requirements into structured JSON
      │
      ▼
Layout Agent         (backend/layout_agent.py)    — deterministic recursive spatial partitioning
      │
      ▼
Layout Validator      (backend/validator.py)       — checks overlaps, bounds, dimensions
      │
      ▼
Blueprint Agent        (backend/blueprint_agent.py) — renders SVG floor plans
      │
      ├──────────────┐
      ▼              ▼
Budget Agent      Research Agent
(backend/budget_agent.py)  (backend/research_agent.py)
```

All five agents are orchestrated by `backend/app.py`, a Flask API.

> **LLM usage:** `planning_agent.py`, `budget_agent.py`, and
> `research_agent.py` now call a real LLM — **Groq** (fast, free-tier
> available) — through `backend/llm_client.py`. If `GROQ_API_KEY` isn't
> set, or a call fails for any reason, each agent automatically falls back
> to its built-in rule-based logic so the project always runs end-to-end,
> even without a key.

## Enabling the LLM (Groq)

1. Get a free API key at **https://console.groq.com/keys**
2. Copy `backend/.env.example` to `backend/.env` and paste your key in:

   ```bash
   cd backend
   cp .env.example .env
   # then edit .env and set GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
   ```

   (`.env` is auto-loaded by `app.py` on startup — no need to `export` it manually. `.env` is also git-ignored so your key never gets committed.)

3. Run `python app.py` as usual. You'll see console logs like
   `[planning_agent] LLM parse failed, falling back...` only if something
   goes wrong (bad key, no internet, rate limit) — otherwise the LLM is
   used silently.
4. Optional: change the model via `GROQ_MODEL` (default:
   `llama-3.3-70b-versatile`).

**Which agents use the LLM:**
| Agent | LLM-powered task |
|---|---|
| Planning Agent | Understands free-form requirements → structured room JSON |
| Budget Agent | Reasons about cost breakdown for the given area/floors/tier |
| Research Agent | Generates plan-specific engineering recommendations |

Layout Agent, Validator, and Blueprint Agent remain fully deterministic
(no LLM) by design — geometry and validation need to be exact and
reproducible, which is a job for algorithms, not language models.

## Project Structure

```
app/
├── backend/
│   ├── app.py                # Flask API — orchestrates the pipeline
│   ├── planning_agent.py     # Agent 1 — NL requirements → structured plan
│   ├── layout_agent.py       # Agent 2 — deterministic room geometry
│   ├── validator.py          # Rule-based layout validation
│   ├── blueprint_agent.py    # Agent 3 — SVG floor plan renderer
│   ├── budget_agent.py       # Agent 4 — construction cost estimate
│   ├── research_agent.py     # Agent 5 — engineering recommendations
│   └── requirements.txt
└── frontend/
    └── index.html            # Single-page UI (no build step needed)
```

## How to Run

### 1. Start the backend

```bash
cd backend
pip install -r requirements.txt
python app.py
```

The API will start on `http://localhost:5000`.

### 2. Open the frontend

Just open `frontend/index.html` directly in your browser (double-click it,
or `open frontend/index.html` / `xdg-open frontend/index.html`).
It talks to the API at `http://localhost:5000` via `fetch`.

### 3. Try it

Type something like:

> I need a 1000 sqft east-facing house with 3 bedrooms, kitchen, pooja room and parking, ground plus first floor.

Click **Generate Plan** to see:
- ✅ Validation status
- 🏠 SVG floor plan(s), one per floor
- 💰 Construction budget breakdown
- 📋 Engineering recommendations

Then try:
- **Regenerate Layout** → produces a new geometric arrangement without
  re-parsing your requirements (only the Layout Agent re-runs).
- Type an instruction like `Move the kitchen near the living room` in the
  revision box and click **Apply Revision** → only the affected rooms move.

## API Reference

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/api/plan` | POST | `{requirements, session_id, seed}` | Runs the full pipeline for a new requirement |
| `/api/regenerate` | POST | `{session_id}` | Re-runs only the Layout Agent (new variation) |
| `/api/revise` | POST | `{session_id, instruction}` | Applies a natural-language layout edit |
| `/api/health` | GET | — | Health check |

## Extending This Project

- Swap `planning_agent.parse()`, `budget_agent.estimate()`, or
  `research_agent.recommend()` internals with real Anthropic API calls for
  smarter, more nuanced output (schemas are documented in each file).
- Add more room types / weights in `planning_agent.DEFAULT_ROOM_WEIGHTS`.
- Extend `layout_agent.revise_layout()` to support more instruction types
  (e.g. "make the kitchen bigger", "swap bedroom 1 and bedroom 2").
- Replace the plain HTML frontend with a React app (as originally planned)
  — the Flask API is already CORS-enabled and framework-agnostic.

## Recent Additions (Save & Compare / 3D Preview / Timeline)

The frontend has since moved to a React app (`app/frontend/src`, Vite-based)
and three extra features have been built on top of the pipeline above:

1. **Save & Compare Plans** — `backend/db.py` adds a SQLite table
   (`plans.db`, auto-created on startup) so a generated plan (plan +
   layout + budget + SVGs + timeline) can be permanently saved via
   `POST /api/plans/save`, listed via `GET /api/plans`, fetched via
   `GET /api/plans/<id>`, deleted via `DELETE /api/plans/<id>`, and
   compared 2-3 at a time via `POST /api/plans/compare` (cost, area,
   layout thumbnail, timeline shown side by side).
2. **3D Floor Plan Preview** — `FloorPlan3D` in `frontend/src/App.jsx`
   extrudes each room's walls in Three.js from the same layout geometry
   the 2D SVG blueprint uses. A "View 3D" / "View 2D" toggle sits on each
   floor card.
3. **Construction Timeline Estimator (Agent 6)** — `backend/timeline_agent.py`
   breaks the build into Foundation → Structure → Roofing → Finishing,
   scaled by area/floors/tier, rendered as a Gantt-style bar chart
   (`TimelineGantt` component) next to the Budget Ledger.

**One-time setup note:** `three` is listed in `frontend/package.json` but
was not yet present in `node_modules` / `package-lock.json` in this copy
of the project — run `npm install` inside `app/frontend` once before
`npm run dev`, or the 3D preview import will fail. Everything else
(DB layer, timeline agent, and their CSS) is wired up and ready to run.
