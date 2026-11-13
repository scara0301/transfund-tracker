"""
Single path for turning a verified payment into a donation: receipt,
AI risk score, ledger block and campaign totals are all written in one
transaction, so a donation can never exist without its ledger entry.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from services import fraud, ledger


def check_daily_limit(db: Session, campaign: models.Campaign, donor_email: str, amount: float) -> None:
    if not campaign.daily_donor_limit:
        return
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_total = db.query(func.sum(models.Donation.amount)).filter(
        models.Donation.campaign_id == campaign.id,
        models.Donation.donor_email == donor_email,
        models.Donation.donated_at >= today_start,
    ).scalar() or 0
    if today_total + amount > campaign.daily_donor_limit:
        remaining = max(0, campaign.daily_donor_limit - today_total)
        raise HTTPException(
            status_code=429,
            detail=f"DAILY_LIMIT_REACHED|{campaign.daily_donor_limit:.0f}|{remaining:.0f}",
        )


def check_can_donate(db: Session, campaign: Optional[models.Campaign], donor_email: str, amount: float) -> models.Campaign:
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "active":
        raise HTTPException(status_code=400, detail="This campaign is no longer accepting donations")
    if amount is None or amount < 1:
        raise HTTPException(status_code=400, detail="Minimum donation is ₹1")
    if amount > 10_00_000:
        raise HTTPException(status_code=400, detail="Maximum single donation is ₹10,00,000")
    check_daily_limit(db, campaign, donor_email, amount)
    return campaign


def record_donation(
    db: Session,
    campaign: models.Campaign,
    donor_name: str,
    donor_email: str,
    amount: float,
    donor_id: Optional[int] = None,
    payment_method: Optional[str] = None,
    transaction_id: Optional[str] = None,
    payment_order_id: Optional[str] = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Caller has already validated the payment. Commits unless commit=False."""
    risk = fraud.score_donation(db, campaign, donor_email, amount)
    if campaign.status != "active":  # paid after the campaign closed — keep it, flag for refund review
        risk["signals"].insert(0, fraud.signal("closed_campaign", "Payment received after campaign closed", 0.3,
                                               "Review for refund."))
        risk = fraud.combine(risk["signals"])

    if donor_id is None:
        donor = db.query(models.Donor).filter(func.lower(models.Donor.email) == donor_email.strip().lower()).first()
        donor_id = donor.id if donor else None

    donation = models.Donation(
        campaign_id=campaign.id,
        donor_id=donor_id,
        donor_name=donor_name,
        donor_email=donor_email,
        amount=amount,
        payment_method=payment_method,
        transaction_id=transaction_id,
        payment_order_id=payment_order_id,
        status="completed",
        risk_score=risk["score"],
        risk_flags=risk["signals"],
        donated_at=datetime.utcnow(),
    )
    db.add(donation)
    db.flush()

    receipt = models.Receipt(
        donation_id=donation.id, receipt_number=f"TMP-{uuid.uuid4().hex}",
        amount=amount, issued_to=donor_name,
    )
    db.add(receipt)
    db.flush()
    receipt.receipt_number = f"RCP-{receipt.id:05d}"

    block = ledger.append_block(db, "donation", ledger.donation_payload(donation),
                                campaign.id, "donation", donation.id)
    donation.ledger_hash = block.block_hash

    campaign.raised_amount = (campaign.raised_amount or 0) + amount
    if campaign.status == "active" and campaign.raised_amount >= campaign.goal_amount:
        campaign.status = "completed"
    if commit:
        db.commit()
        db.refresh(donation)
    else:
        db.flush()

    return {
        "id": donation.id,
        "campaign_id": campaign.id,
        "campaign_title": campaign.title,
        "donor_name": donation.donor_name,
        "donor_email": donation.donor_email,
        "amount": donation.amount,
        "payment_method": donation.payment_method,
        "transaction_id": donation.transaction_id,
        "donated_at": donation.donated_at.isoformat() + "Z",
        "receipt_number": receipt.receipt_number,
        "ledger": {"block_index": block.id, "block_hash": block.block_hash, "data_hash": block.data_hash},
        "risk": {"score": risk["score"], "level": risk["level"]},
    }
