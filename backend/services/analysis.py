"""
AI expenditure analysis: where the money went, whether spending stayed
inside approved milestones, how well it is evidenced, and a composite
transparency score with plain-language insights for donors.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

import models
from services import escrow

OVERHEAD_CATEGORIES = {"administrative", "salaries"}


def _verified(u: models.Utilization) -> bool:
    """Invoice was read by OCR and its total matches the claim (±5%), with no fatal flags."""
    if not u.proof_url or not u.ocr_total or not u.amount:
        return False
    if abs(u.amount - u.ocr_total) / u.amount > 0.05:
        return False
    fatal = {"duplicate_invoice_file", "duplicate_invoice_number", "invalid_gstin", "future_invoice"}
    return not any(s.get("code") in fatal for s in (u.risk_flags or []))


def analyze_campaign(db: Session, campaign: models.Campaign, ledger_report: Optional[dict] = None) -> dict[str, Any]:
    utils = (
        db.query(models.Utilization)
        .filter(models.Utilization.campaign_id == campaign.id)
        .order_by(models.Utilization.created_at.asc())
        .all()
    )
    ms = escrow.milestones_for(db, campaign.id)
    f = escrow.funds(db, campaign)
    spent = f["utilized"]

    by_cat: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for u in utils:
        c = (u.category or "general").lower()
        by_cat[c]["amount"] += u.amount
        by_cat[c]["count"] += 1
    categories = sorted(
        ({"category": k, "amount": round(v["amount"], 2), "count": v["count"],
          "percent": round(100 * v["amount"] / spent, 1) if spent else 0} for k, v in by_cat.items()),
        key=lambda x: -x["amount"],
    )

    milestone_rows = []
    for m in ms:
        m_spent = sum(u.amount for u in utils if u.milestone_id == m.id)
        milestone_rows.append({
            "id": m.id, "sequence": m.sequence, "title": m.title, "status": m.status,
            "budget": round(m.amount, 2), "spent": round(m_spent, 2),
            "variance": round(m.amount - m_spent, 2),
            "percent_spent": round(100 * m_spent / m.amount, 1) if m.amount else 0,
        })
    unassigned = sum(u.amount for u in utils if u.milestone_id is None)

    monthly: dict[str, float] = defaultdict(float)
    for u in utils:
        monthly[u.created_at.strftime("%Y-%m")] += u.amount
    monthly_rows = [{"month": k, "amount": round(v, 2)} for k, v in sorted(monthly.items())]

    recent_cut = datetime.utcnow() - timedelta(days=90)
    recent_spend = sum(u.amount for u in utils if u.created_at >= recent_cut)
    burn_per_month = round(recent_spend / 3, 2)
    runway = round(f["spendable"] / burn_per_month, 1) if burn_per_month > 0 else None

    with_proof = sum(u.amount for u in utils if u.proof_url)
    verified = sum(u.amount for u in utils if _verified(u))
    proof_cov = (with_proof / spent) if spent else 1.0
    verified_rate = (verified / spent) if spent else 1.0
    risks = [u.risk_score for u in utils if u.risk_score is not None]
    avg_risk = sum(risks) / len(risks) if risks else 0.0
    flagged = [u for u in utils if (u.risk_score or 0) >= 60 or u.status == "flagged"]
    overspend = max(0.0, spent - f["released"])

    ledger_ok = ledger_report["valid"] if ledger_report else True
    # ── transparency score (0-100) ──
    components = {
        "proof_coverage": round(30 * proof_cov, 1),
        "invoice_verification": round(20 * verified_rate, 1),
        "ledger_integrity": 20.0 if ledger_ok else 0.0,
        "milestone_discipline": round(15 * (1.0 if overspend == 0 else max(0.0, 1 - overspend / max(spent, 1))), 1)
        if f["escrow"] else 7.5,  # half credit: no escrow means no donor approval step
        "low_risk": round(15 * (1 - avg_risk / 100), 1),
    }
    score = round(sum(components.values()))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"

    insights: list[dict[str, str]] = []
    if not utils:
        insights.append({"type": "info", "text": "No expenses have been logged yet."})
    else:
        if proof_cov >= 0.95:
            insights.append({"type": "positive", "text": f"{proof_cov:.0%} of spending is backed by an uploaded invoice or proof."})
        elif proof_cov < 0.7:
            insights.append({"type": "warning", "text": f"Only {proof_cov:.0%} of spending has proof attached."})
        if verified_rate >= 0.8:
            insights.append({"type": "positive", "text": f"AI verified {verified_rate:.0%} of spend against invoice totals."})
        if categories and categories[0]["percent"] > 60 and len(utils) >= 3:
            insights.append({"type": "info", "text": f"{categories[0]['category'].title()} accounts for {categories[0]['percent']}% of all spending."})
        overhead = sum(c["amount"] for c in categories if c["category"] in OVERHEAD_CATEGORIES)
        if spent and overhead / spent > 0.2:
            insights.append({"type": "warning", "text": f"Overhead (admin + salaries) is {overhead / spent:.0%} of spend (typical is under 20%)."})
        if flagged:
            insights.append({"type": "warning", "text": f"{len(flagged)} expense{'s' if len(flagged) != 1 else ''} flagged as high risk by fraud detection."})
        if unassigned and ms:
            insights.append({"type": "info", "text": f"₹{unassigned:,.0f} of spending isn't linked to a milestone."})
    if f["escrow"]:
        insights.append({"type": "positive", "text": f"₹{f['locked_in_escrow']:,.0f} is locked in escrow until donors approve the next milestone."})
    else:
        insights.append({"type": "info", "text": "This campaign has no milestones, so funds are not escrowed for donor approval."})
    if overspend > 0:
        insights.append({"type": "warning", "text": f"Spending exceeds released funds by ₹{overspend:,.0f}."})
    if not ledger_ok:
        insights.append({"type": "warning", "text": "Ledger verification found integrity issues for this campaign."})
    if runway is not None and f["spendable"] > 0:
        insights.append({"type": "info", "text": f"At the current pace (₹{burn_per_month:,.0f}/month), released funds last about {runway} months."})

    return {
        "campaign_id": campaign.id,
        "funds": f,
        "categories": categories,
        "milestones": milestone_rows,
        "unassigned_spend": round(unassigned, 2),
        "monthly": monthly_rows,
        "burn_per_month": burn_per_month,
        "runway_months": runway,
        "proof_coverage": round(100 * proof_cov, 1),
        "verified_rate": round(100 * verified_rate, 1),
        "average_risk": round(avg_risk, 1),
        "transparency": {"score": score, "grade": grade, "components": components},
        "insights": insights,
        "anomalies": [
            {"id": u.id, "description": u.description, "amount": u.amount, "risk_score": u.risk_score,
             "signals": (u.risk_flags or [])[:3], "created_at": u.created_at.isoformat() + "Z"}
            for u in sorted(flagged, key=lambda x: -(x.risk_score or 0))
        ],
    }
