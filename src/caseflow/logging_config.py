"""Logging: concise console output plus a per-run log file, with a redaction filter as a
second line of defence (the code never logs document text, contact details or keys)."""

from __future__ import annotations

import logging
from pathlib import Path

from .llm_client import sanitize


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(record.getMessage(), limit=2000)
        record.args = ()
        return True


def configure_logging(level: str, log_file: Path | None) -> None:
    # pypdf reports recoverable parse problems as warnings; we report them per file instead.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    root = logging.getLogger("caseflow")
    root.setLevel(level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    console.addFilter(RedactingFilter())
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s"))
        fh.addFilter(RedactingFilter())
        root.addHandler(fh)
