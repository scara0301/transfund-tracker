import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import get_db
from services import analysis, fraud, ledger, ocr

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_OCR_BYTES = 15 * 1024 * 1024


def scan_cached(db: Session, content: bytes, filename: str, content_type: str) -> tuple[str, dict]:
    file_hash = hashlib.sha256(content).hexdigest()
    cached = db.query(models.InvoiceScan).filter(models.InvoiceScan.file_hash == file_hash).first()
    if cached:
        return file_hash, cached.result
    result = ocr.scan_invoice(content, filename, content_type)
    db.add(models.InvoiceScan(file_hash=file_hash, result=result))
    db.commit()
    return file_hash, result


@router.post("/ocr")
def scan_invoice(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Extract vendor, GSTIN, invoice number, date and totals from an invoice photo or PDF."""
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_OCR_BYTES:
        raise HTTPException(status_code=413, detail="File must be under 15 MB")
    file_hash, result = scan_cached(db, content, file.filename or "", file.content_type or "")
    dup = db.query(models.Utilization).filter(models.Utilization.invoice_hash == file_hash).first()
    return {
        **result,
        "file_hash": file_hash,
        "already_claimed": {"utilization_id": dup.id, "campaign_id": dup.campaign_id} if dup else None,
    }


class CampaignPrecheck(BaseModel):
    title: str
    description: str
    category: str = "General"
    goal_amount: float
    organizer_email: str
    milestone_count: int = 0
    campaign_id: Optional[int] = None


@router.post("/campaign-precheck")
def campaign_precheck(body: CampaignPrecheck, db: Session = Depends(get_db)):
    """Score a campaign draft before it is published, so organizers can fix issues."""
    return fraud.score_campaign(db, body.title, body.description, body.category, body.goal_amount,
                                body.organizer_email, body.milestone_count, body.campaign_id)


@router.get("/campaign/{campaign_id}/analysis")
def campaign_analysis(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    report = ledger.verify_chain(db, campaign_id)
    result = analysis.analyze_campaign(db, campaign, report)
    result["ledger"] = {"valid": report["valid"], "issue_count": report["issue_count"],
                        "campaign_blocks": report["campaign_blocks"]}
    result["campaign_risk"] = {"score": campaign.risk_score, "signals": campaign.risk_flags or []}
    return result


@router.get("/alerts")
def fraud_alerts(organizer_email: Optional[str] = None, min_score: float = 30, db: Session = Depends(get_db)):
    """Flagged campaigns, donations and expenses — for an organizer's campaigns, or platform-wide."""
    cq = db.query(models.Campaign)
    if organizer_email:
        cq = cq.filter(models.Campaign.organizer_email == organizer_email)
    campaigns = {c.id: c for c in cq.all()}
    ids = list(campaigns)
    alerts = []
    for c in campaigns.values():
        if (c.risk_score or 0) >= min_score:
            alerts.append({"kind": "campaign", "id": c.id, "campaign_id": c.id, "campaign_title": c.title,
                           "score": c.risk_score, "signals": c.risk_flags or [], "amount": c.goal_amount,
                           "created_at": c.created_at.isoformat() + "Z", "summary": c.title})
    if ids:
        for d in db.query(models.Donation).filter(models.Donation.campaign_id.in_(ids),
                                                  models.Donation.risk_score >= min_score).all():
            alerts.append({"kind": "donation", "id": d.id, "campaign_id": d.campaign_id,
                           "campaign_title": campaigns[d.campaign_id].title, "score": d.risk_score,
                           "signals": d.risk_flags or [], "amount": d.amount,
                           "created_at": d.donated_at.isoformat() + "Z",
                           "summary": f"{d.donor_name} · {d.payment_method or 'payment'}"})
        for u in db.query(models.Utilization).filter(models.Utilization.campaign_id.in_(ids),
                                                     models.Utilization.risk_score >= min_score).all():
            alerts.append({"kind": "expense", "id": u.id, "campaign_id": u.campaign_id,
                           "campaign_title": campaigns[u.campaign_id].title, "score": u.risk_score,
                           "signals": u.risk_flags or [], "amount": u.amount,
                           "created_at": u.created_at.isoformat() + "Z", "summary": u.description})
    alerts.sort(key=lambda a: -(a["score"] or 0))
    return {
        "count": len(alerts),
        "high": sum(1 for a in alerts if a["score"] >= 60),
        "medium": sum(1 for a in alerts if 30 <= a["score"] < 60),
        "alerts": alerts[:200],
    }
