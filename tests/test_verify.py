"""The harness must not turn missing evidence or skipped tests into full success."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest


@pytest.fixture
def harness():
    spec = spec_from_file_location('verify', Path(__file__).resolve().parents[1] / 'scripts/verify.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('allow,expected', [(False, 2), (True, 0)])
def test_skips_are_incomplete_and_failures_always_fail(harness, allow, expected):
    results = [{'status': 'incomplete', 'skipped': 8}]
    assert harness.exit_code(results, allow) == expected
    for status in ('failed', 'not-run'):
        assert harness.exit_code(results + [{'status': status, 'skipped': 0}], allow) == 1


def test_reports_count_skips_and_reject_empty_or_failed_evidence(harness, tmp_path):
    xml = tmp_path / 'pytest.xml'
    xml.write_text('<testsuites><testsuite><testcase/><testcase><skipped/></testcase></testsuite></testsuites>')
    assert harness.test_counts(xml, 'pytest') == (2, 1)
    xml.write_text('<testsuites><testsuite><testcase><failure/></testcase></testsuite></testsuites>')
    with pytest.raises(ValueError):
        harness.test_counts(xml, 'pytest')
    report = tmp_path / 'vitest.json'
    report.write_text(json.dumps({'success': True, 'numTotalTests': 3, 'numPendingTests': 1, 'numFailedTests': 0}))
    assert harness.test_counts(report, 'vitest') == (3, 1)
    report.write_text(json.dumps({'success': True, 'numTotalTests': 0, 'numPendingTests': 0, 'numFailedTests': 0}))
    with pytest.raises(ValueError):
        harness.test_counts(report, 'vitest')


def test_successful_command_without_report_is_failure(harness, monkeypatch, tmp_path):
    class Result:
        returncode = 0
    monkeypatch.setattr(harness.subprocess, 'run', lambda *args, **kwargs: Result())
    assert harness.run_stage('pytest', ['unused'], tmp_path / 'missing.xml', 'pytest')['status'] == 'failed'


def test_failure_continues_other_stages_but_build_failure_blocks_smoke(harness, monkeypatch, capsys):
    stages = []

    def stage(name, *args):
        stages.append(name)
        return {'name': name, 'status': 'failed', 'skipped': 0, 'detail': 'synthetic failure'}

    monkeypatch.setattr(harness, 'run_stage', stage)
    monkeypatch.setattr(harness, 'smoke', lambda *args: pytest.fail('must not start stale build'))
    assert harness.main(['--allow-skips']) == 1
    assert stages == ['pytest', 'vitest', 'build (includes typecheck)']
    assert 'startup: not-run' in capsys.readouterr().out
