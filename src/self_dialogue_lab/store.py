import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        try:
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def _initialize(self):
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY AUTOINCREMENT, thought TEXT NOT NULL,
          reason TEXT, context TEXT, occurred TEXT, previous_id INTEGER REFERENCES records(id) ON DELETE SET NULL,
          superseded INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, role TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS responses(id INTEGER PRIMARY KEY, message_id INTEGER REFERENCES messages(id), body TEXT, refs TEXT);
        CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, message_id INTEGER REFERENCES messages(id),
          thought TEXT, reason TEXT, context TEXT, status TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS feedback(response_id INTEGER PRIMARY KEY REFERENCES responses(id), labels TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY);
        ''')
        # 既存DBにも候補の変更元を追加。削除された変更元のIDも保持し、承認時に検証する。
        if 'previous_id' not in {r['name'] for r in self.db.execute('PRAGMA table_info(candidates)')}:
            self.db.execute('ALTER TABLE candidates ADD COLUMN previous_id INTEGER')
        if 'superseded' not in {r['name'] for r in self.db.execute('PRAGMA table_info(records)')}:
            self.db.execute('ALTER TABLE records ADD COLUMN superseded INTEGER NOT NULL DEFAULT 0')
        self.db.execute('UPDATE records SET superseded=1 WHERE id IN (SELECT previous_id FROM records WHERE previous_id IS NOT NULL)')
        self.db.commit()
        self._migrate_record_ids()

    def _migrate_record_ids(self):
        sql = self.db.execute("SELECT sql FROM sqlite_master WHERE name='records'").fetchone()[0]
        if 'AUTOINCREMENT' in sql.upper():
            return
        self.db.execute('PRAGMA foreign_keys=OFF')
        try:
            with self.transaction():
                self.db.execute('''CREATE TABLE records_new(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thought TEXT NOT NULL, reason TEXT, context TEXT, occurred TEXT,
                    previous_id INTEGER REFERENCES records(id) ON DELETE SET NULL,
                    superseded INTEGER NOT NULL DEFAULT 0)''')
                self.db.execute('''INSERT INTO records_new SELECT id,thought,reason,context,occurred,previous_id,superseded FROM records''')
                self.db.execute('DROP TABLE records')
                self.db.execute('ALTER TABLE records_new RENAME TO records')
                if self.db.execute('PRAGMA foreign_key_check').fetchall():
                    raise sqlite3.IntegrityError('Migration failed foreign-key validation')
        finally:
            self.db.execute('PRAGMA foreign_keys=ON')

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def write(self, sql, args=()):
        with self.db:
            return self.db.execute(sql, args).lastrowid

    def records(self):
        return self.rows('SELECT * FROM records ORDER BY occurred DESC,id DESC')

    def current_records(self):
        return self.rows('''SELECT * FROM records WHERE superseded=0
            ORDER BY occurred DESC,id DESC''')

    def gemini_history(self, limit=10):
        rows = self.rows('''SELECT r.body,m.body AS source FROM responses r
            JOIN messages m ON m.id=r.message_id
            WHERE json_extract(r.body,'$.provider')='gemini' ORDER BY r.id DESC LIMIT ?''', (limit,))
        history = []
        for row in reversed(rows):
            body = json.loads(row['body'])
            history.extend([{'role': 'user', 'text': row['source']},
                            {'role': 'model', 'text': body['interpretation'] + '\n' + body['question']}])
        return history

    def clear_conversations(self):
        """会話と従属データだけを削除。承認済みの長期記録には触れない。"""
        with self.transaction():
            self.db.execute('DELETE FROM feedback')
            self.db.execute('DELETE FROM candidates')
            self.db.execute('DELETE FROM responses')
            self.db.execute('DELETE FROM messages')

    def add(self, thought, reason, context, occurred=None, previous_id=None):
        if not thought.strip():
            raise ValueError('考えを入力してください')
        with self.transaction():
            return self._insert_record(thought.strip(), reason, context, occurred or datetime.now().isoformat(timespec='minutes'), previous_id)

    def _insert_record(self, thought, reason, context, occurred, previous_id):
        if previous_id is not None:
            if not self.db.execute('SELECT id FROM records WHERE id=?', (previous_id,)).fetchone():
                raise ValueError('変更元の記録が見つかりません')
            self.db.execute('UPDATE records SET superseded=1 WHERE id=?', (previous_id,))
        return self.db.execute('INSERT INTO records(thought,reason,context,occurred,previous_id) VALUES(?,?,?,?,?)',
                               (thought, reason, context, occurred, previous_id)).lastrowid

    def edit(self, id, thought, reason, context, occurred):
        if not thought.strip():
            raise ValueError('考えを入力してください')
        with self.transaction():
            result = self.db.execute('UPDATE records SET thought=?,reason=?,context=?,occurred=? WHERE id=?', (thought.strip(), reason, context, occurred, id))
            if result.rowcount != 1:
                raise ValueError('編集する記録が見つかりません')

    def delete_record(self, id):
        with self.transaction():
            result = self.db.execute('DELETE FROM records WHERE id=?', (id,))
            if result.rowcount != 1:
                raise ValueError('削除する記録が見つかりません')

    def save_feedback(self, response_id, labels):
        if not set(labels).issubset({'理解が正確', '有益な問い', '決めつけがある'}):
            raise ValueError('評価項目を確認してください')
        with self.transaction():
            if not self.db.execute('SELECT id FROM responses WHERE id=?', (response_id,)).fetchone():
                raise ValueError('評価する応答が見つかりません')
            self.db.execute('INSERT OR REPLACE INTO feedback VALUES(?,?)', (response_id, json.dumps(labels, ensure_ascii=False)))

    def approve(self, id, thought, reason, context):
        if not thought.strip():
            raise ValueError('考えを入力してください')
        with self.transaction():
            row = self.db.execute("SELECT * FROM candidates WHERE id=? AND status='pending'", (id,)).fetchone()
            if row is None:
                raise ValueError('この候補は処理済みです')
            if row['previous_id'] is not None and not self.db.execute('SELECT id FROM records WHERE id=?', (row['previous_id'],)).fetchone():
                raise ValueError('変更元の記録が削除されています。この候補を拒否し、作り直してください')
            self._insert_record(thought.strip(), reason, context, datetime.now().isoformat(timespec='minutes'), row['previous_id'])
            self.db.execute("UPDATE candidates SET thought=?,reason=?,context=?,status='approved' WHERE id=?", (thought.strip(), reason, context, id))

    def export(self):
        return json.dumps(self.records(), ensure_ascii=False, indent=2)

    def reject(self, id):
        with self.transaction():
            result = self.db.execute("UPDATE candidates SET status='rejected' WHERE id=? AND status='pending'", (id,))
            if result.rowcount != 1:
                raise ValueError('この候補は見つからないか、処理済みです')

    def seed(self):
        seeds = json.loads((Path(__file__).parent / 'samples' / 'thoughts.json').read_text(encoding='utf-8'))['records']
        with self.transaction():
            if self.db.execute("SELECT key FROM meta WHERE key='seeded'").fetchone():
                return
            for item in seeds:
                self.db.execute('INSERT INTO records(thought,reason,context,occurred) VALUES(?,?,?,?)',
                                tuple(item[key] for key in ('thought', 'reason', 'context', 'occurred')))
            self.db.execute("INSERT INTO meta VALUES('seeded')")
