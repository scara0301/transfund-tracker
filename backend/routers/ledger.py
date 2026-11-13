from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from services import chain_anchor, ledger

router = APIRouter(prefix="/ledger", tags=["ledger"])


@router.get("/")
def list_blocks(
    campaign_id: Optional[int] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    before: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.LedgerBlock)
    if campaign_id is not None:
        q = q.filter(models.LedgerBlock.campaign_id == campaign_id)
    if event_type:
        q = q.filter(models.LedgerBlock.event_type == event_type)
    if before is not None:
        q = q.filter(models.LedgerBlock.id < before)
    blocks = q.order_by(models.LedgerBlock.id.desc()).limit(min(max(limit, 1), 200)).all()
    total = db.query(models.LedgerBlock).count()
    return {"chain_length": total, "blocks": [ledger.block_to_dict(b) for b in blocks]}


@router.get("/verify")
def verify(campaign_id: Optional[int] = None, db: Session = Depends(get_db)):
    return ledger.verify_chain(db, campaign_id)


@router.get("/status")
def status(db: Session = Depends(get_db)):
    tip = db.query(models.LedgerBlock).order_by(models.LedgerBlock.id.desc()).first()
    last_anchor = db.query(models.LedgerAnchor).order_by(models.LedgerAnchor.id.desc()).first()
    return {
        "chain_length": (tip.id + 1) if tip else 0,
        "tip_hash": tip.block_hash if tip else None,
        "difficulty": ledger.DIFFICULTY,
        "anchoring": chain_anchor.status(),
        "unanchored_blocks": ((tip.id - last_anchor.to_block) if last_anchor else (tip.id + 1)) if tip else 0,
        "anchors": [
            {"id": a.id, "from_block": a.from_block, "to_block": a.to_block, "merkle_root": a.merkle_root,
             "network": a.network, "tx_hash": a.tx_hash, "created_at": a.created_at.isoformat() + "Z"}
            for a in db.query(models.LedgerAnchor).order_by(models.LedgerAnchor.id.desc()).limit(10).all()
        ],
    }


@router.post("/anchor")
def anchor(db: Session = Depends(get_db)):
    try:
        return chain_anchor.anchor_pending(db)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/block/{block_hash}")
def get_block(block_hash: str, db: Session = Depends(get_db)):
    b = db.query(models.LedgerBlock).filter(models.LedgerBlock.block_hash == block_hash).first()
    if not b:
        raise HTTPException(status_code=404, detail="Block not found")
    nxt = db.get(models.LedgerBlock, b.id + 1)
    return {**ledger.block_to_dict(b), "next_hash": nxt.block_hash if nxt else None}


@router.get("/donation/{donation_id}")
def donation_proof(donation_id: int, db: Session = Depends(get_db)):
    """Everything a donor needs to independently check their donation is on the ledger."""
    d = db.get(models.Donation, donation_id)
    if not d:
        raise HTTPException(status_code=404, detail="Donation not found")
    b = (
        db.query(models.LedgerBlock)
        .filter(models.LedgerBlock.entity_type == "donation", models.LedgerBlock.entity_id == donation_id)
        .order_by(models.LedgerBlock.id.desc())
        .first()
    )
    if not b:
        raise HTTPException(status_code=404, detail="Donation has no ledger entry")
    live = ledger.donation_payload(d)
    live_hash = ledger.sha256_hex(ledger.canonical_json(live))
    return {
        "block": ledger.block_to_dict(b),
        "recomputed_data_hash": live_hash,
        "matches_database": live_hash == b.data_hash,
        "how_to_verify": "sha256(canonical JSON of payload) must equal data_hash; "
                         "sha256(index|timestamp|event_type|data_hash|prev_hash|nonce) must equal block_hash.",
    }
