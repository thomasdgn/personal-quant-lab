"""Export HTML autonome d'un rapport Markdown (lisible sur téléphone).

Les images référencées en chemin relatif sont intégrées en base64 : le fichier
``.html`` se suffit à lui-même (envoi par e-mail, ouverture hors-ligne).
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from pathlib import Path

import markdown

_CSS = """
:root { --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --border: #d1d9e0; --accent: #0969da; --row: #f6f8fa; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --border: #3d444d; --accent: #4493f8; --row: #151b23; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 16px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.6rem; border-bottom: 1px solid var(--border); padding-bottom: .3em; }
h2 { font-size: 1.25rem; margin-top: 1.8em; border-bottom: 1px solid var(--border); padding-bottom: .2em; }
h3 { font-size: 1.05rem; }
a { color: var(--accent); }
em { color: var(--muted); }
code { background: var(--row); padding: .1em .35em; border-radius: 4px; font-size: .9em; }
img { max-width: 100%; height: auto; border: 1px solid var(--border); border-radius: 6px; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { border-collapse: collapse; width: 100%; font-size: .92rem; margin: .6em 0; }
th, td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; white-space: nowrap; }
tr:nth-child(even) td { background: var(--row); }
blockquote { margin: 0; padding: .2em 1em; border-left: 4px solid var(--border); color: var(--muted); }
footer { color: var(--muted); font-size: .85rem; margin-top: 2em; }
"""


def _embed_images(markup: str, base_dir: Path) -> str:
    def replace(match: re.Match) -> str:
        src = match.group(2)
        if src.startswith(("data:", "http://", "https://")):
            return match.group(0)
        path = (base_dir / src).resolve()
        if not path.exists():
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'{match.group(1)}data:{mime};base64,{encoded}{match.group(3)}'

    return re.sub(r'(<img[^>]*?src=")([^"]+)(")', replace, markup)


def markdown_to_html(markdown_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Convertit ``markdown_path`` en HTML autonome ; renvoie le chemin écrit."""
    markdown_path = Path(markdown_path)
    output = Path(output_path) if output_path else markdown_path.with_suffix(".html")
    text = markdown_path.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables", "sane_lists"])
    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body).replace("</table>", "</table></div>")
    body = _embed_images(body, markdown_path.parent)
    title_match = re.search(r"^# (.+)$", text, flags=re.MULTILINE)
    title = html.escape(title_match.group(1).strip() if title_match else markdown_path.stem)
    document = (
        "<!DOCTYPE html>\n<html lang=\"fr\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n<main>\n{body}\n"
        "<footer>Généré par personal-quant-lab — usage éducatif, aucun ordre exécuté.</footer>\n"
        "</main>\n</body>\n</html>\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8", newline="\n")
    return output
