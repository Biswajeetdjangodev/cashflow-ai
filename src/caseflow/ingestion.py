"""File discovery and text extraction for TXT, PDF and DOCX documents.

Every failure is raised as IngestionError with a stable machine-readable code so the
workflow can report it per file and carry on with the rest of the batch.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_FORMATS = {".txt": "txt", ".pdf": "pdf", ".docx": "docx"}
# Fewer meaningful characters than this across a whole PDF => treat as scanned/image-only.
MIN_PDF_TEXT_CHARS = 20


class IngestionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    relative_path: str  # POSIX path relative to the input folder
    file_format: str  # txt | pdf | docx | the unsupported extension
    supported: bool
    size_bytes: int
    document_id: str


def discover_documents(input_dir: Path, recursive: bool = False) -> list[SourceDocument]:
    """List files in input_dir (sorted, deterministic). Hidden files are ignored."""
    pattern = "**/*" if recursive else "*"
    paths = [
        p for p in input_dir.glob(pattern)
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(input_dir).parts)
    ]
    docs = []
    for path in sorted(paths, key=lambda p: p.relative_to(input_dir).as_posix().lower()):
        rel = path.relative_to(input_dir).as_posix()
        suffix = path.suffix.lower()
        fmt = SUPPORTED_FORMATS.get(suffix, suffix.lstrip(".") or "none")
        docs.append(
            SourceDocument(
                path=path,
                relative_path=rel,
                file_format=fmt,
                supported=suffix in SUPPORTED_FORMATS,
                size_bytes=path.stat().st_size,
                document_id=make_document_id(rel, path),
            )
        )
    return docs


def make_document_id(relative_path: str, path: Path) -> str:
    """Readable, collision-safe ID: slug of the relative path (extension included,
    so a.txt and a.pdf differ) + 8 hex chars of the content hash."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        digest.update(relative_path.encode())
    slug = re.sub(r"[^A-Za-z0-9]+", "-", relative_path).strip("-").lower()[:80] or "document"
    return f"{slug}-{digest.hexdigest()[:8]}"


def extract_text(doc: SourceDocument, max_file_bytes: int, max_document_chars: int) -> str:
    if not doc.supported:
        raise IngestionError("unsupported_format", f"'.{doc.file_format}' files are not supported (use TXT, PDF or DOCX)")
    if doc.size_bytes > max_file_bytes:
        raise IngestionError(
            "document_too_large",
            f"file is {doc.size_bytes:,} bytes, above MAX_FILE_BYTES={max_file_bytes:,}. "
            "Split the document or raise MAX_FILE_BYTES; nothing was truncated.",
        )
    if doc.size_bytes == 0:
        raise IngestionError("empty_document", "file is empty (0 bytes)")

    extractor = {"txt": _extract_txt, "pdf": _extract_pdf, "docx": _extract_docx}[doc.file_format]
    try:
        text = extractor(doc.path)
    except IngestionError:
        raise
    except OSError as exc:
        raise IngestionError("read_error", f"could not read file: {exc.strerror or type(exc).__name__}") from exc

    text = _tidy(text)
    if not text:
        raise IngestionError("empty_document", "no text content found in document")
    if len(text) > max_document_chars:
        raise IngestionError(
            "document_too_large",
            f"extracted text is {len(text):,} characters, above MAX_DOCUMENT_CHARS={max_document_chars:,}. "
            "Split the document or raise MAX_DOCUMENT_CHARS; nothing was truncated.",
        )
    return text


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _extract_txt(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")  # strips a UTF-8 BOM if present
    except UnicodeDecodeError as exc:
        raise IngestionError(
            "encoding_error",
            f"not valid UTF-8 (invalid byte at position {exc.start}). Re-save the file as UTF-8.",
        ) from exc


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import DependencyError, FileNotDecryptedError, PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # Owner-password-only PDFs open with an empty password; real locks do not.
            try:
                if not reader.decrypt(""):
                    raise IngestionError("encrypted_pdf", "PDF is password-protected; provide an unlocked copy")
            except (FileNotDecryptedError, NotImplementedError, DependencyError) as exc:
                raise IngestionError("encrypted_pdf", "PDF is encrypted and cannot be opened; provide an unlocked copy") from exc
        pages = [(page.extract_text() or "") for page in reader.pages]
    except IngestionError:
        raise
    except FileNotDecryptedError as exc:
        raise IngestionError("encrypted_pdf", "PDF is password-protected; provide an unlocked copy") from exc
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise IngestionError("corrupted_file", f"PDF could not be parsed ({type(exc).__name__})") from exc

    if not pages:
        raise IngestionError("empty_document", "PDF has no pages")
    text = "\n\n".join(p.strip() for p in pages)
    if len(re.sub(r"\s+", "", text)) < MIN_PDF_TEXT_CHARS:
        raise IngestionError(
            "ocr_required",
            f"PDF has {len(pages)} page(s) but no usable text layer (likely scanned). "
            "OCR is not supported in this version; convert it with an OCR tool first.",
        )
    return text


def _extract_docx(path: Path) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(str(path))
        blocks = list(_docx_blocks(document))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise IngestionError("corrupted_file", f"DOCX could not be opened ({type(exc).__name__})") from exc
    return "\n".join(blocks)


def _docx_blocks(container) -> list[str]:
    """Paragraphs and tables in document order. Table rows become 'cell | cell' lines;
    horizontally merged cells are emitted once; nested tables are flattened in place."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    out: list[str] = []
    for item in container.iter_inner_content():
        if isinstance(item, Paragraph):
            out.append(item.text)
        elif isinstance(item, Table):
            for row in item.rows:
                cells, seen = [], set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(" ".join(b.strip() for b in _docx_blocks(cell) if b.strip()))
                out.append(" | ".join(cells))
            out.append("")
    return out
