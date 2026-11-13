from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import os
from datetime import datetime

from database import get_db
import models
import schemas
from routers.ai import MAX_OCR_BYTES, scan_cached
from services import escrow, fraud, ledger

router = APIRouter(prefix="/utilizations", tags=["utilizations"])


ALLOWED_PROOF = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".tif", ".tiff"}


@router.post("/", response_model=schemas.UtilizationOut)
def create_utilization(
    campaign_id: int = Form(...),
    amount: float = Form(...),
    description: str = Form(...),
    category: str = Form("general"),
    created_by: str = Form(...),
    milestone_id: Optional[int] = Form(None),
    vendor_name: Optional[str] = Form(None),
    vendor_gstin: Optional[str] = Form(None),
    invoice_number: Optional[str] = Form(None),
    invoice_date: Optional[str] = Form(None),
    proof: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    campaign = db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    escrow.require_owner(campaign, created_by)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if not description.strip():
        raise HTTPException(status_code=400, detail="Describe what the money was spent on")

    # Hard rule (not AI): you can only spend what donors have released to you.
    f = escrow.funds(db, campaign)
    if amount > f["spendable"] + 0.005:
        where = "released from escrow" if f["escrow"] else "raised"
        raise HTTPException(
            status_code=400,
            detail=f"Only ₹{f['spendable']:,.0f} is available to spend (₹{f['released']:,.0f} {where}, ₹{f['utilized']:,.0f} already used)",
        )
    if milestone_id is not None:
        m = db.get(models.Milestone, milestone_id)
        if not m or m.campaign_id != campaign_id:
            raise HTTPException(status_code=400, detail="Milestone doesn't belong to this campaign")
        if m.status != "released":
            raise HTTPException(status_code=400, detail="Expenses can only be logged against released milestones")

    proof_url = invoice_hash = None
    scan = None
    if proof and proof.filename:
        base = os.path.basename(proof.filename).replace(" ", "_")
        if os.path.splitext(base)[1].lower() not in ALLOWED_PROOF:
            raise HTTPException(status_code=400, detail="Proof must be a PDF or image")
        content = proof.file.read()
        if len(content) > MAX_OCR_BYTES:
            raise HTTPException(status_code=413, detail="Proof file must be under 15 MB")
        # Re-run (or reuse cached) OCR server-side; client-supplied fields are never trusted for checks.
        invoice_hash, scan = scan_cached(db, content, base, proof.content_type or "")
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "proofs")
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = f"util_{campaign_id}_{invoice_hash[:12]}_{base}"
        with open(os.path.join(upload_dir, safe_name), "wb") as buffer:
            buffer.write(content)
        proof_url = f"/uploads/proofs/{safe_name}"

    clean = lambda v: (v or "").strip() or None  # noqa: E731
    vendor_name = clean(vendor_name) or (scan or {}).get("vendor_name")
    vendor_gstin = (clean(vendor_gstin) or (scan or {}).get("vendor_gstin") or "").upper() or None
    invoice_number = clean(invoice_number) or (scan or {}).get("invoice_number")
    invoice_date = clean(invoice_date) or (scan or {}).get("invoice_date")

    risk = fraud.score_utilization(
        db, campaign, amount, description, bool(proof_url), invoice_hash, scan,
        invoice_number, vendor_gstin, vendor_name, invoice_date,
    )
    utilization = models.Utilization(
        campaign_id=campaign_id,
        amount=amount,
        description=description.strip(),
        category=(category or "general").lower(),
        proof_url=proof_url,
        created_by=created_by,
        milestone_id=milestone_id,
        vendor_name=vendor_name,
        vendor_gstin=vendor_gstin,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        invoice_hash=invoice_hash,
        ocr_total=(scan or {}).get("total_amount"),
        ocr_confidence=(scan or {}).get("confidence"),
        risk_score=risk["score"],
        risk_flags=risk["signals"],
        status="flagged" if risk["score"] >= 60 else "recorded",
        created_at=datetime.utcnow(),
    )
    db.add(utilization)
    db.flush()
    block = ledger.append_block(db, "expenditure", ledger.utilization_payload(utilization),
                                campaign_id, "utilization", utilization.id)
    utilization.ledger_hash = block.block_hash
    db.commit()
    db.refresh(utilization)
    return utilization


@router.get("/", response_model=List[schemas.UtilizationOut])
def list_utilizations(
    campaign_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Utilization)
    if campaign_id:
        query = query.filter(models.Utilization.campaign_id == campaign_id)
    return query.order_by(models.Utilization.created_at.desc()).all()


@router.get("/{utilization_id}", response_model=schemas.UtilizationOut)
def get_utilization(utilization_id: int, db: Session = Depends(get_db)):
    util = (
        db.query(models.Utilization)
        .filter(models.Utilization.id == utilization_id)
        .first()
    )
    if not util:
        raise HTTPException(status_code=404, detail="Utilization record not found")
    return util


@router.get("/summary/{campaign_id}")
def utilization_summary(campaign_id: int, db: Session = Depends(get_db)):
    """Get total utilized vs raised for a campaign — transparency dashboard."""
    campaign = (
        db.query(models.Campaign)
        .filter(models.Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    utilizations = (
        db.query(models.Utilization)
        .filter(models.Utilization.campaign_id == campaign_id)
        .all()
    )

    total_utilized = sum(u.amount for u in utilizations)
    f = escrow.funds(db, campaign)
    return {
        "campaign_id": campaign_id,
        "campaign_title": campaign.title,
        "total_raised": campaign.raised_amount,
        "total_utilized": total_utilized,
        "remaining": campaign.raised_amount - total_utilized,
        "utilization_count": len(utilizations),
        "escrow": f["escrow"],
        "released": f["released"],
        "locked_in_escrow": f["locked_in_escrow"],
        "spendable": f["spendable"],
        "flagged_count": sum(1 for u in utilizations if (u.risk_score or 0) >= 60),
    }
