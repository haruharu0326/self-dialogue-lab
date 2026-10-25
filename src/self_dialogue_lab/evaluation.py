"""Isolated fictional response evaluation; never opens the application database."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time

from . import gemini
from .responder import Reply

METRICS = ('faithfulness', 'non_assumption', 'useful_question')
DEFAULT_CASES = Path(__file__).with_name('samples') / 'evaluation.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load_cases(path):
    suite = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(suite, dict) or suite.get('fictional') is not True or not suite.get('version'):
        raise ValueError('fictional suite and version required')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('cases required')
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'] or case['id'] in ids:
            raise ValueError('unique case id required')
        ids.add(case['id'])
        if not isinstance(case.get('turns'), list) or not case['turns'] or any(
                not isinstance(turn, str) or not turn.strip() for turn in case['turns']):
            raise ValueError('nonempty turns required')
        records = case.get('records', [])
        if not isinstance(records, list):
            raise ValueError('records must be a list')
        record_ids = set()
        for record in records:
            if (not isinstance(record, dict) or type(record.get('id')) is not int
                    or record['id'] in record_ids or record.get('superseded', 0)
                    or not isinstance(record.get('thought'), str)):
                raise ValueError('only unique current records allowed')
            record_ids.add(record['id'])
    return suite


class EvaluationMock:
    """Fixed reply for testing the harness, independent of input semantics."""

    model = 'mock-fixed-v1'

    def respond(self, *args, **kwargs):
        return Reply('モック・固定応答。入力を理解した結果ではありません。',
                     'どの前提をもう少し考えたいですか？', [])


def run(suite, responder, *, live=False, repeat=1):
    if type(repeat) is not int or not 1 <= repeat <= 20:
        raise ValueError('repeat must be 1..20')
    source = Path(gemini.__file__).read_text(encoding='utf-8')
    report = {
        'format_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'live' if live else 'mock-fixed', 'model': responder.model,
        'suite_hash': digest(suite), 'suite': suite, 'repeat': repeat,
        'prompt_hash': digest(gemini.SYSTEM), 'adapter_hash': digest(source),
        'generation_config': gemini.GENERATION_CONFIG,
        'generation_config_hash': digest(gemini.GENERATION_CONFIG),
        'runner_hash': digest(Path(__file__).read_text(encoding='utf-8')),
        'results': [],
    }
    for case in suite['cases']:
        for iteration in range(repeat):
            result = {'case_id': case['id'], 'iteration': iteration + 1, 'turns': [],
                      'status': 'passed', 'scores': dict.fromkeys(METRICS), 'note': ''}
            history = []
            records = case.get('records', [])
            for message in case['turns']:
                start = time.perf_counter()
                try:
                    reply = responder.respond(message, '', records, history=history[-20:], demo=True)
                    if (not isinstance(reply.interpretation, str) or not reply.interpretation.strip()
                            or not isinstance(reply.question, str) or not isinstance(reply.references, list)
                            or any(ref not in records for ref in reply.references)):
                        raise ValueError('invalid reply')
                    turn = {'input': message, 'reply': asdict(reply), 'status': 'passed'}
                    history.extend([{'role': 'user', 'text': message},
                                    {'role': 'model', 'text': reply.interpretation + '\n' + reply.question}])
                except Exception:
                    # Exception text can contain secrets or remote request bodies.
                    turn = {'input': message, 'status': 'failed', 'error': 'response_failed'}
                    result['status'] = 'failed'
                turn['elapsed_seconds'] = time.perf_counter() - start
                result['turns'].append(turn)
                if turn['status'] == 'failed':
                    break
            report['results'].append(result)
    return report


def summary(report):
    rows = report['results']
    elapsed = [turn['elapsed_seconds'] for row in rows for turn in row['turns']]
    scores = {}
    for metric in METRICS:
        values = [row['scores'][metric] for row in rows if row['status'] == 'passed'
                  and row['scores'][metric] is not None]
        if any(type(value) is not int or not 0 <= value <= 2 for value in values):
            raise ValueError('scores must be null or integer 0..2')
        scores[metric] = {'rated': len(values), 'mean': statistics.mean(values) if values else None}
    return {'runs': len(rows), 'failed': sum(row['status'] != 'passed' for row in rows),
            'turns': len(elapsed), 'mean_seconds': statistics.mean(elapsed) if elapsed else None,
            'scores': scores}


def compare(left, right):
    if (left['format_version'] != 1 or right['format_version'] != 1
            or left['suite_hash'] != right['suite_hash'] or left['mode'] != right['mode']):
        raise ValueError('comparison requires identical suite and mode')
    conditions = ('model', 'prompt_hash', 'generation_config_hash', 'adapter_hash', 'runner_hash', 'repeat')
    return {'mode': left['mode'], 'condition_changes': {
        key: [left[key], right[key]] for key in conditions if left[key] != right[key]},
        'baseline': summary(left), 'candidate': summary(right)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    execute = commands.add_parser('run')
    execute.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    execute.add_argument('--output', type=Path, required=True)
    execute.add_argument('--repeat', type=int, default=1, choices=range(1, 21))
    execute.add_argument('--live', action='store_true', help='send fictional cases to Gemini API')
    comparison = commands.add_parser('compare')
    comparison.add_argument('baseline', type=Path)
    comparison.add_argument('candidate', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'compare':
            result = compare(json.loads(args.baseline.read_text(encoding='utf-8')),
                             json.loads(args.candidate.read_text(encoding='utf-8')))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        suite = load_cases(args.cases)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Reserve before any billable requests; existing reports are never overwritten.
        with args.output.open('x', encoding='utf-8') as output:
            report = run(suite, gemini.GeminiResponder() if args.live else EvaluationMock(),
                         live=args.live, repeat=args.repeat)
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps({'mode': report['mode'], **summary(report)}, ensure_ascii=False, indent=2))
        return 1 if any(row['status'] == 'failed' for row in report['results']) else 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Evaluation failed: check fictional cases, report format, scores and output path.')
        return 2
