"""Public shape of ``references`` returned by the chat flow.

Ingestion already stores a domain-relative POSIX source
(``domains/<dominio>/knowledge/...``). This module is the last guard before the
response leaves the core: it collapses repeated sources (one per chunk) while
preserving retrieval order, and rewrites legacy absolute filesystem paths (rows
ingested into pgvector/Chroma before the fix) so the server layout never
reaches a client.
"""

from collections.abc import Iterable
from pathlib import PurePosixPath
import re

_DRIVE_PATH = re.compile(r"^[A-Za-z]:/")


def public_reference(source: str, domain_name: str) -> str:
    value = source.strip().replace("\\", "/")
    if not value or not _is_absolute_path(value):
        return value

    marker = f"/domains/{domain_name}/"
    index = value.find(marker)
    if index >= 0:
        return value[index + 1 :]
    return PurePosixPath(value).name


def public_references(sources: Iterable[str], domain_name: str) -> list[str]:
    references: list[str] = []
    seen: set[str] = set()
    for source in sources:
        reference = public_reference(str(source), domain_name)
        if not reference or reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
    return references


def _is_absolute_path(value: str) -> bool:
    return value.startswith("/") or value.startswith("~") or bool(_DRIVE_PATH.match(value))
