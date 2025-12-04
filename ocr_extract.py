# ocr_extract.py
import pdfplumber
from PIL import Image
import pytesseract
import io
import os

def extract_text_from_pdf(path: str) -> str:
    """
    Try to extract text from a PDF using pdfplumber (fast for text PDFs).
    If no text or pages, fall back to rendering pages as images and use pytesseract.
    """
    text_parts = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        # if pdfplumber can't open, we will try image OCR below
        pass

    combined = "\n".join(text_parts).strip()
    if combined:
        return combined

    # fallback: render each page to image and OCR (slower)
    # pdfplumber can render page images via page.to_image() but that needs pillow
    try:
        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                # get PIL image of page
                im = p.to_image(resolution=200).original
                txt = pytesseract.image_to_string(im)
                if txt:
                    text_parts.append(txt)
    except Exception:
        # last fallback: try using pytesseract on the file path (if single image PDF)
        try:
            img = Image.open(path)
            txt = pytesseract.image_to_string(img)
            if txt:
                text_parts.append(txt)
        except Exception:
            # nothing else to try
            pass

    result = "\n".join(text_parts).strip()
    if not result:
        raise RuntimeError("No text found in PDF (text-based extraction and image OCR both failed).")
    return result
