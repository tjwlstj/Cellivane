"""Host-only cursor guards; no engine, network or model execution."""
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("cellivane_log_cursor", Path(__file__).parents[1] / "cellivane_log_cursor.py")
cursor_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cursor_module)
IncrementalLog = cursor_module.IncrementalLog
LogCursorError = cursor_module.LogCursorError
REFERENCE_FATAL = re.compile(r"\blevel=(?:ERROR|FATAL)\b|out of memory|cuda error|cudamalloc.*failed|cublas_status_alloc_failed|panic:|fatal error:|failed to (?:allocate|load|initialize)|error loading model|runner process has terminated", re.I)
RECEIPT_KEYS = {"seq", "start", "end", "new_bytes", "chunk_sha256", "prefix_sha256", "bytes_read_total", "bytes_scanned_total", "carry_bytes", "poll_wall_s", "fatal"}


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "backend.log"
        self.path.write_bytes(b"")

    def make(self, **kwargs):
        cursor = IncrementalLog(self.path, **kwargs)
        self.addCleanup(cursor.close)
        return cursor

    def append(self, raw):
        with self.path.open("ab") as stream:
            stream.write(raw)

    def test_empty_receipts_and_finish_lifecycle(self):
        cursor = self.make()
        first = cursor.poll()
        final = cursor.finish()
        self.assertEqual(set(first), RECEIPT_KEYS)
        self.assertEqual(first["seq"], 1)
        self.assertEqual(final["seq"], 2)
        self.assertEqual(first["chunk_sha256"], sha256(b"").hexdigest())
        self.assertEqual(first["prefix_sha256"], sha256(b"").hexdigest())
        self.assertIs(first["fatal"], False)
        self.assertEqual(first["new_bytes"], 0)
        self.assertGreaterEqual(first["poll_wall_s"], 0)
        for method in (cursor.poll, cursor.finish):
            with self.assertRaisesRegex(LogCursorError, "unavailable"):
                method()
        cursor.close()
        cursor.close()

    def test_chunk_and_prefix_raw_hashes_contiguous_offsets(self):
        cursor = self.make(chunk_bytes=3, anchor_bytes=4)
        all_bytes = b""
        offset = 0
        for seq, raw in enumerate((b"abc\r", b"\n", "한글🙂\n".encode(), b"tail"), 1):
            self.append(raw)
            all_bytes += raw
            row = cursor.poll()
            self.assertEqual((row["seq"], row["start"], row["end"], row["new_bytes"]), (seq, offset, len(all_bytes), len(raw)))
            self.assertEqual(row["chunk_sha256"], sha256(raw).hexdigest())
            self.assertEqual(row["prefix_sha256"], sha256(all_bytes).hexdigest())
            self.assertLessEqual(row["bytes_read_total"], len(all_bytes) + 2 * seq * 4)
            self.assertLessEqual(row["carry_bytes"], 259)
            offset = len(all_bytes)
        self.assertEqual(cursor.finish()["prefix_sha256"], sha256(all_bytes).hexdigest())

    def test_all_fatal_vocabulary_at_every_byte_split(self):
        texts = ("level=ERROR ", "LEVEL=FATAL ", "out of memory", "CUDA error", "cudamalloc -- failed",
                 "cublas_status_alloc_failed", "panic:", "fatal error:", "failed to allocate", "failed to load",
                 "failed to initialize", "error loading model", "runner process has terminated")
        for text in texts:
            self.assertIsNotNone(REFERENCE_FATAL.search(text))
            raw = text.encode()
            for split in range(len(raw) + 1):
                with self.subTest(text=text, split=split):
                    self.path.write_bytes(b"")
                    cursor = IncrementalLog(self.path, chunk_bytes=3)
                    try:
                        detected = False
                        for part in (raw[:split], raw[split:]):
                            self.append(part)
                            try:
                                cursor.poll()
                            except LogCursorError:
                                detected = True
                                break
                        if not detected:
                            with self.assertRaisesRegex(LogCursorError, "fatal"):
                                cursor.finish()
                    finally:
                        cursor.close()

    def test_fatal_every_single_byte_append(self):
        cursor = self.make(chunk_bytes=1)
        for byte in b"safe\nrunner process has terminate":
            self.append(bytes((byte,)))
            cursor.poll()
        self.append(b"d")
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.poll()

    def test_utf8_four_byte_codepoint_at_every_split(self):
        raw = "한🙂글\r\n안녕".encode()
        for split in range(len(raw) + 1):
            with self.subTest(split=split):
                self.path.write_bytes(b"")
                cursor = IncrementalLog(self.path, chunk_bytes=1)
                try:
                    self.append(raw[:split]); cursor.poll()
                    self.append(raw[split:]); row = cursor.finish()
                    self.assertEqual(row["prefix_sha256"], sha256(raw).hexdigest())
                finally:
                    cursor.close()

    def test_invalid_utf8_poisoned(self):
        cursor = self.make()
        self.append(b"safe\n\xff")
        with self.assertRaisesRegex(LogCursorError, "UnicodeDecodeError"):
            cursor.poll()
        with self.assertRaisesRegex(LogCursorError, "unavailable"):
            cursor.poll()

    def test_incomplete_utf8_rejected_only_on_finish(self):
        cursor = self.make()
        self.append(b"safe\n\xf0\x9f")
        row = cursor.poll()
        self.assertGreaterEqual(row["carry_bytes"], 2)
        with self.assertRaisesRegex(LogCursorError, "UnicodeDecodeError"):
            cursor.finish()

    def test_level_word_boundary_delayed_until_known(self):
        cursor = self.make()
        self.append(b"level=ERROR"); cursor.poll()
        self.append(b"s and level=FATAL"); cursor.poll()
        self.append(b"_not and safe\n"); cursor.finish()

    def test_level_final_eof_is_fatal(self):
        cursor = self.make()
        self.append(b"level=ERROR"); cursor.poll()
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.finish()

    def test_level_boundary_across_empty_poll(self):
        cursor = self.make()
        self.append(b"level=FATAL"); cursor.poll(); cursor.poll()
        self.append(b" ")
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.poll()

    def test_unicode_word_boundary_matches_reference(self):
        cursor = self.make(chunk_bytes=1)
        raw = "한level=ERROR글 level=FATAL🙂".encode()
        self.assertIsNotNone(REFERENCE_FATAL.search(raw.decode()))
        self.append(raw[:-4]); cursor.poll()
        self.append(raw[-4:])
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.poll()

    def test_cuda_wildcard_beyond_tail(self):
        cursor = self.make(chunk_bytes=17)
        self.append(b"cudamalloc " + b"x" * 4096); cursor.poll()
        self.append(b" FAILED")
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.poll()

    def test_cuda_wildcard_crosses_cr_but_not_lf(self):
        cursor = self.make()
        self.append(b"cudamalloc\nfailed\nfailed cudamalloc "); cursor.poll()
        self.append(b"still fine "); cursor.poll()
        self.append(b"\rfailed")
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.poll()

    def test_prior_failed_before_cudamalloc_not_replayed(self):
        cursor = self.make()
        self.append(b"failed cudamalloc "); cursor.poll()
        self.append(b"ordinary suffix\n"); cursor.finish()

    def test_harmless_failed_zero_and_fatal_token_prefixes(self):
        cursor = self.make(chunk_bytes=1)
        raw = b"failed=0 level=ERRORS level=FATAL_more allocated=ok\n"
        self.assertIsNone(REFERENCE_FATAL.search(raw.decode()))
        self.append(raw); cursor.finish()

    def test_fatal_after_success_markers_and_without_newline(self):
        cursor = self.make()
        self.append(b"PASS ready=1\n"); cursor.poll()
        self.append(b"out of memory")
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.finish()

    def test_fatal_after_long_unicode_context_and_tail_cut(self):
        cursor = self.make(chunk_bytes=5)
        self.append(("한글" * 100 + "cuda error").encode())
        with self.assertRaisesRegex(LogCursorError, "fatal"):
            cursor.poll()

    def test_truncate_rejected(self):
        cursor = self.make()
        self.append(b"123456789"); cursor.poll()
        self.path.write_bytes(b"12")
        with self.assertRaisesRegex(LogCursorError, "truncated"):
            cursor.poll()

    def test_truncate_and_regrow_rejected_by_anchor(self):
        cursor = self.make(anchor_bytes=4)
        self.append(b"abcdefgh"); cursor.poll()
        self.path.write_bytes(b"ABCDefgh-more".replace(b"efgh", b"EFGH"))
        with self.assertRaisesRegex(LogCursorError, "anchor"):
            cursor.poll()

    def test_same_size_tail_rewrite_rejected(self):
        cursor = self.make(anchor_bytes=4)
        self.append(b"abcdefgh"); cursor.poll()
        with self.path.open("r+b") as stream:
            stream.seek(7); stream.write(b"X")
        with self.assertRaisesRegex(LogCursorError, "anchor"):
            cursor.poll()

    def test_replacement_identity_rejected(self):
        cursor = self.make()
        self.append(b"safe"); cursor.poll()
        other = self.path.with_name("replacement.log")
        other.write_bytes(b"safe")
        observed = other.stat()
        with patch.object(type(cursor.path), "stat", return_value=observed):
            with self.assertRaisesRegex(LogCursorError, "identity"):
                cursor.poll()

    def test_nonanchor_rewrite_retains_conflicting_prefix_evidence(self):
        # The online anchor is deliberately bounded. A final independent raw
        # replay, not this cursor, detects a rewrite outside its observed tail.
        cursor = self.make(anchor_bytes=4)
        self.append(b"abcdefgh"); cursor.poll()
        with self.path.open("r+b") as stream:
            stream.write(b"X")
        row = cursor.finish()
        self.assertNotEqual(row["prefix_sha256"], sha256(self.path.read_bytes()).hexdigest())

    def test_size_limit_exact_and_plus_one(self):
        cursor = self.make(max_bytes=8)
        self.append(b"12345678"); cursor.poll()
        self.append(b"9")
        with self.assertRaisesRegex(LogCursorError, "size-limit"):
            cursor.poll()

    def test_line_limit_exact_and_plus_one_across_polls(self):
        cursor = self.make(line_limit=4)
        self.append(b"1234"); cursor.poll()
        self.append(b"5")
        with self.assertRaisesRegex(LogCursorError, "line-limit"):
            cursor.poll()

    def test_line_limit_resets_only_on_lf(self):
        cursor = self.make(line_limit=4, chunk_bytes=1)
        self.append(b"1234\n123\r\n1234"); cursor.finish()

    def test_line_limit_counts_utf8_bytes(self):
        cursor = self.make(line_limit=5)
        self.append("한글".encode())
        with self.assertRaisesRegex(LogCursorError, "line-limit"):
            cursor.poll()

    def test_initial_limit_and_missing_file_rejected(self):
        self.path.write_bytes(b"123456789")
        with self.assertRaisesRegex(LogCursorError, "size-limit"):
            IncrementalLog(self.path, max_bytes=8)
        with self.assertRaisesRegex(LogCursorError, "FileNotFoundError"):
            IncrementalLog(self.path.with_name("missing"))

    def test_short_read_fails_closed(self):
        cursor = self.make()
        self.append(b"safe\n")
        real = cursor._file
        class ShortFile:
            def fileno(self): return real.fileno()
            def seek(self, *args): return real.seek(*args)
            def read(self, count): return real.read(max(0, count - 1))
            def close(self): return real.close()
        cursor._file = ShortFile()
        with self.assertRaisesRegex(LogCursorError, "short-read"):
            cursor.poll()

    def test_finish_drains_append_observed_at_first_eof(self):
        cursor = self.make(chunk_bytes=2)
        self.append(b"a\n")
        original = cursor._size
        calls = 0
        def grew():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.append(b"b\n")
            return original()
        with patch.object(cursor, "_size", side_effect=grew):
            row = cursor.finish()
        self.assertEqual(row["end"], 4)
        self.assertEqual(row["chunk_sha256"], sha256(b"a\nb\n").hexdigest())

    def test_work_counters_linear_in_new_bytes_and_polls(self):
        def run(count):
            self.path.write_bytes(b"")
            cursor = IncrementalLog(self.path, anchor_bytes=16, chunk_bytes=128)
            try:
                raw = ("한글🙂 safe " * 5 + "\n").encode()
                for _ in range(count):
                    self.append(raw)
                    row = cursor.poll()
                final = cursor.finish()
                total = len(raw) * count
                polls = count + 1
                reads = count * ((len(raw) + 127) // 128)
                self.assertEqual(final["end"], total)
                self.assertLessEqual(final["bytes_read_total"], total + 2 * polls * 16)
                self.assertLessEqual(final["bytes_scanned_total"], total + (reads + 1) * 256)
                return final
            finally:
                cursor.close()
        one, two = run(100), run(200)
        self.assertLessEqual(two["bytes_read_total"], one["bytes_read_total"] * 2 + 32)
        self.assertLessEqual(two["bytes_scanned_total"], one["bytes_scanned_total"] * 2 + 256)

    def test_empty_polls_read_only_bounded_anchors(self):
        cursor = self.make(anchor_bytes=7)
        self.append(b"safe ordinary\n"); cursor.poll()
        for _ in range(100):
            row = cursor.poll()
            self.assertEqual(row["new_bytes"], 0)
            self.assertLessEqual(row["bytes_read_total"], row["end"] + 2 * row["seq"] * 7)

    def test_invalid_numeric_configuration_rejected(self):
        for name in ("max_bytes", "line_limit", "anchor_bytes", "chunk_bytes"):
            for value in (True, False, 0, -1, 1.0, float("nan"), float("inf"), "64", None):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        IncrementalLog(self.path, **{name: value})

    def test_close_prevents_admission(self):
        cursor = self.make()
        cursor.close()
        with self.assertRaisesRegex(LogCursorError, "unavailable"):
            cursor.poll()


if __name__ == "__main__":
    unittest.main()
