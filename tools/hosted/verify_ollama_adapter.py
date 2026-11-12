#!/usr/bin/env python3
"""Independent bounded /api/chat fixture evidence; no actual Ollama qualification.

Only saved bytes, source hashes and owned-worker/Task consistency are checked.
No runtime validator is imported and no HTTP, model or process is started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import uuid
from datetime import datetime, timedelta
from pathlib import Path

FAMILY = 'ollama-adapter-fixture-v1'
FILE_LIMIT = 4 * 1024 * 1024
WIRE_LIMIT = 16384
STDOUT_LIMIT = 128 * 1024
STDERR_LIMIT = 16 * 1024
# This independent inventory deliberately does not import the producer or an
# evolving public MAIN inventory. P1a is a separate source/evidence family.
SOURCE_FILES = (
    'aios-agent.py', 'aios_agent/__init__.py', 'aios_agent/inference.py',
    'aios_agent/protocol.py', 'aios_agent/client.py', 'aios_agent/daemon.py',
    'aios_management/__init__.py', 'aios_management/binding.py',
    'aios_service/__init__.py', 'aios_service/lifecycle.py',
    'aios_hosted/__init__.py', 'aios_hosted/boot.py', 'aios_hosted/hardware.py',
    'aios_resources/__init__.py', 'aios_resources/proc.py', 'aios_resources/backend.py',
    'aios_resources/runtime.py', 'aios_management/resources.py', 'aios-backend.py',
    'aios_backend/__init__.py', 'aios_backend/protocol.py', 'aios_backend/client.py',
    'aios_backend/daemon.py', 'aios_agent/backend_binding.py', 'aios_agent/space.py',
    'aios_agent/async_inference.py', 'aios_agent/request_state.py',
    'aios_agent/request_runtime.py', 'aios_engines/__init__.py',
    'aios_engines/contracts.py', 'aios_engines/legacy_llamafile.py',
    'aios_engines/fixtures.py', 'aios_engines/ollama_chat.py',
)
ENVELOPE_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'deployment', 'endpoint',
    'request_body', 'request_sha256', 'response_body', 'response_sha256', 'http_status',
    'content', 'usage', 'outcome', 'error', 'evidence_kind', 'elapsed_ns', 'actual_server_qualification'}
STATE_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'owner', 'deployment', 'endpoint',
    'source_before', 'management_before', 'backend_expected', 'space_context', 'user_prompt',
    'request_body', 'request_sha256', 'revision', 'phase', 'model_outcome', 'accepted_ns', 'updated_ns',
    'started_ns', 'cancel_requested_ns', 'finished_ns', 'worker_process_id', 'worker_exit_code',
    'inference_receipt', 'backend_stop', 'backend_stopped_ns', 'not_started_reason'}
NULL_BINDINGS = {'source_before', 'management_before', 'backend_expected', 'space_context',
                 'user_prompt', 'backend_stop', 'backend_stopped_ns'}
STATIC_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'owner', 'deployment', 'endpoint',
              'source_before', 'management_before', 'backend_expected', 'space_context',
              'user_prompt', 'request_body', 'request_sha256', 'accepted_ns'}
WORKER_KEYS = {'request_id', 'done', 'worker_pid', 'worker_exit_code', 'worker_exit_observed_monotonic_ns',
    'cancel_requested', 'timed_out', 'stop_reason', 'terminate_requested', 'kill_requested',
    'signal_error', 'io_error', 'output_bytes', 'receipt'}
RESPONSE_KEYS = {'model', 'created_at', 'message', 'done', 'done_reason'}
STAT_KEYS = {'total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_cached_count',
             'prompt_eval_duration', 'eval_count', 'eval_duration'}


def require(condition, reason):
    if not condition:
        raise ValueError('ollama-' + reason)


def keys(value, expected, reason):
    require(type(value) is dict and set(value) == expected, reason + '-keys')


def integer(value, minimum=0):
    return type(value) is int and minimum <= value < 1 << 63


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def same(left, right):
    return encoded(left) == encoded(right)


def parse(raw, maximum=FILE_LIMIT):
    require(type(raw) in (bytes, str), 'json-type')
    data = raw.encode('utf-8') if type(raw) is str else raw
    require(len(data) <= maximum, 'json-size')
    def pairs(items):
        result = {}
        for name, value in items:
            require(name not in result, 'json-duplicate:' + name)
            result[name] = value
        return result
    def constant(_value):
        raise ValueError('ollama-json-nonfinite')
    value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    def finite(item):
        if type(item) is float:
            require(math.isfinite(item), 'json-nonfinite')
        elif type(item) is dict:
            for child in item.values():
                finite(child)
        elif type(item) is list:
            for child in item:
                finite(child)
    finite(value)
    return value


def path_guard(path, *, directory=False):
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        metadata = item.lstat()
        require(not stat.S_ISLNK(metadata.st_mode)
                and not getattr(metadata, 'st_file_attributes', 0) & 0x400, 'source-path-link')
        require(stat.S_ISDIR(metadata.st_mode) if item != path or directory
                else stat.S_ISREG(metadata.st_mode), 'source-path-type')
    return path


def read(path):
    path = path_guard(path)
    before = path.stat()
    require(before.st_size <= FILE_LIMIT, 'file-size')
    with path.open('rb') as handle:
        data = handle.read(FILE_LIMIT + 1)
        after = os.fstat(handle.fileno())
    require(len(data) <= FILE_LIMIT and before.st_size == after.st_size == len(data)
            and (before.st_dev, before.st_ino, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_mtime_ns), 'file-changed')
    path_guard(path)
    return data


def identifier(value):
    require(type(value) is str, 'identity')
    parsed = uuid.UUID(value)
    require(str(parsed) == value and parsed.int != 0, 'identity')


def deployment(value):
    keys(value, {'engine', 'model_id', 'service_id', 'instance_id', 'start_generation', 'ownership'}, 'deployment')
    keys(value['engine'], {'adapter_kind', 'wire_protocol', 'evidence_kind', 'contract_version'}, 'engine')
    require(same(value['engine'], {'adapter_kind': 'ollama-chat', 'wire_protocol': 'ollama-api-chat',
                                  'evidence_kind': 'protocol-contract', 'contract_version': 1}), 'engine')
    require(type(value['model_id']) is str and 0 < len(value['model_id']) <= 128
            and all(c.isprintable() for c in value['model_id']), 'model')
    identifier(value['service_id'])
    identifier(value['instance_id'])
    require(integer(value['start_generation'], 1) and value['ownership'] == 'attached', 'deployment-ownership')


def endpoint(value):
    keys(value, {'host', 'port', 'path'}, 'endpoint')
    require(value['host'] == '127.0.0.1' and value['path'] == '/api/chat'
            and integer(value['port'], 1) and value['port'] <= 65535, 'endpoint')


def wire(raw):
    require(type(raw) is str, 'wire-type')
    value = parse(raw, WIRE_LIMIT)
    require(type(value) is dict, 'wire-object')
    return value


def request(row):
    value = wire(row['request_body'])
    keys(value, {'model', 'messages', 'stream', 'think', 'options'}, 'request')
    require(value['model'] == row['deployment']['model_id'] and value['stream'] is False
            and value['think'] is False and same(value['options'], {'num_predict': 64}), 'request-mode')
    messages = value['messages']
    require(type(messages) is list and 1 <= len(messages) <= 16, 'messages')
    for message in messages:
        keys(message, {'role', 'content'}, 'message')
        require(message['role'] in ('system', 'user', 'assistant') and type(message['content']) is str
                and message['content'].strip()
                and not any(ord(c) < 32 and c not in '\n\t' for c in message['content']),
                'message-content')
    require(sum(len(m['content'].encode('utf-8')) for m in messages) <= 4096
            and any(m['role'] == 'user' for m in messages), 'messages-budget')
    raw = row['request_body'].encode('utf-8')
    require(raw == encoded(value) and row['request_sha256'] == digest(raw), 'request-bytes')


def response(raw, model):
    value = wire(raw)
    require(RESPONSE_KEYS <= set(value) <= RESPONSE_KEYS | STAT_KEYS, 'response-keys')
    require(value['model'] == model and value['done'] is True and value['done_reason'] == 'stop', 'response-mode')
    created = value['created_at']
    require(type(created) is str and 0 < len(created) <= 128, 'response-time')
    timestamp = datetime.fromisoformat(created.replace('Z', '+00:00'))
    require(timestamp.tzinfo is not None and timestamp.utcoffset() == timedelta(0), 'response-time')
    keys(value['message'], {'role', 'content'}, 'response-message')
    require(value['message']['role'] == 'assistant' and type(value['message']['content']) is str
            and value['message']['content'].strip()
            and not any(ord(c) < 32 and c not in '\n\t' for c in value['message']['content']), 'response-content')
    require(all(integer(value[name]) for name in set(value) & STAT_KEYS), 'response-stats')
    return value['message']['content']


def envelope(value, row, *, template=False):
    keys(value, ENVELOPE_KEYS, 'envelope')
    require(same(value['schema_version'], 1) and value['adapter_kind'] == 'ollama-chat'
            and value['evidence_kind'] == 'protocol-contract' and value['actual_server_qualification'] is False
            and value['usage'] is None and integer(value['elapsed_ns']), 'envelope-boundary')
    require(all(same(value[name], row[name]) for name in
                ('request_id', 'deployment', 'endpoint', 'request_body', 'request_sha256')), 'envelope-join')
    if template:
        require(value['outcome'] == 'ERROR' and value['error'] is None and same(value['elapsed_ns'], 0)
                and all(value[name] is None for name in
                        ('response_body', 'response_sha256', 'http_status', 'content')), 'template')
    elif value['outcome'] == 'ERROR':
        require(value['error'] in ('backend-failed', 'backend-timeout')
                and all(value[name] is None for name in
                        ('response_body', 'response_sha256', 'http_status', 'content')), 'envelope-error')
    else:
        require(value['outcome'] == 'OK' and value['error'] is None
                and type(value['http_status']) is int and value['http_status'] == 200, 'envelope-response')
        content = response(value['response_body'], row['deployment']['model_id'])
        require(value['content'] == content and value['response_sha256']
                == digest(value['response_body'].encode('utf-8')), 'response-bytes')


def state(row):
    keys(row, STATE_KEYS, 'task')
    require(same(row['schema_version'], 3) and row['adapter_kind'] == 'ollama-chat'
            and all(row[name] is None for name in NULL_BINDINGS), 'task-unbound')
    identifier(row['request_id'])
    deployment(row['deployment'])
    endpoint(row['endpoint'])
    keys(row['owner'], {'host_boot_id', 'process_id', 'process_start_ticks', 'uid'}, 'owner')
    identifier(row['owner']['host_boot_id'])
    require(integer(row['owner']['process_id'], 1) and integer(row['owner']['process_start_ticks'], 1)
            and integer(row['owner']['uid']), 'owner')
    request(row)
    require(integer(row['accepted_ns']) and integer(row['updated_ns'])
            and row['updated_ns'] >= row['accepted_ns'] and integer(row['revision'], 1)
            and row['revision'] <= 8, 'task-clock')
    for name in ('started_ns', 'cancel_requested_ns', 'finished_ns'):
        require(row[name] is None or integer(row[name])
                and row['accepted_ns'] <= row[name] <= row['updated_ns'], 'task-clock')
    worker, code, phase = row['worker_process_id'], row['worker_exit_code'], row['phase']
    require(worker is None or integer(worker, 1) and worker != row['owner']['process_id'], 'task-worker')
    require((worker is None) == (row['started_ns'] is None), 'task-start')
    require(code is None or type(code) is int and -(1 << 31) <= code < 1 << 32, 'task-exit')
    require(phase in ('ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'FINISHED'), 'task-phase')
    if phase == 'ACCEPTED':
        require(worker is None and row['cancel_requested_ns'] is None and row['revision'] == 1
                and row['updated_ns'] == row['accepted_ns'], 'task-admission')
    if phase == 'RUNNING':
        require(worker is not None and row['cancel_requested_ns'] is None and row['revision'] == 2, 'task-running')
    if phase == 'CANCEL_REQUESTED':
        require(row['cancel_requested_ns'] is not None, 'task-cancel')
    if phase != 'FINISHED':
        require(all(row[name] is None for name in
                    ('model_outcome', 'finished_ns', 'worker_exit_code', 'inference_receipt', 'not_started_reason')),
                'task-pending')
        return
    outcome, receipt = row['model_outcome'], row['inference_receipt']
    require(outcome in ('ANSWERED', 'UNKNOWN', 'NOT_STARTED') and row['finished_ns'] is not None, 'task-finished')
    if outcome == 'NOT_STARTED':
        require(worker is None and code is None and receipt is None
                and row['not_started_reason'] in ('cancel-before-dispatch', 'dispatch-failed'), 'not-started')
        require(row['not_started_reason'] != 'cancel-before-dispatch' or row['cancel_requested_ns'] is not None,
                'cancel-not-started')
    else:
        require(worker is not None and code is not None and row['not_started_reason'] is None
                and row['finished_ns'] >= row['started_ns'], 'finished-worker')
        require(receipt is not None, 'finished-receipt')
        envelope(receipt, row)
        require((outcome == 'ANSWERED') == (receipt['outcome'] == 'OK')
                and (outcome != 'ANSWERED' or code == 0), 'model-outcome')
    require(outcome == 'UNKNOWN' or row['cancel_requested_ns'] is None
            or row['cancel_requested_ns'] <= row['finished_ns'], 'late-cancel')


def worker_progress(value, row):
    if row['worker_process_id'] is None:
        require(value is None, 'worker-not-dispatched')
        return
    keys(value, WORKER_KEYS, 'worker')
    require(value['request_id'] == row['request_id'] and same(value['worker_pid'], row['worker_process_id']),
            'worker-identity')
    require(all(type(value[name]) is bool for name in
                ('done', 'cancel_requested', 'timed_out', 'terminate_requested', 'kill_requested')), 'worker-flags')
    keys(value['output_bytes'], {'stdout', 'stderr'}, 'worker-bytes')
    require(all(integer(number) for number in value['output_bytes'].values()), 'worker-bytes')
    require(value['io_error'] in (None, 'stdout-limit', 'stderr-limit', 'stdout-read', 'stderr-read',
                                 'stdout-close', 'stderr-close'), 'worker-io-error')
    require(value['signal_error'] in (None, 'worker-terminate', 'worker-kill'), 'worker-signal-error')
    require(value['stop_reason'] in (None, 'cancel', 'timeout', 'close', 'io-failed')
            and (not value['cancel_requested'] or row['cancel_requested_ns'] is not None), 'worker-cancel')
    require(not value['kill_requested'] or value['terminate_requested'], 'worker-kill-order')
    require(value['signal_error'] != 'worker-terminate' or value['terminate_requested'], 'worker-signal-order')
    require(value['signal_error'] != 'worker-kill' or value['kill_requested'], 'worker-signal-order')
    require(not value['cancel_requested'] or value['stop_reason'] is not None
            and value['terminate_requested'], 'worker-cancel-order')
    require(value['stop_reason'] != 'cancel' or value['cancel_requested'], 'worker-cancel-reason')
    require(value['stop_reason'] != 'timeout' or value['timed_out'], 'worker-timeout-reason')
    for name, limit in (('stdout', STDOUT_LIMIT), ('stderr', STDERR_LIMIT)):
        require(value['io_error'] != name + '-limit' or value['output_bytes'][name] > limit, 'worker-overflow')
    code, observed = value['worker_exit_code'], value['worker_exit_observed_monotonic_ns']
    require(code is None or type(code) is int and -(1 << 31) <= code < 1 << 32, 'worker-exit')
    require((code is None) == (observed is None), 'worker-exit-time')
    if observed is not None:
        require(integer(observed) and row['accepted_ns'] <= observed <= row['updated_ns'], 'worker-exit-time')
    if value['done']:
        require(code is not None and value['receipt'] is not None, 'worker-terminal')
        envelope(value['receipt'], row)
        require(value['receipt']['elapsed_ns'] <= observed - row['accepted_ns'], 'worker-elapsed')
        overflow = value['output_bytes']['stdout'] > STDOUT_LIMIT or value['output_bytes']['stderr'] > STDERR_LIMIT
        require(not overflow or value['receipt']['outcome'] == 'ERROR' and value['io_error'] is not None,
                'worker-overflow')
        if value['receipt']['outcome'] == 'OK':
            require(code == 0 and not value['timed_out'] and not value['cancel_requested']
                    and value['stop_reason'] is None and value['signal_error'] is None and value['io_error'] is None
                    and same(value['output_bytes']['stderr'], 0), 'worker-answer')
        else:
            require((value['receipt']['error'] == 'backend-timeout') == value['timed_out'], 'worker-timeout')
    else:
        require(value['receipt'] is None, 'worker-pending-receipt')
    if row['phase'] == 'FINISHED':
        require(value['done'] and same(code, row['worker_exit_code'])
                and same(value['receipt'], row['inference_receipt']), 'worker-final-join')


def transition(previous, current):
    require(current['revision'] == previous['revision'] + 1
            and current['updated_ns'] >= previous['updated_ns']
            and all(same(current[name], previous[name]) for name in STATIC_KEYS), 'task-transition')
    at = current['updated_ns']
    base = {**previous, 'revision': current['revision'], 'updated_ns': at}
    allowed = []
    if previous['phase'] == 'ACCEPTED':
        allowed.append({**base, 'phase': 'RUNNING', 'worker_process_id': current['worker_process_id'], 'started_ns': at})
    if previous['cancel_requested_ns'] is None and (previous['phase'] != 'FINISHED'
                                                    or previous['model_outcome'] == 'UNKNOWN'):
        allowed.append({**base, 'phase': 'FINISHED' if previous['phase'] == 'FINISHED' else 'CANCEL_REQUESTED',
                        'cancel_requested_ns': at})
    if previous['phase'] != 'FINISHED' and previous['worker_process_id'] is None:
        allowed.append({**base, 'phase': 'FINISHED', 'model_outcome': 'NOT_STARTED', 'finished_ns': at,
                        'not_started_reason': current['not_started_reason']})
    if previous['phase'] in ('RUNNING', 'CANCEL_REQUESTED') and previous['worker_process_id'] is not None:
        allowed.append({**base, 'phase': 'FINISHED', 'finished_ns': at, 'model_outcome': current['model_outcome'],
                        'worker_exit_code': current['worker_exit_code'], 'inference_receipt': current['inference_receipt']})
    require(any(same(current, candidate) for candidate in allowed), 'task-transition')


def worker_transition(previous, current):
    if previous is None:
        return
    require(current is not None and all(current['output_bytes'][name] >= previous['output_bytes'][name]
                                        for name in ('stdout', 'stderr')), 'worker-counter-regression')
    for name in ('done', 'cancel_requested', 'timed_out', 'terminate_requested', 'kill_requested'):
        require(not previous[name] or current[name], 'worker-flag-regression')
    for name in ('worker_exit_code', 'worker_exit_observed_monotonic_ns', 'stop_reason', 'signal_error', 'io_error'):
        require(previous[name] is None or same(previous[name], current[name]), 'worker-observation-rewrite')
    require(not previous['done'] or same(previous, current), 'worker-terminal-rewrite')


def capture(value, row, worker):
    keys(value, {'request_id', 'worker_pid', 'input_body', 'stdout', 'stderr'}, 'capture')
    require(value['request_id'] == row['request_id'] and same(value['worker_pid'], row['worker_process_id']),
            'capture-identity')
    packet = wire(value['input_body'])
    keys(packet, {'schema_version', 'request_id', 'deployment', 'capabilities', 'endpoint', 'request'}, 'stdin')
    require(same(packet['schema_version'], 1) and packet['request_id'] == row['request_id']
            and same(packet['deployment'], row['deployment']) and same(packet['endpoint'], row['endpoint'])
            and packet['request'] == row['request_body'] and value['input_body'].encode('utf-8') == encoded(packet),
            'stdin-join')
    report = packet['capabilities']
    keys(report, {'deployment', 'text_completion', 'messages', 'streaming', 'usage', 'request_cancel',
                  'evidence_kind', 'contract_version'}, 'capabilities')
    require(same(report['deployment'], row['deployment']) and report['messages'] is True
            and report['evidence_kind'] == 'protocol-contract' and same(report['contract_version'], 1)
            and all(report[name] is None or type(report[name]) is bool for name in
                    ('text_completion', 'messages', 'streaming', 'usage', 'request_cancel')), 'capabilities')
    for name, limit in (('stdout', STDOUT_LIMIT), ('stderr', STDERR_LIMIT)):
        require(type(value[name]) is str, 'capture-type')
        retained = len(value[name].encode('utf-8'))
        total = worker['output_bytes'][name]
        require(retained == min(total, limit), 'capture-bytes')
    return value['stdout'], value['stderr']


def exchanges(values, row):
    require(type(values) is list and len(values) <= 1, 'http-count')
    for value in values:
        keys(value, {'request_id', 'endpoint', 'request_body', 'http_status', 'response_body',
                     'request_method', 'response_content_type', 'response_content_encoding'}, 'http')
        require(value['request_id'] == row['request_id'] and same(value['endpoint'], row['endpoint'])
                and value['request_body'] == row['request_body'] and value['request_method'] == 'POST', 'http-request-join')
        require(type(value['http_status']) is int and 100 <= value['http_status'] <= 599
                and type(value['response_body']) is str
                and len(value['response_body'].encode('utf-8')) <= STDOUT_LIMIT, 'http-response')
        require(type(value['response_content_type']) is str and type(value['response_content_encoding']) is str,
                'http-headers')


def raw_worker_result(stdout, stderr, code, model):
    require(code == 0 and not stderr, 'raw-worker-exit')
    result = parse(stdout, STDOUT_LIMIT)
    keys(result, {'http_status', 'response_body'}, 'raw-worker')
    require(stdout.encode('utf-8') == encoded(result) and type(result['http_status']) is int
            and result['http_status'] == 200, 'raw-worker-status')
    content = response(result['response_body'], model)
    return result, content


def verify_sources(manifest, source_root):
    keys(manifest, {'schema_version', 'source_hashes'}, 'source-manifest')
    require(same(manifest['schema_version'], 1), 'source-schema')
    keys(manifest['source_hashes'], set(SOURCE_FILES), 'source-inventory')
    source_root = path_guard(source_root, directory=True)
    for name, checksum in manifest['source_hashes'].items():
        require(type(checksum) is str and re.fullmatch('[0-9a-f]{64}', checksum) is not None, 'source-hash')
        require(digest(read(source_root / name)) == checksum, 'source-hash:' + name)


def verdict(outcome, reasons, **fields):
    return {'schema_version': 1, 'artifact_family': FAMILY, 'outcome': outcome, 'reasons': reasons,
            'evidence_kind': 'protocol-contract', 'actual_server_qualification': False,
            'process_liveness_verified': False, **fields}


def verify_record(value, *, source_manifest=None, source_root=None):
    try:
        keys(value, {'artifact_family', 'schema_version', 'snapshots', 'completed', 'http_exchanges', 'worker_capture'}, 'bundle')
        require(value['artifact_family'] == FAMILY and same(value['schema_version'], 1)
                and type(value['snapshots']) is list and 2 <= len(value['snapshots']) <= 8
                and type(value['completed']) is list and len(value['completed']) == 1, 'bundle-shape')
        previous, previous_worker, template, first_finished = None, None, None, None
        for snapshot in value['snapshots']:
            keys(snapshot, {'schema_version', 'request_state', 'receipt_template', 'worker_progress',
                            'control_failure', 'backend_observation'}, 'snapshot')
            require(same(snapshot['schema_version'], 1) and snapshot['control_failure'] is None
                    and snapshot['backend_observation'] is None, 'snapshot-failure')
            row, worker = snapshot['request_state'], snapshot['worker_progress']
            state(row)
            envelope(snapshot['receipt_template'], row, template=True)
            worker_progress(worker, row)
            if previous is None:
                require(row['phase'] == 'ACCEPTED', 'initial-admission')
                template = snapshot['receipt_template']
            else:
                require(same(snapshot['receipt_template'], template), 'template-rewrite')
                transition(previous, row)
                worker_transition(previous_worker, worker)
            if row['phase'] == 'FINISHED' and first_finished is None:
                first_finished = row
            previous, previous_worker = row, worker
        # Completion is emitted once at the first terminal transition. A later
        # authenticated cancel may add one observation to UNKNOWN, preserving
        # that already-completed outcome and the immutable terminal worker.
        require(previous['phase'] == 'FINISHED' and same(value['completed'][0], first_finished), 'finalization')
        exchanges(value['http_exchanges'], previous)
        if previous['model_outcome'] == 'NOT_STARTED':
            require(not value['http_exchanges'] and value['worker_capture'] is None, 'not-started-transport')
        else:
            stdout, stderr = capture(value['worker_capture'], previous, previous_worker)
            receipt = previous['inference_receipt']
            if receipt['outcome'] == 'OK':
                output, content = raw_worker_result(stdout, stderr, previous['worker_exit_code'], previous['deployment']['model_id'])
                require(len(value['http_exchanges']) == 1, 'http-answer-count')
                exchange = value['http_exchanges'][0]
                require(exchange['response_content_type'].split(';', 1)[0].strip().lower() == 'application/json'
                        and exchange['response_content_encoding'].lower() == 'identity', 'http-headers')
                require(same(output['http_status'], receipt['http_status']) and content == receipt['content']
                        and output['response_body'] == receipt['response_body'] == exchange['response_body']
                        and same(exchange['http_status'], receipt['http_status']), 'http-worker-envelope-join')
            else:
                # A clean, valid response cannot be rewritten as a failure. A
                # local stop, timeout or pipe fault retains UNKNOWN even if a
                # response races with the stop; it proves no backend stop.
                failed = previous['worker_exit_code'] != 0 or bool(stderr) or any(previous_worker[name] is not None
                              for name in ('stop_reason', 'io_error', 'signal_error')) or previous_worker['timed_out']
                if not failed:
                    try:
                        raw_worker_result(stdout, stderr, previous['worker_exit_code'], previous['deployment']['model_id'])
                    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                        failed = True
                require(failed, 'fabricated-worker-error')
                # When a complete transport record exists, it must match the
                # independently captured HTTP bytes even for a rejected body.
                try:
                    output = parse(stdout, STDOUT_LIMIT)
                    keys(output, {'http_status', 'response_body'}, 'raw-worker')
                except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                    output = None
                if output is not None:
                    require(len(value['http_exchanges']) == 1
                            and same(output['http_status'], value['http_exchanges'][0]['http_status'])
                            and same(output['response_body'], value['http_exchanges'][0]['response_body']), 'http-worker-error-join')
        require((source_manifest is None) == (source_root is None), 'source-arguments')
        if source_manifest is not None:
            verify_sources(source_manifest, source_root)
        return verdict('PASS', [], model_outcome=previous['model_outcome'], snapshots=len(value['snapshots']),
                       source_files_verified=len(SOURCE_FILES) if source_manifest is not None else 0)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, OverflowError) as exc:
        return verdict('FAIL', [str(exc) or type(exc).__name__])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_record(parse(read(args.artifact)), source_manifest=parse(read(args.source_manifest)),
                               source_root=args.source_root)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as exc:
        result = verdict('FAIL', [str(exc) or type(exc).__name__])
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0 if result['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
