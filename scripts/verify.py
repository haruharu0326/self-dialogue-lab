"""Local verification harness; no dependency installation or real model requests."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_counts(path, kind):
    if kind == 'pytest':
        cases = list(ET.parse(path).getroot().iter('testcase'))
        total = len(cases)
        skipped = sum(case.find('skipped') is not None for case in cases)
        failed = sum(case.find('failure') is not None or case.find('error') is not None for case in cases)
    else:
        report = json.loads(path.read_text(encoding='utf-8'))
        total, skipped, failed = (report[key] for key in ('numTotalTests', 'numPendingTests', 'numFailedTests'))
        skipped += report.get('numTodoTests', 0)
        if report.get('success') is not True:
            raise ValueError('test runner reported failure')
    if any(type(value) is not int or value < 0 for value in (total, skipped, failed)) or total == 0 or skipped + failed > total:
        raise ValueError('invalid or empty test counts')
    if failed:
        raise ValueError('failed test cases')
    return total, skipped


def run_stage(name, command, report=None, kind=None):
    print(f'\n--- {name} ---', flush=True)
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return {'name': name, 'status': 'failed', 'skipped': 0, 'detail': f'exit code {result.returncode}; see runner output above'}
        total, skipped = test_counts(report, kind) if report else (None, 0)
        detail = f'{total - skipped} passed, {skipped} skipped' if total is not None else 'passed'
        return {'name': name, 'status': 'incomplete' if skipped else 'passed', 'skipped': skipped, 'detail': detail}
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        # Avoid printing environment or arbitrary command errors containing credentials.
        return {'name': name, 'status': 'failed', 'skipped': 0, 'detail': type(error).__name__}


def smoke(temp):
    print('\n--- startup ---', flush=True)
    env = os.environ.copy()
    for name in ('GEMINI_API_KEY', 'VOICE_MODEL_PATH', 'SENTIMENT_MODEL_PATH'):
        env.pop(name, None)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env.update(SELF_DIALOGUE_PERSONAL_DB=str(temp / 'smoke.sqlite3'),
               SELF_DIALOGUE_HOST='127.0.0.1', SELF_DIALOGUE_PORT=str(port))
    process = subprocess.Popen([sys.executable, str(ROOT / 'src/app.py')], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    opener = build_opener(ProxyHandler({}))

    def get(path):
        with opener.open(f'http://127.0.0.1:{port}{path}', timeout=1) as response:
            if response.status != 200:
                raise ValueError('unexpected HTTP status')
            return response.read()

    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise ValueError('server exited before readiness')
            try:
                if json.loads(get('/api/health')) != {'status': 'ok'}:
                    raise ValueError('unexpected health response')
                break
            except (URLError, TimeoutError, ConnectionError):
                if time.monotonic() >= deadline:
                    raise ValueError('startup timeout') from None
                time.sleep(0.2)
        state = json.loads(get('/api/state'))
        if state != {'configured': False, 'voiceConfigured': False, 'toneConfigured': False,
                     'exchanges': [], 'memories': []}:
            raise ValueError('initial state was not isolated')
        page = get('/')
        if b'<div id="root">' not in page or b'/assets/' not in page:
            raise ValueError('built React page missing')
        if not (temp / 'smoke.sqlite3').is_file():
            raise ValueError('isolated database missing')
        return {'name': 'startup', 'status': 'passed', 'skipped': 0, 'detail': 'health, empty state, React page: HTTP 200'}
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def exit_code(results, allow_skips=False):
    if any(result['status'] in ('failed', 'not-run') for result in results):
        return 1
    return 2 if any(result['skipped'] for result in results) and not allow_skips else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-skips', action='store_true', help='allow skipped tests while still reporting them')
    parser.add_argument('--report', type=Path, help='write a JSON summary for the review harness')
    args = parser.parse_args(argv)
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm') or ('npm.cmd' if os.name == 'nt' else 'npm')
    with tempfile.TemporaryDirectory(prefix='.test-temp-verify-', dir=ROOT) as directory:
        temp = Path(directory)
        results = [run_stage('pytest', [sys.executable, '-m', 'pytest', '-q',
                    f'--basetemp={temp / "pytest"}', f'--junitxml={temp / "pytest.xml"}', '-rs'],
                    temp / 'pytest.xml', 'pytest')]
        results.append(run_stage('vitest', [npm, '--prefix', 'frontend', 'test', '--',
                       '--reporter=json', f'--outputFile={temp / "vitest.json"}'], temp / 'vitest.json', 'vitest'))
        results.append(run_stage('build (includes typecheck)', [npm, '--prefix', 'frontend', 'run', 'build']))
        if results[-1]['status'] != 'passed':
            results.append({'name': 'startup', 'status': 'not-run', 'skipped': 0, 'detail': 'build failed'})
        else:
            try:
                results.append(smoke(temp))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                results.append({'name': 'startup', 'status': 'failed', 'skipped': 0, 'detail': type(error).__name__})
    print('\nVerification summary:', flush=True)
    for result in results:
        print(f"{result['name']}: {result['status']} ({result['detail']})")
    code = exit_code(results, args.allow_skips)
    if args.report:
        args.report.write_text(json.dumps({'exit_code': code, 'stages': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Exit code: {code}. Browser, Docker, real models/API and specification review are not covered.')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
