"""SHA-256 checksum helpers for export artifacts."""

from __future__ import annotations

import hashlib


def sha256_bytes(data: bytes) -> str:
    """Return lowercase hex SHA-256 of byte content."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """Return lowercase hex SHA-256 of a file, reading in 64 KiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_sha256(artifact_hashes: list[str]) -> str:
    """Stable hash over all artifact sha256s joined in sorted filename order."""
    payload = "|".join(sorted(artifact_hashes)).encode()
    return hashlib.sha256(payload).hexdigest()
