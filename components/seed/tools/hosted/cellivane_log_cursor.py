"""Bounded, append-only UTF-8 log guard with incremental evidence receipts.

Only newly appended bytes are hashed/decoded. Two bounded tail-anchor reads per
poll detect observed rewrites; stable file identity detects replacement. A later
independent reader must compare the final raw log to every chunk/prefix digest:
anchors do not attest that unobserved bytes were never modified. ``finish`` must
be called after the owned writer has exited and its output has been drained.

The scan counter includes each new byte and each re-examined UTF-8 scan tail.
The read counter includes new bytes and actual anchor reads. Thus work is
O(B + P*K), with fixed chunk/tail/anchor bounds, rather than repeated full reads.
No producer/runtime/verifier module is imported.
"""
from __future__ import annotations

import codecs
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import time


class LogCursorError(RuntimeError):
    """The log guard failed; this cursor cannot be resumed."""


# Same fatal vocabulary as the frozen soak reader. The sole unbounded regex
# branch, cudamalloc.*failed, is recognized by ordered per-line token state.
_FINITE = re.compile(
    r"\blevel=(?:ERROR|FATAL)\b|out of memory|cuda error|"
    r"cublas_status_alloc_failed|panic:|fatal error:|"
    r"failed to (?:allocate|load|initialize)|error loading model|"
    r"runner process has terminated", re.I)
_ORDERED = re.compile(r"cudamalloc|failed|\n", re.I)
_WORD = re.compile(r"\w")
_TAIL_CHARS = 64  # longer than every finite fatal token, including boundaries


class IncrementalLog:
    """Guard one existing regular file; failures poison and close the cursor.

    Receipts cover [start,end) and hash exactly those raw new bytes. Empty polls
    hash b'' and still advance seq. carry_bytes counts retained UTF-8 scan-tail
    bytes plus at most three pending decoder bytes, not the line length counter.
    A Unicode word boundary after level=ERROR/FATAL is delayed until the next
    decoded character or finish; a partial UTF-8 sequence is likewise pending.
    """

    def __init__(self, path, max_bytes=16 * 1024**2, line_limit=64 * 1024,
                 anchor_bytes=256, chunk_bytes=64 * 1024):
        for name, value in (("max_bytes", max_bytes), ("line_limit", line_limit),
                            ("anchor_bytes", anchor_bytes), ("chunk_bytes", chunk_bytes)):
            if type(value) is not int or not 1 <= value <= 2**31 - 1:
                raise ValueError("log-cursor-invalid-" + name)
        self.path = Path(path)
        self.max_bytes, self.line_limit = max_bytes, line_limit
        self.anchor_bytes, self.chunk_bytes = anchor_bytes, chunk_bytes
        self._file = None
        self._closed = self._failed = self._finished = False
        self._offset = self._seq = self._read = self._scanned = self._line_bytes = 0
        self._prefix = sha256()
        self._anchor = b""
        self._tail = ""
        self._cuda_seen = self._pending_level = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        try:
            self._file = self.path.open("rb", buffering=0)
            info = os.fstat(self._file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise LogCursorError("log-cursor-not-regular")
            self._identity = (info.st_dev, info.st_ino)
            self._size()
        except Exception as exc:
            self._failed = True
            self.close()
            if isinstance(exc, OSError):
                raise LogCursorError("log-cursor-" + type(exc).__name__) from exc
            raise

    def _size(self):
        opened = os.fstat(self._file.fileno())
        named = self.path.stat()
        if ((opened.st_dev, opened.st_ino) != self._identity
                or (named.st_dev, named.st_ino) != self._identity):
            raise LogCursorError("log-cursor-identity-changed")
        if opened.st_size < self._offset or named.st_size < self._offset:
            raise LogCursorError("log-cursor-truncated")
        if opened.st_size > self.max_bytes or named.st_size > self.max_bytes:
            raise LogCursorError("log-cursor-size-limit")
        return opened.st_size

    def _check_anchor(self):
        if self._anchor:
            self._file.seek(self._offset - len(self._anchor))
            observed = self._file.read(len(self._anchor))
            self._read += len(observed)
            if observed != self._anchor:
                raise LogCursorError("log-cursor-anchor-changed")

    def _scan_text(self, text, final=False):
        if self._pending_level:
            if text and not _WORD.match(text[0]):
                raise LogCursorError("fatal-backend-log")
            if text:
                self._pending_level = False
            elif final:
                raise LogCursorError("fatal-backend-log")
        boundary = len(self._tail)
        combined = self._tail + text
        for match in _FINITE.finditer(combined):
            if match.end() <= boundary:
                continue
            # An apparent EOF word boundary can disappear on the next append.
            if match.group().lower().startswith("level=") and match.end() == len(combined) and not final:
                self._pending_level = True
            else:
                raise LogCursorError("fatal-backend-log")
        for match in _ORDERED.finditer(combined):
            if match.end() <= boundary:
                continue
            token = match.group().lower()
            if token == "\n":
                self._cuda_seen = False
            elif token == "cudamalloc":
                self._cuda_seen = True
            elif self._cuda_seen:
                raise LogCursorError("fatal-backend-log")
        self._tail = combined[-_TAIL_CHARS:]

    def _consume(self, raw):
        self._scanned += len(raw) + len(self._tail.encode("utf-8"))
        parts = raw.split(b"\n")
        for index, part in enumerate(parts):
            self._line_bytes += len(part)
            if self._line_bytes > self.line_limit:
                raise LogCursorError("log-cursor-line-limit")
            if index != len(parts) - 1:
                self._line_bytes = 0
        self._scan_text(self._decoder.decode(raw, final=False))

    def _poll(self, final):
        began = time.perf_counter()
        if self._failed or self._closed or self._finished:
            raise LogCursorError("log-cursor-unavailable")
        start = self._offset
        chunk_hash = sha256()
        try:
            end = self._size()
            self._check_anchor()
            while True:
                self._file.seek(self._offset)
                while self._offset < end:
                    count = min(self.chunk_bytes, end - self._offset)
                    raw = self._file.read(count)
                    self._read += len(raw)
                    if len(raw) != count:
                        raise LogCursorError("log-cursor-short-read")
                    self._consume(raw)
                    self._prefix.update(raw)
                    chunk_hash.update(raw)
                    self._offset += len(raw)
                    self._anchor = (self._anchor + raw)[-self.anchor_bytes:]
                observed_end = self._size()
                if not final or observed_end == self._offset:
                    break
                end = observed_end
            self._check_anchor()
            if final:
                self._scanned += len(self._tail.encode("utf-8"))
                self._scan_text(self._decoder.decode(b"", final=True), final=True)
                self._finished = True
            self._seq += 1
            return {"seq": self._seq, "start": start, "end": self._offset,
                    "new_bytes": self._offset - start, "chunk_sha256": chunk_hash.hexdigest(),
                    "prefix_sha256": self._prefix.hexdigest(), "bytes_read_total": self._read,
                    "bytes_scanned_total": self._scanned,
                    "carry_bytes": len(self._tail.encode("utf-8")) + len(self._decoder.getstate()[0]),
                    "poll_wall_s": time.perf_counter() - began, "fatal": False}
        except Exception as exc:
            self._failed = True
            self.close()
            if isinstance(exc, LogCursorError):
                raise
            if isinstance(exc, (OSError, UnicodeError)):
                raise LogCursorError("log-cursor-" + type(exc).__name__) from exc
            raise

    def poll(self):
        return self._poll(False)

    def finish(self):
        return self._poll(True)

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None
        self._closed = True
