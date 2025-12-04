# parser_rules.py
import re
from typing import Dict, Any, List, Tuple

AMOUNT_RE = re.compile(r'(?P<sym>[$₹€£])?\s*(?P<amt>\d{1,3}(?:[,\d{3}]*)(?:\.\d{1,2})?)')
# fallback numbers that look like money (with decimals) but we filter by context
CURRENCY_WORDS = ['$', 'usd', 'inr', 'rs', '₹', '€', '£']

DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})|(\d{2}/\d{2}/\d{4})|(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})')

def try_parse_amount(s: str) -> str:
    """Return normalized amount string like $123.45 or 123.45, or empty if not found."""
    if not s:
        return ""
    m = AMOUNT_RE.search(s.replace(',', ''))
    if not m:
        return ""
    amt = m.group('amt').replace(',', '')
    sym = m.group('sym') or ""
    # normalize
    try:
        v = float(amt)
    except Exception:
        return ""
    # filter out tiny numbers that are likely page numbers, dates etc.
    if v < 1.0:  # treat < $1 as unlikely to be invoice lines
        return ""
    if sym:
        return f"{sym}{v:,.2f}"
    return f"{v:,.2f}"

def find_label_value(lines: List[str], keywords: List[str]) -> Tuple[str,int]:
    """Find a line containing any of the keywords and return parsed amount and its line index."""
    for i, line in enumerate(lines):
        low = line.lower()
        for kw in keywords:
            if kw in low:
                amt = try_parse_amount(line)
                if amt:
                    return amt, i
                # if no amount on same line, check next 2 lines
                for j in (1,2):
                    if i+j < len(lines):
                        amt = try_parse_amount(lines[i+j])
                        if amt:
                            return amt, i+j
    return "", -1

def extract_line_items(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Simple heuristic to locate a 2-3 column table area.
    Looks for lines with two amounts or an amount and a small integer (qty).
    Returns list of {description, qty, amount}.
    """
    items = []
    for line in lines:
        # split by multiple spaces or tab - many PDFs give big spacing between columns
        parts = re.split(r'\s{2,}|\t', line.strip())
        if len(parts) >= 2:
            # heuristic: last part has money
            amt = try_parse_amount(parts[-1])
            if not amt:
                continue
            qty = ""
            # check second-last part for qty (integer) or unit
            if len(parts) >= 3:
                mid = parts[-2].strip()
                if re.fullmatch(r'\d{1,4}', mid):
                    qty = mid
            description = " ".join(parts[:-2]) if qty else " ".join(parts[:-1])
            items.append({"description": description.strip(), "qty": qty, "amount": amt})
    # if nothing found, fallback: find any line with an amount
    if not items:
        for line in lines:
            amt = try_parse_amount(line)
            if amt:
                # try to pick preceding text as description
                idx = lines.index(line)
                desc = lines[idx-1] if idx-1 >= 0 else ""
                items.append({"description": desc.strip(), "qty": "", "amount": amt})
    return items

def extract_invoice_fields(text: str) -> Dict[str, Any]:
    """
    Main function expected by app.py: returns dict with vendor, invoice, dates, amounts, items.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lowtext = text.lower()

    # vendor: heuristic - top 5 lines that look like a name / address (non-numeric)
    vendor = ""
    for i in range(min(6, len(lines))):
        ln = lines[i]
        if any(c.isalpha() for c in ln) and not any(d.isdigit() for d in ln.strip().split()[:2]):
            vendor = vendor + ((" " + ln) if vendor else ln)
    vendor = vendor.strip()

    # invoice id - look for "invoice", "invoice #", "inv"
    invoice = ""
    for l in lines:
        if 'invoice' in l.lower():
            # try to extract pattern like INV-2025-0098 or INV 123 or just #1234
            m = re.search(r'(INV[-\s]?\d[\d-]*)|(?:invoice\s*[:#\s]+\s*([A-Za-z0-9\-]+))|(#\s*\d{2,8})', l, re.IGNORECASE)
            if m:
                invoice = (m.group(1) or m.group(2) or m.group(0)).strip()
                break

    # dates
    dates = []
    for l in lines:
        m = DATE_RE.search(l)
        if m:
            match = m.group(0)
            dates.append(match)
    # de-dup and keep best
    dates = list(dict.fromkeys(dates))

    # amounts: label-first
    subtotal, tax_amt, total = "", "", ""
    subtotal, _ = find_label_value(lines, ['subtotal'])
    tax_amt, _ = find_label_value(lines, ['tax', 'gst', 'vat'])
    total, _ = find_label_value(lines, ['total due', 'total:', 'amount due', 'balance due', 'total'])

    # fallback: find largest amount (should be total)
    if not total:
        found = []
        for l in lines:
            a = try_parse_amount(l)
            if a:
                # convert to float for comparison
                try:
                    f = float(a.replace('$','').replace(',',''))
                    found.append((f, a))
                except:
                    continue
        if found:
            found.sort(key=lambda x: x[0], reverse=True)
            total = found[0][1]

    # line items
    items = extract_line_items(lines)

    # amounts list (distinct)
    amounts = []
    for l in lines:
        a = try_parse_amount(l)
        if a and a not in amounts:
            amounts.append(a)

    out = {
        "vendor": vendor,
        "invoice": invoice,
        "dates": dates,
        "subtotal": subtotal,
        "tax": tax_amt,
        "total": total,
        "amounts": amounts,
        "items": items
    }
    return out

# backward compatibility alias
def extract_fields(text: str) -> Dict[str, Any]:
    return extract_invoice_fields(text)
