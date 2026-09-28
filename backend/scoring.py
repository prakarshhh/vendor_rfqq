"""Deterministic scoring.

The LLM does NOT invent the number. It only judges each RFQ criterion
(met / partial / not_met / no_evidence) and quotes evidence. This module turns
those verdicts into a 0-100 score with fixed weights and hard caps for mandatory
requirements, so the same verdicts always give the same score and every point
can be traced back to a criterion.
"""

VERDICTS = ("met", "partial", "not_met", "no_evidence")
CREDIT = {"met": 1.0, "partial": 0.5, "not_met": 0.0, "no_evidence": 0.0}

# Weights sum to 100. If an RFQ has no criteria in a group, its weight is
# redistributed proportionally over the groups that do exist.
GROUP_WEIGHTS = {"mandatory": 20, "technical": 25, "required": 35, "preferred": 10, "commercial": 10}

# Hard caps: a vendor that fails / cannot prove a MANDATORY item can't score high,
# no matter how good the rest is.
CAP_MANDATORY_NOT_MET = 30
CAP_MANDATORY_NO_EVIDENCE = 40
CAP_MANDATORY_PARTIAL = 60


def build_criteria(rfq: dict) -> list[dict]:
    """Flatten an RFQ into an ordered list of criteria with stable ids."""
    items: list[dict] = []

    def add(group: str, text: str):
        n = sum(1 for c in items if c["group"] == group) + 1
        items.append({"id": f"{group}-{n}", "group": group, "text": text})

    for t in rfq.get("mandatory", []):
        add("mandatory", t)
    if rfq.get("material"):
        add("technical", f"Material: {rfq['material']}")
    for t in rfq.get("technical", []):
        add("technical", t)
    for t in rfq.get("required", []):
        add("required", t)
    for t in rfq.get("preferred", []):
        add("preferred", t)
    if rfq.get("delivery"):
        add("commercial", f"Delivery: {rfq['delivery']}")
    if rfq.get("quantity"):
        add("commercial", f"Volume / capacity: {rfq['quantity']}")
    return items


def _clean(s, limit=300) -> str:
    return " ".join(str(s or "").split())[:limit]


def compute(rfq: dict, llm_out: dict) -> dict:
    """Validate the LLM output and compute the final result.

    Returns dict with: vendor_name, score, reasons[3], gaps[2], breakdown.
    """
    criteria = build_criteria(rfq)
    warnings: list[str] = []

    by_id = {}
    for row in llm_out.get("criteria") or []:
        if isinstance(row, dict) and row.get("id"):
            by_id[str(row["id"])] = row

    for c in criteria:
        row = by_id.get(c["id"])
        verdict = str(row.get("verdict", "")).strip().lower() if row else ""
        if verdict not in VERDICTS:
            if row is None:
                warnings.append(f"LLM skipped {c['id']}; treated as no_evidence")
            else:
                warnings.append(f"LLM gave invalid verdict for {c['id']}; treated as no_evidence")
            verdict = "no_evidence"
        c["verdict"] = verdict
        c["evidence"] = _clean(row.get("evidence")) if row else ""
        c["credit"] = CREDIT[verdict]

    # ---- weighted score ----
    groups = {}
    for g in GROUP_WEIGHTS:
        members = [c for c in criteria if c["group"] == g]
        if members:
            groups[g] = {"members": members, "avg": sum(c["credit"] for c in members) / len(members)}
    total_w = sum(GROUP_WEIGHTS[g] for g in groups)
    group_summary = {}
    raw = 0.0
    for g, info in groups.items():
        eff_w = GROUP_WEIGHTS[g] * 100 / total_w
        pts = eff_w * info["avg"]
        raw += pts
        group_summary[g] = {
            "weight": round(eff_w, 1),
            "points": round(pts, 1),
            "met": sum(1 for c in info["members"] if c["verdict"] == "met"),
            "total": len(info["members"]),
        }

    # ---- mandatory caps ----
    mand = [c for c in criteria if c["group"] == "mandatory"]
    cap, cap_reason = None, None
    if any(c["verdict"] == "not_met" for c in mand):
        cap, cap_reason = CAP_MANDATORY_NOT_MET, "A mandatory requirement is not met"
    elif any(c["verdict"] == "no_evidence" for c in mand):
        cap, cap_reason = CAP_MANDATORY_NO_EVIDENCE, "A mandatory requirement is not evidenced in the profile"
    elif any(c["verdict"] == "partial" for c in mand):
        cap, cap_reason = CAP_MANDATORY_PARTIAL, "A mandatory requirement is only partially met"

    score = raw
    capped = False
    if cap is not None and raw > cap:
        score, capped = cap, True
    score = int(round(max(0, min(100, score))))

    # ---- reasons (3) and gaps (2): LLM text first, fill from verdicts if short ----
    order = {"mandatory": 0, "required": 1, "technical": 2, "commercial": 3, "preferred": 4}

    def fill(items, target, pool, fmt):
        items = [_clean(x, 400) for x in (items or []) if _clean(x)]
        items = items[:target]
        if len(items) < target:
            warnings.append(f"LLM returned {len(items)} of {target} items; filled from criterion verdicts")
            for c in pool:
                if len(items) >= target:
                    break
                items.append(fmt(c))
        return items

    met_pool = sorted((c for c in criteria if c["verdict"] == "met"), key=lambda c: order[c["group"]])
    gap_pool = sorted(
        (c for c in criteria if c["verdict"] != "met"),
        key=lambda c: (order[c["group"]], 0 if c["verdict"] == "not_met" else 1),
    )
    reasons = fill(llm_out.get("reasons"), 3, met_pool, lambda c: f"{c['text']} - {c['evidence'] or 'met'}")
    gaps = fill(llm_out.get("gaps"), 2, gap_pool,
                lambda c: f"{c['text']} - {c['verdict'].replace('_', ' ')}. {c['evidence']}".strip())
    while len(reasons) < 3:
        reasons.append("No further supporting evidence found in the profile.")
    while len(gaps) < 2:
        gaps.append("No further significant gaps identified.")

    return {
        "vendor_name": _clean(llm_out.get("vendor_name"), 120) or "Unknown vendor",
        "score": score,
        "reasons": reasons,
        "gaps": gaps,
        "breakdown": {
            "criteria": criteria,
            "groups": group_summary,
            "raw_score": round(raw, 1),
            "cap": cap,
            "cap_applied": capped,
            "cap_reason": cap_reason if capped else None,
            "warnings": warnings,
        },
    }
