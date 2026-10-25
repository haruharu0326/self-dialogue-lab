import json
from .responder import Responder


def converse(store, responder: Responder, message, scenario, correction_of=None, previous_id=None, reason='', context=''):
    if not message.strip():
        raise ValueError('メッセージを入力してください')
    target = None
    change_from = None
    if previous_id is not None:
        if correction_of is not None:
            raise ValueError('解釈の訂正と考えの変化は別々に登録してください')
        matches = store.rows('SELECT * FROM records WHERE id=?', (previous_id,))
        if not matches:
            raise ValueError('変更元の記録が見つかりません')
        change_from = matches[0]
    elif scenario == 'C. 以前とは考えが変わった':
        raise ValueError('変更元の記録を選んでください')
    if correction_of is not None:
        matches = store.rows('SELECT * FROM responses WHERE id=?', (correction_of,))
        if not matches:
            raise ValueError('訂正する応答が見つかりません')
        target = json.loads(matches[0]['body'])
    reply = responder.respond(message, scenario, store.current_records(), correction_of=target, change_from=change_from)
    _save_exchange(store, reply, message, correction_of, previous_id, reason, context)


def converse_gemini(store, responder, message, *, reference_ids=(), include_history=True,
                    consent=False, demo=False, correction_of=None):
    if not consent:
        raise ValueError('Googleへ送信する情報を確認して、送信確認にチェックしてください。')
    if not message.strip():
        raise ValueError('メッセージを入力してください')
    current = {r['id']: r for r in store.current_records()}
    if any(type(id) is not int or id not in current for id in reference_ids):
        raise ValueError('参照する記録が変更・削除されています。選び直してください。')
    target = None
    if correction_of is not None:
        rows = store.rows('SELECT body FROM responses WHERE id=?', (correction_of,))
        if not rows:
            raise ValueError('訂正する応答が見つかりません')
        body = json.loads(rows[0]['body'])
        target = {'interpretation': body['interpretation'], 'question': body['question']}
    reply = responder.respond(message, 'Geminiチャット', [current[id] for id in dict.fromkeys(reference_ids)],
                              correction_of=target, history=store.gemini_history() if include_history else [], demo=demo)
    _save_exchange(store, reply, message, correction_of, provider='gemini', model=responder.model)


def converse_personal(store, responder, message, *, consent=False):
    """Use only explicitly remembered, current answers as long-term context."""
    return converse_gemini(store, responder, message,
                          reference_ids=[record['id'] for record in store.current_records()],
                          include_history=True, consent=consent, demo=False)


def _save_exchange(store, reply, message, correction_of=None, previous_id=None, reason='', context='', provider='mock', model=None):
    candidate_context = context if previous_id is not None else (
        f'応答 #{correction_of} の解釈への訂正（本人の発言）' if correction_of is not None
        else 'Geminiチャットの本人発言（原文候補）' if provider == 'gemini'
        else '対話からの保存候補（固定モック）')
    with store.transaction():
        mid = store.db.execute("INSERT INTO messages(role,body) VALUES('user',?)", (message,)).lastrowid
        store.db.execute('INSERT INTO responses(message_id,body,refs) VALUES(?,?,?)',
                         (mid, json.dumps({'interpretation': reply.interpretation, 'question': reply.question, 'correction_of': correction_of,
                                           'provider': provider, 'model': model}, ensure_ascii=False), json.dumps(reply.references, ensure_ascii=False)))
        # 抽出器の代わりに、送信発言をそのまま候補とする。承認までは records に入れない。
        store.db.execute('INSERT INTO candidates(message_id,thought,reason,context,previous_id) VALUES(?,?,?,?,?)',
                         (mid, message, reason, candidate_context, previous_id))
