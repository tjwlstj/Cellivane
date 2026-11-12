"""Messages-only protocol fixture through the real bounded Task worker lifetime.

No engine server, model computation, canonical MAIN binding or stop authority.
The raw response deliberately has no prompt echo, usage, or backend descriptor.
"""
from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aios_engines.contracts import Deployment, EngineSpec, CapabilityReport, require_capabilities
from aios_agent import inference
from aios_agent.async_inference import _StartLease
from aios_agent.request_state import RequestState, require, tick, same
from aios_backend.protocol import validate_identity
from aios_service.lifecycle import is_uuid

SPEC = EngineSpec('messages-fixture', 'messages-json', 'fixture')
ENVELOPE_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'deployment', 'request_body',
                 'request_sha256', 'response_body', 'response_sha256', 'content', 'usage',
                 'outcome', 'error', 'evidence_kind', 'elapsed_ns'}


class MessagesFixtureAdapter:
    spec = SPEC

    @staticmethod
    def serialize(deployment, messages):
        if (type(messages) is not list or not 1 <= len(messages) <= 16):
            raise ValueError('engine-messages')
        total = 0
        for message in messages:
            if (type(message) is not dict or set(message) != {'role', 'content'}
                    or message['role'] not in ('system', 'user', 'assistant')
                    or type(message['content']) is not str or not message['content'].strip()
                    or any(ord(c) < 32 and c not in '\n\t' for c in message['content'])
                    or any(mark in message['content'] for mark in ('<|im_start|>', '<|im_end|>', '<think>'))):
                raise ValueError('engine-messages')
            total += len(message['content'].encode('utf-8'))
        if total > 4096 or not any(m['role'] == 'user' for m in messages):
            raise ValueError('engine-messages')
        return inference.encoded({'model': deployment.model_id, 'messages': messages, 'stream': False})

    @staticmethod
    def response(deployment, raw):
        payload = inference.parse(raw)
        if (set(payload) != {'id', 'model', 'choices'} or type(payload['id']) is not str
                or not 0 < len(payload['id']) <= 128 or payload['model'] != deployment.model_id
                or type(payload['choices']) is not list or len(payload['choices']) != 1):
            raise ValueError('engine-response')
        choice = payload['choices'][0]
        if (type(choice) is not dict or set(choice) != {'index', 'message', 'finish_reason'}
                or type(choice['index']) is not int or choice['index'] != 0 or choice['finish_reason'] != 'stop'
                or type(choice['message']) is not dict or set(choice['message']) != {'role', 'content'}
                or choice['message']['role'] != 'assistant' or type(choice['message']['content']) is not str
                or not choice['message']['content'].strip()):
            raise ValueError('engine-response')
        return choice['message']['content']

    @classmethod
    def validate_envelope(cls, envelope, *, template):
        require(type(envelope) is dict and set(envelope) == ENVELOPE_KEYS
                and type(envelope['schema_version']) is int and envelope['schema_version'] == 1,
                'envelope-schema')
        for name in ('adapter_kind', 'request_id', 'deployment', 'request_body', 'request_sha256', 'evidence_kind'):
            require(same(envelope[name], template[name]), 'envelope-join')
        tick(envelope['elapsed_ns'])
        require(envelope['usage'] is None, 'envelope-usage')
        require(envelope['outcome'] in ('OK', 'ERROR'), 'envelope-outcome')
        if envelope['outcome'] == 'OK':
            require(type(envelope['response_body']) is str and envelope['error'] is None, 'envelope-response')
            raw = envelope['response_body'].encode('utf-8')
            content = cls.response(Deployment.from_record(template['deployment']), raw)
            require(envelope['response_sha256'] == inference.digest(raw)
                    and envelope['content'] == content, 'envelope-response')
        else:
            require(envelope['error'] in ('backend-failed', 'backend-timeout')
                    and all(envelope[k] is None for k in ('response_body', 'response_sha256', 'content')),
                    'envelope-error')


@dataclass(frozen=True)
class PreparedMessages:
    _input: bytes
    _template: bytes
    _timeout: float = 5.0
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
        require(set(packet) == {'request_id', 'deployment', 'capabilities', 'request'}, 'prepared-messages')
        deployment = Deployment.from_record(packet['deployment'])
        report = CapabilityReport.from_record(packet['capabilities'])
        messages = inference.parse(packet['request'].encode('utf-8'))['messages']
        checked = prepare_messages(deployment, report, messages, request_id=packet['request_id'])
        require(self._input == checked._input and self._template == checked._template
                and self._timeout == checked._timeout, 'prepared-messages')

    def validated_output(self, stdout, stderr, returncode):
        if returncode != 0 or stderr:
            raise ValueError('backend-worker-failed')
        output = inference.parse(stdout, maximum=inference.MAX_WORKER_OUTPUT)
        require(set(output) == {'response_body'}, 'engine-worker-schema')
        require(type(output['response_body']) is str, 'engine-worker-response')
        raw = output['response_body'].encode('utf-8')
        deployment = Deployment.from_record(self.receipt_template['deployment'])
        content = MessagesFixtureAdapter.response(deployment, raw)
        return {'response_body': output['response_body'], 'response_sha256': inference.digest(raw),
                'content': content, 'outcome': 'OK'}


def prepare_messages(deployment, capabilities, messages, *, request_id, streaming=False, require_usage=False):
    if type(deployment) is not Deployment or deployment.engine != SPEC:
        raise ValueError('engine-fixture-deployment')
    require(is_uuid(request_id), 'id')
    if type(streaming) is not bool or type(require_usage) is not bool:
        raise ValueError('engine-request-options')
    required = ['messages'] + (['streaming'] if streaming else []) + (['usage'] if require_usage else [])
    require_capabilities(deployment, capabilities, *required)
    if streaming or require_usage:
        raise ValueError('engine-fixture-mode-unsupported')
    body = MessagesFixtureAdapter.serialize(deployment, messages)
    packet = inference.encoded({'request_id': request_id, 'deployment': deployment.snapshot(),
        'capabilities': capabilities.snapshot(), 'request': body.decode('utf-8')})
    inference.parse(packet)
    template = {'schema_version': 1, 'adapter_kind': SPEC.adapter_kind, 'request_id': request_id,
        'deployment': deployment.snapshot(), 'request_body': body.decode('utf-8'),
        'request_sha256': inference.digest(body), 'response_body': None, 'response_sha256': None,
        'content': None, 'usage': None, 'outcome': 'ERROR', 'error': None,
        'evidence_kind': 'fixture', 'elapsed_ns': 0}
    return PreparedMessages(packet, inference.encoded(template))


class MessagesRequestState(RequestState):
    """Reuse lifecycle transitions; admission and result evidence are unbound."""
    def __init__(self, *, owner, prepared, accepted_ns):
        prepared.validate_prepared()
        validate_identity(owner)
        tick(accepted_ns)
        self._template = prepared.receipt_template
        self._row = copy.deepcopy({'schema_version': 2, 'adapter_kind': SPEC.adapter_kind,
            'request_id': prepared.request_id, 'owner': owner, 'source_before': None,
            'management_before': None, 'backend_expected': None, 'space_context': None,
            'user_prompt': None, 'deployment': self._template['deployment'],
            'request_body': self._template['request_body'], 'request_sha256': self._template['request_sha256'],
            'revision': 1, 'phase': 'ACCEPTED', 'model_outcome': None,
            'accepted_ns': accepted_ns, 'updated_ns': accepted_ns, 'started_ns': None,
            'cancel_requested_ns': None, 'finished_ns': None, 'worker_process_id': None,
            'worker_exit_code': None, 'inference_receipt': None, 'backend_stop': None,
            'backend_stopped_ns': None, 'not_started_reason': None})

    def mark_running(self, worker_pid, *, now_ns):
        require(self._row['phase'] == 'ACCEPTED', 'dispatch-state')
        require(type(worker_pid) is int and 0 < worker_pid < 1 << 63
                and worker_pid != self._row['owner']['process_id'], 'worker-identity')
        self._update(now_ns, phase='RUNNING', worker_process_id=worker_pid, started_ns=now_ns)

    def _check_receipt(self, receipt):
        MessagesFixtureAdapter.validate_envelope(receipt, template=self._template)

    def record_backend_stop(self, stopped, *, now_ns):
        raise ValueError('request-instance-stop-unsupported')


def worker(packet):
    deployment = Deployment.from_record(packet['deployment'])
    request = inference.parse(packet['request'].encode('utf-8'))
    checked = prepare_messages(deployment, CapabilityReport.from_record(packet['capabilities']),
                               request['messages'], request_id=packet['request_id'])
    require(checked._input == inference.encoded(packet), 'fixture-wire-request')
    # Fixture producer emits an actual, distinct response protocol. No request
    # echo or legacy descriptor is present in the response.
    raw = inference.encoded({'id': 'fixture-response', 'model': deployment.model_id,
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'messages fixture answer'},
                     'finish_reason': 'stop'}]})
    return {'response_body': raw.decode('utf-8')}


if __name__ == '__main__':
    try:
        packet = inference.parse(sys.stdin.buffer.read(inference.MAX_BODY + 1))
        sys.stdout.buffer.write(inference.encoded(worker(packet)))
    except (ValueError, TypeError, KeyError, OSError):
        raise SystemExit(1)
