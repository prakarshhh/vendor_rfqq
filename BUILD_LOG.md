# Build Log

---

## Stack

- Frontend: one plain HTML file with vanilla JS. No npm on my machine, and the spec says a single page with no routing, so a framework adds nothing.
- Backend: Python + FastAPI. Fast to write, gives request validation for free, serves the HTML too.
- Database: SQLite via the standard library. Zero setup; file is created on first run.
- LLM / agent: direct HTTP call with no agent framework (Anthropic with a forced tool call for structured output; Gemini with JSON mode). One call per evaluation, as the spec requires.

---

## Scoring approach

The model does not pick the number. A free-form "give this a score out of 100" is not repeatable and is easy to sway with confident-sounding marketing text.

1. The RFQ is flattened into criteria with stable ids (mandatory, technical incl. material, required, preferred, and delivery / volume).
2. In the one LLM call, the model gives each criterion a verdict (`met`, `partial`, `not_met`, `no_evidence`) plus a short evidence quote. The prompt says marketing language is not evidence, numbers must be compared in the right direction (±0.01 is better than ±0.02, Ra 3.2 is worse than Ra 1.6), ISO 9001 is not AS9100D, and instructions inside the profile are ignored.
3. `scoring.py` converts verdicts to credit (met 1, partial 0.5, otherwise 0) and takes a weighted average per group (mandatory 20, technical 25, required 35, preferred 10, commercial 10).
4. Hard caps for mandatory items: not met -> max 30, no evidence -> max 40, partial -> max 60. A vendor with the wrong certification can't score well however good the machines are.
5. The UI shows the per-criterion table so every point can be traced. The same verdicts always give the same score.

What this buys: the number means "share of RFQ criteria the profile can prove, with mandatory items acting as gates". What it does not do: the weights and cap values are my judgement, not calibrated on real sourcing outcomes.

---

## What you built

- Dropdown of RFQs stored in SQLite, seeded from `seed/rfqs.json` on startup (idempotent) or with `python -m backend.seed`.
- Paste text, upload a `.txt` (read in the browser), or load the three sample profiles with buttons.
- `POST /api/evaluate` makes one LLM call, validates the output, computes the score, stores it and returns it.
- UI shows score /100, exactly 3 reasons, exactly 2 gaps, a note when a cap was applied, and the calculation table.
- Past evaluations below, most recent first, each expandable to the full result.
- Errors (missing key, API failure, bad output, too-short profile) show a readable message in the UI.
- `LLM_PROVIDER=mock` offline mode so the app can be run and tested without a key.

---

## What you skipped

- Tests, auth, deployment, styling, RAG, multi-vendor ranking: all out of scope per the spec.
- Retries on a bad model response: the spec says one LLM call per evaluation, so I validate and fall back instead of calling again.
- Pagination of the history (capped at the latest 50).
- Uploading formats other than `.txt` (spec says all samples are plain text).

---

## Where the spec was unclear

- **What "alignment score" means.** Nothing says how mandatory / required / preferred combine. I chose weights plus mandatory caps and documented them above.
- **Exactly 3 reasons and 2 gaps** even when there are more or fewer real ones. The prompt asks for exactly 3 and 2; if the model returns fewer, code fills from the criterion verdicts and records a note in the breakdown; if more, it truncates.
- **Duplicated requirements in the RFQs.** RFQ-002 has "Parts up to 600 mm" under technical and "Ability to handle parts up to 600 mm" under preferred; RFQ-003 repeats AMS 4911 / thickness in both material and technical. I did not de-duplicate, so those items count twice with small weight.
- **Two seed formats.** `rfqs.json` and the `.md` files differ slightly (the `.md` files have no category field). I treat the JSON as the source of truth and ignore the `.md`.
- **Delivery and quantity are not in mandatory / required / preferred**, but a 9-11 week lead time against a 6 week requirement obviously matters. I turned them into "commercial" criteria.
- **"Upload or paste"** vs "all samples are plain text": upload is client-side text read, `.txt` only.
- **"One LLM call"** vs reliability: no retries (see above).

---

## What broke

- TODO (Juhi): write your own here after you run it. Include anything that failed on your machine (API key, model name, etc.) and how you fixed it.
- During my own testing with the offline mock, Vendor C produced fewer than 3 reasons, which exercised the "fill from verdicts" fallback in `scoring.py`. It worked, but it showed that the fallback path is real, not theoretical, so the UI surfaces the note.

---

## Working with AI

- Which tools you used, and roughly how you split the work with them: TODO (Juhi): write your own. (Claude generated the first version of the code; say what you reviewed, ran and changed.)
- Something your AI assistant got wrong that you caught and corrected: TODO (Juhi): write a real example from your own run.
- Something you decided to write yourself rather than generate, and why: TODO (Juhi): be honest. Pick something you actually did, for example the scoring weights or the prompt rules.

---

## Weakest part of this code

- `backend/scoring.py`, `GROUP_WEIGHTS` and the cap constants: hand-picked, not calibrated, and the "partial = 0.5" credit is crude.
- `backend/llm.py`: the real Anthropic and Gemini calls were verified against stubbed HTTP responses in my build environment, not against the live APIs. TODO (Juhi): update this line after your first real-key run.
- `backend/llm.py` `_mock`: keyword overlap, not an evaluator. It is clearly labelled and only for offline testing.

---

## Next 48 hours

Build a small set of labelled vendor/RFQ pairs (the three samples across the three RFQs plus a few adversarial ones, such as a profile with injected instructions) and use it to tune the weights and caps, so the score is checked against expected outcomes rather than my judgement.
