#!/usr/bin/env python3
"""Independent SERVE-P0 messages protocol and saved Task evidence verifier.

Only host verification modules are imported. A consistent fixture artifact
does not qualify a real engine, model computation, stop authority or liveness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import uuid
from pathlib import Path

from verify_boot import parse, keys, require, integer
from verify_agent import SERVE_SOURCES

LIMIT = 4 * 1024 * 1024
# Independently mirror the producer's raw JSON and retained worker pipe limits.
# output_bytes is a cumulative drain counter, so ERROR evidence may exceed them.
WIRE_LIMIT = 16384
STDOUT_LIMIT = 128 * 1024
STDERR_LIMIT = 16 * 1024
STATE_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'owner', 'deployment',
    'source_before', 'management_before', 'backend_expected', 'space_context', 'user_prompt',
    'request_body', 'request_sha256', 'revision', 'phase', 'model_outcome', 'accepted_ns',
    'updated_ns', 'started_ns', 'cancel_requested_ns', 'finished_ns', 'worker_process_id',
    'worker_exit_code', 'inference_receipt', 'backend_stop', 'backend_stopped_ns', 'not_started_reason'}
STATIC_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'owner', 'deployment',
    'source_before', 'management_before', 'backend_expected', 'space_context', 'user_prompt',
    'request_body', 'request_sha256', 'accepted_ns'}
ENVELOPE_KEYS = {'schema_version', 'adapter_kind', 'request_id', 'deployment', 'request_body',
    'request_sha256', 'response_body', 'response_sha256', 'content', 'usage', 'outcome', 'error',
    'evidence_kind', 'elapsed_ns'}
WORKER_KEYS = {'request_id', 'done', 'worker_pid', 'worker_exit_code', 'worker_exit_observed_monotonic_ns',
    'cancel_requested', 'timed_out', 'stop_reason', 'terminate_requested', 'kill_requested',
    'signal_error', 'io_error', 'output_bytes', 'receipt'}
NULL_BINDING = ('source_before', 'management_before', 'backend_expected', 'space_context',
                'user_prompt', 'backend_stop', 'backend_stopped_ns')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def same(left, right):
    return encoded(left) == encoded(right)


def identifier(value):
    require(type(value) is str and str(uuid.UUID(value)) == value and uuid.UUID(value).int != 0,
            'fixture_uuid')


def text(value, maximum=128):
    return type(value) is str and 0 < len(value) <= maximum and all(c.isprintable() for c in value)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    path = Path(path)
    require(stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink(), 'fixture_regular_file')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    require(len(raw) <= LIMIT, 'fixture_size')
    return raw


def wire(value):
    require(type(value) is str and len(value.encode('utf-8')) <= WIRE_LIMIT, 'fixture_wire_size')
    record = parse(value.encode('utf-8'))
    require(type(record) is dict, 'fixture_wire_object')
    return record


def deployment(value):
    keys(value, {'engine', 'model_id', 'service_id', 'instance_id', 'start_generation', 'ownership'},
         'fixture_deployment')
    require(same(value['engine'], {'adapter_kind': 'messages-fixture', 'wire_protocol': 'messages-json',
                'evidence_kind': 'fixture', 'contract_version': 1}), 'fixture_engine')
    identifier(value['service_id'])
    identifier(value['instance_id'])
    require(text(value['model_id']) and integer(value['start_generation'], 1)
            and value['ownership'] in ('managed', 'attached'), 'fixture_deployment')


def request(value):
    body = wire(value['request_body'])
    keys(body, {'model', 'messages', 'stream'}, 'fixture_request')
    require(body['model'] == value['deployment']['model_id'] and body['stream'] is False,
            'fixture_request_model')
    messages = body['messages']
    require(type(messages) is list and 1 <= len(messages) <= 16, 'fixture_messages')
    total, user = 0, False
    for message in messages:
        keys(message, {'role', 'content'}, 'fixture_message')
        content = message['content']
        require(message['role'] in ('system', 'user', 'assistant') and type(content) is str
                and content.strip() and all(ord(c) >= 32 or c in '\n\t' for c in content)
                and not any(mark in content for mark in ('<|im_start|>', '<|im_end|>', '<think>')),
                'fixture_messages')
        total += len(content.encode('utf-8'))
        user |= message['role'] == 'user'
    require(total <= 4096 and user, 'fixture_messages')
    require(encoded(body) == value['request_body'].encode('utf-8')
            and digest(value['request_body'].encode('utf-8')) == value['request_sha256'],
            'fixture_request_bytes')


def envelope(value, row, *, template=False):
    keys(value, ENVELOPE_KEYS, 'fixture_envelope')
    require(same(value['schema_version'], 1) and value['adapter_kind'] == 'messages-fixture'
            and value['evidence_kind'] == 'fixture' and value['usage'] is None
            and integer(value['elapsed_ns']), 'fixture_envelope_boundary')
    require(all(same(value[name], row[name]) for name in
                ('request_id', 'deployment', 'adapter_kind', 'request_body', 'request_sha256')),
            'fixture_envelope_join')
    if template:
        require(value['outcome'] == 'ERROR' and value['error'] is None and same(value['elapsed_ns'], 0)
                and all(value[name] is None for name in ('response_body', 'response_sha256', 'content')),
                'fixture_template')
        return
    require(value['outcome'] in ('OK', 'ERROR'), 'fixture_envelope_outcome')
    if value['outcome'] == 'ERROR':
        require(value['error'] in ('backend-failed', 'backend-timeout')
                and all(value[name] is None for name in ('response_body', 'response_sha256', 'content')),
                'fixture_envelope_error')
        return
    require(value['error'] is None, 'fixture_envelope_error')
    response = wire(value['response_body'])
    keys(response, {'id', 'model', 'choices'}, 'fixture_response')
    require(text(response['id']) and response['model'] == row['deployment']['model_id']
            and type(response['choices']) is list and len(response['choices']) == 1,
            'fixture_response_model')
    choice = response['choices'][0]
    keys(choice, {'index', 'message', 'finish_reason'}, 'fixture_choice')
    keys(choice['message'], {'role', 'content'}, 'fixture_assistant')
    require(same(choice['index'], 0) and choice['finish_reason'] == 'stop'
            and choice['message']['role'] == 'assistant'
            and type(choice['message']['content']) is str and choice['message']['content'].strip(),
            'fixture_response_content')
    require(value['content'] == choice['message']['content']
            and digest(value['response_body'].encode('utf-8')) == value['response_sha256'],
            'fixture_response_bytes')


def state(row):
    keys(row, STATE_KEYS, 'fixture_task')
    require(same(row['schema_version'], 2) and row['adapter_kind'] == 'messages-fixture'
            and all(row[name] is None for name in NULL_BINDING), 'fixture_task_unbound')
    identifier(row['request_id'])
    deployment(row['deployment'])
    keys(row['owner'], {'host_boot_id', 'process_id', 'process_start_ticks', 'uid'}, 'fixture_owner')
    identifier(row['owner']['host_boot_id'])
    require(integer(row['owner']['process_id'], 1) and integer(row['owner']['process_start_ticks'], 1)
            and integer(row['owner']['uid']), 'fixture_owner')
    request(row)
    require(integer(row['accepted_ns']) and integer(row['updated_ns'])
            and row['updated_ns'] >= row['accepted_ns'] and integer(row['revision'], 1)
            and row['revision'] <= 8, 'fixture_task_clock')
    for name in ('started_ns', 'cancel_requested_ns', 'finished_ns'):
        require(row[name] is None or integer(row[name])
                and row['accepted_ns'] <= row[name] <= row['updated_ns'], 'fixture_task_clock')
    worker, code, phase = row['worker_process_id'], row['worker_exit_code'], row['phase']
    require(worker is None or integer(worker, 1) and worker != row['owner']['process_id'], 'fixture_task_worker')
    require((worker is None) == (row['started_ns'] is None), 'fixture_task_start')
    require(code is None or type(code) is int and -(1 << 31) <= code < 1 << 32, 'fixture_task_exit')
    require(phase in ('ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'FINISHED'), 'fixture_task_phase')
    if phase == 'ACCEPTED':
        require(worker is None and row['cancel_requested_ns'] is None and row['revision'] == 1
                and row['updated_ns'] == row['accepted_ns'], 'fixture_task_admission')
    if phase == 'RUNNING':
        require(worker is not None and row['cancel_requested_ns'] is None and row['revision'] == 2,
                'fixture_task_running')
    if phase == 'CANCEL_REQUESTED':
        require(row['cancel_requested_ns'] is not None, 'fixture_task_cancel')
    if phase != 'FINISHED':
        require(all(row[name] is None for name in
                    ('model_outcome', 'finished_ns', 'worker_exit_code', 'inference_receipt', 'not_started_reason')),
                'fixture_task_pending')
        return
    outcome, receipt = row['model_outcome'], row['inference_receipt']
    require(outcome in ('ANSWERED', 'UNKNOWN', 'NOT_STARTED') and row['finished_ns'] is not None,
            'fixture_task_finished')
    if outcome == 'NOT_STARTED':
        require(worker is None and code is None and receipt is None
                and row['not_started_reason'] in ('cancel-before-dispatch', 'dispatch-failed'), 'fixture_not_started')
        require(row['not_started_reason'] != 'cancel-before-dispatch' or row['cancel_requested_ns'] is not None,
                'fixture_cancel_not_started')
    else:
        require(worker is not None and code is not None and row['not_started_reason'] is None
                and row['finished_ns'] >= row['started_ns'], 'fixture_finished_worker')
        if receipt is not None:
            envelope(receipt, row)
        require((outcome == 'ANSWERED') == (receipt is not None and receipt['outcome'] == 'OK')
                and (outcome != 'ANSWERED' or code == 0), 'fixture_model_outcome')
    require(outcome == 'UNKNOWN' or row['cancel_requested_ns'] is None
            or row['cancel_requested_ns'] <= row['finished_ns'], 'fixture_late_cancel')


def worker_progress(value, row):
    if row['worker_process_id'] is None:
        require(value is None, 'fixture_worker_not_dispatched')
        return
    keys(value, WORKER_KEYS, 'fixture_worker')
    require(value['request_id'] == row['request_id'] and same(value['worker_pid'], row['worker_process_id']),
            'fixture_worker_identity')
    require(all(type(value[name]) is bool for name in
                ('done', 'cancel_requested', 'timed_out', 'terminate_requested', 'kill_requested')),
            'fixture_worker_flags')
    keys(value['output_bytes'], {'stdout', 'stderr'}, 'fixture_worker_bytes')
    require(all(integer(number) for number in value['output_bytes'].values()), 'fixture_worker_bytes')
    require(value['io_error'] in (None, 'stdout-limit', 'stderr-limit', 'stdout-read', 'stderr-read',
                                 'stdout-close', 'stderr-close'), 'fixture_worker_io_error')
    for name, limit in (('stdout', STDOUT_LIMIT), ('stderr', STDERR_LIMIT)):
        require(value['io_error'] != name + '-limit' or value['output_bytes'][name] > limit,
                'fixture_worker_overflow')
    require(value['stop_reason'] in (None, 'cancel', 'timeout', 'close', 'io-failed')
            and (value['cancel_requested'] is False or row['cancel_requested_ns'] is not None),
            'fixture_worker_cancel')
    code, observed = value['worker_exit_code'], value['worker_exit_observed_monotonic_ns']
    require(code is None or type(code) is int and -(1 << 31) <= code < 1 << 32, 'fixture_worker_exit')
    require((code is None) == (observed is None), 'fixture_worker_exit_time')
    if observed is not None:
        require(integer(observed) and row['accepted_ns'] <= observed <= row['updated_ns'], 'fixture_worker_exit_time')
    if value['done']:
        require(code is not None and value['receipt'] is not None, 'fixture_worker_terminal')
        envelope(value['receipt'], row)
        require(value['receipt']['elapsed_ns'] <= observed - row['accepted_ns'], 'fixture_worker_elapsed')
        overflow = (value['output_bytes']['stdout'] > STDOUT_LIMIT
                    or value['output_bytes']['stderr'] > STDERR_LIMIT)
        require(not overflow or value['receipt']['outcome'] == 'ERROR' and value['io_error'] is not None,
                'fixture_worker_overflow')
        if value['receipt']['outcome'] == 'OK':
            require(code == 0 and value['timed_out'] is False and value['stop_reason'] is None
                    and value['signal_error'] is None and value['io_error'] is None
                    and same(value['output_bytes']['stderr'], 0), 'fixture_worker_answer')
            require(value['output_bytes']['stdout'] == len(encoded({'response_body': value['receipt']['response_body']})),
                    'fixture_worker_answer_bytes')
        else:
            require((value['receipt']['error'] == 'backend-timeout') == value['timed_out'], 'fixture_worker_timeout')
    else:
        require(value['receipt'] is None, 'fixture_worker_pending_receipt')
    if row['phase'] == 'FINISHED':
        require(value['done'] and same(code, row['worker_exit_code'])
                and same(value['receipt'], row['inference_receipt']), 'fixture_worker_final_join')


def transition(previous, current):
    require(current['revision'] == previous['revision'] + 1
            and current['updated_ns'] >= previous['updated_ns']
            and all(same(current[name], previous[name]) for name in STATIC_KEYS), 'fixture_task_transition')
    at = current['updated_ns']
    base = {**previous, 'revision': current['revision'], 'updated_ns': at}
    allowed = []
    if previous['phase'] == 'ACCEPTED':
        allowed.append({**base, 'phase': 'RUNNING', 'worker_process_id': current['worker_process_id'], 'started_ns': at})
    if previous['cancel_requested_ns'] is None and (previous['phase'] != 'FINISHED' or previous['model_outcome'] == 'UNKNOWN'):
        allowed.append({**base, 'phase': 'FINISHED' if previous['phase'] == 'FINISHED' else 'CANCEL_REQUESTED',
                        'cancel_requested_ns': at})
    if previous['phase'] != 'FINISHED' and previous['worker_process_id'] is None:
        allowed.append({**base, 'phase': 'FINISHED', 'model_outcome': 'NOT_STARTED',
                        'finished_ns': at, 'not_started_reason': current['not_started_reason']})
    if previous['phase'] in ('RUNNING', 'CANCEL_REQUESTED') and previous['worker_process_id'] is not None:
        allowed.append({**base, 'phase': 'FINISHED', 'finished_ns': at, 'model_outcome': current['model_outcome'],
                        'worker_exit_code': current['worker_exit_code'], 'inference_receipt': current['inference_receipt']})
    require(any(same(current, candidate) for candidate in allowed), 'fixture_task_transition')


def verify_sources(manifest, source_root):
    keys(manifest, {'schema_version', 'source_hashes'}, 'fixture_source_manifest')
    require(same(manifest['schema_version'], 1), 'fixture_source_schema')
    keys(manifest['source_hashes'], set(SERVE_SOURCES), 'fixture_source_inventory')
    for name, checksum in manifest['source_hashes'].items():
        require(type(checksum) is str and re.fullmatch('[0-9a-f]{64}', checksum) is not None, 'fixture_source_hash')
        require(digest(read(Path(source_root) / name)) == checksum, 'fixture_source_hash:' + name)


def verify_record(value, *, source_manifest=None, source_root=None):
    try:
        keys(value, {'schema_version', 'snapshots', 'completed'}, 'fixture_bundle')
        require(same(value['schema_version'], 1) and type(value['snapshots']) is list
                and 2 <= len(value['snapshots']) <= 8 and type(value['completed']) is list
                and len(value['completed']) == 1, 'fixture_bundle_shape')
        previous, template = None, None
        for snapshot in value['snapshots']:
            keys(snapshot, {'schema_version', 'request_state', 'receipt_template', 'worker_progress',
                            'control_failure', 'backend_observation'}, 'fixture_snapshot')
            require(same(snapshot['schema_version'], 1) and snapshot['control_failure'] is None
                    and snapshot['backend_observation'] is None, 'fixture_snapshot_failure')
            row = snapshot['request_state']
            state(row)
            envelope(snapshot['receipt_template'], row, template=True)
            worker_progress(snapshot['worker_progress'], row)
            if previous is None:
                require(row['phase'] == 'ACCEPTED', 'fixture_initial_admission')
                template = snapshot['receipt_template']
            else:
                require(same(snapshot['receipt_template'], template), 'fixture_template_rewrite')
                transition(previous, row)
            previous = row
        require(previous['phase'] == 'FINISHED' and same(value['completed'][0], previous), 'fixture_finalization')
        require((source_manifest is None) == (source_root is None), 'fixture_source_arguments')
        if source_manifest is not None:
            verify_sources(source_manifest, source_root)
        return {'schema_version': 1, 'outcome': 'PASS', 'reasons': [], 'evidence_kind': 'fixture',
                'model_outcome': previous['model_outcome'], 'snapshots': len(value['snapshots']),
                'source_files_verified': len(SERVE_SOURCES) if source_manifest is not None else 0,
                'real_engine_compatibility': False, 'process_liveness_verified': False}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        return {'schema_version': 1, 'outcome': 'FAIL', 'reasons': [str(exc) or type(exc).__name__],
                'evidence_kind': 'fixture', 'real_engine_compatibility': False, 'process_liveness_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2] / 'hosted/linux')
    args = parser.parse_args()
    try:
        value = verify_record(parse(read(args.artifact)), source_manifest=parse(read(args.source_manifest)),
                              source_root=args.source_root)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        value = {'schema_version': 1, 'outcome': 'FAIL', 'reasons': [str(exc) or type(exc).__name__]}
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0 if value['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
