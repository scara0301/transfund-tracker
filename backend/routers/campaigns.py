from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import json
import shutil
import os

from database import get_db
import models
import schemas
from services import fraud, ledger
from routers.milestones import MilestoneIn, create_plan

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("/", response_model=List[schemas.CampaignOut])
def get_campaigns(
    category: Optional[str] = None,
    organizer_email: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Campaign)
    if category and category != "All":
        query = query.filter(models.Campaign.category == category)
    if organizer_email:
        query = query.filter(models.Campaign.organizer_email == organizer_email)
    return query.order_by(models.Campaign.created_at.desc()).all()


@router.get("/{campaign_id}", response_model=schemas.CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = (
        db.query(models.Campaign)
        .filter(models.Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/", response_model=schemas.CampaignOut)
def create_campaign(
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    goal_amount: float = Form(...),
    organizer_email: str = Form(...),
    daily_donor_limit: Optional[float] = Form(None),
    milestones: Optional[str] = Form(None),  # JSON: [{title, amount, description}]
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    if goal_amount <= 0:
        raise HTTPException(status_code=400, detail="Goal must be positive")
    plan: list[MilestoneIn] = []
    if milestones:
        try:
            plan = [MilestoneIn(**m) for m in json.loads(milestones)]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid milestones")

    image_url = None
    if image and image.filename:
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(image.filename).replace(" ", "_")
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/uploads/{safe_name}"

    campaign = models.Campaign(
        title=title,
        description=description,
        category=category,
        goal_amount=goal_amount,
        organizer_email=organizer_email,
        image_url=image_url,
        daily_donor_limit=daily_donor_limit,
    )
    risk = fraud.score_campaign(db, title, description, category, goal_amount, organizer_email, len(plan))
    campaign.risk_score = risk["score"]
    campaign.risk_flags = risk["signals"]
    db.add(campaign)
    db.flush()
    ledger.append_block(db, "campaign_created", {
        "campaign_id": campaign.id,
        "title": title,
        "category": category,
        "goal_paise": ledger.paise(goal_amount),
        "organizer_email_hash": ledger.sha256_hex(organizer_email.strip().lower()),
        "description_hash": ledger.sha256_hex(description),
        "daily_donor_limit_paise": ledger.paise(daily_donor_limit) if daily_donor_limit else None,
    }, campaign.id, "campaign", campaign.id)
    create_plan(db, campaign, plan)
    db.commit()
    db.refresh(campaign)
    return campaign

class CloseRequest(BaseModel):
    reason: str


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = (
        db.query(models.Campaign)
        .filter(models.Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # Financial history is immutable: a campaign that has received money can
    # be closed, but not erased (that would orphan its ledger entries).
    has_money = db.query(models.Donation.id).filter(models.Donation.campaign_id == campaign_id).first() \
        or db.query(models.Utilization.id).filter(models.Utilization.campaign_id == campaign_id).first()
    if has_money:
        raise HTTPException(
            status_code=409,
            detail="This campaign has donations or expenses recorded on the ledger and can't be deleted. End it instead.",
        )
    ms_ids = [mid for (mid,) in db.query(models.Milestone.id).filter(models.Milestone.campaign_id == campaign_id).all()]
    if ms_ids:
        db.query(models.MilestoneVote).filter(models.MilestoneVote.milestone_id.in_(ms_ids)).delete(synchronize_session=False)
        db.query(models.Milestone).filter(models.Milestone.id.in_(ms_ids)).delete(synchronize_session=False)
    db.query(models.PaymentOrder).filter(models.PaymentOrder.campaign_id == campaign_id).delete()
    db.query(models.CampaignUpdate).filter(models.CampaignUpdate.campaign_id == campaign_id).delete()
    ledger.append_block(db, "campaign_deleted", {"campaign_id": campaign_id, "title": campaign.title},
                        campaign_id, "campaign", campaign_id)
    if campaign.image_url:
        img_path = os.path.join(os.path.dirname(__file__), "..", campaign.image_url.lstrip("/"))
        if os.path.exists(img_path):
            os.remove(img_path)
    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted"}


@router.patch("/{campaign_id}")
def update_campaign(
    campaign_id: int,
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    goal_amount: Optional[float] = Form(None),
    daily_donor_limit: Optional[float] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    campaign = db.query(models.Campaign).filter(models.Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if title is not None:
        campaign.title = title
    if description is not None:
        campaign.description = description
    if category is not None:
        campaign.category = category
    if goal_amount is not None:
        planned = sum(m.amount for m in campaign.milestones)
        if goal_amount < planned:
            raise HTTPException(status_code=400, detail=f"Goal can't be below the ₹{planned:,.0f} committed to milestones")
        campaign.goal_amount = goal_amount
    if daily_donor_limit is not None:
        campaign.daily_donor_limit = daily_donor_limit

    if image and image.filename:
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(image.filename).replace(" ", "_")
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        campaign.image_url = f"/uploads/{safe_name}"

    db.commit()
    db.refresh(campaign)
    return campaign


@router.patch("/{campaign_id}/close")
def close_campaign(
    campaign_id: int,
    body: CloseRequest,
    db: Session = Depends(get_db),
):
    campaign = (
        db.query(models.Campaign)
        .filter(models.Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.status = "completed"
    campaign.close_reason = body.reason
    ledger.append_block(db, "campaign_closed", {
        "campaign_id": campaign_id, "reason": body.reason,
        "raised_paise": ledger.paise(campaign.raised_amount),
    }, campaign_id, "campaign", campaign_id)
    db.commit()
    return {"message": "Campaign closed", "reason": body.reason}
