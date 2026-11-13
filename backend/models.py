from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class Donor(Base):
    __tablename__ = "donors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    donations = relationship("Donation", back_populates="donor")


class Organizer(Base):
    __tablename__ = "organizers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String, default="General")
    goal_amount = Column(Float, default=0)
    raised_amount = Column(Float, default=0)
    status = Column(String, default="active")  # active | completed | cancelled
    organizer_email = Column(String, nullable=False)
    image_url = Column(String, nullable=True)
    close_reason = Column(String, nullable=True)
    daily_donor_limit = Column(Float, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    # AI fraud screening result at creation time (0-100, higher = riskier)
    risk_score = Column(Float, nullable=True)
    risk_flags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    donations = relationship("Donation", back_populates="campaign")
    utilizations = relationship("Utilization", back_populates="campaign")
    milestones = relationship("Milestone", back_populates="campaign", order_by="Milestone.sequence")


class Donation(Base):
    __tablename__ = "donations"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=True)
    donor_name = Column(String, nullable=False)
    donor_email = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String, nullable=True)  # UPI | Card | Bank Transfer
    transaction_id = Column(String, nullable=True)
    status = Column(String, default="completed")  # pending | completed | failed
    payment_order_id = Column(String, nullable=True, index=True)
    risk_score = Column(Float, nullable=True)
    risk_flags = Column(JSON, nullable=True)
    ledger_hash = Column(String, nullable=True)
    donated_at = Column(DateTime, default=datetime.utcnow)

    campaign = relationship("Campaign", back_populates="donations")
    donor = relationship("Donor", back_populates="donations")
    receipt = relationship("Receipt", back_populates="donation", uselist=False)


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    donation_id = Column(Integer, ForeignKey("donations.id"), unique=True, nullable=False)
    receipt_number = Column(String, unique=True, index=True, nullable=False)
    amount = Column(Float, nullable=False)
    issued_to = Column(String, nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow)

    donation = relationship("Donation", back_populates="receipt")


class Utilization(Base):
    __tablename__ = "utilizations"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    proof_url = Column(String, nullable=True)
    category = Column(String, default="general")  # logistics | medical | infrastructure | general
    created_by = Column(String, nullable=False)  # organizer email
    milestone_id = Column(Integer, ForeignKey("milestones.id"), nullable=True)
    # Invoice details (from AI OCR, editable by the organizer)
    vendor_name = Column(String, nullable=True)
    vendor_gstin = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True)
    invoice_date = Column(String, nullable=True)
    invoice_hash = Column(String, nullable=True, index=True)  # sha256 of proof file
    ocr_total = Column(Float, nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    risk_flags = Column(JSON, nullable=True)
    status = Column(String, default="recorded")  # recorded | flagged
    ledger_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    campaign = relationship("Campaign", back_populates="utilizations")


class CampaignUpdate(Base):
    __tablename__ = "campaign_updates"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    file_url = Column(String, nullable=True)
    posted_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="moderator")  # super_admin | moderator
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Milestone-based escrow ──────────────────────────────────────

class Milestone(Base):
    """
    A tranche of the campaign goal. Funds for a milestone are released to
    the organizer only after they submit proof and contributing donors
    approve it (votes weighted by amount donated).
    """
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)  # 1-based release order
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Float, nullable=False)
    # pending → voting → released | rejected (rejected can resubmit → voting)
    status = Column(String, default="pending")
    proof_url = Column(String, nullable=True)
    proof_note = Column(Text, nullable=True)
    proof_hash = Column(String, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    voting_deadline = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    ledger_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    campaign = relationship("Campaign", back_populates="milestones")
    votes = relationship("MilestoneVote", back_populates="milestone")


class MilestoneVote(Base):
    __tablename__ = "milestone_votes"
    __table_args__ = (UniqueConstraint("milestone_id", "donor_email", "round", name="uq_vote_per_round"),)

    id = Column(Integer, primary_key=True, index=True)
    milestone_id = Column(Integer, ForeignKey("milestones.id"), nullable=False, index=True)
    donor_email = Column(String, nullable=False)
    approve = Column(Boolean, nullable=False)
    weight = Column(Float, nullable=False)  # donor's contribution in ₹ at vote time
    round = Column(Integer, default=1)  # increments each time proof is resubmitted
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    milestone = relationship("Milestone", back_populates="votes")


# ── Blockchain ledger ───────────────────────────────────────────

class LedgerBlock(Base):
    """
    Append-only, hash-chained record of every financial event. Each block
    commits to the previous block's hash, so altering any historical block
    (or the database row it describes) is detectable by /ledger/verify.
    """
    __tablename__ = "ledger_blocks"

    id = Column(Integer, primary_key=True)  # == block index
    timestamp = Column(String, nullable=False)  # ISO-8601 UTC, part of the hash
    event_type = Column(String, nullable=False, index=True)
    campaign_id = Column(Integer, nullable=True, index=True)  # no FK: blocks outlive rows
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=False)
    data_hash = Column(String, nullable=False)
    prev_hash = Column(String, nullable=False)
    nonce = Column(Integer, nullable=False)
    block_hash = Column(String, nullable=False, unique=True, index=True)
    anchor_id = Column(Integer, ForeignKey("ledger_anchors.id"), nullable=True)


class LedgerAnchor(Base):
    """A Merkle root of a range of blocks, published to a public EVM chain."""
    __tablename__ = "ledger_anchors"

    id = Column(Integer, primary_key=True)
    from_block = Column(Integer, nullable=False)
    to_block = Column(Integer, nullable=False)
    merkle_root = Column(String, nullable=False)
    network = Column(String, nullable=False)
    tx_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Payments ────────────────────────────────────────────────────

class PaymentOrder(Base):
    """An INR payment intent. Becomes a Donation once payment is verified."""
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True)
    order_id = Column(String, unique=True, index=True, nullable=False)
    provider = Column(String, nullable=False)  # razorpay | demo
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=True)
    donor_name = Column(String, nullable=False)
    donor_email = Column(String, nullable=False)
    amount = Column(Float, nullable=False)  # rupees
    currency = Column(String, default="INR")
    status = Column(String, default="created")  # created | paid | failed
    payment_id = Column(String, nullable=True)
    donation_id = Column(Integer, ForeignKey("donations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── AI: cached invoice OCR results ──────────────────────────────

class InvoiceScan(Base):
    __tablename__ = "invoice_scans"

    id = Column(Integer, primary_key=True)
    file_hash = Column(String, unique=True, index=True, nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
