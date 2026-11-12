"""Single-writer execution of one durably admitted request.

The daemon owns authentication, one-active-request/event capacity, live source
and binding checks, and independent backend terminal verification. This object
owns only its prepared worker and durable question transitions. It never stops
the backend, adopts a PID, retries a request, or restores a live task from disk.
The internal messages fixture reuses this lifetime without inheriting MAIN
management or backend stop authority.
"""
from __future__ import annotations

import copy
import threading
import time

from . import async_inference
from .request_state import RequestState, require, same


class RequestExecutionFailure(RuntimeError):
    """The caller must end this producer; an uncertain transition is not retried."""


class RequestExecution:
    """Persist acceptance before dispatch and cancellation before signalling.

save(envelope) must durably store the copied record or raise. complete(record)
is the daemon's once-only source/resource finalizer. A finalizer or persistence
failure poisons this object; it cannot dispatch, finalize or write again. The
caller still owns the obligation to terminate its failed producer lifetime.
"""

    def __init__(self, *, save, complete, request_id, owner, config, source,
                 management, space_context, prompt, backend_expected,
                 clock=time.monotonic_ns):
        prepared = async_inference.prepare(config, prompt, request_id=request_id,
            backend_descriptor=backend_expected['descriptor'],
            backend_capture_kind=backend_expected['capture_kind'], space_context=space_context)
        state = RequestState(request_id=request_id, owner=owner, config=config,
            source=source, management=management, space_context=space_context,
            prompt=prompt, backend_expected=backend_expected, accepted_ns=clock())
        self._admit(save=save, complete=complete, clock=clock, prepared=prepared, state=state,
                    backend_stop_supported=True)

    @classmethod
    def for_messages(cls, *, save, complete, request_id, owner, deployment, capabilities, messages,
                     streaming=False, require_usage=False, clock=time.monotonic_ns):
        """Internal P0 fixture entry; does not register a second MAIN or expand capacity."""
        from aios_engines.fixtures import prepare_messages, MessagesRequestState
        prepared = prepare_messages(deployment, capabilities, messages, request_id=request_id,
            streaming=streaming, require_usage=require_usage)
        state = MessagesRequestState(owner=owner, prepared=prepared, accepted_ns=clock())
        execution = cls.__new__(cls)
        execution._admit(save=save, complete=complete, clock=clock, prepared=prepared, state=state,
                         backend_stop_supported=False)
        return execution

    @classmethod
    def for_ollama(cls, *, save, complete, request_id, owner, deployment, capabilities, messages,
                   port, streaming=False, require_usage=False, clock=time.monotonic_ns):
        """Internal P1a attached loopback adapter; no public MAIN or stop authority."""
        from aios_engines.ollama_chat import prepare_ollama, OllamaRequestState
        prepared = prepare_ollama(deployment, capabilities, messages, request_id=request_id,
            port=port, streaming=streaming, require_usage=require_usage)
        state = OllamaRequestState(owner=owner, prepared=prepared, accepted_ns=clock())
        execution = cls.__new__(cls)
        execution._admit(save=save, complete=complete, clock=clock, prepared=prepared, state=state,
                         backend_stop_supported=False)
        return execution

    @classmethod
    def for_engine_messages(cls, *, save, complete, request_id, owner, deployment, capabilities,
                            messages, port=None, streaming=False, require_usage=False,
                            clock=time.monotonic_ns):
        """Closed internal selector; unknown declarations never fall back to another adapter."""
        from aios_engines.contracts import Deployment
        from aios_engines.fixtures import SPEC as fixture_spec
        if type(deployment) is not Deployment:
            raise ValueError('engine-messages-deployment')
        options = dict(save=save, complete=complete, request_id=request_id, owner=owner,
            deployment=deployment, capabilities=capabilities, messages=messages,
            streaming=streaming, require_usage=require_usage, clock=clock)
        if deployment.engine == fixture_spec:
            if port is not None:
                raise ValueError('engine-fixture-endpoint')
            return cls.for_messages(**options)
        if deployment.engine.adapter_kind == 'ollama-chat':
            from aios_engines.ollama_chat import SPEC as ollama_spec
            if deployment.engine == ollama_spec:
                return cls.for_ollama(**options, port=port)
        raise ValueError('engine-messages-deployment')

    def _admit(self, *, save, complete, clock, prepared, state, backend_stop_supported):
        """Initialize the shared lifetime after its closed factory validates admission."""
        self._thread = threading.get_ident()
        self._save = save
        self._complete = complete
        self._clock = clock
        self._pending = None
        self._worker = None
        self._backend_observation = None
        self._failed = None
        self._finalized = False
        self._closed = False
        self._backend_stop_supported = backend_stop_supported
        self._prepared, self._state = prepared, state
        require(self._prepared.request_body.decode('utf-8') == self._state.snapshot()['request_body'],
                'prepared-mismatch')
        self._persist()

    def _check(self):
        require(threading.get_ident() == self._thread, 'writer-mismatch')
        if self._failed is not None:
            raise RequestExecutionFailure('request-execution-failed')

    def snapshot(self):
        require(threading.get_ident() == self._thread, 'writer-mismatch')
        return copy.deepcopy({'schema_version': 1, 'request_state': self._state.snapshot(),
            'receipt_template': self._prepared.receipt_template,
            'worker_progress': self._worker, 'control_failure': self._failed,
            'backend_observation': self._backend_observation})

    @property
    def terminal(self):
        return self._state.terminal and self._finalized and self._failed is None

    def _fail(self, code, exc):
        # Never turn a failure after invoking start() into NOT_STARTED. Popen
        # may have returned and its worker may already have sent HTTP bytes.
        self._failed = {'code': code, 'worker_cleanup_confirmed': None,
                        'start_evidence': copy.deepcopy(getattr(exc, 'evidence', None))}
        if self._pending is None:
            self._pending = getattr(exc, 'owned_worker', None)
        if self._pending is not None:
            try:
                self._pending.close()
                self._worker = self._pending.poll()
                self._failed['worker_cleanup_confirmed'] = self._pending.closed
            except BaseException:
                self._failed['worker_cleanup_confirmed'] = False
        raise RequestExecutionFailure(code) from exc

    def _persist(self):
        try:
            self._save(self.snapshot())
        except BaseException as exc:
            self._fail('request-persistence-failed', exc)

    def _finish(self):
        if self._finalized:
            return
        # The terminal record is durable before counters/resources are closed.
        # Any partial finalizer failure ends the producer instead of retrying
        # an increment or resource attribution with unknown prior effects.
        self._finalized = True
        try:
            self._complete(self._state.snapshot())
            if self._pending is not None:
                self._pending.close()
        except BaseException as exc:
            self._fail('request-finalization-failed', exc)

    def dispatch(self):
        self._check()
        require(not self._closed and self._pending is None, 'dispatch-state')
        if self._state.terminal:
            require(self._state.snapshot()['model_outcome'] == 'NOT_STARTED', 'dispatch-state')
            return self.snapshot()
        require(self._state.snapshot()['phase'] == 'ACCEPTED', 'dispatch-state')
        try:
            self._pending = async_inference.start(self._prepared)
            self._worker = self._pending.poll()
            self._state.mark_running(self._worker['worker_pid'], now_ns=self._clock())
        except BaseException as exc:
            self._fail('request-dispatch-uncertain', exc)
        self._persist()
        return self.poll()

    def poll(self):
        self._check()
        if self._pending is None or self._state.terminal:
            return self.snapshot()
        try:
            progress = self._pending.poll()
            require(progress['request_id'] == self._state.snapshot()['request_id'], 'worker-request')
            self._worker = progress
            if progress['done']:
                self._state.record_worker_exit(progress['worker_pid'], progress['worker_exit_code'],
                    receipt=progress['receipt'], now_ns=self._clock())
                self._persist()
                self._finish()
        except RequestExecutionFailure:
            raise
        except BaseException as exc:
            self._fail('request-worker-uncertain', exc)
        return self.snapshot()

    def cancel(self, observed_owner):
        self._check()
        self._state.check_owner(observed_owner)
        # Observe an already-completed result first; a late cancel must not
        # discard an answer or stop a replacement worker/backend.
        self.poll()
        outcome = self._state.request_cancel(observed_owner, now_ns=self._clock())
        if outcome != 'ACCEPTED':
            return {'outcome': outcome, 'record': self.snapshot()}
        self._persist()
        if self._pending is None:
            self._state.finish_without_dispatch('cancel-before-dispatch', now_ns=self._clock())
            self._persist()
            self._finish()
        else:
            try:
                self._pending.request_cancel()
            except BaseException as exc:
                self._fail('request-cancel-uncertain', exc)
            self.poll()
        return {'outcome': outcome, 'record': self.snapshot()}

    def observe_backend_stop(self, observed_owner, verify_stopped):
        """Call the daemon's independent held-lifetime + terminal verifier.

        verify_stopped(expected) must validate the exact admission generation,
        both retained pidfd deaths and terminal artifacts. A caller-supplied
        STOPPED dict or listener health is not that observation. Return both
        backend_stop and evidence (including the exact expected admission).
        """
        self._check()
        self._state.check_owner(observed_owner)
        require(self._backend_stop_supported, 'instance-stop-unsupported')
        row = self._state.snapshot()
        require(row['cancel_requested_ns'] is not None, 'cancel-not-requested')
        if row['backend_stop'] is not None:
            return self.snapshot()
        observation = verify_stopped(copy.deepcopy(row['backend_expected']))
        require(type(observation) is dict and set(observation) == {'backend_stop', 'evidence'}
                and type(observation['evidence']) is dict
                and same(observation['evidence'].get('expected'), row['backend_expected']),
                'backend-observation')
        if self._state.record_backend_stop(observation['backend_stop'], now_ns=self._clock()):
            self._backend_observation = copy.deepcopy(observation)
            self._persist()
        return self.snapshot()

    def close(self):
        """Bounded local worker cleanup, never evidence that the backend stopped."""
        require(threading.get_ident() == self._thread, 'writer-mismatch')
        if self._closed:
            return
        if self._pending is not None:
            self._pending.close()
            if self._failed is None:
                self.poll()
        self._closed = True

    def abort(self, reason):
        """End an uncertain producer lifetime without inventing a task result."""
        self._check()
        self._fail(reason, RuntimeError(reason))
