"""開発チャット用: サブエージェントへの依頼・作業・報告を1行ずつ記録する。

scripts/agent_chat.py を一度起動して .claude/activity/ ができるまでは何もしない。
通常のツールは名前と対象（ファイル名・コマンド先頭）だけを残し、ファイルの中身は残さない。
コマンド・URL・検索の要約は、秘密らしい値を伏せてから切り詰める。
Agentツール（サブエージェント呼び出し）だけは、依頼文と返ってきた報告を上限付きで残す。
ユーザーの入力文は記録しない。どんな失敗でも作業を止めないよう、常に終了コード0で終わる。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get('CLAUDE_PROJECT_DIR') or Path(__file__).resolve().parents[2])
LOG = ROOT / '.claude' / 'activity' / 'events.jsonl'
MAX_BYTES = 2_000_000
KEEP_LINES = 3000
PROMPT_CHARS = 4000
REPORT_CHARS = 8000
EVENTS = {'PreToolUse', 'PostToolUse', 'SubagentStart', 'SubagentStop', 'Stop', 'UserPromptSubmit'}
AGENT_TOOLS = {'Agent', 'Task'}
# 伏せる前に切る長さ。要約は最終的に60字以下なので情報は減らず、正規表現の計算量も抑えられる
REDACT_CHARS = 300
# 要約に入りうる秘密を伏せる（パターン, 置換）。誤検出で無害な値が伏せられるのは許容する
# 値は閉じていない引用符や連結（abc"def ghi"）もまとめて1つとして扱い、断片を残さない
VALUE = r'''(?:'[^']*'?|"[^"]*"?|[^\s'";|&)}])+'''
SECRET_OPTION = r'(?:token|key|secret|password|passwd|pwd|auth|credential)'
SECRET_HEADER = r'(?:api[-_]?key|token|secret|password|passwd|auth|credential|cookie)'
REDACTIONS = [
    (re.compile(r'''(\w+://)[^/\s?#'"]+@'''), r'\1***@'),
    (re.compile(r'''(\w+://[^\s?#'"]*)([?#])[^\s'"]*'''), r'\1\2***'),
    (re.compile(r'(?i)(?<![\w-])(?=\w)([\w-]*' + SECRET_HEADER + r'[\w-]*\s*:\s*)[^\'"\r\n]+'), r'\1***'),
    # 引用符付きのキー（{"token": …}、@{'X-Api-Key'=…}、['TOKEN']=…）
    (re.compile(r'''(?i)((['"])[\w-]*''' + SECRET_OPTION + r'''[\w-]*\2\]?\s*[:=]\s*)''' + VALUE), r'\1***'),
    (re.compile(r'(?i)\b(Bearer\s+)[^\s\'"]+'), r'\1***'),
    (re.compile(r'(?i)(\$env:\w+\s*=\s*)' + VALUE), r'\1***'),
    (re.compile(r'(?i)(?<![\w$-])(\$?[\w-]*' + SECRET_OPTION + r'[\w-]*\s*=\s*)' + VALUE), r'\1***'),
    (re.compile(r'(?:^|(?<=[\s;&|(]))([A-Za-z_]\w*=)' + VALUE), r'\1***'),
    (re.compile(r'(?i)(?<!\S)(--?[\w-]*' + SECRET_OPTION + r'[\w-]*)(=|:|\s+)' + VALUE), r'\1\2***'),
]


def redact(text):
    """コマンドやURLの要約から、環境変数の値・認証ヘッダー・URLの認証情報やクエリ等を伏せる。"""
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def brief(text, size):
    """1行にまとめ、先に長さを抑えてから秘密を伏せ、最後に切り詰める。"""
    return clip(redact(' '.join(str(text).split())[:REDACT_CHARS]), size)


def clip(text, size, oneline=True):
    text = ' '.join(str(text).split()) if oneline else str(text).strip()
    return text if len(text) <= size else text[:size - 1] + '…'


def summarize(tool, tool_input):
    """一覧表示用の短い要約。中身ではなく対象だけを返す。"""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    path = tool_input.get('file_path') or tool_input.get('notebook_path')
    if path:
        return Path(str(path).replace('\\', '/')).name
    if tool in ('Bash', 'PowerShell'):
        command = str(tool_input.get('command') or '')
        return brief(command.splitlines()[0] if command else '', 60)
    if tool in ('Grep', 'Glob'):
        return brief(tool_input.get('pattern', ''), 40)
    if tool in AGENT_TOOLS:
        return clip(tool_input.get('description', ''), 60)
    if tool == 'WebSearch':
        return brief(tool_input.get('query', ''), 40)
    if tool == 'WebFetch':
        return brief(tool_input.get('url', ''), 60)
    return ''


def response_text(response):
    """Agentツールの結果から報告本文を取り出す。形が変わっても落ちないようにする。"""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get('content', response.get('result', ''))
        if isinstance(content, list):
            return '\n'.join(c.get('text', '') for c in content if isinstance(c, dict))
        return str(content or '')
    if isinstance(response, list):
        return '\n'.join(c.get('text', '') for c in response if isinstance(c, dict))
    return ''


def record(data, now=None):
    event = data.get('hook_event_name', '')
    if event not in EVENTS:
        return None
    tool = data.get('tool_name') or ''
    tool_input = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    entry = {
        'ts': now if now is not None else time.time(),
        'event': event,
        'session': data.get('session_id', ''),
        'agent_id': data.get('agent_id') or '',
        'agent_type': data.get('agent_type') or '',
        'tool': tool,
        'tool_use_id': data.get('tool_use_id') or '',
        'summary': summarize(tool, tool_input) if tool else '',
    }
    if tool in AGENT_TOOLS:
        entry['subagent_type'] = tool_input.get('subagent_type') or 'general-purpose'
        if event == 'PreToolUse':
            entry['prompt'] = clip(tool_input.get('prompt', ''), PROMPT_CHARS, oneline=False)
        elif event == 'PostToolUse':
            entry['report'] = clip(response_text(data.get('tool_response')), REPORT_CHARS, oneline=False)
    if event == 'SubagentStop' and data.get('last_assistant_message'):
        # バックグラウンド実行ではAgentツールの結果が受付の文だけになるため、最後の発言を報告として使う
        entry['report'] = clip(data['last_assistant_message'], REPORT_CHARS, oneline=False)
    return entry


def append(entry, log=LOG):
    if not log.parent.is_dir():
        return
    with log.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    if log.stat().st_size > MAX_BYTES:
        lines = log.read_text(encoding='utf-8').splitlines()[-KEEP_LINES:]
        log.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    try:
        if not LOG.parent.is_dir():
            return 0
        entry = record(json.loads(sys.stdin.buffer.read().decode('utf-8')))
        if entry:
            append(entry)
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
