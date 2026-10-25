import copy
import json

import pytest

from self_dialogue_lab.evaluation import (
    DEFAULT_CASES, EvaluationMock, compare, load_cases, main, run, summary,
)


def test_multiturn_history_repetitions_and_unrated_scores():
    class Spy(EvaluationMock):
        def __init__(self):
            self.histories = []

        def respond(self, *args, **kwargs):
            self.histories.append(copy.deepcopy(kwargs['history']))
            return super().respond(*args, **kwargs)

    spy = Spy()
    report = run(load_cases(DEFAULT_CASES), spy, repeat=2)
    assert len(report['results']) == 6
    assert spy.histories[0] == []
    assert spy.histories[1][1]['role'] == 'model'
    assert spy.histories[2] == []
    assert summary(report)['scores']['faithfulness'] == {'rated': 0, 'mean': None}
    assert report['mode'] == 'mock-fixed'


def test_cli_persistence_and_no_overwrite(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail('default CLI must not instantiate Gemini')
    monkeypatch.setattr('self_dialogue_lab.evaluation.gemini.GeminiResponder', forbidden)
    path = tmp_path / 'run.json'
    assert main(['run', '--output', str(path)]) == 0
    original = path.read_bytes()
    assert json.loads(original)['results'][0]['turns'][0]['reply']['references'] == []
    assert main(['run', '--output', str(path)]) == 2
    assert path.read_bytes() == original
    assert main(['compare', str(path), str(path)]) == 0


@pytest.mark.parametrize('change', ['fictional', 'duplicate', 'superseded', 'blank'])
def test_invalid_cases_rejected(tmp_path, change):
    suite = load_cases(DEFAULT_CASES)
    if change == 'fictional':
        suite['fictional'] = False
    elif change == 'duplicate':
        suite['cases'].append(suite['cases'][0])
    elif change == 'superseded':
        suite['cases'][-1]['records'][0]['superseded'] = 1
    else:
        suite['cases'][0]['turns'] = [' ']
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(suite), encoding='utf-8')
    with pytest.raises(ValueError):
        load_cases(path)


def test_failure_is_sanitized_and_stops_sequence():
    class Broken(EvaluationMock):
        def respond(self, *args, **kwargs):
            raise RuntimeError('secret-key-and-remote-body')
    report = run(load_cases(DEFAULT_CASES), Broken())
    assert summary(report)['failed'] == 3
    assert all(len(row['turns']) == 1 for row in report['results'])
    assert 'secret-key' not in json.dumps(report)


def test_compare_conditions_scores_and_boundaries():
    baseline = run(load_cases(DEFAULT_CASES), EvaluationMock())
    candidate = copy.deepcopy(baseline)
    candidate['model'] = 'new-model'
    candidate['results'][0]['scores']['faithfulness'] = 2
    comparison = compare(baseline, candidate)
    assert comparison['candidate']['scores']['faithfulness'] == {'rated': 1, 'mean': 2}
    assert comparison['condition_changes']['model'] == ['mock-fixed-v1', 'new-model']
    candidate['results'][0]['scores']['faithfulness'] = 3
    with pytest.raises(ValueError):
        compare(baseline, candidate)
    for key in ('mode', 'suite_hash'):
        candidate = copy.deepcopy(baseline)
        candidate[key] = 'different'
        with pytest.raises(ValueError):
            compare(baseline, candidate)


def test_unknown_references_fail_automatic_check():
    class Wrong(EvaluationMock):
        def respond(self, *args, **kwargs):
            reply = super().respond(*args, **kwargs)
            reply.references = [{'id': 999}]
            return reply
    assert summary(run(load_cases(DEFAULT_CASES), Wrong()))['failed'] == 3


def test_live_runner_uses_production_adapter_with_fictional_payload():
    from io import BytesIO
    from self_dialogue_lab.gemini import GeminiResponder

    requests = []

    def transport(request, **kwargs):
        requests.append(json.loads(request.data))
        return BytesIO(json.dumps({'candidates': [{
            'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps({
                'interpretation': '架空ケースへの返答', 'question': 'なぜですか？',
                'reference_ids': [],
            })}]},
        }]}).encode())

    report = run(load_cases(DEFAULT_CASES), GeminiResponder(api_key='test-only', transport=transport), live=True)
    assert summary(report)['failed'] == 0
    payload = json.loads(requests[1]['contents'][0]['parts'][0]['text'])
    assert payload['demo'] is True
    assert len(payload['history']) == 2
    assert requests[0]['generationConfig'] == report['generation_config']
    assert 'test-only' not in json.dumps(report)
