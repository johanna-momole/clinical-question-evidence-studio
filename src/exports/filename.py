"""Safe filename generation and sanitization for export artifacts."""

from __future__ import annotations

import re

from src.schemas.exports import extension_for

_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9_\-]")
_TRAVERSAL_PATTERN = re.compile(r"(^|[\\/])\.\.?($|[\\/])")
_ABSOLUTE_PATTERN = re.compile(r"^[/\\]|^[A-Za-z]:[/\\]")

_MAX_BASE_LEN = 80


def sanitize(name: str) -> str:
    """Replace unsafe characters with underscores and strip leading dots/spaces."""
    name = name.strip().lstrip(".")
    return _SAFE_PATTERN.sub("_", name)[:_MAX_BASE_LEN] or "export"


def artifact_filename(brief_id: str, export_format: str, version: int = 1) -> str:
    """Return a safe filename for an export artifact."""
    safe_id = sanitize(brief_id)
    ext = extension_for(export_format)
    suffix_map = {
        "json": "brief",
        "markdown": "brief",
        "citation_map_tsv": "citations",
        "citation_map_json": "citations",
        "qa_report_markdown": "qa_report",
        "qa_report_json": "qa_report",
        "review_history_markdown": "review_history",
        "review_history_json": "review_history",
        "provenance": "provenance",
        "schema": "schema",
        "pdf": "brief",
        "pptx": "brief",
        "zip": "bundle",
    }
    suffix = suffix_map.get(export_format, export_format)
    return f"{safe_id}_v{version}_{suffix}{ext}"


def bundle_filename(brief_id: str, bundle_name: str | None, version: int = 1) -> str:
    """Return a safe ZIP filename."""
    if bundle_name:
        base = sanitize(bundle_name)
    else:
        base = sanitize(brief_id) + f"_v{version}_bundle"
    return base + ".zip"


def assert_no_traversal(entry_name: str) -> None:
    """Raise ValueError if entry_name could escape the archive root."""
    if _TRAVERSAL_PATTERN.search(entry_name):
        raise ValueError(f"Archive entry would traverse directory: {entry_name!r}")
    if _ABSOLUTE_PATTERN.match(entry_name):
        raise ValueError(f"Archive entry must not be absolute: {entry_name!r}")
    if entry_name.startswith(("/", "\\", "../", "..\\")):
        raise ValueError(f"Archive entry has unsafe prefix: {entry_name!r}")


def zip_entry_path(subfolder: str, filename: str) -> str:
    """Compose a safe ZIP entry path like 'brief/filename.json'."""
    safe_folder = sanitize(subfolder)
    safe_file = sanitize_filename(filename)
    entry = f"{safe_folder}/{safe_file}"
    assert_no_traversal(entry)
    return entry


def sanitize_filename(filename: str) -> str:
    """Keep extension; sanitize the stem."""
    if "." in filename:
        stem, _, ext = filename.rpartition(".")
        return sanitize(stem) + "." + sanitize(ext)
    return sanitize(filename)
