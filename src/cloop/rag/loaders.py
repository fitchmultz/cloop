"""Document loading and file I/O operations.

Purpose:
    Load text and PDF documents from filesystem for ingestion.

Responsibilities:
    - Load text files with encoding detection
    - Extract text from PDF documents

Non-scope:
    - Document storage (see documents.py)
    - Chunking (see chunking.py)
- Validate file sizes and extensions
- Generate file metadata (hash, mtime)
- Iterate over candidate files for ingestion

Non-scope:
- Database operations (see documents.py)
- Text processing (see chunking.py)
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence, Set

from pypdf import PdfReader

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _check_file_size(path: Path, max_size_mb: int) -> None:
    """Raise ValueError if file exceeds max size limit."""
    max_bytes = max_size_mb * 1024 * 1024
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"File too large: {path.name} ({size / (1024 * 1024):.1f} MB) "
            f"exceeds maximum allowed size of {max_size_mb} MB"
        )


def load_document(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _read_text_file(path)
    if ext in PDF_EXTENSIONS:
        return _read_pdf(path)
    raise ValueError(f"Unsupported file type: {ext}")


def _normalize_path(value: Path) -> Path:
    return value.expanduser().resolve(strict=False)


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _iter_candidate_files(targets: Sequence[Path], recursive: bool) -> Iterable[Path]:
    seen: Set[str] = set()
    for target in targets:
        normalized = _normalize_path(target)
        if normalized.exists() and normalized.is_dir():
            iterator = normalized.rglob("*") if recursive else normalized.iterdir()
            for entry in iterator:
                if entry.is_file() and _is_supported_file(entry):
                    resolved = _normalize_path(entry)
                    key = str(resolved)
                    if key not in seen:
                        seen.add(key)
                        yield resolved
        elif normalized.exists() and normalized.is_file():
            if _is_supported_file(normalized):
                key = str(normalized)
                if key not in seen:
                    seen.add(key)
                    yield normalized


def _file_stat_metadata(path: Path) -> Dict[str, Any]:
    """
    Get file metadata via stat only (no content read).

    Returns:
        Dict with path, mtime_ns, size_bytes (no sha256)
    """
    stat = path.stat()
    return {
        "path": str(_normalize_path(path)),
        "mtime_ns": int(stat.st_mtime_ns),
        "size_bytes": int(stat.st_size),
    }


def _document_file_metadata(
    path: Path,
    *,
    compute_hash: bool = True,
) -> Dict[str, Any]:
    """
    Get file metadata, optionally with SHA256 hash.

    Args:
        path: File path
        compute_hash: If True, compute SHA256; if False, skip hash

    Returns:
        Dict with path, mtime_ns, size_bytes, and optionally sha256
    """
    meta = _file_stat_metadata(path)
    if compute_hash:
        file_bytes = path.read_bytes()
        meta["sha256"] = hashlib.sha256(file_bytes).hexdigest()
    return meta
