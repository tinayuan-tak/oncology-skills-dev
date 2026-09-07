"""Run log — tee stdout+stderr to `<out>/run.log` for development + provenance.

Every wired skill already narrates its backend to stdout/stderr (card resolution,
dependency-status behavior, verdict, figure emission, warnings). That output is
transient and untimestamped. `install_run_log` TEES both streams to `<out>/run.log`,
stamping each complete line with a UTC timestamp + `OUT`/`ERR` tag, so the same
narration becomes a durable, greppable audit trail that travels with the artifact
tree. Live terminal output is preserved byte-for-byte — the tee only ADDS a file copy.

Design notes:
- **Best-effort.** A failure to open/write the log degrades to a WARN and the run
  continues with the streams untouched. Verdict-inert: capturing output cannot change
  a deterministic spine.
- **Idempotent + clobber-safe.** A harness that execs a skill and calls its entry
  point more than once in one process (the test suites do) never stacks tees:
  `install_run_log` tears down a prior tee first. Teardown only unwraps a stream that
  is STILL our tee — if something downstream (e.g. pytest's `capsys`) swapped the
  stream in the meantime, we leave it alone rather than clobber it.
- **Flush per line** so `tail -f <out>/run.log` follows a run live and the file is
  complete on disk even if the process is killed before a clean close.
"""

from __future__ import annotations

import atexit
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Module-global install state. Holds the open log file, the original streams we wrapped,
# and the tee objects we installed (so teardown can tell OUR tee from a later swap).
_STATE: dict = {
    "file": None,
    "stdout_orig": None,
    "stdout_tee": None,
    "stderr_orig": None,
    "stderr_tee": None,
    "atexit": False,
}


class _TeeStream:
    """Wrap a text stream, mirroring writes to a shared log file with per-line stamps.

    The original stream is written first (live output unchanged); each COMPLETE line is
    then copied to `logfile`, prefixed `<ISO8601-UTC> <tag> `. Partial lines are buffered
    until their newline so a stamp never lands mid-line. A shared lock guards the buffer
    because the sub-skill fan-out writes from worker threads.
    """

    def __init__(self, orig, logfile, tag: str, lock: threading.Lock):
        self._orig = orig
        self._log = logfile
        self._tag = tag
        self._lock = lock
        self._buf = ""

    def write(self, s: str) -> int:
        n = self._orig.write(s)
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                try:
                    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    self._log.write(f"{ts} {self._tag} {line}\n")
                    self._log.flush()
                except (ValueError, OSError):
                    pass  # log closed/failed — never disturb the real stream
        return n

    def flush(self) -> None:
        self._orig.flush()
        try:
            self._log.flush()
        except (ValueError, OSError):
            pass

    def __getattr__(self, name):
        # Delegate isatty(), fileno(), encoding, … to the wrapped stream.
        return getattr(self._orig, name)


def restore_run_log() -> None:
    """Uninstall the tee and close the log file. Idempotent and clobber-safe.

    A stream is unwrapped ONLY if it is still the exact tee we installed; if it was
    swapped since (e.g. a fresh pytest `capsys`), we leave the current stream in place.
    """
    st = _STATE
    for name in ("stdout", "stderr"):
        cur = getattr(sys, name)
        tee = st[f"{name}_tee"]
        if tee is not None and cur is tee:
            setattr(sys, name, st[f"{name}_orig"])
        st[f"{name}_tee"] = None
        st[f"{name}_orig"] = None
    if st["file"] is not None:
        try:
            st["file"].flush()
            st["file"].close()
        except (ValueError, OSError):
            pass
        st["file"] = None


def install_run_log(out_dir, *, header: Optional[dict] = None) -> bool:
    """Tee stdout+stderr to `<out_dir>/run.log` for the remainder of the run.

    Args:
        out_dir: directory that receives run.log (created if absent).
        header: optional ordered key→value pairs written as `# key: value` comment lines
            after the standard header (e.g. skill name/version).

    Returns True if the tee was installed, False if logging was skipped (best-effort).
    """
    restore_run_log()  # tear down any tee left by a previous in-process run
    out_dir = Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        f = open(out_dir / "run.log", "w", encoding="utf-8")
    except OSError as e:
        print(f"[run-log] WARN: could not open {out_dir}/run.log ({e}); continuing without a run log.", file=sys.stderr)
        return False
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    f.write("# run log\n")
    for k, v in (header or {}).items():
        f.write(f"# {k}: {v}\n")
    f.write(f"# started_at: {started}\n# argv: {' '.join(sys.argv)}\n\n")
    f.flush()
    lock = threading.Lock()
    _STATE["file"] = f
    _STATE["stdout_orig"] = sys.stdout
    _STATE["stderr_orig"] = sys.stderr
    _STATE["stdout_tee"] = _TeeStream(sys.stdout, f, "OUT", lock)
    _STATE["stderr_tee"] = _TeeStream(sys.stderr, f, "ERR", lock)
    sys.stdout = _STATE["stdout_tee"]
    sys.stderr = _STATE["stderr_tee"]
    if not _STATE["atexit"]:
        atexit.register(restore_run_log)  # flush+close on interpreter exit (idempotent)
        _STATE["atexit"] = True
    return True
