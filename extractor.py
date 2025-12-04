# extractor.py
"""
Robust field extractor for invoice-like text.
Expose one function used by the app: extract_fields(text: str) -> dict

Output structure (example):
{
  "vendor": "Acme Widgets Ltd.",
  "invoice": "INV-2025-0098",
  "dates": {
     "issue_date": "2025-12-01",
     "due_date": "2025-12-15",
     "delivery_date": null
  },
  "amounts": [
     {"amount": 2000.0, "currency": "USD", "raw": "$2,000.00", "context": "Professional consulting (Nov 2025)", "line": "Professional consulting (Nov 2025) 10 $2,000.00"},
     ...
  ],
  "totals": {"subtotal": 3250.0, "tax": 585.0, "total_due": 3835.0}
}
"""

import re
from typing import List, Dict, Any, Optional, Tuple
import dateparser
from datetime import datetime

# ----- regex patterns -----
# currency-aware amount: handles $ 1,234.56  or 1,234.56 USD or INR12,340.00 or -150.00
CURRENCY_SYMS = r"[$€£₹¥]"  # extend if needed
CURRENCY_CODES = r"\b(?:USD|EUR|INR|GBP|AUD|CAD|JPY)\b"
AMOUNT_RE = re.compile(
    rf"(?P<sign>[-−])?\s*(?P<sym>{CURRENCY_SYMS})?\s*(?P<amt>\d{{1,3}}(?:[,.\s]\d{{3}})*|\d+(?:[.,]\d+)?)\s*(?P<code>{CURRENCY_CODES})?",
    flags=re.IGNORECASE,
)

# dates - multiple loose patterns (we'll push through dateparser to canonicalize)
DATE_RE = re.compile(
    r"\b(?:(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})|(?:\d{4}[/-]\d{1,2}[/-]\d{1,2})|(?:[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}))\b"
)

INVOICE_RE = re.compile(r"\b(?:Invoice|Invoice #|Invoice No|Inv|INV)[\s:]*([A-Z0-9\-\_/]+)", flags=re.IGNORECASE)
VENDOR_HINTS = ["vendor", "from", "bill to", "billing", "supplier", "acme", "company", "ltd", "co\.", "solutions"]
# phone-like pattern for filtering
PHONE_RE = re.compile(r"\+?\d[\d\s\-\(\)]{6,}\d")

# small helper: convert matched numeric text into float
def parse_amount_text(amt_text: str) -> Optional[float]:
    if not amt_text:
        return None
    # remove spaces, non-breaking spaces
    s = amt_text.replace("\u00A0", "").replace(" ", "")
    # allow both comma-thousand/dot-decimal and dot-thousand/comma-decimal - heuristic:
    # If both comma and dot present and comma before dot -> treat comma as thousand sep
    if "," in s and "." in s:
        if s.rfind(",") < s.rfind("."):
            # "1,234.56" typical -> remove commas
            s = s.replace(",", "")
        else:
            # "1.234,56" -> remove dots, replace comma with dot
            s = s.replace(".", "").replace(",", ".")
    else:
        # only commas present -> if comma appears >1 or comma followed by 3 digits treat as thousand sep
        if "," in s and re.search(r",\d{3}\b", s):
            s = s.replace(",", "")
        else:
            # comma as decimal separator -> convert to dot
            s = s.replace(",", ".")
    # Strip non-digit/.- characters
    s = re.sub(r"[^\d\.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None

# canonicalize currency: prefer symbol or code
def detect_currency(sym: Optional[str], code: Optional[str], raw: str) -> Optional[str]:
    if code:
        return code.upper()
    if sym:
        mapping = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
        return mapping.get(sym, None)
    # try detection by trailing letters in raw (e.g., "INR12,340.00")
    m = re.search(r"\b(USD|EUR|INR|GBP|AUD|CAD|JPY)\b", raw, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None

# break text into lines and also into "table-like" chunks by splitting on two+ spaces or pipes
def text_to_lines(text: str) -> List[str]:
    lines = []
    for raw in text.splitlines():
        # normalize whitespace
        ln = raw.strip()
        if not ln:
            continue
        # if it's a table row joined with many spaces, keep it
        lines.append(ln)
    return lines

# find amounts with context by scanning each line and also scanning full text for totals
def find_amounts_with_context(text: str) -> List[Dict[str, Any]]:
    found = []
    lines = text_to_lines(text)
    for i, ln in enumerate(lines):
        # skip short lines that look like headings without numbers
        # look for all amount matches in this line
        for m in AMOUNT_RE.finditer(ln):
            raw = m.group(0)
            amt_text = m.group("amt")
            sign = m.group("sign") or ""
            sym = m.group("sym")
            code = m.group("code")
            # skip if this looks like phone or account (long strings with many digits) - but we still capture if currency symbol exists
            if not sym and not code:
                # if the matched raw contains more than 8 digits total, consider noise (account/serial)
                digits = re.sub(r"\D", "", raw)
                if len(digits) > 10 and not re.search(r"[,\.]\d{2}\b", raw):
                    continue
            value = parse_amount_text(sign + amt_text)
            if value is None:
                continue
            currency = detect_currency(sym, code, raw)
            context = ln
            # look to previous line if previous line doesn't contain amounts (possible multi-line item)
            if i > 0 and not AMOUNT_RE.search(lines[i-1]):
                context = lines[i-1] + " | " + ln
            # compute label guess like "subtotal" or "tax" by searching nearby words
            label = None
            low = ln.lower()
            if "subtotal" in low:
                label = "subtotal"
            elif "tax" in low:
                label = "tax"
            elif "total" in low and "due" in low:
                label = "total_due"
            # filter tiny numbers that are probably counts, not money (e.g., 1, 2, 10)
            if abs(value) < 3.0 and label is None:
                # but sometimes INR1 is valid; if currency present keep it
                if currency is None:
                    continue
            found.append({
                "amount": value,
                "currency": currency,
                "raw": raw.strip(),
                "context": context.strip(),
                "line": ln,
                "label": label
            })
    # deduplicate by (amount,currency,raw,context) approximate
    dedup = []
    keys = set()
    for f in found:
        key = (f["amount"], f["currency"], f["raw"], f["context"][:60])
        if key in keys:
            continue
        keys.add(key)
        dedup.append(f)
    # sort heuristically: totals/subtotal/tax first, then by where they appear (bottom of doc often totals)
    def score_item(it):
        s = 0
        if it["label"] == "subtotal": s -= 100
        if it["label"] == "tax": s -= 90
        if it["label"] == "total_due": s -= 110
        # later lines (higher index) should score earlier (we don't have index now)
        return s
    dedup.sort(key=score_item)
    return dedup

# find labeled dates: try to pick issue/due/delivery by looking for words near the date
def parse_dates_and_labels(text: str) -> Dict[str, Optional[str]]:
    labels = {"issue_date": None, "due_date": None, "delivery_date": None, "other_dates": []}
    for m in DATE_RE.finditer(text):
        raw = m.group(0)
        # Attempt to parse twice: dayfirst True and False, then use heuristics to decide.
        dt1 = dateparser.parse(raw, settings={"PREFER_DAY_OF_MONTH": "first", "DATE_ORDER": "DMY"})
        dt2 = dateparser.parse(raw, settings={"PREFER_DAY_OF_MONTH": "first", "DATE_ORDER": "MDY"})
        # choose by detecting if parse yields impossible month > 12 in one variant
        chosen = None
        if dt1 and not dt2:
            chosen = dt1
        elif dt2 and not dt1:
            chosen = dt2
        elif dt1 and dt2:
            # if they are equal choose dt1
            if dt1 == dt2:
                chosen = dt1
            else:
                # heuristics: prefer ISO-like format (YYYY-MM-DD) or long month name
                if re.match(r"\d{4}-\d{1,2}-\d{1,2}", raw):
                    chosen = dt1
                else:
                    # if day>12 in raw -> unambiguous DMY
                    parts = re.findall(r"\d+", raw)
                    if parts and int(parts[0]) > 12:
                        chosen = dt1
                    else:
                        # fall back to dt1
                        chosen = dt1
        else:
            chosen = dt1 or dt2
        iso = chosen.date().isoformat() if chosen else None
        # find surrounding text (window) to label it
        span_start = max(m.start() - 40, 0)
        span_end = min(m.end() + 40, len(text))
        window = text[span_start:span_end].lower()
        if "issue" in window or "issued" in window:
            labels["issue_date"] = iso
        elif "due" in window:
            labels["due_date"] = iso
        elif "delivery" in window or "deliv" in window:
            labels["delivery_date"] = iso
        else:
            labels["other_dates"].append(iso)
    return labels

# vendor heuristics: look for top-of-document lines containing company-style tokens or uppercase blocks
def extract_vendor(text: str) -> Optional[str]:
    # look at the top 6 non-empty lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    top = lines[:8]
    # prefer line that contains 'Ltd' 'Solutions' 'Inc' 'Co' or has many uppercase words
    for ln in top:
        if re.search(r"\b(Ltd|Ltd\.|Solutions|Inc|Inc\.|Co\.|Corporation|LLP|LLC|GLOBAL|CORP|SOLUTIONS)\b", ln, flags=re.IGNORECASE):
            # sanitize - remove phone-like and address-like parts
            candidate = re.sub(r"\s*\|.*$", "", ln).strip()
            candidate = re.sub(r"Phone[:\s]*\+?\d[0-9\-\s\(\)]*", "", candidate).strip()
            return candidate
    # fallback: choose first line with multiple capitalized words
    for ln in top:
        words = ln.split()
        if len([w for w in words if w and w[0].isupper()]) >= 2 and len(ln) < 60:
            return ln
    return None

# invoice id extraction
def extract_invoice_number(text: str) -> Optional[str]:
    m = INVOICE_RE.search(text)
    if m:
        return m.group(1).strip()
    # fallback: common pattern INV- or INV\d
    m2 = re.search(r"\b(INV[-\d/]+)\b", text, flags=re.IGNORECASE)
    if m2:
        return m2.group(1)
    return None

# Try to find subtotals/total/tax by label proximity
def find_totals(amounts: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    totals = {"subtotal": None, "tax": None, "total_due": None}
    for a in amounts:
        lab = a.get("label")
        if lab == "subtotal":
            totals["subtotal"] = a["amount"]
        elif lab == "tax":
            totals["tax"] = a["amount"]
        elif lab == "total_due":
            totals["total_due"] = a["amount"]
    # If not found by label, try to guess by magnitude: the largest absolute value at bottom likely total
    if totals["total_due"] is None and amounts:
        by_amount = sorted(amounts, key=lambda x: abs(x["amount"]), reverse=True)
        totals["total_due"] = by_amount[0]["amount"]
    return totals

# main function expected by app
def extract_fields(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}

    vendor = extract_vendor(text)
    invoice = extract_invoice_number(text)
    dates = parse_dates_and_labels(text)

    amounts = find_amounts_with_context(text)

    # Post-filter: remove amounts that are phone numbers or IBAN-like long sequences without currency
    clean_amounts = []
    for a in amounts:
        raw = a["raw"]
        # skip if raw looks like phone (many digits, separators)
        if PHONE_RE.search(raw) and a["currency"] is None:
            continue
        # skip if raw length digits>10 and no currency
        digits = re.sub(r"\D", "", raw)
        if len(digits) > 12 and a["currency"] is None:
            continue
        clean_amounts.append(a)

    totals = find_totals(clean_amounts)

    # Build "items" mapping: try to map amounts to item descriptions by scanning lines and linking amounts to the nearest preceding textual chunk
    # We'll attempt a simple heuristic: if an amount's context contains a description-like substring before the amount, use that.
    items = []
    for a in clean_amounts:
        desc = None
        line = a.get("line", "")
        # if line contains letters before the amount, treat that as description
        # remove the raw amount itself from the line and trim
        line_no_raw = line.replace(a["raw"], "").strip()
        # if line_no_raw has words and not just numbers, use it
        if re.search(r"[A-Za-z]", line_no_raw):
            desc = line_no_raw
        else:
            # look at context field (which may include previous line)
            ctx = a.get("context", "")
            # split by pipe or '|' if present
            if "|" in ctx:
                parts = [p.strip() for p in ctx.split("|") if p.strip()]
                # use leftmost part with letters
                for p in parts:
                    if re.search(r"[A-Za-z]", p):
                        desc = p
                        break
            if not desc:
                # fallback: take up to 60 chars from context, but only alphabetic
                m = re.search(r"([A-Za-z].{0,60})", ctx)
                if m:
                    desc = m.group(1).strip()
        items.append({
            "amount": a["amount"],
            "currency": a["currency"],
            "raw": a["raw"],
            "description": desc,
            "label": a.get("label"),
            "context": a.get("context")
        })

    # final cleaning: remove duplicate amounts where same amount appears multiple times in noisy text (but keep if description differs)
    final_items = []
    seen = set()
    for it in items:
        key = (it["amount"], (it["description"] or "").lower())
        if key in seen:
            continue
        seen.add(key)
        final_items.append(it)

    return {
        "vendor": vendor,
        "invoice": invoice,
        "dates": dates,
        "amounts": final_items,
        "totals": totals,
    }

# convenience debug runner
if __name__ == "__main__":
    import sys, json
    sample = ""
    if len(sys.argv) > 1:
        sample = open(sys.argv[1], "r", encoding="utf8").read()
    else:
        sample = sys.stdin.read()
    out = extract_fields(sample)
    print(json.dumps(out, indent=2, ensure_ascii=False))
