"""Cross-process, non-queuing locks for local machine index mutations."""

import fcntl
import os
from contextlib import contextmanager

from fastapi import HTTPException

from newton.config import settings


@contextmanager
def machine_index(machine_id: str):
    """Serialize index use and deletion for one already-authorized machine.

    Args:
        machine_id: Persisted UUID, never an unvalidated path from the caller.

    Raises:
        HTTPException: Another process is already working on this machine index.

    Nonblocking acquisition prevents a queued question from outliving its lease.
    All local server processes must share the configured private data directory.
    """
    root = settings.data_dir.parent / "locks"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(root / f"{machine_id}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(
                409, "This machine's evidence index is busy; try again later."
            ) from None
        yield
