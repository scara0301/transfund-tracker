from services import fraud
from services.ocr import gstin_checksum_valid, parse_invoice

SAMPLE = """Shree Ganesh Traders
GSTIN: 27AAPFU0939F1ZV
TAX INVOICE
Invoice No: SGT-1182        Date: 05-11-2026
Due Date: 20-11-2026
Rice 50kg x 20                 40,000.00
Sub Total                      40,000.00
CGST 2.5%                       1,000.00
SGST 2.5%                       1,000.00
Total Amount Payable    ₹ 42,000.00
"""


def test_gstin_checksum():
    assert gstin_checksum_valid("27AAPFU0939F1ZV")
    assert not gstin_checksum_valid("27AAPFU0939F1ZX")
    assert not gstin_checksum_valid("NOTAGSTIN")


def test_parse_invoice_fields():
    f = parse_invoice(SAMPLE)
    assert f["vendor_name"] == "Shree Ganesh Traders"
    assert f["vendor_gstin"] == "27AAPFU0939F1ZV" and f["gstin_valid"] is True
    assert f["invoice_number"] == "SGT-1182"
    assert f["invoice_date"] == "2026-11-05"  # invoice date, not the due date
    assert f["total_amount"] == 42000.0 and f["subtotal"] == 40000.0
    assert f["arithmetic_ok"] is True


def test_noisy_or_combination():
    one = fraud.combine([fraud.signal("a", "a", 0.5)])
    two = fraud.combine([fraud.signal("a", "a", 0.5), fraud.signal("b", "b", 0.5)])
    assert one["score"] == 50 and two["score"] == 75 and two["level"] == "high"
    assert fraud.combine([])["score"] == 0


def test_robust_z_flags_outlier_not_normal():
    hist = [500, 1000, 750, 1200, 900, 600, 800, 1100]
    assert fraud.robust_z(1000, hist) < 2
    assert fraud.robust_z(500000, hist) > 3.5


def test_precheck_flags_scam_language(client):
    r = client.post("/ai/campaign-precheck", json={
        "title": "Help", "description": "Guaranteed returns, send money directly to pay@okaxis!",
        "category": "Medical", "goal_amount": 300000, "organizer_email": "x@y.in"}).json()
    codes = {s["code"] for s in r["signals"]}
    assert {"scam_language", "off_platform_payment", "no_milestones"} <= codes and r["level"] == "high"
