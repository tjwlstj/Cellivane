#!/usr/bin/env python3
"""Run the fixed ABC/CBA calibration sequentially; retain every phase.

No concurrent workers, automatic retries, or changed model/quantization. Reader
replays are performed after the six model runs to avoid their CPU/I/O load in
the measured phases. The manifest records local execution order, not host
attestation. This orchestrator is outside the 21-file inference family.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
ORDER = ("reference", "gpu29", "gpu29-threads8", "gpu29-threads8", "gpu29", "reference")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('model-file', 'asset-root', 'storage-root'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPO / 'tools/hosted'))
    sys.path.insert(0, str(REPO / 'hosted/experimental'))
    from cellivane_bridge.storage import local_root
    root = local_root(args.storage_root)
    directory = local_root(root / 'calibration-matrices') / str(uuid4())
    directory.mkdir()
    record = {'schema_version': 1, 'family': 'cellivane-efficiency-orchestration-v1', 'run_id': directory.name,
        'outcome': 'FAILED', 'error': None, 'started_at_utc': stamp(), 'completed_at_utc': None,
        'order': list(ORDER), 'phases': [],
        'orchestrator_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'sequential-local-model-runs; independent-replays-and-selection-pending; no execution attestation'}
    clock = time.perf_counter()
    reference = None
    try:
        for index, profile in enumerate(ORDER):
            phase = {'index': index, 'round': 0 if index < 3 else 1, 'profile': profile,
                'started_at_utc': stamp(), 'started_s': time.perf_counter() - clock}
            record['phases'].append(phase)
            print(json.dumps({'phase': index, 'profile': profile, 'state': 'START'}), flush=True)
            command = [sys.executable, '-B', str(REPO / 'tools/hosted/cellivane_seed_optimize.py'),
                '--mode', 'calibrate', '--profile', profile, '--model-file', args.model_file,
                '--asset-root', args.asset_root, '--storage-root', str(root)]
            phase['argv'] = command
            output = directory / f'{index:02d}-{profile}.stdout.log'
            try:
                result = subprocess.run(command, cwd=REPO, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
            except subprocess.TimeoutExpired as exc:
                raw = exc.stdout or b''
                with output.open('xb') as stream:
                    stream.write(raw)
                phase.update(completed_at_utc=stamp(), completed_s=time.perf_counter() - clock,
                    exit_code=None, timed_out=True, output={'path': str(output), 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})
                raise RuntimeError('calibration-phase-timeout:' + str(index)) from exc
            with output.open('xb') as stream:
                stream.write(result.stdout)
            phase.update(completed_at_utc=stamp(), completed_s=time.perf_counter() - clock,
                         exit_code=result.returncode, output={'path': str(output), 'bytes': len(result.stdout),
                             'sha256': sha256(result.stdout).hexdigest()})
            if result.returncode != 0:
                raise RuntimeError('calibration-phase-failed:' + str(index))
            terminal = json.loads(result.stdout.decode('utf-8').splitlines()[-1])
            summary_path = Path(terminal['summary']).resolve(strict=True)
            if not summary_path.is_relative_to(root / 'efficiency-runs'):
                raise ValueError('calibration-summary-outside-root')
            raw = summary_path.read_bytes()
            summary = json.loads(raw)
            if (terminal.get('acceptance') != 'PASS' or summary.get('acceptance') != 'PASS'
                    or summary.get('outcome') != 'COMPLETED' or summary.get('mode') != 'calibrate'
                    or summary.get('profile', {}).get('name') != profile or len(summary.get('rows', [])) != 56):
                raise ValueError('calibration-phase-contract')
            identity = {name: summary[name] for name in ('source', 'host_profile', 'model', 'corpus_sha256')}
            identity['backend_tree_sha256'] = summary['backend']['tree_sha256']
            if reference is not None and identity != reference:
                raise ValueError('calibration-phase-identity-drift')
            reference = identity
            phase['summary'] = {'path': str(summary_path), 'sha256': sha256(raw).hexdigest(), 'run_id': summary['run_id']}
            print(json.dumps({'phase': index, 'profile': profile, 'state': 'COMPLETED',
                'summary': str(summary_path), 'median_wall_s': summary['metrics']['median_wall_s']}), flush=True)
        record['outcome'] = 'MODEL_RUNS_COMPLETED'
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        record['error'] = type(exc).__name__ + ':' + str(exc)[:256]
    finally:
        record['completed_at_utc'] = stamp()
        record['wall_s'] = time.perf_counter() - clock
        save(directory / 'orchestration.json', record)
        print(json.dumps({'outcome': record['outcome'], 'manifest': str(directory / 'orchestration.json'),
            'error': record['error']}), flush=True)
    return 0 if record['outcome'] == 'MODEL_RUNS_COMPLETED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
