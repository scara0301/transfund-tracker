import hashlib
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import get_db
from services import escrow, ledger

router = APIRouter(prefix="/milestones", tags=["milestones"])


def _out(db: Session, m: models.Milestone, campaign: models.Campaign, donor_email: Optional[str] = None) -> dict:
    rnd = escrow.round_of(db, m)
    t = escrow.tally(db, m, campaign, rnd)
    my_vote = None
    if donor_email:
        v = db.query(models.MilestoneVote).filter(
            models.MilestoneVote.milestone_id == m.id,
            models.MilestoneVote.donor_email == donor_email.strip().lower(),
            models.MilestoneVote.round == rnd,
        ).first()
        my_vote = None if v is None else ("approve" if v.approve else "reject")
    iso = lambda d: d.isoformat() + "Z" if d else None  # noqa: E731
    return {
        "id": m.id, "campaign_id": m.campaign_id, "sequence": m.sequence, "title": m.title,
        "description": m.description, "amount": m.amount, "status": m.status,
        "proof_url": m.proof_url, "proof_note": m.proof_note, "proof_hash": m.proof_hash,
        "submitted_at": iso(m.submitted_at), "voting_deadline": iso(m.voting_deadline),
        "released_at": iso(m.released_at), "ledger_hash": m.ledger_hash, "tally": t, "my_vote": my_vote,
    }


@router.get("/")
def list_milestones(campaign_id: int, donor_email: Optional[str] = None, db: Session = Depends(get_db)):
    campaign = db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    ms = escrow.milestones_for(db, campaign_id)
    nxt = escrow.next_milestone(ms)
    weight = escrow.donor_weight(db, campaign_id, donor_email) if donor_email else 0
    return {
        "campaign_id": campaign_id,
        "funds": escrow.funds(db, campaign),
        "next_milestone_id": nxt.id if nxt else None,
        "voting_hours": escrow.VOTING_HOURS,
        "quorum_percent": escrow.QUORUM_BPS / 100,
        "my_weight": round(weight, 2),
        "milestones": [_out(db, m, campaign, donor_email) for m in ms],
    }


class MilestoneIn(BaseModel):
    title: str
    amount: float
    description: Optional[str] = None


class MilestonePlan(BaseModel):
    campaign_id: int
    organizer_email: str
    milestones: list[MilestoneIn]


def create_plan(db: Session, campaign: models.Campaign, items: list[MilestoneIn]) -> list[models.Milestone]:
    """Validate and insert a milestone plan; records it on the ledger. Caller commits."""
    if not items:
        return []
    if len(items) > 12:
        raise HTTPException(status_code=400, detail="At most 12 milestones")
    for it in items:
        if not it.title.strip() or it.amount <= 0:
            raise HTTPException(status_code=400, detail="Each milestone needs a title and a positive amount")
    total = sum(it.amount for it in items)
    if total > campaign.goal_amount + 0.5:
        raise HTTPException(status_code=400, detail=f"Milestones total ₹{total:,.0f}, more than the ₹{campaign.goal_amount:,.0f} goal")
    rows = []
    for i, it in enumerate(items, start=1):
        m = models.Milestone(campaign_id=campaign.id, sequence=i, title=it.title.strip(),
                             description=(it.description or "").strip() or None, amount=round(it.amount, 2))
        db.add(m)
        rows.append(m)
    db.flush()
    block = ledger.append_block(db, "milestone_plan", {
        "campaign_id": campaign.id,
        "goal_paise": ledger.paise(campaign.goal_amount),
        "quorum_bps": escrow.QUORUM_BPS,
        "milestones": [{"id": m.id, "sequence": m.sequence, "title": m.title, "amount_paise": ledger.paise(m.amount)} for m in rows],
    }, campaign.id, "campaign", campaign.id)
    for m in rows:
        m.ledger_hash = block.block_hash
    return rows


@router.post("/plan")
def set_plan(body: MilestonePlan, db: Session = Depends(get_db)):
    """Add a milestone plan to a campaign that doesn't have one yet (e.g. older campaigns)."""
    campaign = db.get(models.Campaign, body.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    escrow.require_owner(campaign, body.organizer_email)
    if escrow.milestones_for(db, campaign.id):
        raise HTTPException(status_code=409, detail="This campaign already has a milestone plan; plans are immutable once set")
    if escrow.utilized_total(db, campaign.id) > 0:
        raise HTTPException(status_code=409, detail="Milestones must be set before any funds are spent")
    create_plan(db, campaign, body.milestones)
    db.commit()
    return list_milestones(campaign.id, None, db)


@router.post("/{milestone_id}/proof")
def submit_proof(
    milestone_id: int,
    organizer_email: str = Form(...),
    note: str = Form(...),
    proof: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    m = db.get(models.Milestone, milestone_id)
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    campaign = db.get(models.Campaign, m.campaign_id)
    escrow.require_owner(campaign, organizer_email)
    ms = escrow.milestones_for(db, campaign.id)
    nxt = escrow.next_milestone(ms)
    if not nxt or nxt.id != m.id:
        raise HTTPException(status_code=400, detail="Milestones are released in order — complete the earlier one first")
    if m.status not in ("pending", "rejected"):
        raise HTTPException(status_code=400, detail=f"Milestone is already {m.status}")
    needed = escrow.released_total(ms) + m.amount
    if (campaign.raised_amount or 0) + 0.005 < needed:
        raise HTTPException(status_code=400, detail=f"Raise at least ₹{needed:,.0f} in total before requesting this tranche")
    if not note.strip():
        raise HTTPException(status_code=400, detail="Describe what was achieved")

    proof_hash = hashlib.sha256(note.strip().encode()).hexdigest()
    if proof and proof.filename:
        content = proof.file.read()
        if len(content) > 15 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Proof file must be under 15 MB")
        proof_hash = hashlib.sha256(content).hexdigest()
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "milestones")
        os.makedirs(upload_dir, exist_ok=True)
        safe = f"ms_{m.id}_{int(time.time())}_{os.path.basename(proof.filename).replace(' ', '_')}"
        with open(os.path.join(upload_dir, safe), "wb") as f:
            f.write(content)
        m.proof_url = f"/uploads/milestones/{safe}"

    now = datetime.utcnow()
    m.proof_note = note.strip()
    m.proof_hash = proof_hash
    m.submitted_at = now
    m.voting_deadline = now + timedelta(hours=escrow.VOTING_HOURS)
    m.status = "voting"
    block = ledger.append_block(db, "milestone_proof_submitted", {
        "milestone_id": m.id, "campaign_id": campaign.id, "sequence": m.sequence,
        "amount_paise": ledger.paise(m.amount), "proof_hash": proof_hash,
        "voting_deadline": m.voting_deadline.isoformat(),
    }, campaign.id, "milestone", m.id)
    m.ledger_hash = block.block_hash
    db.commit()
    return _out(db, m, campaign)


class VoteIn(BaseModel):
    donor_email: str
    approve: bool
    comment: Optional[str] = None


@router.post("/{milestone_id}/vote")
def vote(milestone_id: int, body: VoteIn, db: Session = Depends(get_db)):
    m = db.get(models.Milestone, milestone_id)
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    campaign = db.get(models.Campaign, m.campaign_id)
    email = body.donor_email.strip().lower()
    if m.status != "voting":
        raise HTTPException(status_code=400, detail="This milestone is not open for voting")
    if m.voting_deadline and datetime.utcnow() > m.voting_deadline:
        raise HTTPException(status_code=400, detail="Voting has closed")
    if email == (campaign.organizer_email or "").lower():
        raise HTTPException(status_code=403, detail="Organizers can't vote on their own milestones")
    weight = escrow.donor_weight(db, campaign.id, email)
    if weight <= 0:
        raise HTTPException(status_code=403, detail="Only donors to this campaign can vote")
    rnd = escrow.round_of(db, m)
    if db.query(models.MilestoneVote).filter(
        models.MilestoneVote.milestone_id == m.id, models.MilestoneVote.donor_email == email,
        models.MilestoneVote.round == rnd,
    ).first():
        raise HTTPException(status_code=409, detail="You have already voted on this milestone")

    v = models.MilestoneVote(milestone_id=m.id, donor_email=email, approve=body.approve,
                             weight=weight, round=rnd, comment=(body.comment or "").strip() or None)
    db.add(v)
    db.flush()
    ledger.append_block(db, "milestone_vote", {
        "milestone_id": m.id, "campaign_id": campaign.id, "round": rnd,
        "donor_email_hash": ledger.sha256_hex(email), "approve": body.approve,
        "weight_paise": ledger.paise(weight),
    }, campaign.id, "milestone_vote", v.id)
    db.commit()
    return _out(db, m, campaign, email)


class FinalizeIn(BaseModel):
    organizer_email: str


@router.post("/{milestone_id}/finalize")
def finalize(milestone_id: int, body: FinalizeIn, db: Session = Depends(get_db)):
    """Close voting: release the tranche if donors approved, otherwise mark it rejected."""
    m = db.get(models.Milestone, milestone_id)
    if not m:
        raise HTTPException(status_code=404, detail="Milestone not found")
    campaign = db.get(models.Campaign, m.campaign_id)
    escrow.require_owner(campaign, body.organizer_email)
    if m.status != "voting":
        raise HTTPException(status_code=400, detail="This milestone is not in voting")
    rnd = escrow.round_of(db, m)
    t = escrow.tally(db, m, campaign, rnd)
    if not t["can_finalize"]:
        raise HTTPException(
            status_code=400,
            detail=f"Voting is still open: needs {t['quorum_percent']:.0f}% turnout (now {t['turnout_percent']:.1f}%) or the deadline to pass",
        )
    now = datetime.utcnow()
    if t["passing"]:
        ms = escrow.milestones_for(db, campaign.id)
        if escrow.released_total(ms) + m.amount > (campaign.raised_amount or 0) + 0.005:
            raise HTTPException(status_code=400, detail="Not enough raised funds to release this tranche")
        m.status, m.released_at, event = "released", now, "milestone_released"
    else:
        m.status, event = "rejected", "milestone_rejected"
    block = ledger.append_block(db, event, {
        "milestone_id": m.id, "campaign_id": campaign.id, "sequence": m.sequence, "round": rnd,
        "amount_paise": ledger.paise(m.amount),
        "approve_weight_paise": ledger.paise(t["approve_weight"]),
        "reject_weight_paise": ledger.paise(t["reject_weight"]),
        "turnout_bps": int(t["turnout_percent"] * 100),
    }, campaign.id, "milestone", m.id)
    m.ledger_hash = block.block_hash
    db.commit()
    return _out(db, m, campaign)
