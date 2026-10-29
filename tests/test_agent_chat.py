"""開発チャット: 記録hookが残す範囲と、記録からスレッドを組み立てる規則。"""

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
