"""開発チャット: 記録hookが残す範囲と、記録からスレッドを組み立てる規則。"""

import io
import json
import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = spec_from_file_location(name, ROOT / path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook():
    return load('log_activity_hook', '.claude/hooks/log_activity.py')


@pytest.fixture
def chat():
    return load('agent_chat_server', 'scripts/agent_chat.py')


def test_records_targets_but_not_file_contents_or_user_prompts(hook):
    write = hook.record({'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
                         'tool_input': {'file_path': 'C:\\repo\\src\\store.py', 'content': 'SECRET BODY'}}, now=1)
    assert write['summary'] == 'store.py'
    assert 'SECRET BODY' not in str(write)
    prompt = hook.record({'hook_event_name': 'UserPromptSubmit', 'prompt': 'PRIVATE THOUGHT'}, now=1)
    assert prompt['event'] == 'UserPromptSubmit' and 'PRIVATE THOUGHT' not in str(prompt)
    bash = hook.record({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                        'tool_input': {'command': 'python -m pytest -q\nsecond line'}}, now=1)
    assert bash['summary'] == 'python -m pytest -q'
    assert hook.record({'hook_event_name': 'Notification'}) is None


def test_agent_calls_keep_bounded_request_and_report(hook):
    pre = hook.record({'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_use_id': 'call1',
                       'tool_input': {'subagent_type': 'planner', 'description': '計画', 'prompt': 'x' * 9000}}, now=1)
    assert pre['subagent_type'] == 'planner' and pre['tool_use_id'] == 'call1'
    assert len(pre['prompt']) == hook.PROMPT_CHARS and pre['prompt'].endswith('…')
    post = hook.record({'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
                        'tool_input': {'subagent_type': 'planner'},
                        'tool_response': {'content': [{'type': 'text', 'text': '結論: 手順は3つ'}]}}, now=2)
    assert post['report'] == '結論: 手順は3つ'
    stop = hook.record({'hook_event_name': 'SubagentStop', 'agent_id': 'a1', 'last_assistant_message': '最終報告'}, now=3)
    assert stop['report'] == '最終報告'


def bash_summary(hook, command, tool='Bash'):
    return hook.record({'hook_event_name': 'PreToolUse', 'tool_name': tool,
                        'tool_input': {'command': command}}, now=1)['summary']


@pytest.mark.parametrize('command, expected', [
    ('GEMINI_API_KEY=abc123 python app.py', 'GEMINI_API_KEY=*** python app.py'),
    ('export TOKEN="s3 cr3t" && run', 'export TOKEN=*** && run'),
    ("$env:GEMINI_API_KEY = 'abc123'; python app.py", '$env:GEMINI_API_KEY = ***; python app.py'),
    ('$env:GEMINI_API_KEY="abc123"', '$env:GEMINI_API_KEY=***'),
    ('curl -H "Authorization: token abc123" x', 'curl -H "Authorization: ***" x'),
    ('curl -H "X-Auth: Bearer abc123" x', 'curl -H "X-Auth: ***" x'),
    ('curl -H "X-Custom: Bearer abc123" x', 'curl -H "X-Custom: Bearer ***" x'),
    ('curl https://u:pw@example.com/a?key=abc&b=1', 'curl https://***@example.com/a?***'),
    ('tool --token=abc123 --api-key xyz', 'tool --token=*** --api-key ***'),
    ('Connect -Password "p w" --secret=s', 'Connect -Password *** --secret=***'),
    # URLのuserinfo: トークンだけ、パスワードに@を含む場合
    ('git clone https://ghp_abc123@github.com/o/r.git', 'git clone https://***@github.com/o/r.git'),
    ('git push https://user:p@ss@host/x', 'git push https://***@host/x'),
    # PowerShellの変数代入と、大文字小文字違いの$Env:
    ("$apiKey = 'sk-abc123'; python app.py", '$apiKey = ***; python app.py'),
    ('$DbPassword="abc123"', '$DbPassword=***'),
    ('$Env:OPENAI_API_KEY = "sk-abc123"', '$Env:OPENAI_API_KEY = ***'),
    # 名前に秘密らしい語を含むヘッダーと、ハッシュテーブル形式
    ('curl -H "X-Api-Key: abc123" x', 'curl -H "X-Api-Key: ***" x'),
    ('curl -H "x-goog-api-key: abc123" x', 'curl -H "x-goog-api-key: ***" x'),
    ('irm -Headers @{Authorization = "token abc123"} -Uri u', 'irm -Headers @{Authorization = ***} -Uri u'),
    # オプションのコロン形式
    ('Connect -Password:abc123 -Name x', 'Connect -Password:*** -Name x'),
    ('tool --token:abc123 run', 'tool --token:*** run'),
    # 閉じていない引用符・連結
    ('export TOKEN="abc123 def', 'export TOKEN=***'),
    ('TOKEN=abc"def ghi" run', 'TOKEN=*** run'),
    ('TOKEN=abc|grep x', 'TOKEN=***|grep x'),
    # 引用符付きのキー
    ("irm -Headers @{'X-Api-Key'='abc123'} u", "irm -Headers @{'X-Api-Key'=***} u"),
    ("$h = @{ 'Authorization' = 'Basic abc' }", "$h = @{ 'Authorization' = *** }"),
    ('curl -d \'{"token":"abc123"}\' x', 'curl -d \'{"token":***}\' x'),
    ('echo {"api_key": "abc123"}', 'echo {"api_key": ***}'),
    ("os.environ['TOKEN']='abc123'", "os.environ['TOKEN']=***"),
])
def test_command_summaries_hide_secrets(hook, command, expected):
    assert bash_summary(hook, command) == expected
    assert bash_summary(hook, command, tool='PowerShell') == expected


@pytest.mark.parametrize('command', ['git status', 'python -m pytest -q', 'npm --prefix frontend test',
                                     'git diff -- src/app.py', 'python -m pytest -q --basetemp=.test-temp',
                                     'git log --format=%H', 'git -c core.autocrlf=false status',
                                     'git clone https://github.com/o/r.git', 'curl https://host:8080/path'])
def test_ordinary_commands_are_unchanged(hook, command):
    assert bash_summary(hook, command) == command


def test_secrets_are_hidden_before_clipping_and_in_urls(hook):
    # 切り詰めの境界にまたがる秘密も、一部が残らないこと
    summary = bash_summary(hook, 'x' * 45 + ' API_KEY=abcdefghijklmnop run')
    assert len(summary) == 60 and summary.endswith('…')
    assert 'abc' not in summary and 'API_KEY=***' in summary
    fetch = hook.record({'hook_event_name': 'PreToolUse', 'tool_name': 'WebFetch',
                         'tool_input': {'url': 'https://example.com/docs?access_token=abcdef'}}, now=1)
    assert fetch['summary'] == 'https://example.com/docs?***'


@pytest.mark.parametrize('command, expected', [
    ('x' * 52 + ' TOKEN=abcdef', 'x' * 52 + ' TOKEN=…'),
    ('x' * 58 + ' TOKEN=abcdef', 'x' * 58 + ' …'),
])
def test_no_fragment_remains_at_the_clipping_boundary(hook, command, expected):
    assert bash_summary(hook, command) == expected


def test_long_first_line_is_cut_before_redaction(hook):
    summary = bash_summary(hook, 'x' * 100000 + ' TOKEN="' + 'a"' * 5000)
    assert summary == 'x' * 59 + '…'


def fetch_summary(hook, url):
    return hook.record({'hook_event_name': 'PreToolUse', 'tool_name': 'WebFetch',
                        'tool_input': {'url': url}}, now=1)['summary']


def test_webfetch_hides_credentials_query_and_fragment(hook):
    assert fetch_summary(hook, 'https://u:p@example.com/x?y=1#frag') == 'https://***@example.com/x?***'
    long_url = 'https://example.com/' + 'p' * 40 + '/page?token=abcdef&x=1'
    summary = fetch_summary(hook, long_url)
    assert summary == ('https://example.com/' + 'p' * 40 + '/page?***')[:59] + '…'
    assert 'abc' not in summary and 'token' not in summary


@pytest.mark.parametrize('tool, field, value, expected', [
    ('Grep', 'pattern', 'API_KEY=abc123', 'API_KEY=***'),
    ('Glob', 'pattern', '**/token=abc123', '**/token=***'),
    ('Glob', 'pattern', 'src/**/*.py', 'src/**/*.py'),
    ('WebSearch', 'query', 'curl -H "X-Api-Key: abc123"', 'curl -H "X-Api-Key: ***"'),
])
def test_search_summaries_hide_secrets(hook, tool, field, value, expected):
    entry = hook.record({'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': {field: value}}, now=1)
    assert entry['summary'] == expected


def load_hook_for(project, monkeypatch):
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project))
    return load('log_activity_hook_isolated', '.claude/hooks/log_activity.py')


@pytest.mark.parametrize('stdin', [b'{not json', b'[1,2]', b'\xff\xfe{}', b''])
def test_hook_exits_zero_on_broken_input(tmp_path, monkeypatch, stdin):
    (tmp_path / '.claude' / 'activity').mkdir(parents=True)
    module = load_hook_for(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(stdin)))
    assert module.main() == 0
    assert not (tmp_path / '.claude' / 'activity' / 'events.jsonl').exists()


def test_hook_exits_zero_when_log_cannot_be_written(tmp_path, monkeypatch):
    (tmp_path / '.claude' / 'activity' / 'events.jsonl').mkdir(parents=True)
    module = load_hook_for(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'{"hook_event_name": "Stop"}')))
    assert module.main() == 0


def run_hook(project, stdin):
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(project)}
    return subprocess.run([sys.executable, str(ROOT / '.claude' / 'hooks' / 'log_activity.py')],
                          input=stdin, env=env, capture_output=True, timeout=30)


def test_hook_process_exits_zero_and_writes_only_to_the_given_project(tmp_path):
    activity = tmp_path / '.claude' / 'activity'
    activity.mkdir(parents=True)
    assert run_hook(tmp_path, b'{not json').returncode == 0
    assert not (activity / 'events.jsonl').exists()
    event = b'{"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "TOKEN=abc run"}}'
    assert run_hook(tmp_path, event).returncode == 0
    [line] = (activity / 'events.jsonl').read_text(encoding='utf-8').splitlines()
    assert json.loads(line)['summary'] == 'TOKEN=*** run'
    broken = tmp_path / 'broken'
    (broken / '.claude' / 'activity' / 'events.jsonl').mkdir(parents=True)
    assert run_hook(broken, event).returncode == 0


def test_startup_message_tells_how_to_stop_recording(chat, tmp_path, monkeypatch, capsys):
    class FakeServer:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(chat, 'ACTIVITY', tmp_path / 'activity')
    monkeypatch.setattr(chat, 'ThreadingHTTPServer', FakeServer)
    assert chat.main(['--port', '9999']) == 0
    out = capsys.readouterr().out
    assert 'http://127.0.0.1:9999/' in out and chat.STOP_HINT in out
    assert '記録は続きます' in chat.STOP_HINT and '.claude/activity/' in chat.STOP_HINT
    assert (tmp_path / 'activity').is_dir()


def test_append_is_disabled_until_the_chat_server_created_the_folder(hook, tmp_path):
    log = tmp_path / 'activity' / 'events.jsonl'
    hook.append({'ts': 1}, log)
    assert not log.exists()
    log.parent.mkdir()
    hook.append({'ts': 1}, log)
    assert log.read_text(encoding='utf-8').strip() == '{"ts": 1}'


def ev(ts, event, **fields):
    return {'ts': ts, 'event': event, **fields}


DELEGATION = [
    ev(1, 'UserPromptSubmit'),
    ev(2, 'PreToolUse', tool='Agent', tool_use_id='c1', subagent_type='planner', summary='計画を立てる', prompt='排他制御の計画'),
    ev(3, 'SubagentStart', agent_id='a1', agent_type='planner'),
    ev(4, 'PreToolUse', agent_id='a1', agent_type='planner', tool='Read', summary='App.tsx'),
    ev(5, 'PostToolUse', agent_id='a1', agent_type='planner', tool='Read', summary='App.tsx'),
    ev(6, 'SubagentStop', agent_id='a1', agent_type='planner', report='手順は3つです'),
    ev(7, 'PostToolUse', tool='Agent', tool_use_id='c1', subagent_type='planner', report='手順は3つです'),
    ev(8, 'Stop'),
]


def test_delegation_becomes_one_thread_with_work_and_report(chat):
    state = chat.build_chat(DELEGATION, [{'name': 'main', 'label': 'リーダー', 'model': ''}], now=10)
    [thread] = state['threads']
    assert (thread['from'], thread['to'], thread['prompt']) == ('main', 'planner', '排他制御の計画')
    assert [r['summary'] for r in thread['replies']] == ['App.tsx']
    assert thread['status'] == 'done' and thread['report'] == '手順は3つです' and not thread['stale']
    members = {m['name']: m for m in state['members']}
    assert members['planner']['guest'] and members['planner']['status'] == 'idle'
    assert [n['text'] for n in state['notices']] == ['ユーザーから新しい指示が届きました', 'リーダーが応答を返しました']


def test_in_progress_and_out_of_order_records(chat):
    shuffled = [DELEGATION[3], DELEGATION[1], DELEGATION[2], DELEGATION[0]]
    state = chat.build_chat(shuffled, [], now=10)
    [thread] = state['threads']
    assert thread['status'] == 'running' and thread['agent_id'] == 'a1'
    planner = next(m for m in state['members'] if m['name'] == 'planner')
    assert (planner['status'], planner['tool'], planner['summary']) == ('working', 'Read', 'App.tsx')


def test_missing_start_attaches_on_first_tool_and_background_ack_reopens(chat):
    events = [
        ev(1, 'PreToolUse', tool='Agent', tool_use_id='c1', subagent_type='tester', summary='確認'),
        ev(2, 'PostToolUse', tool='Agent', tool_use_id='c1', subagent_type='tester', report='バックグラウンドで開始'),
        ev(3, 'PreToolUse', agent_id='b1', agent_type='tester', tool='Bash', summary='pytest'),
    ]
    [thread] = chat.build_chat(events, [], now=4)['threads']
    assert thread['agent_id'] == 'b1' and thread['status'] == 'running'
    events.append(ev(5, 'SubagentStop', agent_id='b1', agent_type='tester', report='全件成功'))
    [thread] = chat.build_chat(events, [], now=6)['threads']
    assert (thread['status'], thread['report']) == ('done', '全件成功')


def test_silent_runs_are_marked_stale(chat):
    events = DELEGATION[1:4]
    [thread] = chat.build_chat(events, [], now=4 + chat.STALE_SECONDS + 1)['threads']
    assert thread['stale']
    planner = next(m for m in chat.build_chat(events, [], now=4 + chat.STALE_SECONDS + 1)['members'] if m['name'] == 'planner')
    assert planner['status'] == 'idle'


def test_roster_reads_agent_frontmatter_with_crlf(chat, tmp_path):
    (tmp_path / 'reviewer.md').write_bytes(b'---\r\nname: reviewer\r\nmodel: opus\r\n---\r\nbody')
    roster = chat.load_roster(tmp_path)
    assert roster[0]['name'] == 'main'
    assert roster[1] == {'name': 'reviewer', 'label': 'レビュー', 'model': 'opus'}
