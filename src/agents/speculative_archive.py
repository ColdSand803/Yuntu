"""Export-only JSONL archive for completed speculative Writer drafts."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path


logger = logging.getLogger(__name__)

SPECULATIVE_ARCHIVE_DIR = Path("reports/speculative")
SPECULATIVE_ARCHIVE_MAX_FILE_BYTES = 500 * 1024 * 1024

_path_locks_guard = threading.Lock()
_path_locks: dict[Path, threading.Lock] = {}


@dataclass(frozen=True)
class SpeculativeArchiveRecord:
    job_id: str
    generator: str
    adopted: bool
    draft_body: str
    latency_ms: int
    structurally_valid: bool
    writer_prompt_version: str
    token_in: int
    token_out: int

    def __post_init__(self) -> None:
        if self.generator not in {"opus", "ds_flash"}:
            raise ValueError("archive generator must be opus or ds_flash")
        if not self.writer_prompt_version:
            raise ValueError("writer_prompt_version is required")

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "generator": self.generator,
            "adopted": self.adopted,
            "draft_body": self.draft_body,
            "latency_ms": max(0, int(self.latency_ms)),
            "structurally_valid": bool(self.structurally_valid),
            "writer_prompt_version": self.writer_prompt_version,
            "token_in": max(0, int(self.token_in)),
            "token_out": max(0, int(self.token_out)),
        }


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _path_locks_guard:
        return _path_locks.setdefault(resolved, threading.Lock())


def _append_line_with_size_cap(path: Path, line: bytes) -> bool:
    """Append one whole line under a process-local lock, or reject at 500 MB."""
    lock = _lock_for(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        current_size = path.stat().st_size if path.exists() else 0
        if current_size + len(line) > SPECULATIVE_ARCHIVE_MAX_FILE_BYTES:
            logger.warning(
                "speculative_archive_size_cap_reached path=%s "
                "current_bytes=%s attempted_bytes=%s max_bytes=%s",
                path,
                current_size,
                len(line),
                SPECULATIVE_ARCHIVE_MAX_FILE_BYTES,
            )
            return False
        with path.open("ab", buffering=0) as handle:
            handle.write(line)
        return True


async def append_speculative_archive(
    record: SpeculativeArchiveRecord,
    *,
    archive_dir: Path | None = None,
    archive_date: date | None = None,
) -> bool:
    """Append a losing draft without letting archive failures fail delivery."""
    selected_date = archive_date or date.today()
    path = Path(archive_dir or SPECULATIVE_ARCHIVE_DIR) / (
        f"{selected_date.isoformat()}.jsonl"
    )
    line = (
        json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    try:
        return await asyncio.to_thread(_append_line_with_size_cap, path, line)
    except Exception as exc:
        logger.warning(
            "speculative_archive_write_failed path=%s error_type=%s",
            path,
            exc.__class__.__name__,
        )
        return False
