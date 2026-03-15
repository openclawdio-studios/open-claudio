"""
Ingestion pipeline for the RAG system.

Supports:
  - Plain text  (.txt)
  - Markdown    (.md, .markdown)
  - PDF         (.pdf) via PyMuPDF

Chunking strategy: paragraph-aware with word-count ceiling.
  1. Split on double newlines (paragraph boundaries).
  2. Accumulate paragraphs until chunk_size words is reached.
  3. If a single paragraph exceeds chunk_size, split it with overlap.
  4. Add an overlap buffer of the last `overlap` words to the next chunk
     so context is not lost at boundaries.
"""

import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------

def parse_text(content: str) -> str:
    """Normalise whitespace in a plain-text document."""
    # Collapse runs of 3+ blank lines to 2
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def parse_markdown(content: str) -> str:
    """
    Convert Markdown to clean prose suitable for embedding.

    What is preserved:
      - All text content
      - Header text (without # markers) — kept as prominent lines
      - List items (bullet/number stripped)

    What is removed:
      - HTML tags
      - Image syntax  ![alt](url)
      - Link URLs     [text](url) → text
      - Code fences   ```...```  (content kept)
      - Inline code   `code`     (content kept)
      - Bold/italic markers
      - Horizontal rules
    """
    text = content

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Images: remove entirely
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)

    # Links: keep visible text
    text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)

    # Code fences: keep content, remove markers
    text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"~~~[^\n]*\n(.*?)~~~", r"\1", text, flags=re.DOTALL)

    # Inline code: keep content
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Headers: remove # markers, keep text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Bold / italic
    text = re.sub(r"\*{1,3}([^\*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)

    # Strikethrough
    text = re.sub(r"~~([^~\n]+)~~", r"\1", text)

    # Horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # List markers (- item, * item, 1. item)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def parse_pdf(path: str) -> str:
    """
    Extract text from a PDF using PyMuPDF (fitz).

    Each page is prefixed with [Page N] so the agent can cite sources.
    Scanned PDFs (no text layer) will return an empty string per page —
    OCR is not included in this implementation.

    Args:
        path: Absolute path to the PDF file.

    Returns:
        Extracted text with page markers, joined by double newlines.

    Raises:
        ImportError: If PyMuPDF is not installed.
        FileNotFoundError: If the PDF path does not exist.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required to parse PDFs. "
            "Install it with: pip install pymupdf"
        ) from exc

    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = fitz.open(path)
    pages: list[str] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            # Normalise whitespace within the page
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            pages.append(f"[Page {page_num + 1}]\n{text.strip()}")

    doc.close()
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# File loader — detects format by extension
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".txt", ".text", ".md", ".markdown", ".pdf"}


def load_file(path: str) -> tuple[str, str]:
    """
    Load a file and return (cleaned_text, format_label).

    Format labels: "text", "markdown", "pdf"

    Args:
        path: Absolute path to the file.

    Returns:
        Tuple of (content_string, format_label).

    Raises:
        ValueError: If the file format is not supported.
        FileNotFoundError: If the file does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = p.suffix.lower()

    if ext == ".pdf":
        return parse_pdf(str(p)), "pdf"

    if ext in (".md", ".markdown"):
        return parse_markdown(p.read_text(encoding="utf-8", errors="replace")), "markdown"

    if ext in (".txt", ".text", ""):
        return parse_text(p.read_text(encoding="utf-8", errors="replace")), "text"

    # Unknown extension — try as UTF-8 text
    try:
        return parse_text(p.read_text(encoding="utf-8", errors="replace")), "text"
    except Exception as exc:
        raise ValueError(
            f"Unsupported file format '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        ) from exc


# ---------------------------------------------------------------------------
# Chunking — paragraph-aware with word-count ceiling
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = 400,
    overlap: int = 50,
) -> list[str]:
    """
    Split text into overlapping chunks that respect paragraph boundaries.

    Algorithm:
      1. Split on blank lines → paragraph list.
      2. Accumulate paragraphs until chunk_size words would be exceeded.
      3. When limit is reached, emit the chunk and carry over the last
         `overlap` words as context for the next chunk.
      4. Paragraphs longer than chunk_size are hard-split with overlap.

    Args:
        text: Input text (already cleaned by a parser).
        chunk_size: Target maximum words per chunk.
        overlap: Words from the end of each chunk carried into the next.

    Returns:
        List of non-empty text chunks.
    """
    # Split into paragraphs on one or more blank lines
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    if not paragraphs:
        return []

    chunks: list[str] = []
    buffer: list[str] = []   # word buffer for current chunk
    buffer_size = 0

    def _flush(buf: list[str]) -> list[str]:
        """Emit chunk and return overlap tail."""
        if buf:
            chunks.append(" ".join(buf))
        return buf[-overlap:] if overlap and len(buf) > overlap else []

    for para in paragraphs:
        words = para.split()
        if not words:
            continue

        # Paragraph fits in the current buffer
        if buffer_size + len(words) <= chunk_size:
            buffer.extend(words)
            buffer_size += len(words)
        else:
            # Flush what we have first
            if buffer:
                buffer = _flush(buffer)
                buffer_size = len(buffer)

            # If the paragraph itself exceeds chunk_size, hard-split it
            if len(words) > chunk_size:
                i = 0
                while i < len(words):
                    segment = words[i : i + chunk_size]
                    if i == 0 and buffer:
                        # Prepend carry-over overlap
                        segment = buffer + segment
                    chunks.append(" ".join(segment))
                    i += chunk_size - overlap
                # Carry last overlap into buffer
                tail = words[-(overlap):] if overlap else []
                buffer = tail
                buffer_size = len(buffer)
            else:
                buffer = list(words)
                buffer_size = len(words)

    # Flush remainder
    if buffer:
        chunks.append(" ".join(buffer))

    return [c for c in chunks if c.strip()]
