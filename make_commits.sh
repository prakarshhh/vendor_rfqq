#!/usr/bin/env bash
# Run this INSIDE the vendor-rfq-scorer folder (once) to create a meaningful commit history.
# Before running, set your git identity if you have not:
#   git config --global user.name  "Juhi"
#   git config --global user.email "juhisaxena2002@gmail.com"
set -e
[ -d .git ] || git init -b main
c() { git add $1 && git commit -q -m "$2" && echo "committed: $2"; }

c "SPEC.md seed samples"                          "Add case-study spec, seed RFQs and sample vendor profiles"
c ".gitignore backend/__init__.py backend/db.py backend/seed.py" "Add SQLite storage layer and idempotent RFQ seeding"
c "backend/prompts.py"                            "Add rubric prompt: per-criterion verdicts, marketing fluff is not evidence"
c "backend/scoring.py"                            "Compute score in code from LLM verdicts, with mandatory-requirement caps"
c "backend/llm.py requirements.txt .env.example"  "Add single-call LLM client for Anthropic and Gemini, plus offline mock"
c "backend/app.py"                                "Expose evaluate and history API, serve the single-page app"
c "static/index.html"                             "Add single-page UI: RFQ picker, paste/upload, result and past evaluations"
c "README.md BUILD_LOG.md"                        "Add README setup guide and fill in BUILD_LOG"
git log --oneline
