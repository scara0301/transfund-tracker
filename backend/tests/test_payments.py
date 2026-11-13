import hashlib
import hmac
import json
import uuid

import httpx
import pytest

SECRET = "rzp_test_secret_123"


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d


@pytest.fixture
def razorpay(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec")
    calls = []

    def fake_post(url, auth=None, json=None, timeout=None):
        calls.append((url, auth, json))
        return FakeResp({"id": f"order_{uuid.uuid4().hex[:14]}", "amount": json["amount"]})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp({"method": "upi"}))
    return calls


def sign(order_id, payment_id):
    return hmac.new(SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def test_config_reports_razorpay(client, razorpay):
    cfg = client.get("/payments/config").json()
    assert cfg["provider"] == "razorpay" and cfg["key_id"] == "rzp_test_key"


def test_order_amount_sent_in_paise(client, campaign, razorpay):
    r = client.post("/payments/order", json={"campaign_id": campaign["id"], "donor_name": "A", "donor_email": "a@x.in", "amount": 499.5})
    assert r.status_code == 200, r.text
    assert razorpay[-1][2]["amount"] == 49950 and razorpay[-1][2]["currency"] == "INR"


def test_valid_signature_records_donation(client, campaign, razorpay):
    o = client.post("/payments/order", json={"campaign_id": campaign["id"], "donor_name": "A", "donor_email": "a@x.in", "amount": 1500}).json()
    r = client.post("/payments/verify", json={"order_id": o["order_id"], "payment_id": "pay_1", "signature": sign(o["order_id"], "pay_1")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["amount"] == 1500 and d["payment_method"] == "UPI" and d["receipt_number"].startswith("RCP-")
    assert d["ledger"]["block_hash"]


def test_forged_signature_rejected(client, campaign, razorpay):
    o = client.post("/payments/order", json={"campaign_id": campaign["id"], "donor_name": "A", "donor_email": "a@x.in", "amount": 1000}).json()
    r = client.post("/payments/verify", json={"order_id": o["order_id"], "payment_id": "pay_2", "signature": "0" * 64})
    assert r.status_code == 400
    before = client.get(f"/campaigns/{campaign['id']}").json()["raised_amount"]
    assert before == 0


def test_demo_payment_and_direct_donation_blocked_in_razorpay_mode(client, campaign, razorpay):
    o = client.post("/payments/order", json={"campaign_id": campaign["id"], "donor_name": "A", "donor_email": "a@x.in", "amount": 100}).json()
    assert client.post("/payments/verify", json={"order_id": o["order_id"]}).status_code == 400  # no signature
    r = client.post("/donations/", json={"campaign_id": campaign["id"], "donor_name": "A", "donor_email": "a@x.in", "amount": 100})
    assert r.status_code == 400


def test_webhook_is_verified_and_idempotent(client, campaign, razorpay):
    o = client.post("/payments/order", json={"campaign_id": campaign["id"], "donor_name": "W", "donor_email": "w@x.in", "amount": 700}).json()
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_wh", "order_id": o["order_id"], "method": "card"}}}}).encode()
    good = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert client.post("/payments/webhook", content=body, headers={"X-Razorpay-Signature": "bad"}).status_code == 400
    assert client.post("/payments/webhook", content=body, headers={"X-Razorpay-Signature": good}).status_code == 200
    # browser callback arriving after the webhook must not double-count
    r = client.post("/payments/verify", json={"order_id": o["order_id"], "payment_id": "pay_wh", "signature": sign(o["order_id"], "pay_wh")})
    assert r.json()["duplicate"] is True
    donations = client.get(f"/donations/?campaign_id={campaign['id']}").json()
    assert sum(1 for d in donations if d["donor_email"] == "w@x.in") == 1


def test_daily_limit_enforced_at_order_time(client, razorpay):
    org = "limit-org@ngo.in"
    c = client.post("/campaigns/", data={"title": "Limited", "description": "d " * 50, "category": "Others",
                                         "goal_amount": "100000", "organizer_email": org, "daily_donor_limit": "1000"}).json()
    r = client.post("/payments/order", json={"campaign_id": c["id"], "donor_name": "A", "donor_email": "a@x.in", "amount": 1500})
    assert r.status_code == 429 and r.json()["detail"].startswith("DAILY_LIMIT_REACHED|1000|")
