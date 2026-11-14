from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
import models
import schemas
from routers import payments
from services import donation_service

router = APIRouter(prefix="/donations", tags=["donations"])


@router.post("/")
def make_donation(donation: schemas.DonationCreate, db: Session = Depends(get_db)):
    """
    Direct donation without a payment gateway. Only available in demo mode —
    with Razorpay configured, donations must go through /payments/order + /payments/verify.
    """
    if payments.provider() != "demo":
        raise HTTPException(status_code=400, detail="Use /payments/order to donate")
    campaign = db.get(models.Campaign, donation.campaign_id)
    donation_service.check_can_donate(db, campaign, donation.donor_email, donation.amount)
    return donation_service.record_donation(
        db, campaign, donation.donor_name, donation.donor_email, donation.amount,
        donor_id=donation.donor_id, payment_method=donation.payment_method or "Direct",
        transaction_id=donation.transaction_id,
    )


def _extra(d: models.Donation) -> dict:
    return {
        "payment_method": d.payment_method,
        "transaction_id": d.transaction_id,
        "ledger_hash": d.ledger_hash,
        "risk_score": d.risk_score,
    }


@router.get("/")
def get_donations(
    donor_email: Optional[str] = None,
    organizer_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Flexible donations endpoint:
    - ?donor_email=x  → this donor's all donations (with campaign title)
    - ?organizer_email=x → grouped by campaign for the organizer
    - ?campaign_id=x  → all donations for a specific campaign
    """

    # Donor's own donations
    if donor_email:
        rows = (
            db.query(models.Donation, models.Campaign.title)
            .join(models.Campaign, models.Donation.campaign_id == models.Campaign.id)
            .filter(models.Donation.donor_email == donor_email)
            .order_by(models.Donation.donated_at.desc())
            .all()
        )
        return [
            {
                "id": d.id,
                "campaign_id": d.campaign_id,
                "campaign_title": title,
                "donor_name": d.donor_name,
                "donor_email": d.donor_email,
                "amount": d.amount,
                "donated_at": d.donated_at.isoformat() + "Z",
                **_extra(d),
            }
            for d, title in rows
        ]

    # Organizer's donations grouped by campaign
    if organizer_email:
        campaigns = (
            db.query(models.Campaign)
            .filter(models.Campaign.organizer_email == organizer_email)
            .order_by(models.Campaign.created_at.desc())
            .all()
        )
        result = []
        for c in campaigns:
            donations = (
                db.query(models.Donation)
                .filter(models.Donation.campaign_id == c.id)
                .order_by(models.Donation.donated_at.desc())
                .all()
            )
            result.append(
                {
                    "campaign_id": c.id,
                    "campaign_title": c.title,
                    "campaign_category": c.category,
                    "campaign_status": c.status,
                    "donations": [
                        {
                            "id": d.id,
                            "donor_name": d.donor_name,
                            "donor_email": d.donor_email,
                            "amount": d.amount,
                            "donated_at": d.donated_at.isoformat() + "Z",
                            **_extra(d),
                        }
                        for d in donations
                    ],
                }
            )
        return result

    # Single campaign donations
    if campaign_id:
        rows = (
            db.query(models.Donation)
            .filter(models.Donation.campaign_id == campaign_id)
            .order_by(models.Donation.donated_at.desc())
            .all()
        )
        return [
            {
                "id": d.id,
                "donor_name": d.donor_name,
                "donor_email": d.donor_email,
                "amount": d.amount,
                "donated_at": d.donated_at.isoformat() + "Z",
                **_extra(d),
            }
            for d in rows
        ]

    raise HTTPException(status_code=400, detail="Provide donor_email, organizer_email, or campaign_id")


@router.get("/impact")
def donor_impact(donor_email: str, db: Session = Depends(get_db)):
    """
    Proportional impact breakdown for a donor.

    For each campaign the donor contributed to, compute their share of
    every logged utilization based on (donor_total / campaign_raised).
    """
    donor_donations = (
        db.query(models.Donation)
        .filter(models.Donation.donor_email == donor_email)
        .all()
    )
    if not donor_donations:
        return []

    # Sum per campaign for this donor
    by_campaign: dict[int, float] = {}
    for d in donor_donations:
        by_campaign[d.campaign_id] = by_campaign.get(d.campaign_id, 0) + d.amount

    result = []
    for campaign_id, donor_total in by_campaign.items():
        campaign = db.query(models.Campaign).filter(models.Campaign.id == campaign_id).first()
        if not campaign:
            continue
        raised = campaign.raised_amount or 0
        share = (donor_total / raised) if raised > 0 else 0

        utilizations = (
            db.query(models.Utilization)
            .filter(models.Utilization.campaign_id == campaign_id)
            .order_by(models.Utilization.created_at.desc())
            .all()
        )
        total_utilized = sum(u.amount for u in utilizations)
        your_utilized = round(share * total_utilized, 2)
        your_unspent = round(max(0, donor_total - your_utilized), 2)

        result.append({
            "campaign_id": campaign_id,
            "campaign_title": campaign.title,
            "campaign_status": campaign.status,
            "your_donation": round(donor_total, 2),
            "campaign_raised": round(raised, 2),
            "share_percent": round(share * 100, 2),
            "your_utilized": your_utilized,
            "your_unspent": your_unspent,
            "breakdown": [
                {
                    "utilization_id": u.id,
                    "description": u.description,
                    "category": u.category,
                    "utilization_amount": round(u.amount, 2),
                    "your_share": round(share * u.amount, 2),
                    "proof_url": u.proof_url,
                    "created_at": u.created_at.isoformat() + "Z",
                }
                for u in utilizations
            ],
        })

    return result
