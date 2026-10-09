"""Generate a copyright-free 35-page PDF solely for automated tests."""

import sys
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

writer = PdfWriter()
font = DictionaryObject(
    {
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }
)
font_ref = writer._add_object(font)
for number in range(1, 36):
    page = writer.add_blank_page(width=595, height=842)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        f"BT /F1 22 Tf 60 740 Td (PaperFlow test document - Page {number}) Tj ET\nBT /F1 12 Tf 60 700 Td (Generated fixture: selectable text, navigation and persistence.) Tj ET".encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
writer.add_metadata({"/Title": "PaperFlow Test Research", "/Author": "Automated Fixture"})
path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/paperflow-e2e.pdf")
with path.open("wb") as target:
    writer.write(target)
print(path)
