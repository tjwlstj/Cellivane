"""Protocol framing failures are rejected before becoming worker observations."""
from pathlib import Path
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cellivane_runtime_transport import strict_line, MAX_LINE, NativeTransport


class FrameTests(unittest.TestCase):
    def test_complete_unicode_frame(self):
        self.assertEqual({"text": "안녕"}, strict_line('{"text":"안녕"}\n'.encode()))

    def test_truncated_duplicate_nonfinite_and_nonobject_frames(self):
        for raw in (b'{"kind":"result"}', b'{"id":1,"id":2}\n', b'{"time":NaN}\n', b'[]\n',
                    b'{"text":"\xff"}\n', b'\n', b' ' * MAX_LINE + b'\n'):
            with self.subTest(raw=raw[:24]):
                with self.assertRaises((ValueError, UnicodeError)):
                    strict_line(raw)


class _Stream:
    def __init__(self, write=None, close_error=False):
        self.data = bytearray()
        self.write_hook = write
        self.closed = False
        self.close_error = close_error

    def write(self, raw):
        if self.write_hook is not None:
            return self.write_hook(raw)
        self.data.extend(raw)
        return len(raw)

    def close(self):
        self.closed = True
        if self.close_error:
            raise OSError("injected pipe close")


class _Process:
    def __init__(self):
        self.stdin, self.stdout = _Stream(), _Stream()
        self.returncode = None
        self.created_suspended = self.assigned_before_resume = True
        self.primary_thread_closed, self.process_handle_closed = True, False
        self.wait_error = False
        self.terminated = False

    def wait(self, timeout):
        if self.wait_error:
            raise OSError("injected wait failure")
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def close_handles(self):
        self.process_handle_closed = True


class _Job:
    def __init__(self, release=None, error=False, confirmed=True):
        self.release = release
        self.error, self.confirmed = error, confirmed
        self.closed = False

    def close(self):
        self.closed = True
        if self.release is not None:
            self.release.set()
        if self.error:
            raise OSError("injected Job failure")
        return {"job_cleanup_confirmed": self.confirmed, "job_terminated": True,
                "job_active_processes": 0, "job_closed": True}


class TransportFaultTests(unittest.TestCase):
    def make_transport(self, root, *, timeout=.08):
        transport = NativeTransport.__new__(NativeTransport)
        transport.root = root
        transport.command = []
        transport.timeout_s = timeout
        transport._queue = queue.Queue(maxsize=4)
        transport.process, transport.job = _Process(), _Job()
        transport.reader = transport.writer = None
        transport._exchange_lock = threading.Lock()
        transport._closed = transport._failed = False
        transport.cleanup = None
        transport._stdin_log = (root / "stdin.jsonl").open("xb")
        transport._stdout_log = (root / "stdout.jsonl").open("xb")
        transport._stderr_log = (root / "stderr.log").open("xb")
        self.addCleanup(lambda: transport.close() if not transport._closed else None)
        return transport

    def test_blocked_write_deadline_kills_job_and_joins_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            released, entered = threading.Event(), threading.Event()

            def blocked(raw):
                entered.set()
                if not released.wait(2):
                    raise AssertionError("test writer was stranded")
                raise BrokenPipeError("owned worker closed")

            transport.process.stdin = _Stream(write=blocked)
            transport.job = _Job(released)
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "worker-stdin-timeout"):
                transport.exchange({"id": 1, "op": "shutdown"})
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(transport.job.closed)
            self.assertFalse(transport.writer.is_alive())
            self.assertTrue(transport.cleanup["process_handle_closed"])
            self.assertTrue(transport._failed)
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                transport.exchange({"id": 2, "op": "shutdown"})

    def test_response_wait_uses_remaining_write_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory), timeout=.25)

            def slow_write(raw):
                time.sleep(.12)
                return len(raw)

            transport.process.stdin = _Stream(write=slow_write)
            received = []

            def receive(deadline):
                received.append(deadline - time.monotonic())
                return {"kind": "stopped", "id": 1}

            with mock.patch.object(transport, "_receive", side_effect=receive):
                self.assertEqual(transport.exchange({"id": 1, "op": "shutdown"})["kind"], "stopped")
            self.assertGreater(received[0], 0)
            self.assertLess(received[0], .2)
            transport.close()

    def test_partial_pipe_writes_preserve_exact_raw_command(self):
        with tempfile.TemporaryDirectory() as directory:
            # Framing success must allow durable-log I/O and host scheduling.
            # Deadline and blocked-write tests retain their short budgets.
            transport = self.make_transport(Path(directory), timeout=2)
            captured = bytearray()

            def partial(raw):
                count = min(3, len(raw))
                captured.extend(raw[:count])
                return count

            transport.process.stdin = _Stream(write=partial)
            transport._queue.put({"kind": "stopped", "id": 1})
            transport.exchange({"op": "shutdown", "id": 1})
            self.assertEqual(captured, b'{"id":1,"op":"shutdown"}\n')
            self.assertEqual((Path(directory) / "stdin.jsonl").read_bytes(), captured)
            transport.close()

    def test_zero_write_and_response_eof_poison_and_cleanup(self):
        for fault in ("zero-write", "eof"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                transport = self.make_transport(Path(directory))
                if fault == "zero-write":
                    transport.process.stdin = _Stream(write=lambda raw: 0)
                else:
                    transport._queue.put(EOFError("worker-stdout-closed"))
                with self.assertRaises((BrokenPipeError, EOFError)):
                    transport.exchange({"id": 1, "op": "shutdown"})
                self.assertTrue(transport._failed)
                self.assertTrue(transport.cleanup["process_handle_closed"])
                self.assertTrue(transport.job.closed)

    def test_response_timeout_cleans_job_without_a_second_full_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "worker-response-timeout"):
                transport.exchange({"id": 1, "op": "shutdown"})
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(transport.cleanup["job_cleanup_confirmed"])

    def test_already_queued_reply_cannot_extend_expired_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            transport._queue.put({"kind": "stopped", "id": 1})
            with self.assertRaisesRegex(TimeoutError, "worker-response-timeout"):
                transport._receive(time.monotonic() - .01)
            self.assertTrue(transport._failed)
            self.assertEqual(transport._queue.qsize(), 1)
            transport.close()

    def test_cleanup_continues_after_job_wait_and_pipe_close_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            transport._failed = True
            transport.job = _Job(error=True)
            transport.process.wait_error = True
            transport.process.stdin.close_error = True
            reader_joined = []
            transport.reader = mock.Mock()
            transport.reader.join.side_effect = lambda timeout: reader_joined.append(True)
            transport.reader.is_alive.return_value = False
            with self.assertRaisesRegex(RuntimeError, "native-cleanup-unconfirmed"):
                transport.close()
            self.assertTrue(transport.process.terminated)
            self.assertTrue(reader_joined)
            self.assertTrue(transport.process.stdin.closed)
            self.assertTrue(transport.process.stdout.closed)
            self.assertTrue(transport.process.process_handle_closed)
            self.assertTrue(all(stream.closed for stream in (transport._stdin_log, transport._stdout_log, transport._stderr_log)))
            self.assertIn("job:OSError", transport.cleanup["error"])
            self.assertIn("process-wait:OSError", transport.cleanup["error"])
            self.assertIn("stdin-close:OSError", transport.cleanup["error"])
            with self.assertRaisesRegex(RuntimeError, "native-cleanup-unconfirmed"):
                transport.close()

    def test_active_reader_makes_cleanup_fail_even_with_confirmed_job(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            transport.reader = mock.Mock()
            transport.reader.is_alive.return_value = True
            with self.assertRaisesRegex(RuntimeError, "native-cleanup-unconfirmed"):
                transport.close()
            self.assertIn("reader:thread-still-active", transport.cleanup["error"])
            self.assertTrue(transport.process.process_handle_closed)

    def test_log_close_failure_does_not_skip_other_streams(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            transport._stdin_log.close()
            transport._stdin_log = _Stream(close_error=True)
            with self.assertRaisesRegex(RuntimeError, "native-cleanup-unconfirmed"):
                transport.close()
            self.assertTrue(transport._stdout_log.closed)
            self.assertTrue(transport._stderr_log.closed)
            self.assertIn("_stdin_log-close", transport.cleanup["error"])

    def test_concurrent_exchange_rejected_without_writing_or_poison(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(Path(directory))
            transport._exchange_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "worker-exchange-active"):
                    transport.exchange({"id": 1, "op": "shutdown"})
            finally:
                transport._exchange_lock.release()
            self.assertEqual((Path(directory) / "stdin.jsonl").read_bytes(), b"")
            self.assertFalse(transport._failed)
            transport.close()


@unittest.skipUnless(os.name == "nt", "Windows owned Job and anonymous pipe test")
class WindowsPipeDeadlineTests(unittest.TestCase):
    def test_partial_audit_open_failure_closes_every_prior_stream_before_spawn(self):
        for collision in ("stdout.jsonl", "stderr.log"):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / collision).write_bytes(b"preserve existing evidence")
                with mock.patch("cellivane_runtime_transport.lab._OwnedJob") as owned_job:
                    with self.assertRaises(FileExistsError):
                        NativeTransport(["must-not-execute"], root)
                owned_job.assert_not_called()
                self.assertEqual((root / collision).read_bytes(), b"preserve existing evidence")
                # Windows refuses renaming these Python files while an earlier
                # open handle is still live. Only files created by this test move.
                for name in ("stdin.jsonl", "stdout.jsonl"):
                    if name != collision and (root / name).exists():
                        (root / name).rename(root / (name + ".closed"))

    def test_real_nonreading_owned_child_is_terminated_after_pipe_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "nonreading-fixture.py"
            script.write_text('import time\nprint(\'{"kind":"ready"}\', flush=True)\ntime.sleep(20)\n', encoding="utf-8")
            transport = NativeTransport([sys.executable, str(script)], root, timeout_s=1)
            started = time.monotonic()
            try:
                with self.assertRaisesRegex(TimeoutError, "worker-stdin-timeout"):
                    transport.exchange({"id": 1, "op": "generate", "fixture": "x" * 20000})
                self.assertLess(time.monotonic() - started, 5)
                self.assertTrue(transport.cleanup["job_cleanup_confirmed"])
                self.assertEqual(transport.cleanup["job_active_processes"], 0)
                self.assertTrue(transport.cleanup["process_exited"])
                self.assertTrue(transport.cleanup["process_handle_closed"])
                self.assertFalse(transport.writer.is_alive())
                self.assertFalse(transport.reader.is_alive())
            finally:
                if not transport._closed:
                    transport.close()


if __name__ == "__main__": unittest.main()
