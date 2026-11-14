"""
Milestone-based fund release. Mirrors the rules enforced by
contracts/TransFundEscrow.sol so the off-chain and on-chain behaviour match:

  * milestones release strictly in order
  * proof → donor vote (weighted by ₹ contributed) → finalize
  * release needs approve weight > reject weight AND (quorum of raised
    funds voted OR the voting window has closed)
  * cumulative releases ≤ raised;  expenditure ≤ released
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models

QUORUM_BPS = int(os.getenv("ESCROW_QUORUM_BPS", "2000"))  # 20% of raised must vote for early close
VOTING_HOURS = float(os.getenv("ESCROW_VOTING_HOURS", "72"))


def milestones_for(db: Session, campaign_id: int) -> list[models.Milestone]:
    return (
        db.query(models.Milestone)
        .filter(models.Milestone.campaign_id == campaign_id)
        .order_by(models.Milestone.sequence.asc())
        .all()
    )


def released_total(milestones: list[models.Milestone]) -> float:
    return sum(m.amount for m in milestones if m.status == "released")


def utilized_total(db: Session, campaign_id: int) -> float:
    return db.query(func.coalesce(func.sum(models.Utilization.amount), 0.0)).filter(
        models.Utilization.campaign_id == campaign_id
    ).scalar() or 0.0


def funds(db: Session, campaign: models.Campaign) -> dict[str, Any]:
    ms = milestones_for(db, campaign.id)
    raised = campaign.raised_amount or 0
    utilized = utilized_total(db, campaign.id)
    if ms:
        released = released_total(ms)
        locked = max(0.0, raised - released)
    else:  # legacy campaigns without milestones: everything raised is spendable
        released, locked = raised, 0.0
    return {
        "escrow": bool(ms),
        "raised": round(raised, 2),
        "released": round(released, 2),
        "locked_in_escrow": round(locked, 2),
        "utilized": round(utilized, 2),
        "spendable": round(max(0.0, released - utilized), 2),
    }


def donor_weight(db: Session, campaign_id: int, donor_email: str) -> float:
    return db.query(func.coalesce(func.sum(models.Donation.amount), 0.0)).filter(
        models.Donation.campaign_id == campaign_id,
        func.lower(models.Donation.donor_email) == donor_email.strip().lower(),
        models.Donation.status == "completed",
    ).scalar() or 0.0



def tally(db: Session, m: models.Milestone, campaign: models.Campaign, round_no: int) -> dict[str, Any]:
    votes = db.query(models.MilestoneVote).filter(
        models.MilestoneVote.milestone_id == m.id, models.MilestoneVote.round == round_no,
    ).all()
    approve = sum(v.weight for v in votes if v.approve)
    reject = sum(v.weight for v in votes if not v.approve)
    raised = campaign.raised_amount or 0
    voted_bps = int((approve + reject) * 10_000 / raised) if raised > 0 else 0
    now = datetime.utcnow()
    window_over = bool(m.voting_deadline and now > m.voting_deadline)
    quorum = voted_bps >= QUORUM_BPS
    return {
        "round": round_no,
        "approve_weight": round(approve, 2),
        "reject_weight": round(reject, 2),
        "voter_count": len(votes),
        "approve_count": sum(1 for v in votes if v.approve),
        "reject_count": sum(1 for v in votes if not v.approve),
        "turnout_percent": round(voted_bps / 100, 2),
        "quorum_percent": QUORUM_BPS / 100,
        "quorum_met": quorum,
        "window_over": window_over,
        "can_finalize": m.status == "voting" and (quorum or window_over),
        "passing": approve > reject,
    }


def next_milestone(milestones: list[models.Milestone]) -> Optional[models.Milestone]:
    return next((m for m in milestones if m.status != "released"), None)


def round_of(db: Session, m: models.Milestone) -> int:
    """Current voting round = number of proof submissions so far (min 1)."""
    n = db.query(func.count(models.LedgerBlock.id)).filter(
        models.LedgerBlock.entity_type == "milestone",
        models.LedgerBlock.entity_id == m.id,
        models.LedgerBlock.event_type == "milestone_proof_submitted",
    ).scalar() or 0
    return max(1, n)


def require_owner(campaign: models.Campaign, organizer_email: str) -> None:
    if (organizer_email or "").strip().lower() != (campaign.organizer_email or "").strip().lower():
        raise HTTPException(status_code=403, detail="Only the campaign organizer can do this")
