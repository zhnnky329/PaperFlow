"""Bundle KaTeX locally; no CDN/network in reading documents."""

from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = root / "frontend/node_modules/katex/dist"
target = root / "backend/app/reader_static"
for name in ("katex.min.js", "katex.min.css"):
    shutil.copyfile(source / name, target / name)
shutil.copytree(source / "fonts", target / "fonts", dirs_exist_ok=True)
print("Reader KaTeX assets bundled")
