"""Content helpers: HTML sanitizing and file import."""
import html
import io
from pathlib import Path

import mammoth
import markdown as md
import nh3
from markdownify import markdownify

# Only the tags the editor can produce. Everything else is stripped on save,
# so a crafted API request cannot store a <script> tag.
ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s",
    "h1", "h2", "h3", "ul", "ol", "li", "blockquote", "pre", "code", "a", "span",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "target"},
    "li": {"data-list"},
    "span": {"class"},
    "p": {"class"},
    "pre": {"class"},
}

SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


class ImportError_(ValueError):
    """Raised when an uploaded file cannot be turned into a document."""


def sanitize_html(raw: str) -> str:
    return nh3.clean(
        raw or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )


def _txt_to_html(text: str) -> str:
    paragraphs = text.replace("\r\n", "\n").split("\n")
    return "".join(f"<p>{html.escape(p) if p.strip() else '<br>'}</p>" for p in paragraphs)


def file_to_html(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ImportError_(
            f"Unsupported file type '{ext or 'none'}'. Supported: .txt, .md, .docx"
        )
    if len(data) == 0:
        raise ImportError_("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportError_("File is larger than the 2 MB limit.")

    if ext == ".docx":
        try:
            result = mammoth.convert_to_html(io.BytesIO(data))
        except Exception as exc:  # mammoth raises several error types
            raise ImportError_("Could not read this .docx file.") from exc
        return sanitize_html(result.value)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImportError_("Text files must be UTF-8 encoded.") from exc

    if ext == ".md":
        return sanitize_html(md.markdown(text, extensions=["extra"]))
    return sanitize_html(_txt_to_html(text))


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return (stem or "Imported document")[:200]


def html_to_markdown(content: str) -> str:
    return markdownify(content or "", heading_style="ATX", bullets="-").strip() + "\n"
