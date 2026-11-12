"""Windows-owned, suspended-before-Job-assignment NDJSON native transport.

No endpoint, existing PID, model server, or shared process is adopted. The
transport retains exact stdin/stdout/stderr locally; records can contain text.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

import cellivane_bridge_lab as lab

MAX_LINE = 256 * 1024


def strict_line(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("worker-duplicate-key")
            value[key] = item
        return value
    if not 1 <= len(raw) <= MAX_LINE or not raw.endswith(b"\n"):
        raise ValueError("worker-frame")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("worker-number")))
    if type(value) is not dict:
        raise ValueError("worker-object")
    return value


class PipeProcess(lab._SuspendedProcess):
    def __init__(self, args, env, cwd, log):
        if os.name != "nt":
            raise RuntimeError("native-runtime-windows-only")
        import _winapi
        import msvcrt
        self.api, self.args = _winapi, list(args)
        self._handle = self._thread_handle = None
        self.returncode, self.pid = None, None
        self.created_suspended = self.assigned_before_resume = False
        self.primary_thread_closed = self.process_handle_closed = False
        self.stdin = self.stdout = None
        in_read, in_write = os.pipe()
        out_read, out_write = os.pipe()
        inherited = []
        try:
            current = _winapi.GetCurrentProcess()
            for descriptor in (in_read, out_write, log.fileno()):
                inherited.append(_winapi.DuplicateHandle(current, msvcrt.get_osfhandle(descriptor), current,
                                                        0, True, _winapi.DUPLICATE_SAME_ACCESS))
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = inherited
            startup.lpAttributeList = {"handle_list": inherited}
            flags = 0x00000004 | subprocess.CREATE_NO_WINDOW | 0x00080000
            hp, ht, self.pid, _ = _winapi.CreateProcess(os.fspath(args[0]), subprocess.list2cmdline(args),
                None, None, True, flags, env, os.fspath(cwd), startup)
            self._handle, self._thread_handle = hp, ht
            self.created_suspended = True
            self.stdin, self.stdout = os.fdopen(in_write, "wb", buffering=0), os.fdopen(out_read, "rb", buffering=0)
            in_write = out_read = None
        except BaseException:
            if self._handle is not None:
                self.terminate()
                self.wait(timeout=10)
                self.close_handles()
            raise
        finally:
            for handle in inherited:
                _winapi.CloseHandle(handle)
            for descriptor in (in_read, out_write, in_write, out_read):
                if descriptor is not None:
                    os.close(descriptor)


def memory_snapshot():
    from ctypes import wintypes
    class Status(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended")]
    status = Status()
    status.length = ctypes.sizeof(status)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Status)]
    api.GlobalMemoryStatusEx.restype = wintypes.BOOL
    if not api.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"source": "GlobalMemoryStatusEx", "available_bytes": status.avail_phys, "total_bytes": status.total_phys}


class NativeTransport:
    def __init__(self, command, root, *, env=None, timeout_s=60):
        if os.name != "nt":
            raise RuntimeError("native-runtime-windows-only")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 300:
            raise ValueError("worker-timeout")
        self.root, self.command, self.timeout_s = Path(root), command, timeout_s
        self._queue = queue.Queue(maxsize=4)
        self.process = self.job = self.reader = self.writer = None
        self._exchange_lock = threading.Lock()
        self._closed, self._failed = False, False
        self.cleanup = None
        self._stdin_log = self._stdout_log = self._stderr_log = None
        started = time.perf_counter()
        try:
            self._stdin_log = (self.root / "stdin.jsonl").open("xb")
            self._stdout_log = (self.root / "stdout.jsonl").open("xb")
            self._stderr_log = (self.root / "stderr.log").open("xb")
            self.job = lab._OwnedJob()
            self.process = PipeProcess(command, env or dict(os.environ), self.root, self._stderr_log)
            self.job.assign(self.process)
            self.process.resume(self.job)
            self.reader = threading.Thread(target=self._read, name="cellivane-native-reader", daemon=True)
            self.reader.start()
            self.ready = self._receive()
            self.load_wall_s = time.perf_counter() - started
            if self.ready.get("kind") != "ready":
                raise RuntimeError("worker-not-ready")
        except BaseException:
            try:
                self.close()
            except BaseException:
                pass
            raise

    def _read(self):
        try:
            while True:
                raw = self.process.stdout.readline(MAX_LINE + 1)
                if not raw:
                    self._queue.put(EOFError("worker-stdout-closed"), timeout=2)
                    return
                self._stdout_log.write(raw)
                self._stdout_log.flush()
                os.fsync(self._stdout_log.fileno())
                value = strict_line(raw)
                self._queue.put(value, timeout=2)
        except BaseException as exc:
            try:
                self._queue.put(exc, timeout=2)
            except queue.Full:
                self._failed = True

    def _receive(self, deadline=None):
        try:
            remaining = self.timeout_s if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("worker-response-timeout")
            try:
                result = self._queue.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("worker-response-timeout") from exc
            if isinstance(result, BaseException):
                raise result
            if (self.root / "stderr.log").stat().st_size > 16 * 1024**2:
                raise RuntimeError("worker-log-limit")
            return result
        except BaseException:
            self._failed = True
            raise

    def exchange(self, command):
        if self._closed or self._failed:
            raise RuntimeError("worker-transport-unavailable")
        raw = json.dumps(command, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        if len(raw) > 32 * 1024:
            raise ValueError("worker-command-bytes")
        if not self._exchange_lock.acquire(blocking=False):
            raise RuntimeError("worker-exchange-active")
        deadline = time.monotonic() + self.timeout_s
        try:
            self._stdin_log.write(raw)
            self._stdin_log.flush()
            os.fsync(self._stdin_log.fileno())
            done = threading.Event()
            errors = []

            def write_command():
                try:
                    remaining = memoryview(raw)
                    while remaining:
                        written = self.process.stdin.write(remaining)
                        if type(written) is not int or not 0 < written <= len(remaining):
                            raise BrokenPipeError("worker-stdin-write")
                        remaining = remaining[written:]
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    done.set()

            # A synchronous Windows pipe write can block when the owned worker
            # stops reading. Keep it off the caller thread, and use the same
            # monotonic deadline for the write and its response. On failure the
            # Job is terminated below, releasing the child's pipe handles.
            self.writer = threading.Thread(target=write_command, name="cellivane-native-writer", daemon=True)
            self.writer.start()
            if not done.wait(max(0, deadline - time.monotonic())):
                raise TimeoutError("worker-stdin-timeout")
            self.writer.join()
            if errors:
                raise errors[0]
            return self._receive(deadline)
        except BaseException:
            self._failed = True
            try:
                self.close()
            except BaseException:
                # Preserve the exchange failure; the cleanup receipt separately
                # retains every failed cleanup stage and cannot report success.
                pass
            raise
        finally:
            self._exchange_lock.release()

    def close(self):
        if self._closed:
            if (self.cleanup is None or self.cleanup.get("error") or not self.cleanup.get("job_cleanup_confirmed")
                    or not self.cleanup.get("process_exited")):
                raise RuntimeError("native-cleanup-unconfirmed")
            return self.cleanup
        self._closed = True
        process = self.process
        errors, receipt = [], {}

        def attempt(label, operation):
            try:
                return operation()
            except BaseException as exc:
                errors.append(label + ":" + type(exc).__name__ + ":" + str(exc)[:256])
                return None

        # Each stage must run even when an earlier wait, pipe close, Job call,
        # audit stream or reader fails. No shared/existing process is touched.
        if process is not None and not self._failed:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            except BaseException as exc:
                errors.append("grace-wait:" + type(exc).__name__ + ":" + str(exc)[:256])
        if self.job is not None:
            result = attempt("job", self.job.close)
            if type(result) is dict:
                receipt = result
            elif result is not None:
                errors.append("job:invalid-receipt")
        if process is not None:
            if not receipt.get("job_cleanup_confirmed"):
                # The Job receipt still stays unconfirmed; this fallback only
                # avoids stranding the directly owned process on a Job error.
                attempt("owned-process-terminate", process.terminate)
            attempt("process-wait", lambda: process.wait(timeout=10))
        for label, thread in (("writer", self.writer), ("reader", self.reader)):
            if thread is not None:
                attempt(label + "-join", lambda thread=thread: thread.join(timeout=3))
                if thread.is_alive():
                    errors.append(label + ":thread-still-active")
        if process is not None:
            for label in ("stdin", "stdout"):
                stream = getattr(process, label, None)
                if stream is not None:
                    attempt(label + "-close", stream.close)
            attempt("process-handles", process.close_handles)
        for label in ("_stdin_log", "_stdout_log", "_stderr_log"):
            stream = getattr(self, label, None)
            if stream is not None:
                attempt(label + "-close", stream.close)
        error = ";".join(errors) or None
        self.cleanup = {**receipt, "process_exited": process is not None and process.returncode is not None,
                        "returncode": process.returncode if process is not None else None, "error": error,
                        **{key: getattr(process, key, False) for key in ("created_suspended", "assigned_before_resume", "primary_thread_closed", "process_handle_closed")}}
        if error or not self.cleanup.get("job_cleanup_confirmed") or not self.cleanup["process_exited"]:
            raise RuntimeError("native-cleanup-unconfirmed:" + str(error))
        return self.cleanup
