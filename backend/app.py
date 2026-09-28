"""FastAPI app. Single page UI served from /static, JSON API under /api."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # must run before llm reads env vars

from . import db, llm, scoring  # noqa: E402

log = logging.getLogger("uvicorn.error")
MAX_PROFILE_CHARS = 20_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    n = db.seed_rfqs()  # seeds on every start; idempotent
    log.info("Seeded %d RFQs. LLM provider=%s model=%s", n, llm.provider(), llm.model_name())
    yield


app = FastAPI(title="Vendor vs RFQ scorer", lifespan=lifespan)


class EvaluateRequest(BaseModel):
    rfq_id: str
    profile_text: str = Field(min_length=1, max_length=MAX_PROFILE_CHARS)


@app.get("/api/rfqs")
def api_rfqs():
    return db.list_rfqs()


@app.get("/api/evaluations")
def api_evaluations():
    return db.list_evaluations()


@app.post("/api/evaluate")
def api_evaluate(req: EvaluateRequest):
    profile = req.profile_text.strip()
    if len(profile) < 20:
        raise HTTPException(400, "Vendor profile is too short to evaluate.")
    rfq = db.get_rfq(req.rfq_id)
    if rfq is None:
        raise HTTPException(404, f"Unknown RFQ '{req.rfq_id}'.")

    criteria = scoring.build_criteria(rfq)
    try:
        raw = llm.evaluate(rfq, criteria, profile)  # exactly one LLM call
    except llm.LLMError as e:
        raise HTTPException(502, str(e))

    result = scoring.compute(rfq, raw)
    eval_id = db.save_evaluation(
        rfq_id=rfq["id"], vendor_name=result["vendor_name"], profile_text=profile,
        score=result["score"], reasons=result["reasons"], gaps=result["gaps"],
        breakdown=result["breakdown"], model=f"{llm.provider()}:{llm.model_name()}",
    )
    return db.get_evaluation(eval_id)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")  # sample vendor profiles for the UI buttons
