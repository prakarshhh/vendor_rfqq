"""One LLM call per evaluation. Direct HTTP calls, no agent framework.

Providers (LLM_PROVIDER): anthropic | gemini | openai_compat | mock
"""
import json
import os
import re
import time

import httpx

from .prompts import SYSTEM_PROMPT, build_user_prompt

TIMEOUT = 90.0
RETRY_STATUS = {429, 500, 502, 503, 504}  
MAX_ATTEMPTS = 3
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "gemini": "gemini-3.8-flash", "mock": "mock-keyword-matcher"}

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["met", "partial", "not_met", "no_evidence"]},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "verdict", "evidence"],
            },
        },
        "reasons": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["vendor_name", "criteria", "reasons", "gaps"],
}


class LLMError(Exception):
    """Anything that went wrong talking to the model. Message is shown to the user."""


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic").strip().lower()


def model_name() -> str:
    return os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODELS.get(provider(), "unknown")


def evaluate(rfq: dict, criteria: list[dict], profile_text: str) -> dict:
    """Single call. Returns the raw dict from the model (validated later in scoring.py)."""
    p = provider()
    user_prompt = build_user_prompt(rfq, criteria, profile_text)
    if p == "anthropic":
        return _anthropic(user_prompt)
    if p == "gemini":
        return _gemini(user_prompt)
    if p == "openai_compat":
        return _openai_compat(user_prompt)
    if p == "mock":
        return _mock(rfq, criteria, profile_text)
    raise LLMError(f"Unknown LLM_PROVIDER '{p}'. Use anthropic, gemini, openai_compat or mock.")


# --------------------------------------------------------------------------- Anthropic
def _anthropic(user_prompt: str) -> dict:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    body = {
        "model": model_name(),
        "max_tokens": 3000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        # Forced tool call => structured output, no JSON-in-prose parsing.
        "tools": [{
            "name": "submit_evaluation",
            "description": "Submit the criterion-by-criterion evaluation of the vendor profile.",
            "input_schema": TOOL_SCHEMA,
        }],
        "tool_choice": {"type": "tool", "name": "submit_evaluation"},
    }
    data = _post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        body=body,
    )
    for block in data.get("content", []):
        if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
            return block["input"]
    raise LLMError("Anthropic response did not contain the expected structured result.")


# --------------------------------------------------------------------------- Gemini
def _gemini(user_prompt: str) -> dict:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMError("GEMINI_API_KEY is not set. Add it to your .env file.")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    data = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name()}:generateContent",
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        body=body,
    )
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("Gemini response was empty or blocked. Try again or rephrase the profile.")
    return _parse_json(text)


# --------------------------------------------------------------------------- OpenAI-compatible (Qwen etc.)
def _openai_compat(user_prompt: str) -> dict:
    """Any server that speaks the OpenAI /chat/completions API: OpenRouter, Groq, DashScope, Ollama..."""
    base = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    local = "localhost" in base or "127.0.0.1" in base
    if not key and not local:
        raise LLMError("OPENAI_API_KEY is not set. Add it to your .env file.")
    if not model:
        raise LLMError("LLM_MODEL is not set. For openai_compat you must name the model in .env.")
    headers = {"content-type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    data = _post(f"{base}/chat/completions", headers=headers, body=body)
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("Model response was empty. Try again or use a different model.")
    return _parse_json(text or "")


# --------------------------------------------------------------------------- helpers
def _post(url: str, headers: dict, body: dict) -> dict:
    """POST with a small retry for temporary errors (429 / 5xx / network). Same request is re-sent."""
    r = None
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            if last:
                raise LLMError(f"Could not reach the LLM API: {e.__class__.__name__}") from e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in RETRY_STATUS and not last:
            time.sleep(2 * (attempt + 1))  # 2s, then 4s
            continue
        break
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {})
            detail = detail.get("message", detail) if isinstance(detail, dict) else detail
        except Exception:
            detail = r.text[:200]
        raise LLMError(f"LLM API error {r.status_code}: {detail}")
    try:
        return r.json()
    except ValueError:
        raise LLMError("LLM API returned invalid JSON.")


def _parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # Qwen3 etc. may emit reasoning
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # strip code fences if present
    try:
        out = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise LLMError("Model did not return valid JSON.")
        try:
            out = json.loads(m.group(0))
        except ValueError:
            raise LLMError("Model did not return valid JSON.")
    if not isinstance(out, dict):
        raise LLMError("Model returned JSON but not an object.")
    return out


_STOP = set("with from that this have will for and the per any all are can our not been such into than "
            "each free issue supplied units unit weeks week days working from".split())


def _mock(rfq: dict, criteria: list[dict], profile: str) -> dict:
    """Crude keyword overlap. NOT an evaluator; exists so the app can be run and tested with no API key."""
    low = profile.lower()
    m = re.search(r"company:\s*(.+)", profile, re.I)
    name = m.group(1).strip() if m else "Unknown vendor"
    out, good, bad = [], [], []
    for c in criteria:
        words = {w for w in re.findall(r"[a-z0-9\-\.\+/]{4,}", c["text"].lower()) if w not in _STOP}
        hit = sum(1 for w in words if w in low)
        frac = hit / len(words) if words else 0
        verdict = "met" if frac >= 0.6 else "partial" if frac >= 0.3 else "no_evidence"
        out.append({"id": c["id"], "verdict": verdict, "evidence": f"[MOCK] {hit}/{len(words)} keywords found"})
        (good if verdict == "met" else bad).append(c["text"])
    return {
        "vendor_name": name,
        "criteria": out,
        "reasons": [f"[MOCK] Keywords found for: {t}" for t in good[:3]],
        "gaps": [f"[MOCK] Weak or no keyword match for: {t}" for t in bad[:2]],
    }