"""PreToolUse: 秘密・個人データ・DBへのアクセスと、ignore回避・強制pushを止める。

AGENTS.mdの「個人データ、DB、書き出し、秘密情報はGitへ追加しない」を、
AIがそれらを読んでモデルへ送ること・Gitへ強制追加することまで含めて機械的に守る。
"""
import json
import re
import sys
from pathlib import PurePosixPath

PRIVATE_DIRS = {'data', 'private', 'exports'}
PRIVATE_SUFFIXES = ('.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12')
FILE_TOOLS = {'Read', 'Edit', 'Write', 'NotebookEdit', 'Grep', 'Glob'}

# コマンド文字列用。直前を区切り文字に限定し、process.env や metadata/ を誤検知しない。
B = r'''(?:^|[\s"'`/\\=:(])'''
COMMAND_RULES = [
    (B + r'\.env(?!\.example)(?:\.[\w-]+)?(?=$|[\s"\'`;|&)])', '.env（秘密情報）'),
    (r'[\w-]\.(?:db|sqlite3?)(?:-\w+)?(?=$|[\s"\'`;|&)])', 'SQLiteのDBファイル（個人データ）'),
    (B + r'(?:data|private|exports)[/\\]', '個人データ用ディレクトリ（data/・private/・exports/）'),
    (B + r'secrets\.toml\b', 'secrets.toml（秘密情報）'),
    (r'\bgit\s+(?:-\S+\s+)*add\b[^;|&]*\s(?:-f|--force)\b', 'git add -f（.gitignoreの回避）'),
    (r'\bgit\s+(?:-\S+\s+)*push\b[^;|&]*\s(?:-f|--force|--force-with-lease)\b', 'git push --force'),
]


def private_path_reason(raw):
    parts = PurePosixPath(raw.replace('\\', '/').lower()).parts
    if not parts:
        return None
    name = parts[-1]
    if name == '.env' or (name.startswith('.env.') and name != '.env.example'):
        return '.env（秘密情報）'
    if name == 'secrets.toml':
        return 'secrets.toml（秘密情報）'
    if name.endswith(PRIVATE_SUFFIXES) or re.search(r'\.(?:db|sqlite3?)-\w+$', name):
        return 'DB・鍵ファイル（個人データ・秘密情報）'
    if PRIVATE_DIRS & set(parts):
        return '個人データ用ディレクトリ（data/・private/・exports/）'
    return None


def reason_for(tool, tool_input):
    if tool in FILE_TOOLS:
        for key in ('file_path', 'notebook_path', 'path', 'pattern' if tool == 'Glob' else ''):
            value = tool_input.get(key) if key else None
            if isinstance(value, str) and (reason := private_path_reason(value)):
                return reason
    if tool in ('Bash', 'PowerShell'):
        command = tool_input.get('command') or ''
        for pattern, reason in COMMAND_RULES:
            if re.search(pattern, command, re.IGNORECASE):
                return reason
    return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # Windowsの既定cp932では日本語の理由が文字化けする
    data = json.loads(sys.stdin.buffer.read().decode('utf-8'))  # stdin is UTF-8; Windows default cp932 breaks it
    reason = reason_for(data.get('tool_name', ''), data.get('tool_input') or {})
    if reason:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': f'プロジェクトのhookで拒否: {reason}への操作は禁止です（AGENTS.md）。'
                                        '必要な場合はユーザーに手動での実施を依頼してください。',
        }}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
