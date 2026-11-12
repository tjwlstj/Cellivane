"""P1a attached Ollama HTTP chat protocol subset; no server qualification.

Protocol reference: https://docs.ollama.com/api/chat (reviewed 2026-10-09).
Own implementation, no upstream code imported. This declaration is not an
immutable Ollama version pin, model compatibility test, or runtime qualification.
Only HTTP 127.0.0.1 with an explicit port and POST /api/chat is admitted. Text
system/user/assistant messages request stream=false, think=false, num_predict=64.
Only done=true / done_reason=stop with one assistant text message is accepted.
Tools, thinking, logprobs, streaming and normalized token usage are unsupported.
Known nonnegative evaluation/duration statistics stay in the raw response only.
No proxy, redirects, retries, discovery, server start/stop, or model unloading.
Worker cancellation means a local worker stop, not engine/KV-cache release.
"""
from __future__ import annotations

import copy
import http.client
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aios_engines.contracts import Deployment, EngineSpec, CapabilityReport, require_capabilities
from aios_agent import inference
from aios_agent.async_inference import _StartLease
from aios_agent.request_state import RequestState, require, tick, same
from aios_backend.protocol import validate_identity
from aios_service.lifecycle import is_uuid

SPEC = EngineSpec('ollama-chat', 'ollama-api-chat', 'protocol-contract')
TIMEOUT = 30.0
MAX_RESPONSE_BODY = 16 * 1024
ENVELOPE_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'deployment', 'endpoint',
    'request_body', 'request_sha256', 'response_body', 'response_sha256', 'http_status',
    'content', 'usage', 'outcome', 'error', 'evidence_kind', 'elapsed_ns', 'actual_server_qualification'}
RESPONSE_REQUIRED = {'model', 'created_at', 'message', 'done', 'done_reason'}
RESPONSE_STATS = {'total_duration', 'load_duration', 'prompt_eval_count',
    'prompt_eval_cached_count', 'prompt_eval_duration', 'eval_count', 'eval_duration'}
PACKET_KEYS = {'schema_version', 'request_id', 'deployment', 'capabilities', 'endpoint', 'request'}


def _endpoint(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('engine-ollama-endpoint')
    return {'host': '127.0.0.1', 'port': port, 'path': '/api/chat'}


def _text(value):
    return (type(value) is str and bool(value.strip())
            and not any(ord(c) < 32 and c not in '\n\t' for c in value))


class OllamaChatAdapter:
    spec = SPEC

    @staticmethod
    def serialize(deployment, messages):
        if type(messages) is not list or not 1 <= len(messages) <= 16:
            raise ValueError('engine-messages')
        total = 0
        for message in messages:
            if (type(message) is not dict or set(message) != {'role', 'content'}
                    or type(message['role']) is not str
                    or message['role'] not in ('system', 'user', 'assistant')
                    or not _text(message['content'])):
                raise ValueError('engine-messages')
            total += len(message['content'].encode('utf-8'))
        if total > 4096 or not any(m['role'] == 'user' for m in messages):
            raise ValueError('engine-messages')
        body = inference.encoded({'model': deployment.model_id, 'messages': messages,
            'stream': False, 'think': False, 'options': {'num_predict': 64}})
        inference.parse(body)
        return body

    @staticmethod
    def response(deployment, raw):
        payload = inference.parse(raw, maximum=MAX_RESPONSE_BODY)
        if (not RESPONSE_REQUIRED <= set(payload) or set(payload) - RESPONSE_REQUIRED - RESPONSE_STATS
                or payload['model'] != deployment.model_id or payload['done'] is not True
                or payload['done_reason'] != 'stop' or type(payload['created_at']) is not str
                or not 0 < len(payload['created_at']) <= 128):
            raise ValueError('engine-ollama-response')
        try:
            created = datetime.fromisoformat(payload['created_at'].replace('Z', '+00:00'))
            if created.tzinfo is None or created.utcoffset() != timedelta(0):
                raise ValueError('engine-ollama-response')
        except ValueError as exc:
            raise ValueError('engine-ollama-response') from exc
        message = payload['message']
        if (type(message) is not dict or set(message) != {'role', 'content'}
                or message['role'] != 'assistant' or not _text(message['content'])):
            raise ValueError('engine-ollama-response')
        for name in RESPONSE_STATS & set(payload):
            if type(payload[name]) is not int or not 0 <= payload[name] < 1 << 63:
                raise ValueError('engine-ollama-response')
        return message['content']

    @classmethod
    def validate_envelope(cls, envelope, *, template):
        require(type(envelope) is dict and set(envelope) == ENVELOPE_KEYS
                and type(envelope['schema_version']) is int and envelope['schema_version'] == 1,
                'envelope-schema')
        for name in ('adapter_kind', 'request_id', 'deployment', 'endpoint', 'request_body',
                     'request_sha256', 'evidence_kind'):
            require(same(envelope[name], template[name]), 'envelope-join')
        tick(envelope['elapsed_ns'])
        require(envelope['usage'] is None and envelope['actual_server_qualification'] is False,
                'envelope-qualification')
        require(envelope['outcome'] in ('OK', 'ERROR'), 'envelope-outcome')
        if envelope['outcome'] == 'OK':
            require(type(envelope['http_status']) is int and envelope['http_status'] == 200
                    and type(envelope['response_body']) is str and envelope['error'] is None,
                    'envelope-response')
            raw = envelope['response_body'].encode('utf-8')
            content = cls.response(Deployment.from_record(template['deployment']), raw)
            require(envelope['response_sha256'] == inference.digest(raw)
                    and envelope['content'] == content, 'envelope-response')
        else:
            require(envelope['error'] in ('backend-failed', 'backend-timeout')
                    and all(envelope[k] is None for k in
                            ('response_body', 'response_sha256', 'http_status', 'content')),
                    'envelope-error')


@dataclass(frozen=True)
class PreparedOllama:
    _input: bytes
    _template: bytes
    _timeout: float = TIMEOUT
    _lease: _StartLease = field(default_factory=_StartLease, repr=False, compare=False)

    @property
    def request_id(self):
        return self.receipt_template['request_id']

    @property
    def request_body(self):
        return inference.parse(self._input)['request'].encode('utf-8')

    @property
    def receipt_template(self):
        return inference.parse(self._template, maximum=inference.MAX_WORKER_OUTPUT)

    @property
    def worker_command(self):
        return [sys.executable, str(Path(__file__).resolve()), '--worker']

    def validate_prepared(self):
        packet = inference.parse(self._input)
        require(set(packet) == PACKET_KEYS and type(packet['schema_version']) is int
                and packet['schema_version'] == 1 and type(packet['endpoint']) is dict,
                'prepared-ollama')
        deployment = Deployment.from_record(packet['deployment'])
        report = CapabilityReport.from_record(packet['capabilities'])
        request = inference.parse(packet['request'].encode('utf-8'))
        checked = prepare_ollama(deployment, report, request['messages'],
            request_id=packet['request_id'], port=packet['endpoint']['port'])
        require(self._input == checked._input and self._template == checked._template
                and type(self._timeout) is float and self._timeout == checked._timeout,
                'prepared-ollama')

    def validated_output(self, stdout, stderr, returncode):
        if returncode != 0 or stderr:
            raise ValueError('backend-worker-failed')
        output = inference.parse(stdout, maximum=inference.MAX_WORKER_OUTPUT)
        require(set(output) == {'http_status', 'response_body'}
                and type(output['http_status']) is int and output['http_status'] == 200
                and type(output['response_body']) is str, 'engine-worker-schema')
        raw = output['response_body'].encode('utf-8')
        content = OllamaChatAdapter.response(Deployment.from_record(self.receipt_template['deployment']), raw)
        return {'http_status': 200, 'response_body': output['response_body'],
            'response_sha256': inference.digest(raw), 'content': content, 'outcome': 'OK'}


def prepare_ollama(deployment, capabilities, messages, *, request_id, port,
                   streaming=False, require_usage=False):
    """Validate immutable input before persistence, Popen or any HTTP submission."""
    if (type(deployment) is not Deployment or deployment.engine != SPEC
            or deployment.ownership != 'attached'):
        raise ValueError('engine-ollama-deployment')
    require(is_uuid(request_id), 'id')
    endpoint = _endpoint(port)
    if type(streaming) is not bool or type(require_usage) is not bool:
        raise ValueError('engine-request-options')
    require_capabilities(deployment, capabilities, 'messages')
    if streaming or require_usage:
        raise ValueError('engine-ollama-mode-unsupported')
    body = OllamaChatAdapter.serialize(deployment, messages)
    packet = inference.encoded({'schema_version': 1, 'request_id': request_id,
        'deployment': deployment.snapshot(), 'capabilities': capabilities.snapshot(),
        'endpoint': endpoint, 'request': body.decode('utf-8')})
    inference.parse(packet)
    template = {'schema_version': 1, 'adapter_kind': SPEC.adapter_kind, 'request_id': request_id,
        'deployment': deployment.snapshot(), 'endpoint': endpoint,
        'request_body': body.decode('utf-8'), 'request_sha256': inference.digest(body),
        'response_body': None, 'response_sha256': None, 'http_status': None, 'content': None,
        'usage': None, 'outcome': 'ERROR', 'error': None, 'evidence_kind': SPEC.evidence_kind,
        'elapsed_ns': 0, 'actual_server_qualification': False}
    return PreparedOllama(packet, inference.encoded(template))


class OllamaRequestState(RequestState):
    """Attached P1a evidence, using the common question lifetime with no stop right."""
    def __init__(self, *, owner, prepared, accepted_ns):
        require(type(prepared) is PreparedOllama, 'prepared-ollama')
        PreparedOllama.validate_prepared(prepared)
        validate_identity(owner)
        tick(accepted_ns)
        self._template = prepared.receipt_template
        self._row = copy.deepcopy({'schema_version': 3, 'adapter_kind': SPEC.adapter_kind,
            'request_id': prepared.request_id, 'owner': owner, 'source_before': None,
            'management_before': None, 'backend_expected': None, 'space_context': None,
            'user_prompt': None, 'deployment': self._template['deployment'],
            'endpoint': self._template['endpoint'], 'request_body': self._template['request_body'],
            'request_sha256': self._template['request_sha256'], 'revision': 1,
            'phase': 'ACCEPTED', 'model_outcome': None, 'accepted_ns': accepted_ns,
            'updated_ns': accepted_ns, 'started_ns': None, 'cancel_requested_ns': None,
            'finished_ns': None, 'worker_process_id': None, 'worker_exit_code': None,
            'inference_receipt': None, 'backend_stop': None, 'backend_stopped_ns': None,
            'not_started_reason': None})

    def mark_running(self, worker_pid, *, now_ns):
        require(self._row['phase'] == 'ACCEPTED', 'dispatch-state')
        require(type(worker_pid) is int and 0 < worker_pid < 1 << 63
                and worker_pid != self._row['owner']['process_id'], 'worker-identity')
        self._update(now_ns, phase='RUNNING', worker_process_id=worker_pid, started_ns=now_ns)

    def _check_receipt(self, receipt):
        OllamaChatAdapter.validate_envelope(receipt, template=self._template)

    def record_backend_stop(self, stopped, *, now_ns):
        raise ValueError('request-instance-stop-unsupported')


def worker(packet):
    """Send once to the admitted loopback endpoint, retaining the actual HTTP body."""
    require(type(packet) is dict and set(packet) == PACKET_KEYS, 'ollama-worker-schema')
    deployment = Deployment.from_record(packet['deployment'])
    request = inference.parse(packet['request'].encode('utf-8'))
    checked = prepare_ollama(deployment, CapabilityReport.from_record(packet['capabilities']),
        request['messages'], request_id=packet['request_id'], port=packet['endpoint']['port'])
    require(checked._input == inference.encoded(packet), 'ollama-wire-request')
    endpoint = packet['endpoint']
    connection = http.client.HTTPConnection('127.0.0.1', endpoint['port'], timeout=TIMEOUT)
    deadline = time.monotonic() + TIMEOUT
    timer = None
    try:
        connection.connect()
        connection.auto_open = 0  # No implicit reconnect after the one connection.
        connected_socket = connection.sock
        def expire():
            try:
                connected_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('ollama-deadline')
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        connection.request('POST', '/api/chat', body=checked.request_body,
            headers={'Content-Type': 'application/json', 'Connection': 'close'})
        response = connection.getresponse()
        try:
            content_type = response.getheader('Content-Type', '')
            if content_type.split(';', 1)[0].strip().lower() != 'application/json':
                raise ValueError('ollama-http-content-type')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('ollama-http-content-encoding')
            raw = response.read(MAX_RESPONSE_BODY + 1)
            if len(raw) > MAX_RESPONSE_BODY or time.monotonic() >= deadline:
                raise ValueError('ollama-http-bound')
            return {'http_status': response.status, 'response_body': raw.decode('utf-8')}
        finally:
            response.close()
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


if __name__ == '__main__':
    try:
        packet = inference.parse(sys.stdin.buffer.read(inference.MAX_BODY + 1))
        sys.stdout.buffer.write(inference.encoded(worker(packet)))
    except (ValueError, TypeError, KeyError, OSError, http.client.HTTPException):
        raise SystemExit(1)
