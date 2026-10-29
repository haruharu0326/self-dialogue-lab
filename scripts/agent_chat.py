"""開発チャット: サブエージェントとのやり取りをSlack風に表示するローカルサーバー。

.claude/hooks/log_activity.py が書く記録を、依頼ごとのスレッドに組み立てて127.0.0.1だけで配信する。
表示する依頼文・報告・作業内容はすべて記録から取り、台詞を作らない。
標準ライブラリのみで動き、製品のAPI・DBとは独立している。
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT / '.claude' / 'activity'
LOG = ACTIVITY / 'events.jsonl'
PAGE = Path(__file__).with_name('agent_chat.html')
MAIN = 'main'
AGENT_TOOLS = {'Agent', 'Task'}
STALE_SECONDS = 15 * 60
FEED = 300
LABELS = {
    MAIN: 'リーダー', 'planner': '計画', 'be-engineer': 'バックエンド', 'fe-engineer': 'フロント',
    'reviewer': 'レビュー', 'tester': 'テスト', 'refactorer': 'リファクタ', 'doc-keeper': '文書',
}


def load_roster(agents_dir=ROOT / '.claude' / 'agents'):
    """.claude/agents/*.md のfrontmatterからメンバー一覧を作る。メインは常に先頭。"""
    roster = [{'name': MAIN, 'label': LABELS[MAIN], 'model': ''}]
    for path in sorted(agents_dir.glob('*.md')):
        head = re.match(r'---\r?\n(.*?)\r?\n---', path.read_text(encoding='utf-8'), re.S)
        meta = dict(re.findall(r'^(\w+):\s*(.+?)\s*$', head.group(1), re.M)) if head else {}
        name = meta.get('name', path.stem)
        roster.append({'name': name, 'label': LABELS.get(name, name), 'model': meta.get('model', '')})
    return roster


def read_events(log=LOG):
    if not log.exists():
        return []
    events = []
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def build_chat(events, roster, now):
    """記録を、依頼ごとのスレッド・作業フィード・メンバーの在席状況にまとめる。"""
    members = {m['name']: {**m, 'status': 'idle', 'tool': '', 'summary': '', 'guest': False}
               for m in [{'name': MAIN, 'label': LABELS[MAIN], 'model': ''}, *roster]}
    threads, by_call, by_agent, notices, feed = [], {}, {}, [], []

    def member(name):
        if name not in members:
            members[name] = {'name': name, 'label': LABELS.get(name, name), 'model': '', 'status': 'idle',
                             'tool': '', 'summary': '', 'guest': True}
        return members[name]

    def open_thread(ts, to, sender, call_id='', description='', prompt=''):
        thread = {'id': call_id or f't{len(threads)}', 'ts': ts, 'from': sender, 'to': to,
                  'description': description, 'prompt': prompt, 'agent_id': '', 'status': 'waiting',
                  'replies': [], 'report': '', 'report_ts': None, 'last': ts}
        threads.append(thread)
        member(to)
        if call_id:
            by_call[call_id] = thread
        return thread

    # 記録hookは非同期なので、ファイル上の順序ではなく時刻で並べ直す
    for e in sorted(events, key=lambda e: e.get('ts', 0)):
        ts, kind, tool, agent = e.get('ts', 0), e.get('event'), e.get('tool', ''), e.get('agent_id', '')
        who = e.get('agent_type') or MAIN if agent else MAIN
        thread = by_agent.get(agent) if agent else None

        if kind == 'SubagentStart' or (agent and not thread and kind in ('PreToolUse', 'PostToolUse')):
            kind_name = e.get('agent_type') or 'general-purpose'
            # 同じ種類への依頼のうち、まだ担当が着いていない最も古いものに結び付ける
            # （バックグラウンド実行は受付の時点で完了扱いになっているため、状態では絞らない）
            thread = next((t for t in threads if t['to'] == kind_name and not t['agent_id']), None) \
                or open_thread(ts, kind_name, MAIN)
            thread['agent_id'], thread['status'], thread['last'] = agent, 'running', ts
            by_agent[agent] = thread
            who = kind_name
            if kind == 'SubagentStart':
                continue

        if kind == 'PreToolUse':
            if tool in AGENT_TOOLS:
                open_thread(ts, e.get('subagent_type') or 'general-purpose', who, e.get('tool_use_id', ''),
                            e.get('summary', ''), e.get('prompt', ''))
            m = member(who)
            m['status'], m['tool'], m['summary'] = 'working', tool, e.get('summary', '')
            feed.append({'ts': ts, 'who': who, 'tool': tool, 'summary': e.get('summary', '')})
            if thread:
                thread['replies'].append({'ts': ts, 'tool': tool, 'summary': e.get('summary', '')})
        elif kind == 'PostToolUse':
            m = member(who)
            m['tool'], m['summary'] = '', ''
            if tool in AGENT_TOOLS:
                call = by_call.get(e.get('tool_use_id', '')) or next(
                    (t for t in threads if t['to'] == e.get('subagent_type') and t['status'] != 'done'), None)
                if call and not call.get('stopped'):
                    # バックグラウンド実行ではここが受付の文になる。その後の作業で再び作業中に戻す
                    call['status'] = 'done'
                    if e.get('report'):
                        call['report'], call['report_ts'] = e['report'], ts
        elif kind == 'SubagentStop' and thread:
            thread.update(status='done', stopped=True, last=ts)
            if e.get('report'):
                thread['report'], thread['report_ts'] = e['report'], ts
        if thread and kind in ('PreToolUse', 'PostToolUse'):
            thread['last'] = ts
            if not thread.get('stopped'):
                thread['status'] = 'running'
        elif kind == 'UserPromptSubmit':
            members[MAIN]['status'] = 'working'
            notices.append({'ts': ts, 'text': 'ユーザーから新しい指示が届きました'})
        elif kind == 'Stop':
            members[MAIN].update(status='idle', tool='', summary='')
            notices.append({'ts': ts, 'text': 'リーダーが応答を返しました'})

    running = {t['to'] for t in threads if t['status'] == 'running' and now - t['last'] <= STALE_SECONDS}
    for t in threads:
        t['stale'] = t['status'] != 'done' and now - t['last'] > STALE_SECONDS
    for name, m in members.items():
        if name != MAIN and name not in running:
            m.update(status='idle', tool='', summary='')
    if members[MAIN]['status'] == 'working' and feed and now - max(f['ts'] for f in feed) > STALE_SECONDS:
        members[MAIN].update(status='idle', tool='', summary='')
    return {'now': now, 'members': list(members.values()), 'threads': threads,
            'notices': notices, 'feed': feed[-FEED:]}


def current_chat():
    return build_chat(read_events(), load_roster(), time.time())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, kind):
        data = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', f'{kind}; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self.send(PAGE.read_text(encoding='utf-8'), 'text/html')
        elif self.path == '/api/chat':
            self.send(json.dumps(current_chat(), ensure_ascii=False), 'application/json')
        elif self.path == '/api/stream':
            self.stream()
        else:
            self.send_error(404)

    def stream(self):
        """記録の更新時と10秒ごとに全体を送る（応答なしの判定を進めるため）。"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        seen, sent = None, 0.0
        try:
            while True:
                mtime = LOG.stat().st_mtime if LOG.exists() else 0
                if mtime != seen or time.time() - sent > 10:
                    seen, sent = mtime, time.time()
                    payload = json.dumps(current_chat(), ensure_ascii=False)
                    self.wfile.write(f'data: {payload}\n\n'.encode('utf-8'))
                    self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description='サブエージェントとのやり取りをSlack風に表示する')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true', help='起動後にブラウザを開く')
    args = parser.parse_args(argv)
    ACTIVITY.mkdir(parents=True, exist_ok=True)  # これ以降、log_activity.pyが記録を始める
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    url = f'http://127.0.0.1:{args.port}/'
    print(f'開発チャット: {url}  （Ctrl+Cで停止）', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
