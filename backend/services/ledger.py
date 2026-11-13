"""
Hash-chained, append-only ledger ("TransFund chain").

Every financial event — donation, milestone proof, donor vote, fund release,
expenditure — is written as a block:

    data_hash  = sha256(canonical_json(payload))
    block_hash = sha256(index | timestamp | event_type | data_hash | prev_hash | nonce)

with a small proof-of-work (block_hash must start with LEDGER_DIFFICULTY hex
zeros). Because each block commits to its predecessor, rewriting any block
invalidates every block after it. `verify_chain` also re-derives the payload
of donation / expenditure blocks from the live database rows, so a record
edited directly in Postgres is reported as tampered even if the chain itself
was left intact.

Ranges of blocks can be committed to a public EVM chain as a Merkle root
(see services/chain_anchor.py), making the history externally verifiable.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

import models

GENESIS_PREV = "0" * 64
DIFFICULTY = int(os.getenv("LEDGER_DIFFICULTY", "3"))
_ADVISORY_LOCK_KEY = 0x7F_7F_10  # arbitrary app-wide key


# ── hashing primitives ──────────────────────────────────────────

def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def paise(amount: float | None) -> int:
    """Money is hashed as integer paise so float formatting can never change a hash."""
    return int(round((amount or 0) * 100))


def compute_block_hash(index: int, timestamp: str, event_type: str, data_hash: str, prev_hash: str, nonce: int) -> str:
    return sha256_hex(f"{index}|{timestamp}|{event_type}|{data_hash}|{prev_hash}|{nonce}")


def _mine(index: int, timestamp: str, event_type: str, data_hash: str, prev_hash: str) -> tuple[int, str]:
    target = "0" * DIFFICULTY
    nonce = 0
    while True:
        h = compute_block_hash(index, timestamp, event_type, data_hash, prev_hash, nonce)
        if h.startswith(target):
            return nonce, h
        nonce += 1


def merkle_root(hashes: list[str]) -> str:
    if not hashes:
        return GENESIS_PREV
    level = [bytes.fromhex(h) for h in hashes]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0].hex()


# ── canonical payloads for each entity type ─────────────────────
# These are the single source of truth for what gets hashed. verify_chain
# calls the same functions on live rows to detect database tampering.

def donation_payload(d: models.Donation) -> dict:
    return {
        "donation_id": d.id,
        "campaign_id": d.campaign_id,
        "donor_email_hash": sha256_hex((d.donor_email or "").strip().lower()),  # no PII on the chain
        "amount_paise": paise(d.amount),
        "currency": "INR",
        "payment_method": d.payment_method,
        "transaction_id": d.transaction_id,
        "donated_at": d.donated_at.isoformat() if d.donated_at else None,
    }


def utilization_payload(u: models.Utilization) -> dict:
    return {
        "utilization_id": u.id,
        "campaign_id": u.campaign_id,
        "milestone_id": u.milestone_id,
        "amount_paise": paise(u.amount),
        "category": u.category,
        "description": u.description,
        "vendor_gstin": u.vendor_gstin,
        "invoice_number": u.invoice_number,
        "invoice_hash": u.invoice_hash,
        "created_by_hash": sha256_hex((u.created_by or "").strip().lower()),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


DRIFT_CHECKS = {
    "donation": (models.Donation, donation_payload),
    "utilization": (models.Utilization, utilization_payload),
}


# ── writing ─────────────────────────────────────────────────────

def _lock(db: Session) -> None:
    """Serialise appends so two concurrent writers can't both extend the same tip."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY})


def _tip(db: Session) -> Optional[models.LedgerBlock]:
    return db.query(models.LedgerBlock).order_by(models.LedgerBlock.id.desc()).first()


def ensure_genesis(db: Session) -> models.LedgerBlock:
    tip = _tip(db)
    if tip:
        return tip
    return _write(db, None, "genesis", None, None, None,
                  {"chain": "TransFund", "purpose": "Transparent crowdfunding ledger", "version": 1})


def _write(db, tip, event_type, campaign_id, entity_type, entity_id, payload) -> models.LedgerBlock:
    index = (tip.id + 1) if tip else 0
    prev_hash = tip.block_hash if tip else GENESIS_PREV
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    data_hash = sha256_hex(canonical_json(payload))
    nonce, block_hash = _mine(index, timestamp, event_type, data_hash, prev_hash)
    block = models.LedgerBlock(
        id=index, timestamp=timestamp, event_type=event_type, campaign_id=campaign_id,
        entity_type=entity_type, entity_id=entity_id, payload=payload,
        data_hash=data_hash, prev_hash=prev_hash, nonce=nonce, block_hash=block_hash,
    )
    db.add(block)
    db.flush()
    return block


def append_block(
    db: Session,
    event_type: str,
    payload: dict,
    campaign_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
) -> models.LedgerBlock:
    """
    Append a block inside the caller's transaction. The caller commits, so
    the block and the business row it describes are written atomically.
    """
    _lock(db)
    tip = _tip(db) or ensure_genesis(db)
    return _write(db, tip, event_type, campaign_id, entity_type, entity_id, payload)


# ── reading / verification ──────────────────────────────────────

def block_to_dict(b: models.LedgerBlock) -> dict[str, Any]:
    return {
        "index": b.id,
        "timestamp": b.timestamp,
        "event_type": b.event_type,
        "campaign_id": b.campaign_id,
        "entity_type": b.entity_type,
        "entity_id": b.entity_id,
        "payload": b.payload,
        "data_hash": b.data_hash,
        "prev_hash": b.prev_hash,
        "nonce": b.nonce,
        "block_hash": b.block_hash,
        "anchor_id": b.anchor_id,
    }


def verify_chain(db: Session, campaign_id: Optional[int] = None) -> dict[str, Any]:
    """
    Walk the whole chain and report:
      * broken links / altered blocks (hash mismatches, bad proof-of-work)
      * database drift — donation/expense rows whose current values no longer
        match what was committed to the chain, or that were deleted.
    If campaign_id is given, issues are filtered to that campaign but the
    full chain is still checked (a campaign's blocks are only trustworthy if
    every earlier block is).
    """
    blocks = db.query(models.LedgerBlock).order_by(models.LedgerBlock.id.asc()).all()
    issues: list[dict[str, Any]] = []
    target = "0" * DIFFICULTY
    prev_hash = GENESIS_PREV
    chain_broken_at: Optional[int] = None

    for expected_index, b in enumerate(blocks):
        problems = []
        if b.id != expected_index:
            problems.append(f"index gap: expected {expected_index}, found {b.id}")
        if b.prev_hash != prev_hash:
            problems.append("prev_hash does not match previous block")
        if sha256_hex(canonical_json(b.payload)) != b.data_hash:
            problems.append("payload was modified after it was written")
        recomputed = compute_block_hash(b.id, b.timestamp, b.event_type, b.data_hash, b.prev_hash, b.nonce)
        if recomputed != b.block_hash:
            problems.append("block hash mismatch")
        elif not b.block_hash.startswith(target):
            problems.append("proof-of-work not satisfied")
        if problems:
            if chain_broken_at is None:
                chain_broken_at = b.id
            issues.append({"type": "chain", "block_index": b.id, "campaign_id": b.campaign_id, "problems": problems})
        prev_hash = b.block_hash

    # Database drift: latest block per financial entity vs the live row.
    latest: dict[tuple[str, int], models.LedgerBlock] = {}
    for b in blocks:
        if b.entity_type in DRIFT_CHECKS and b.entity_id is not None:
            latest[(b.entity_type, b.entity_id)] = b
    drift = 0
    for (etype, eid), b in latest.items():
        Model, fn = DRIFT_CHECKS[etype]
        row = db.get(Model, eid)
        if row is None:
            issues.append({"type": "drift", "block_index": b.id, "campaign_id": b.campaign_id,
                           "problems": [f"{etype} #{eid} was deleted from the database"]})
            drift += 1
            continue
        if sha256_hex(canonical_json(fn(row))) != b.data_hash:
            issues.append({"type": "drift", "block_index": b.id, "campaign_id": b.campaign_id,
                           "problems": [f"{etype} #{eid} differs from the value recorded on the ledger"]})
            drift += 1

    # Financial rows that never made it onto the chain at all.
    for etype, (Model, _fn) in DRIFT_CHECKS.items():
        q = db.query(Model.id, Model.campaign_id)
        if campaign_id is not None:
            q = q.filter(Model.campaign_id == campaign_id)
        for rid, cid in q.all():
            if (etype, rid) not in latest:
                issues.append({"type": "unrecorded", "block_index": None, "campaign_id": cid,
                               "problems": [f"{etype} #{rid} has no ledger entry"]})

    if campaign_id is not None:
        issues = [i for i in issues if i["campaign_id"] == campaign_id or i["type"] == "chain"]

    anchored = db.query(models.LedgerAnchor).order_by(models.LedgerAnchor.id.desc()).first()
    return {
        "valid": not issues,
        "chain_valid": chain_broken_at is None,
        "chain_length": len(blocks),
        "tip_hash": blocks[-1].block_hash if blocks else None,
        "difficulty": DIFFICULTY,
        "broken_at": chain_broken_at,
        "drift_count": drift,
        "issues": issues[:100],
        "issue_count": len(issues),
        "campaign_blocks": sum(1 for b in blocks if campaign_id is not None and b.campaign_id == campaign_id),
        "last_anchor": {
            "to_block": anchored.to_block, "merkle_root": anchored.merkle_root,
            "network": anchored.network, "tx_hash": anchored.tx_hash,
            "created_at": anchored.created_at.isoformat() + "Z",
        } if anchored else None,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def backfill(db: Session) -> int:
    """
    Record pre-existing donations and expenditures (created before the ledger
    existed) so the chain covers the full history. Idempotent.
    """
    ensure_genesis(db)
    recorded = {
        (et, eid) for et, eid in db.query(models.LedgerBlock.entity_type, models.LedgerBlock.entity_id)
        .filter(models.LedgerBlock.entity_type.in_(list(DRIFT_CHECKS))).all()
    }
    n = 0
    for etype, (Model, fn) in DRIFT_CHECKS.items():
        ts_col = Model.donated_at if etype == "donation" else Model.created_at
        for row in db.query(Model).order_by(ts_col.asc(), Model.id.asc()).all():
            if (etype, row.id) in recorded:
                continue
            # The hashed payload must equal fn(row) exactly for drift checks,
            # so the "backfilled" marker lives in the event type instead.
            block = append_block(db, f"{etype}_backfill", fn(row), row.campaign_id, etype, row.id)
            row.ledger_hash = block.block_hash
            n += 1
    db.commit()
    return n
