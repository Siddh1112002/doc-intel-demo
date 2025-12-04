from fpdf import FPDF
import os

os.makedirs("uploads", exist_ok=True)
out = os.path.join("uploads","sample_invoice.pdf")

pdf = FPDF(unit="mm", format="A4")
pdf.add_page()
pdf.set_font("Helvetica", "B", 18)
pdf.cell(0, 10, "Acme Widgets Ltd.", ln=True)
pdf.set_font("Helvetica", "", 11)
pdf.cell(0, 6, "123 Industrial Drive, Example City, EX 10101", ln=True)
pdf.cell(0, 6, "Phone: +1 555-0199", ln=True)
pdf.ln(6)

pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 6, "INVOICE", ln=True)
pdf.ln(4)

pdf.set_font("Helvetica", "", 11)
pdf.cell(0, 6, "Invoice #: INV-2025-0098", ln=True)
pdf.cell(0, 6, "Date: 2025-12-01", ln=True)
pdf.cell(0, 6, "Due Date: 2025-12-15", ln=True)
pdf.ln(6)

pdf.set_font("Helvetica", "B", 11)
pdf.cell(120, 7, "Description", border=1)
pdf.cell(30, 7, "Qty", border=1)
pdf.cell(40, 7, "Amount", border=1, ln=True)

pdf.set_font("Helvetica", "", 11)
pdf.cell(120, 7, "Professional consulting (Nov 2025)", border=1)
pdf.cell(30, 7, "10", border=1)
pdf.cell(40, 7, "$2,000.00", border=1, ln=True)

pdf.cell(120, 7, "Implementation services", border=1)
pdf.cell(30, 7, "1", border=1)
pdf.cell(40, 7, "$1,250.00", border=1, ln=True)

pdf.ln(8)
pdf.set_font("Helvetica", "B", 12)
pdf.cell(120, 7, "Subtotal:")
pdf.cell(0, 7, "$3,250.00", ln=True)
pdf.cell(120, 7, "Tax (18%):")
pdf.cell(0, 7, "$585.00", ln=True)
pdf.cell(120, 7, "Total Due:")
pdf.cell(0, 7, "$3,835.00", ln=True)

pdf.ln(8)
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 6, "Please pay by bank transfer to: Acme Widgets Ltd., Account: 123456789, IFSC: ACME0001234. Thank you for your business.")

pdf.output(out)
print("WROTE:", out)
