"""Render public PDF first pages next to real Chrome screenshots for visual QA.

Run in the isolated Marker environment (PDFium and Pillow); outputs to /tmp by
default. This is a contact sheet, not an automated visual acceptance assertion.
"""

import argparse
from pathlib import Path
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--samples-dir", type=Path, required=True)
parser.add_argument("--screenshots-dir", type=Path, default=Path("docs/validation/quality"))
parser.add_argument("--output-dir", type=Path, default=Path("/tmp/paperflow-quality-contact"))
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)
for pdf in sorted(args.samples_dir.glob("*.pdf")):
    top = args.screenshots_dir / (pdf.stem + "-top.png")
    if not top.is_file():
        continue
    document = pdfium.PdfDocument(str(pdf))
    try:
        page = document[0]
        bitmap = page.render(scale=1.4)
        source = bitmap.to_pil().copy()
        bitmap.close()
        page.close()
    finally:
        document.close()
    sheet = Image.new("RGB", (1500, 1100), "#e8e8e8")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), pdf.stem + " - PDF first page / Chrome HTML top + section", fill="black")
    source.thumbnail((730, 1060))
    sheet.paste(source, (10, 30))
    for index, name in enumerate(("top", "middle")):
        with Image.open(args.screenshots_dir / (pdf.stem + "-" + name + ".png")) as screenshot:
            screenshot.thumbnail((750, 530))
            sheet.paste(screenshot, (750, 30 + index * 530))
    target = args.output_dir / (pdf.stem + ".png")
    sheet.save(target)
    print(target)
