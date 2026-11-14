"""
INR payments.

With RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET set, donations go through Razorpay
Checkout (UPI, cards, netbanking, wallets): the server creates an order,
the browser pays, and the server verifies Razorpay's HMAC signature before
recording anything. RAZORPAY_WEBHOOK_SECRET enables the webhook as a backup
path for payments whose browser callback never arrives.

Without keys the platform runs in *demo* mode: a simulated checkout that
exercises the exact same order → verify → record pipeline.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from database import get_db
from services import donation_service

router = APIRouter(prefix="/payments", tags=["payments"])

RZP_API = "https://api.razorpay.com/v1"


def _keys() -> tuple[Optional[str], Optional[str]]:
    return os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")


def provider() -> str:
    kid, secret = _keys()
    return "razorpay" if kid and secret else "demo"


@router.get("/config")
def payment_config():
    kid, _ = _keys()
    return {
        "provider": provider(),
        "key_id": kid if provider() == "razorpay" else None,
        "currency": "INR",
        "methods": ["UPI", "Card", "NetBanking", "Wallet"],
        "webhook_enabled": bool(os.getenv("RAZORPAY_WEBHOOK_SECRET")),
    }


class OrderRequest(BaseModel):
    campaign_id: int
    donor_name: str
    donor_email: str
    amount: float = Field(gt=0)
    donor_id: Optional[int] = None


@router.post("/order")
def create_order(req: OrderRequest, db: Session = Depends(get_db)):
    amount = round(req.amount, 2)
    campaign = db.get(models.Campaign, req.campaign_id)
    donation_service.check_can_donate(db, campaign, req.donor_email, amount)

    prov = provider()
    if prov == "razorpay":
        kid, secret = _keys()
        try:
            r = httpx.post(
                f"{RZP_API}/orders",
                auth=(kid, secret),
                json={
                    "amount": int(round(amount * 100)),  # paise
                    "currency": "INR",
                    "receipt": f"tf_{req.campaign_id}_{uuid.uuid4().hex[:10]}",
                    "notes": {"campaign_id": str(req.campaign_id), "platform": "TransFund"},
                },
                timeout=20,
            )
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Could not reach Razorpay. Please try again.")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail="Razorpay rejected the order request")
        order_id = r.json()["id"]
    else:
        order_id = f"demo_order_{uuid.uuid4().hex[:16]}"

    db.add(models.PaymentOrder(
        order_id=order_id, provider=prov, campaign_id=campaign.id, donor_id=req.donor_id,
        donor_name=req.donor_name, donor_email=req.donor_email, amount=amount,
    ))
    db.commit()
    return {
        "order_id": order_id,
        "provider": prov,
        "key_id": _keys()[0] if prov == "razorpay" else None,
        "amount": amount,
        "amount_paise": int(round(amount * 100)),
        "currency": "INR",
        "campaign_title": campaign.title,
    }


class VerifyRequest(BaseModel):
    order_id: str
    payment_id: Optional[str] = None
    signature: Optional[str] = None
    payment_method: Optional[Literal["UPI", "Card", "NetBanking", "Wallet"]] = None


def _finalize(db: Session, order: models.PaymentOrder, payment_id: str, method: Optional[str]):
    """Idempotent: a second verify / webhook for the same order returns the first result."""
    if order.status == "paid" and order.donation_id:
        d = db.get(models.Donation, order.donation_id)
        receipt = db.query(models.Receipt).filter(models.Receipt.donation_id == d.id).first()
        return {
            "id": d.id, "campaign_id": d.campaign_id, "amount": d.amount, "donor_name": d.donor_name,
            "donor_email": d.donor_email, "payment_method": d.payment_method, "transaction_id": d.transaction_id,
            "donated_at": d.donated_at.isoformat() + "Z",
            "receipt_number": receipt.receipt_number if receipt else None,
            "ledger": {"block_hash": d.ledger_hash}, "risk": {"score": d.risk_score}, "duplicate": True,
        }
    # Lock the order row so a simultaneous webhook + browser verify can't double-record.
    order = db.query(models.PaymentOrder).filter(models.PaymentOrder.id == order.id).with_for_update().first()
    if order.status == "paid":
        return _finalize(db, order, payment_id, method)
    campaign = db.get(models.Campaign, order.campaign_id)
    result = donation_service.record_donation(
        db, campaign, order.donor_name, order.donor_email, order.amount,
        donor_id=order.donor_id, payment_method=method, transaction_id=payment_id,
        payment_order_id=order.order_id, commit=False,
    )
    order.status = "paid"
    order.payment_id = payment_id
    order.donation_id = result["id"]
    db.commit()
    return result


@router.post("/verify")
def verify_payment(req: VerifyRequest, db: Session = Depends(get_db)):
    order = db.query(models.PaymentOrder).filter(models.PaymentOrder.order_id == req.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Unknown order")

    if order.provider == "razorpay":
        _, secret = _keys()
        if not (req.payment_id and req.signature and secret):
            raise HTTPException(status_code=400, detail="Missing payment confirmation")
        expected = hmac.new(secret.encode(), f"{order.order_id}|{req.payment_id}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, req.signature):
            order.status = "failed"
            db.commit()
            raise HTTPException(status_code=400, detail="Payment signature verification failed")
        method = req.payment_method or _fetch_method(req.payment_id)
        return _finalize(db, order, req.payment_id, method)

    # demo provider
    if provider() != "demo":
        raise HTTPException(status_code=400, detail="Demo payments are disabled")
    payment_id = f"demo_pay_{secrets.token_hex(8)}"
    return _finalize(db, order, payment_id, req.payment_method or "UPI")


def _fetch_method(payment_id: str) -> Optional[str]:
    kid, secret = _keys()
    try:
        r = httpx.get(f"{RZP_API}/payments/{payment_id}", auth=(kid, secret), timeout=15)
        m = r.json().get("method") if r.status_code < 300 else None
    except httpx.HTTPError:
        return None
    return {"upi": "UPI", "card": "Card", "netbanking": "NetBanking", "wallet": "Wallet"}.get(m or "", m)


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=404, detail="Webhook not configured")
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid signature")
    event = json.loads(body)
    if event.get("event") not in ("payment.captured", "order.paid"):
        return {"ok": True, "ignored": event.get("event")}
    entity = event["payload"]["payment"]["entity"]
    order = db.query(models.PaymentOrder).filter(models.PaymentOrder.order_id == entity.get("order_id")).first()
    if not order:
        return {"ok": True, "ignored": "unknown order"}
    method = {"upi": "UPI", "card": "Card", "netbanking": "NetBanking", "wallet": "Wallet"}.get(entity.get("method"))
    _finalize(db, order, entity["id"], method)
    return {"ok": True}
