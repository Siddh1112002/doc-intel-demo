# app.py
import os
import io
import json
import traceback
import unicodedata
from typing import Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiofiles

# optional imports
ocr_extract = None
summarize = None
parser_rules = None

# Try to import user helpers if present
try:
    import ocr_extract as ocr_extract_module
    ocr_extract = ocr_extract_module
except Exception:
    ocr_extract = None

try:
    import summarize as summarize_module
    summarize = summarize_module
except Exception:
    summarize = None

try:
    import parser_rules as parser_rules_module
    parser_rules = parser_rules_module
except Exception:
    parser_rules = None

# fitz fallback for text-based PDFs
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

# PDF summary generator (FPDF)
try:
    from fpdf import FPDF
except Exception:
    FPDF = None

app = FastAPI(title="Document Intelligence (local demo) - unicode-safe PDF")

PROJECT_ROOT = os.path.dirname(__file__)
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
FONTS_DIR = os.path.join(STATIC_DIR, "fonts")
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
if not os.path.exists(FONTS_DIR):
    os.makedirs(FONTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ExtractOut(BaseModel):
    filename: str
    text: str
    clean_text: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    error: Optional[Any] = None


async def save_upload_file(upload_file: UploadFile, dest_path: str) -> None:
    """Save incoming UploadFile to disk asynchronously."""
    async with aiofiles.open(dest_path, "wb") as out_file:
        while content := await upload_file.read(1024 * 64):
            await out_file.write(content)


def pdf_text_extract_fitz(path: str) -> str:
    """Extract text using PyMuPDF (fast for text-based PDFs)."""
    if fitz is None:
        raise RuntimeError("pymupdf (fitz) not installed")
    doc = fitz.open(path)
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text("text"))
    doc.close()
    return "\n".join(text_parts)


def run_ocr_on_file(path: str) -> Dict[str, Any]:
    """Try user's OCR helper; if missing, try fitz (for text pdf)."""
    if ocr_extract:
        for name in ("extract_text_from_pdf", "extract_text", "ocr_extract", "read_pdf_text"):
            fn = getattr(ocr_extract, name, None)
            if callable(fn):
                try:
                    result = fn(path)
                    if hasattr(result, "__await__"):
                        import asyncio
                        result = asyncio.get_event_loop().run_until_complete(result)
                    return {"text": result}
                except Exception as e:
                    return {"error": "ocr_failed", "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}

    try:
        text = pdf_text_extract_fitz(path)
        return {"text": text}
    except Exception as e:
        return {"error": "ocr_failed", "detail": f"fallback_failed: {type(e).__name__}: {e}", "trace": traceback.format_exc()}


def run_field_extraction(text: str) -> Dict[str, Any]:
    if parser_rules:
        for name in ("extract_fields", "extract_invoice_fields", "extract_invoice", "parse_fields", "parse_invoice"):
            fn = getattr(parser_rules, name, None)
            if callable(fn):
                try:
                    out = fn(text)
                    return {"fields": out}
                except Exception as e:
                    return {"error": "extract_failed", "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
        return {"error": "extract_no_fn", "detail": "No expected function found in parser_rules.py"}
    return {"error": "extractor_missing", "detail": "parser_rules.py not found."}


def run_summarize(text: str, sentences_count: int = 3) -> Dict[str, Any]:
    if summarize:
        for name in ("extractive_summary", "summarize_text", "summarize"):
            fn = getattr(summarize, name, None)
            if callable(fn):
                try:
                    if "sentences_count" in fn.__code__.co_varnames:
                        s = fn(text, sentences_count=sentences_count)
                    else:
                        s = fn(text)
                    if isinstance(s, (list, tuple)):
                        s = "\n".join(map(str, s))
                    return {"summary": s}
                except Exception as e:
                    return {"error": "summarize_failed", "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    short = "\n".join(lines[:min(len(lines), sentences_count * 3)])
    return {"summary": short}


@app.get("/")
def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return PlainTextResponse("Put a static/index.html in the static folder.")


@app.post("/upload", response_model=ExtractOut)
async def upload_doc(file: UploadFile = File(...)):
    filename = file.filename or "uploaded_file"
    dest = os.path.join(UPLOAD_DIR, filename)
    try:
        await save_upload_file(file, dest)
    except Exception as e:
        return JSONResponse(status_code=500, content={"filename": filename, "text": "", "error": f"save_failed: {e}"})

    ocr_out = run_ocr_on_file(dest)
    if "error" in ocr_out:
        return JSONResponse(status_code=200, content={
            "filename": filename,
            "text": "",
            "clean_text": "",
            "fields": None,
            "summary": None,
            "error": ocr_out
        })

    text = ocr_out.get("text", "") or ""
    clean_text = text.replace("\r", "")

    extract_out = run_field_extraction(clean_text)
    fields = extract_out.get("fields") if "fields" in extract_out else None

    summary_out = run_summarize(clean_text, sentences_count=4)
    summary = summary_out.get("summary") if "summary" in summary_out else None

    out_json = {
        "filename": filename,
        "text": text,
        "clean_text": clean_text,
        "fields": fields,
        "summary": summary,
        "error": extract_out.get("error") if "error" in extract_out else None
    }
    try:
        save_path = os.path.join(UPLOAD_DIR, f"{filename}.json")
        with open(save_path, "w", encoding="utf8") as fh:
            json.dump(out_json, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return out_json


@app.post("/extract_text_only", response_model=ExtractOut)
async def extract_text_only(file: UploadFile = File(...)):
    filename = file.filename or "uploaded_file"
    dest = os.path.join(UPLOAD_DIR, filename)
    try:
        await save_upload_file(file, dest)
    except Exception as e:
        return JSONResponse(status_code=500, content={"filename": filename, "text": "", "error": f"save_failed: {e}"})

    ocr_out = run_ocr_on_file(dest)
    if "error" in ocr_out:
        return JSONResponse(status_code=200, content={"filename": filename, "text": "", "error": ocr_out})
    text = ocr_out.get("text", "")
    return {"filename": filename, "text": text, "clean_text": text.replace("\r", ""), "fields": None, "summary": None}


@app.get("/export_json")
def export_json(filename: str = Query(..., description="Name of uploaded file (e.g. sample_invoice.pdf)")):
    path = os.path.join(UPLOAD_DIR, f"{filename}.json")
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": f"{path} missing"})
    return FileResponse(path, filename=f"{filename}.json", media_type="application/json")


def sanitize_for_latin1(text: str) -> str:
    """
    Make a best-effort ASCII/latin-1-safe representation:
    - Normalize like NFKD first
    - Replace common punctuation (em-dash -> hyphen)
    - Fall back to encoding replacement for anything else
    """
    if not text:
        return ""
    # map a few common unicode punctuation to ascii
    trans = {
        "\u2014": " - ",  # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # ellipsis
    }
    for k, v in trans.items():
        text = text.replace(k, v)
    # normalize (decompose)
    text = unicodedata.normalize("NFKD", text)
    # finally ensure latin-1 encodable by replacing non-encodable chars
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    return safe


@app.get("/export_pdf")
def export_pdf(filename: str = Query(..., description="Name of uploaded file (e.g. sample_invoice.pdf)")):
    json_path = os.path.join(UPLOAD_DIR, f"{filename}.json")
    if not os.path.exists(json_path):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": "extracted json missing"})

    try:
        with open(json_path, "r", encoding="utf8") as fh:
            data = json.load(fh)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "read_failed", "detail": str(e)})

    if FPDF is None:
        return JSONResponse(status_code=500, content={"error": "fpdf_missing", "detail": "install fpdf to generate PDF: pip install fpdf"})

    # Path to a TrueType font (DejaVu recommended) if user placed it in static/fonts
    dejavu_ttf = os.path.join(FONTS_DIR, "DejaVuSans.ttf")
    use_unicode_font = os.path.exists(dejavu_ttf)

    try:
        pdf = FPDF(unit="mm", format="A4")
        pdf.add_page()
        pdf.set_auto_page_break(True, margin=15)

        # If DejaVu TTF available, register and use it (uni=True)
        if use_unicode_font:
            try:
                # register font (fpdf expects a "family" name)
                pdf.add_font("DejaVu", "", dejavu_ttf, uni=True)
                pdf.set_font("DejaVu", size=14)
            except Exception:
                # fallback to core font
                pdf.set_font("Helvetica", "B", 16)
        else:
            pdf.set_font("Helvetica", "B", 16)

        pdf.cell(0, 10, "Document Intelligence — Summary", ln=True)
        pdf.ln(4)

        # write summary and fields. Use unicode-safe string if font is available, otherwise sanitize.
        def write_text_block(text_val, font_size=11, bold=False):
            if use_unicode_font:
                pdf.set_font("DejaVu", "B" if bold else "", size=font_size)
                # FPDF 1.x add_cell requires ascii-safe string if using core fonts, but with DejaVu and uni=True it's fine
                pdf.multi_cell(0, 6, text_val)
            else:
                pdf.set_font("Helvetica", "B" if bold else "", size=font_size)
                pdf.multi_cell(0, 6, sanitize_for_latin1(text_val))

        write_text_block(f"Source file: {data.get('filename', filename)}", font_size=11, bold=False)
        pdf.ln(2)
        write_text_block("Summary:", font_size=12, bold=True)
        write_text_block(data.get("summary", "") or "", font_size=10, bold=False)
        pdf.ln(4)
        write_text_block("Detected fields:", font_size=12, bold=True)

        fields = data.get("fields") or {}
        # Print simple field list (stringify lists/dicts safely)
        for k, v in fields.items():
            # convert v to a readable string
            if isinstance(v, (list, dict)):
                try:
                    vs = json.dumps(v, ensure_ascii=False)
                except Exception:
                    vs = str(v)
            else:
                vs = str(v)
            write_text_block(f"{k}: {vs}", font_size=10)

        # items table (if present)
        items = fields.get("items") if isinstance(fields, dict) else None
        if items and isinstance(items, list):
            pdf.ln(4)
            write_text_block("Line items:", font_size=12, bold=True)
            for it in items:
                if isinstance(it, dict):
                    desc = it.get("description", "") or ""
                    qty = it.get("qty", "")
                    amount = it.get("amount", "")
                    write_text_block(f"- {desc}   qty: {qty}   amount: {amount}", font_size=10)
                else:
                    write_text_block(f"- {str(it)}", font_size=10)

        # Generate bytes
        s = pdf.output(dest='S')
        if isinstance(s, str):
            out_bytes = s.encode("latin-1", errors="ignore")
        else:
            out_bytes = bytes(s)
        bio = io.BytesIO(out_bytes)
        bio.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="{os.path.splitext(filename)[0]}_summary.pdf"'}
        return StreamingResponse(bio, media_type="application/pdf", headers=headers)

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "pdf_failed", "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})


@app.post("/save_corrections")
async def save_corrections(payload: Dict[str, Any]):
    filename = payload.get("filename")
    fields = payload.get("fields")
    if not filename or fields is None:
        return JSONResponse(status_code=400, content={"error": "bad_request", "detail": "filename and fields required"})
    path = os.path.join(UPLOAD_DIR, f"{filename}.json")
    out = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf8") as fh:
                out = json.load(fh)
        except Exception:
            out = {}
    out["fields"] = fields
    try:
        with open(path, "w", encoding="utf8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "save_failed", "detail": str(e)})
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok", "ocr_module": bool(ocr_extract), "summarize_module": bool(summarize), "parser_rules": bool(parser_rules)}


@app.get("/debug_helpers")
def debug_helpers():
    info = {}
    if ocr_extract:
        info["ocr_functions"] = [n for n in dir(ocr_extract) if not n.startswith("_")]
    else:
        info["ocr_functions"] = "ocr_extract module not loaded"
    if summarize:
        info["summarize_functions"] = [n for n in dir(summarize) if not n.startswith("_")]
    else:
        info["summarize_functions"] = "summarize module not loaded"
    if parser_rules:
        info["parser_rules_functions"] = [n for n in dir(parser_rules) if not n.startswith("_")]
    else:
        info["parser_rules_functions"] = "parser_rules module not loaded"
    return info
