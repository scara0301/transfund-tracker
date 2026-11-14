"""
AI fraud detection for campaigns, donations and expenditures.

Each check produces explainable *signals* (code, label, weight 0-1, detail).
Signals are combined with a noisy-OR, i.e. treated as independent pieces of
evidence that each make fraud more likely:

    risk = 100 * (1 - Π(1 - weight_i))

so two moderate signals outrank one, and no single weak signal saturates the
score. Statistical anomalies use a robust z-score (median / MAD on log
amounts), which is not dragged around by the very outliers it is looking for.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import models

LEVELS = [(30, "low"), (60, "medium"), (101, "high")]

SCAM_PHRASES = [
    "guaranteed return", "double your money", "investment opportunity", "high returns", "crypto",
    "bitcoin", "lottery", "you have won", "prize money", "wire transfer", "western union",
    "gift card", "send money directly", "pay directly", "personal account", "whatsapp me",
    "dm me", "100% returns", "risk free", "no questions asked", "act now", "limited time only",
]
UNRELATED_SPEND = [
    "party", "liquor", "alcohol", "beer", "vacation", "holiday trip", "resort", "jewellery", "jewelry",
    "gold", "iphone", "personal loan", "car purchase", "luxury", "casino", "betting", "cigarette",
]
UPI_RE = re.compile(r"\b[\w.\-]{2,}@(?:ok\w+|ybl|paytm|upi|apl|ibl|axl|sbi|icici|hdfcbank|axisbank|kotak)\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\-\s]?)?[6-9]\d{9}(?!\d)")


# ── scoring primitives ──────────────────────────────────────────

def signal(code: str, label: str, weight: float, detail: str = "") -> dict[str, Any]:
    return {"code": code, "label": label, "weight": round(max(0.0, min(weight, 0.95)), 3), "detail": detail}


def combine(signals: list[dict]) -> dict[str, Any]:
    p_clean = 1.0
    for s in signals:
        p_clean *= 1 - s["weight"]
    score = round(100 * (1 - p_clean), 1)
    level = next(name for cutoff, name in LEVELS if score < cutoff)
    return {"score": score, "level": level, "signals": sorted(signals, key=lambda s: -s["weight"])}


def robust_z(value: float, history: Iterable[float]) -> Optional[float]:
    """Modified z-score on log amounts (Iglewicz & Hoaglin). None if too little history."""
    xs = [math.log1p(v) for v in history if v and v > 0]
    if len(xs) < 6 or value <= 0:
        return None
    med = median(xs)
    mad = median(abs(x - med) for x in xs)
    if mad == 0:
        mad = 1e-6 if max(xs) == min(xs) else median(abs(x - med) for x in xs if x != med) or 1e-6
    return 0.6745 * (math.log1p(value) - med) / mad


def _shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _phrase_hits(text: str, phrases: list[str]) -> list[str]:
    low = (text or "").lower()
    return [p for p in phrases if re.search(r"\b" + re.escape(p) + r"\b", low)]


# ── campaigns ───────────────────────────────────────────────────

def score_campaign(
    db: Session,
    title: str,
    description: str,
    category: str,
    goal_amount: float,
    organizer_email: str,
    milestone_count: int = 0,
    exclude_campaign_id: Optional[int] = None,
) -> dict[str, Any]:
    sigs: list[dict] = []
    text = f"{title}\n{description or ''}"
    words = len(re.findall(r"\w+", description or ""))

    if words < 40:
        sigs.append(signal("thin_description", "Very short description", 0.25 if words < 20 else 0.12,
                           f"{words} words — legitimate campaigns usually explain need, plan and beneficiaries."))

    hits = _phrase_hits(text, SCAM_PHRASES)
    if hits:
        sigs.append(signal("scam_language", "Language common in donation scams", min(0.25 * len(hits), 0.6),
                           "Contains: " + ", ".join(f'“{h}”' for h in hits[:5])))

    letters = [c for c in text if c.isalpha()]
    caps_ratio = sum(c.isupper() for c in letters) / len(letters) if letters else 0
    if caps_ratio > 0.45 or text.count("!") >= 6:
        sigs.append(signal("pressure_tone", "High-pressure tone", 0.15,
                           f"{round(caps_ratio * 100)}% capital letters, {text.count('!')} exclamation marks."))

    off_platform = UPI_RE.findall(text) + PHONE_RE.findall(text)
    if off_platform:
        sigs.append(signal("off_platform_payment", "Asks donors to pay off-platform", 0.35,
                           "Description contains a UPI ID or phone number; payments outside the platform are untracked."))

    # Copy-pasted campaigns are a hallmark of fraud rings.
    mine = _shingles(description)
    if len(mine) >= 8:
        q = db.query(models.Campaign.id, models.Campaign.title, models.Campaign.description, models.Campaign.organizer_email)
        if exclude_campaign_id:
            q = q.filter(models.Campaign.id != exclude_campaign_id)
        best = (0.0, None)
        for cid, ctitle, cdesc, cemail in q.all():
            sim = _jaccard(mine, _shingles(cdesc))
            if sim > best[0]:
                best = (sim, (cid, ctitle, cemail))
        if best[0] >= 0.5 and best[1]:
            same_owner = best[1][2] == organizer_email
            sigs.append(signal(
                "duplicate_description", "Description copied from another campaign",
                0.2 if same_owner else 0.5,
                f"{round(best[0] * 100)}% overlap with campaign #{best[1][0]} “{best[1][1]}”"
                + (" (same organizer)" if same_owner else " by a different organizer"),
            ))

    goals = [g for (g,) in db.query(models.Campaign.goal_amount).filter(models.Campaign.category == category).all() if g]
    if len(goals) >= 3 and goal_amount > 10 * median(goals):
        sigs.append(signal("goal_outlier", "Goal far above similar campaigns", 0.2,
                           f"Goal is {goal_amount / median(goals):.0f}× the median {category} campaign."))
    if goal_amount >= 1_00_00_000:
        sigs.append(signal("very_large_goal", "Very large goal (≥ ₹1 crore)", 0.12, "Large goals warrant extra verification."))

    since = datetime.utcnow() - timedelta(hours=24)
    recent = db.query(func.count(models.Campaign.id)).filter(
        models.Campaign.organizer_email == organizer_email, models.Campaign.created_at >= since,
    ).scalar() or 0
    if exclude_campaign_id:
        recent = max(0, recent - 1)
    if recent >= 3:
        sigs.append(signal("campaign_burst", "Many campaigns created in 24 hours", 0.3,
                           f"Organizer created {recent} other campaigns in the last day."))

    org = db.query(models.Organizer).filter(models.Organizer.email == organizer_email).first()
    if org and org.created_at and datetime.utcnow() - org.created_at < timedelta(days=1) and goal_amount >= 5_00_000:
        sigs.append(signal("new_organizer_large_goal", "Brand-new organizer with a large goal", 0.15,
                           "Account is less than a day old."))

    if milestone_count == 0 and goal_amount >= 2_00_000:
        sigs.append(signal("no_milestones", "No milestone-based release", 0.2,
                           "Large campaigns without milestones receive funds with no donor approval step."))
    return combine(sigs)


# ── donations ───────────────────────────────────────────────────

def score_donation(db: Session, campaign: models.Campaign, donor_email: str, amount: float) -> dict[str, Any]:
    sigs: list[dict] = []
    email = (donor_email or "").strip().lower()
    now = datetime.utcnow()

    if email and email == (campaign.organizer_email or "").strip().lower():
        sigs.append(signal("self_donation", "Organizer donating to own campaign", 0.5,
                           "Can be used to fake momentum or launder funds through the campaign."))

    recent = db.query(func.count(models.Donation.id)).filter(
        models.Donation.campaign_id == campaign.id,
        func.lower(models.Donation.donor_email) == email,
        models.Donation.donated_at >= now - timedelta(minutes=10),
    ).scalar() or 0
    if recent >= 3:
        sigs.append(signal("rapid_repeat", "Rapid repeated donations", 0.35,
                           f"{recent} donations from this donor in the last 10 minutes."))

    if campaign.daily_donor_limit:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_rows = db.query(models.Donation.amount).filter(
            models.Donation.campaign_id == campaign.id,
            func.lower(models.Donation.donor_email) == email,
            models.Donation.donated_at >= today,
        ).all()
        if len(today_rows) >= 2 and sum(a for (a,) in today_rows) + amount >= 0.9 * campaign.daily_donor_limit:
            sigs.append(signal("limit_structuring", "Split payments approaching daily limit", 0.2,
                               "Several payments in one day adding up to just under the cap."))

    history = [a for (a,) in db.query(models.Donation.amount).filter(models.Donation.campaign_id == campaign.id).all()]
    z = robust_z(amount, history)
    if z is not None and z > 3.5:
        sigs.append(signal("amount_anomaly", "Unusually large for this campaign", min(0.15 + 0.04 * (z - 3.5), 0.4),
                           f"Robust z-score {z:.1f} against {len(history)} previous donations."))

    if amount >= 2_00_000:
        sigs.append(signal("high_value", "High-value donation (≥ ₹2 lakh)", 0.2,
                           "Large single payments warrant enhanced due diligence."))

    donor = db.query(models.Donor).filter(func.lower(models.Donor.email) == email).first()
    if donor and donor.created_at and now - donor.created_at < timedelta(minutes=10) and amount >= 50_000:
        sigs.append(signal("new_account_large", "New account making a large donation", 0.2,
                           "Account created minutes before donating ₹50,000+."))

    burst = db.query(func.count(models.Donation.id)).filter(
        models.Donation.campaign_id == campaign.id, models.Donation.donated_at >= now - timedelta(minutes=5),
    ).scalar() or 0
    if burst >= 25:
        sigs.append(signal("donation_burst", "Burst of donations to this campaign", 0.2,
                           f"{burst} donations in the last 5 minutes — possible scripted activity."))
    return combine(sigs)


# ── expenditures ────────────────────────────────────────────────

def score_utilization(
    db: Session,
    campaign: models.Campaign,
    amount: float,
    description: str,
    has_proof: bool,
    invoice_hash: Optional[str],
    ocr: Optional[dict],
    invoice_number: Optional[str],
    vendor_gstin: Optional[str],
    vendor_name: Optional[str],
    invoice_date: Optional[str],
    exclude_id: Optional[int] = None,
) -> dict[str, Any]:
    sigs: list[dict] = []
    others = db.query(models.Utilization)
    if exclude_id:
        others = others.filter(models.Utilization.id != exclude_id)

    if not has_proof:
        sigs.append(signal("no_proof", "No invoice or proof attached", 0.35, "Expenses without proof can't be verified."))

    if invoice_hash:
        dup = others.filter(models.Utilization.invoice_hash == invoice_hash).first()
        if dup:
            where = "this campaign" if dup.campaign_id == campaign.id else f"campaign #{dup.campaign_id}"
            sigs.append(signal("duplicate_invoice_file", "Same invoice file already claimed", 0.75,
                               f"Identical file was submitted for expense #{dup.id} in {where}."))

    if invoice_number:
        q = others.filter(func.lower(models.Utilization.invoice_number) == invoice_number.strip().lower())
        if vendor_gstin:
            q = q.filter(models.Utilization.vendor_gstin == vendor_gstin)
        dup = q.first()
        if dup and not (invoice_hash and dup.invoice_hash == invoice_hash):
            sigs.append(signal("duplicate_invoice_number", "Invoice number already claimed", 0.55,
                               f"Invoice {invoice_number} was already used for expense #{dup.id}."))

    if ocr:
        total = ocr.get("total_amount")
        if total and amount:
            diff = (amount - total) / amount
            if abs(diff) > 0.05:
                over = amount > total
                sigs.append(signal(
                    "amount_mismatch",
                    "Claimed amount exceeds invoice total" if over else "Claimed amount differs from invoice",
                    min((0.3 if over else 0.15) + abs(diff) * 0.5, 0.6),
                    f"Claimed ₹{amount:,.0f} but the invoice reads ₹{total:,.0f}.",
                ))
        if ocr.get("arithmetic_ok") is False:
            sigs.append(signal("arithmetic", "Invoice arithmetic doesn't add up", 0.2,
                               "Subtotal + taxes ≠ total on the document — possible manual edit."))
        if has_proof and (ocr.get("confidence") or 0) < 40:
            sigs.append(signal("unreadable", "Invoice could not be read reliably", 0.1,
                               "Low OCR confidence; a clearer scan helps donors verify it."))

    gstin = vendor_gstin or (ocr or {}).get("vendor_gstin")
    if gstin:
        from services.ocr import gstin_checksum_valid
        if not gstin_checksum_valid(gstin):
            sigs.append(signal("invalid_gstin", "Vendor GSTIN fails checksum", 0.45,
                               f"{gstin} is not a structurally valid GSTIN — likely mistyped or fabricated."))

    inv_date = invoice_date or (ocr or {}).get("invoice_date")
    if inv_date:
        try:
            d = datetime.fromisoformat(inv_date)
            if d.date() > datetime.utcnow().date() + timedelta(days=1):
                sigs.append(signal("future_invoice", "Invoice dated in the future", 0.4, f"Invoice date {inv_date}."))
            elif campaign.created_at and d < campaign.created_at - timedelta(days=30):
                sigs.append(signal("pre_campaign_invoice", "Invoice predates the campaign", 0.25,
                                   f"Dated {inv_date}, before the campaign started — may be a recycled bill."))
        except ValueError:
            pass

    hits = _phrase_hits(f"{description} {vendor_name or ''}", UNRELATED_SPEND)
    if hits:
        sigs.append(signal("unrelated_spend", "Spend looks unrelated to the cause", 0.35,
                           "Mentions: " + ", ".join(hits[:4])))

    org = db.query(models.Organizer).filter(models.Organizer.email == campaign.organizer_email).first()
    if org and vendor_name:
        org_tokens = {t for t in re.findall(r"[a-z]{3,}", org.name.lower())}
        vend_tokens = {t for t in re.findall(r"[a-z]{3,}", vendor_name.lower())}
        common = org_tokens & vend_tokens - {"pvt", "ltd", "the", "and", "foundation", "trust", "services"}
        if common:
            sigs.append(signal("related_party", "Vendor name matches organizer", 0.3,
                               f"Shared name “{', '.join(sorted(common))}” — possible self-dealing."))

    history = [u.amount for u in others.filter(models.Utilization.campaign_id == campaign.id).all()]
    z = robust_z(amount, history)
    if z is not None and z > 3.5:
        sigs.append(signal("amount_anomaly", "Unusually large expense", min(0.15 + 0.04 * (z - 3.5), 0.35),
                           f"Robust z-score {z:.1f} against {len(history)} previous expenses."))

    if not has_proof and amount >= 10_000 and amount % 10_000 == 0:
        sigs.append(signal("round_amount", "Round-number expense without proof", 0.1, ""))
    return combine(sigs)
