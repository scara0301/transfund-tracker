"""
Invoice OCR + field extraction.

Text is pulled from PDFs directly (pypdf); scanned PDFs and photos go through
Tesseract OCR. The text is then parsed for the fields an Indian GST invoice
carries: vendor, GSTIN (validated with its mod-36 checksum), invoice number,
date, tax lines and the payable total.

Everything degrades gracefully: if Tesseract isn't installed the endpoint
still works for text PDFs and reports `engine: "unavailable"` for images.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Optional

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)?\s*((?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?)(?![\d/\-])", re.I)
INVOICE_NO_RE = re.compile(
    r"(?:invoice|inv|bill|receipt)\s*(?:no\.?|number|num|#|id)\s*[:\-#.]?\s*([A-Z0-9][A-Z0-9\-/]{1,30})", re.I
)
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b"), "dmy2"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-]+({MONTHS})[a-z]*[\s\-,]+(\d{{4}})\b", re.I), "dMy"),
    (re.compile(rf"\b({MONTHS})[a-z]*[\s\-]+(\d{{1,2}})(?:st|nd|rd|th)?,?[\s\-]+(\d{{4}})\b", re.I), "Mdy"),
]
# Higher number = stronger signal that this line holds the payable total.
TOTAL_KEYWORDS = [
    (re.compile(r"grand\s*total", re.I), 6),
    (re.compile(r"(amount|net|total)\s*(payable|due)", re.I), 5),
    (re.compile(r"(invoice|bill)\s*(total|amount)", re.I), 5),
    (re.compile(r"balance\s*due", re.I), 4),
    (re.compile(r"total\s*(amount|value|inr|rs)", re.I), 4),
    (re.compile(r"(?<!sub)(?<!sub\s)\btotal\b", re.I), 3),
]
SUBTOTAL_RE = re.compile(r"sub\s*-?\s*total|taxable|before\s*tax", re.I)
TAX_RE = re.compile(r"\b(cgst|sgst|igst|utgst|gst)\b", re.I)
VENDOR_SKIP = re.compile(
    r"tax\s*invoice|^invoice|^bill\b|receipt|gstin|date|^to\b|bill\s*to|ship\s*to|phone|email|www\.|@|page\s*\d", re.I
)


# ── GSTIN checksum ──────────────────────────────────────────────

def gstin_checksum_valid(gstin: str) -> bool:
    gstin = gstin.strip().upper()
    if not GSTIN_RE.fullmatch(gstin):
        return False
    total = 0
    for i, ch in enumerate(gstin[:14]):
        product = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == gstin[14]


# GSTIN layout: 2 digits (state) · 5 letters + 4 digits + 1 letter (PAN) ·
# entity code · 'Z' · checksum. OCR often confuses O/0, I/1, S/5, B/8, so
# coerce each position to the character class it must be.
_GSTIN_LOOSE = re.compile(r"\b([0-9A-Z]{15})\b")
_TO_DIGIT = str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})
_GSTIN_DIGIT_POS = {0, 1, 7, 8, 9, 10}
_GSTIN_ALPHA_POS = {2, 3, 4, 5, 6, 11}


def _fix_gstin(candidate: str) -> Optional[str]:
    chars = list(candidate)
    for i in _GSTIN_DIGIT_POS:
        chars[i] = chars[i].translate(_TO_DIGIT)
    for i in _GSTIN_ALPHA_POS:
        chars[i] = chars[i].translate(_TO_ALPHA)
    if chars[13] == "2":
        chars[13] = "Z"
    fixed = "".join(chars)
    return fixed if GSTIN_RE.fullmatch(fixed) else None


def find_gstins(line: str) -> list[str]:
    compact = re.sub(r"(?<=[0-9A-Z])\s(?=[0-9A-Z])", "", line.upper()) if "GST" in line.upper() else line.upper()
    out = []
    for cand in _GSTIN_LOOSE.findall(compact.replace("GSTIN", " ")):
        fixed = _fix_gstin(cand)
        if fixed and fixed not in out:
            out.append(fixed)
    return out


# ── text extraction ─────────────────────────────────────────────

def _ocr_image(img) -> tuple[str, Optional[float], str]:
    try:
        import pytesseract
        from PIL import ImageOps

        gray = ImageOps.grayscale(img)
        if gray.width < 1400:  # upscale small photos; Tesseract likes ~300dpi
            scale = 1400 / gray.width
            gray = gray.resize((int(gray.width * scale), int(gray.height * scale)))
        data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT, config="--psm 6")
        confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
        text = pytesseract.image_to_string(gray, config="--psm 6")
        return text, (sum(confs) / len(confs) if confs else None), "tesseract"
    except Exception as e:  # tesseract binary missing, bad image, etc.
        return "", None, f"unavailable: {type(e).__name__}"


def extract_text(content: bytes, filename: str = "", content_type: str = "") -> dict[str, Any]:
    name = (filename or "").lower()
    is_pdf = name.endswith(".pdf") or "pdf" in (content_type or "") or content.startswith(b"%PDF")
    if is_pdf:
        text = ""
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:5])
        except Exception:
            pass
        if len(text.strip()) >= 40:
            return {"text": text, "engine": "pdf-text", "ocr_confidence": 99.0}
        # Scanned PDF → rasterise and OCR
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(content)
            parts, confs, engine = [], [], "tesseract"
            for i in range(min(len(pdf), 3)):
                img = pdf[i].render(scale=2.5).to_pil()
                t, c, engine = _ocr_image(img)
                parts.append(t)
                if c is not None:
                    confs.append(c)
            return {"text": "\n".join(parts), "engine": f"pdf-{engine}",
                    "ocr_confidence": sum(confs) / len(confs) if confs else None}
        except Exception as e:
            return {"text": text, "engine": f"unavailable: {type(e).__name__}", "ocr_confidence": None}

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return {"text": "", "engine": "unsupported-file", "ocr_confidence": None}
    text, conf, engine = _ocr_image(img)
    return {"text": text, "engine": engine, "ocr_confidence": conf}


# ── field parsing ───────────────────────────────────────────────

def _to_amount(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _amounts(line: str) -> list[float]:
    out = []
    for m in AMOUNT_RE.finditer(line):
        raw = m.group(1)
        # skip things that are obviously not money: percentages, GST rates, years
        tail = line[m.end(): m.end() + 1]
        if tail == "%":
            continue
        v = _to_amount(raw)
        if v is None:
            continue
        if "," not in raw and "." not in raw and 1900 <= v <= 2100 and len(raw) == 4:
            continue  # likely a year
        out.append(v)
    return out


def _parse_date(text: str) -> Optional[str]:
    lines = text.splitlines()
    # prefer lines that mention an invoice/bill date and not a due date
    ranked = sorted(
        lines,
        key=lambda ln: (0 if re.search(r"(invoice|bill|inv)?\s*date", ln, re.I) and not re.search(r"due", ln, re.I) else 1),
    )
    month_idx = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
    for ln in ranked:
        for rx, kind in DATE_PATTERNS:
            m = rx.search(ln)
            if not m:
                continue
            try:
                g = m.groups()
                if kind == "dmy":
                    d, mo, y = int(g[0]), int(g[1]), int(g[2])
                elif kind == "ymd":
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                elif kind == "dmy2":
                    d, mo, y = int(g[0]), int(g[1]), 2000 + int(g[2])
                elif kind == "dMy":
                    d, mo, y = int(g[0]), month_idx[g[1][:3].lower()], int(g[2])
                else:
                    mo, d, y = month_idx[g[0][:3].lower()], int(g[1]), int(g[2])
                return datetime(y, mo, d).date().isoformat()
            except (ValueError, KeyError):
                continue
    return None


def _parse_total(lines: list[str]) -> tuple[Optional[float], Optional[str]]:
    best: tuple[int, float, str] | None = None
    for i, ln in enumerate(lines):
        if SUBTOTAL_RE.search(ln):
            continue
        prio = max((p for rx, p in TOTAL_KEYWORDS if rx.search(ln)), default=0)
        if not prio:
            continue
        vals = _amounts(ln)
        if not vals and i + 1 < len(lines):  # value printed on the next line
            vals = _amounts(lines[i + 1])
        if not vals:
            continue
        cand = (prio, max(vals), ln.strip())
        if best is None or cand[:2] > best[:2]:
            best = cand
    if best:
        return best[1], best[2]
    all_vals = [v for ln in lines for v in _amounts(ln)]
    return (max(all_vals), None) if all_vals else (None, None)


def _parse_vendor(lines: list[str], gstin_line_idx: Optional[int]) -> Optional[str]:
    def ok(ln: str) -> bool:
        s = ln.strip()
        return len(s) >= 3 and sum(ch.isalpha() for ch in s) >= 3 and not VENDOR_SKIP.search(s) and not GSTIN_RE.search(s)

    for ln in lines:
        m = re.match(r"\s*(?:from|sold\s*by|vendor|supplier|seller)\s*[:\-]\s*(.+)", ln, re.I)
        if m and ok(m.group(1)):
            return m.group(1).strip()[:120]
    for ln in lines[:6]:
        if ok(ln):
            return re.sub(r"\s{2,}", " ", ln.strip())[:120]
    if gstin_line_idx:
        for ln in reversed(lines[max(0, gstin_line_idx - 3):gstin_line_idx]):
            if ok(ln):
                return ln.strip()[:120]
    return None


def parse_invoice(text: str) -> dict[str, Any]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    upper = text.upper()

    gstins = []
    gstin_line_idx = None
    for i, ln in enumerate(lines):
        for g in find_gstins(ln):
            if g not in gstins:
                gstins.append(g)
                if gstin_line_idx is None:
                    gstin_line_idx = i
    vendor_gstin = gstins[0] if gstins else None

    inv = INVOICE_NO_RE.search(text)
    invoice_number = inv.group(1).strip(" .:-") if inv else None
    if invoice_number and invoice_number.lower() in {"date", "no", "number"}:
        invoice_number = None

    taxes: dict[str, float] = {}
    for ln in lines:
        m = TAX_RE.search(ln)
        if m and not SUBTOTAL_RE.search(ln) and not re.search(r"gstin", ln, re.I):
            vals = [v for v in _amounts(ln) if v > 0]
            if vals:
                key = m.group(1).upper()
                taxes[key] = taxes.get(key, 0) + vals[-1]

    total, total_line = _parse_total(lines)
    subtotal = None
    for ln in lines:
        if SUBTOTAL_RE.search(ln):
            vals = _amounts(ln)
            if vals:
                subtotal = max(vals)
                break

    fields = {
        "vendor_name": _parse_vendor(lines, gstin_line_idx),
        "vendor_gstin": vendor_gstin,
        "gstin_valid": gstin_checksum_valid(vendor_gstin) if vendor_gstin else None,
        "all_gstins": gstins,
        "invoice_number": invoice_number,
        "invoice_date": _parse_date(text),
        "subtotal": subtotal,
        "taxes": taxes,
        "total_amount": total,
        "total_line": total_line,
        "currency": "INR" if ("₹" in text or "INR" in upper or "RS" in upper or gstins) else None,
    }
    # arithmetic cross-check: subtotal + taxes ≈ total
    if subtotal and taxes and total:
        fields["arithmetic_ok"] = abs(subtotal + sum(taxes.values()) - total) <= max(2.0, 0.01 * total)
    else:
        fields["arithmetic_ok"] = None

    found = sum(1 for k in ("vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "total_amount") if fields[k])
    fields["field_confidence"] = round(found / 5 * 100)
    return fields


def scan_invoice(content: bytes, filename: str = "", content_type: str = "") -> dict[str, Any]:
    extracted = extract_text(content, filename, content_type)
    fields = parse_invoice(extracted["text"]) if extracted["text"].strip() else {
        "vendor_name": None, "vendor_gstin": None, "gstin_valid": None, "all_gstins": [],
        "invoice_number": None, "invoice_date": None, "subtotal": None, "taxes": {},
        "total_amount": None, "total_line": None, "currency": None, "arithmetic_ok": None,
        "field_confidence": 0,
    }
    ocr_conf = extracted["ocr_confidence"]
    overall = fields["field_confidence"] if ocr_conf is None else round(0.5 * fields["field_confidence"] + 0.5 * ocr_conf)
    return {
        **fields,
        "engine": extracted["engine"],
        "ocr_confidence": round(ocr_conf, 1) if ocr_conf is not None else None,
        "confidence": overall,
        "text_preview": extracted["text"][:1500],
    }
