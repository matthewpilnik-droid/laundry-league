"""Inline data.json into site/template.html -> index.html (one self-contained file)."""
import json, pathlib, sys

root = pathlib.Path(__file__).resolve().parent.parent
data = json.loads((root / "data.json").read_text())
# Keep "</" out of the inline JSON so it can't close the script tag early.
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
html = (root / "site" / "template.html").read_text().replace("__DATA__", blob)
(root / "index.html").write_text(html)
print("wrote", root / "index.html", f"{len(html)/1024:.0f} KB")
