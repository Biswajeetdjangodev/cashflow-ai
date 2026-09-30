from __future__ import annotations

from pathlib import Path

import pytest

from caseflow.ingestion import IngestionError, discover_documents, extract_text


def _extract(path: Path, max_bytes: int = 10**7, max_chars: int = 60_000) -> str:
    [doc] = [d for d in discover_documents(path.parent) if d.path == path]
    return extract_text(doc, max_bytes, max_chars)


def test_txt_with_bom(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes("﻿Hello – café\r\nLine two".encode("utf-8"))
    assert _extract(p) == "Hello – café\nLine two"


def test_txt_invalid_utf8_reports_encoding_error(tmp_path):
    p = tmp_path / "latin.txt"
    p.write_bytes("caf\xe9 complaint".encode("latin-1"))
    with pytest.raises(IngestionError) as e:
        _extract(p)
    assert e.value.code == "encoding_error"


def test_pdf_all_pages_extracted(tmp_path, gen):
    p = tmp_path / "multi.pdf"
    gen.write_pdf(p, ["First page line", "Second page line"], pages=2)
    text = _extract(p)
    assert "First page line" in text and "Second page line" in text
    assert text.index("First") < text.index("Second")


def test_docx_paragraphs_and_tables_in_order(tmp_path, gen):
    p = tmp_path / "t.docx"
    gen.write_docx(p, {"title": "Heading", "table": [("Field", "Value"), ("Customer", "Ann Example")],
                       "paragraphs": ["After the table"]})
    text = _extract(p)
    assert "Customer | Ann Example" in text
    assert text.index("Heading") < text.index("Customer | Ann Example") < text.index("After the table")


@pytest.mark.parametrize("name,content,code", [
    ("empty.txt", b"", "empty_document"),
    ("blank.txt", b"  \n\n ", "empty_document"),
    ("bad.pdf", b"%PDF-1.7 garbage", "corrupted_file"),
    ("bad.docx", b"PK\x03\x04 nope", "corrupted_file"),
])
def test_file_level_failures(tmp_path, name, content, code):
    p = tmp_path / name
    p.write_bytes(content)
    with pytest.raises(IngestionError) as e:
        _extract(p)
    assert e.value.code == code


def test_scanned_pdf_requires_ocr(tmp_path, gen):
    p = tmp_path / "scan.pdf"
    gen.write_scanned_pdf(p)
    with pytest.raises(IngestionError) as e:
        _extract(p)
    assert e.value.code == "ocr_required"


def test_encrypted_pdf(tmp_path, gen):
    p = tmp_path / "locked.pdf"
    gen.write_encrypted_pdf(p)
    with pytest.raises(IngestionError) as e:
        _extract(p)
    assert e.value.code == "encrypted_pdf"


def test_oversized_file_and_text_are_not_truncated(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 5000, encoding="utf-8")
    with pytest.raises(IngestionError) as e:
        _extract(p, max_bytes=1000)
    assert e.value.code == "document_too_large"
    with pytest.raises(IngestionError) as e:
        _extract(p, max_chars=1000)
    assert e.value.code == "document_too_large" and "nothing was truncated" in e.value.message


def test_discovery_sorted_case_insensitive_nonrecursive_by_default(tmp_path):
    for name in ("b.TXT", "a.Pdf", "c.DOCX", "notes.md", ".hidden.txt"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.txt").write_bytes(b"x")
    docs = discover_documents(tmp_path)
    assert [d.relative_path for d in docs] == ["a.Pdf", "b.TXT", "c.DOCX", "notes.md"]
    assert [d.supported for d in docs] == [True, True, True, False]
    assert [d.file_format for d in docs][:3] == ["pdf", "txt", "docx"]
    assert "sub/d.txt" in [d.relative_path for d in discover_documents(tmp_path, recursive=True)]


def test_unsupported_file_is_skipped_not_read(tmp_path):
    p = tmp_path / "sheet.csv"
    p.write_text("a,b", encoding="utf-8")
    with pytest.raises(IngestionError) as e:
        _extract(p)
    assert e.value.code == "unsupported_format"


def test_identical_stems_get_distinct_ids(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    (tmp_path / "x" / "letter.txt").write_text("one", encoding="utf-8")
    (tmp_path / "y" / "letter.txt").write_text("one", encoding="utf-8")  # same content too
    (tmp_path / "letter.pdf").write_bytes(b"%PDF")
    ids = [d.document_id for d in discover_documents(tmp_path, recursive=True)]
    assert len(ids) == len(set(ids)) == 3
