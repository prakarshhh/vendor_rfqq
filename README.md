# Vendor vs RFQ scorer

Single-page web app. Pick a stored RFQ, paste or upload a vendor profile, and an LLM
evaluates it: **score /100, 3 supporting reasons, 2 gaps**. Past evaluations are listed
below, most recent first.

- Backend: Python + FastAPI, SQLite (file created automatically at `data/app.db`)
- Frontend: one plain `static/index.html` (no npm, no build step)
- LLM: direct HTTP call (Anthropic or Gemini), one call per evaluation

## Requirements

- Python 3.10 or newer
- An API key for **Anthropic** or **Gemini** (Gemini has a free tier),
  or use `LLM_PROVIDER=mock` to run without a key (see below)

## Setup

```bash
# 1. clone and enter the repo
git clone <your-repo-url>
cd vendor-rfq-scorer

# 2. create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate          # Windows (cmd):  .venv\Scripts\activate
pip install -r requirements.txt

# 3. create your .env from the template and add your key
cp .env.example .env               # Windows (cmd):  copy .env.example .env
```

Then open `.env` and set:

| Variable | Required | Meaning |
|---|---|---|
| `LLM_PROVIDER` | yes | `anthropic`, `gemini` or `mock` (default `anthropic`) |
| `ANTHROPIC_API_KEY` | if provider is anthropic | your Anthropic key |
| `GEMINI_API_KEY` | if provider is gemini | your Gemini key |
| `LLM_MODEL` | no | override the default model (`claude-sonnet-5` / `gemini-2.5-flash`) |

`.env` is git-ignored. Never commit keys.

## Load the seed data

The three RFQs in `seed/rfqs.json` are loaded **automatically every time the server starts**
(safe to repeat, it never duplicates or deletes evaluations). To load them manually without
starting the server:

```bash
python -m backend.seed
```

## Run

```bash
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000

Use the "Vendor A / B / C" buttons to load the sample profiles from `samples/`, or paste your own
text, or upload a `.txt` file. Click **Evaluate**.

## How the score works (short version)

The LLM does **not** invent the number. In its single call it judges every RFQ criterion as
`met / partial / not_met / no_evidence` and quotes evidence. `backend/scoring.py` then computes
the score from those verdicts with fixed weights (mandatory 20, technical 25, required 35,
preferred 10, delivery/volume 10), and applies hard caps: a mandatory requirement that is not met
caps the score at 30, not evidenced at 40, only partly met at 60. Vague marketing claims count as
`no_evidence`. Each result has a "How this score was calculated" table in the UI.
More detail is in `BUILD_LOG.md`.

## Mock mode (no API key)

`LLM_PROVIDER=mock` swaps the LLM for a crude keyword matcher so you can run and click through the
whole app offline. Its scores are **not meaningful**; it only exists for testing the plumbing.

## Project layout

```
backend/app.py       FastAPI routes: GET /api/rfqs, GET /api/evaluations, POST /api/evaluate
backend/db.py        SQLite schema, seeding, queries
backend/prompts.py   Rubric / system prompt and the user prompt builder
backend/llm.py       The single LLM call (Anthropic, Gemini, mock)
backend/scoring.py   Validation of LLM output + deterministic score
static/index.html    The whole UI
seed/                Provided RFQs (rfqs.json is what gets loaded)
samples/             Provided vendor profiles
```

## Troubleshooting

- `ANTHROPIC_API_KEY is not set` shown in the UI: check `.env` is in the repo root and the server was restarted.
- `LLM API error 404` about the model: set `LLM_MODEL` in `.env` to a model your key can use.
- Port busy: `uvicorn backend.app:app --port 8001`
- Reset everything: stop the server and delete the `data/` folder.
