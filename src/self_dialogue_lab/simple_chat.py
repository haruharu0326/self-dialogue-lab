"""Conversation and a small, explicit 'remember my answer' action."""

import json
import streamlit as st

from .sentiment_ui import render_tone


def render_conversation(store, attempt):
    rows = store.rows('SELECT r.*,m.body AS source FROM responses r JOIN messages m ON m.id=r.message_id ORDER BY r.id')
    for response in rows:
        with st.chat_message('user'):
            st.write(response['source'])
            render_tone(response['source'], response['id'])
            candidates = store.rows('SELECT * FROM candidates WHERE message_id=?', (response['message_id'],))
            if candidates:
                candidate = candidates[0]
                if candidate['status'] == 'pending':
                    with st.expander('この回答を覚えておく'):
                        with st.form(f"remember{candidate['id']}"):
                            thought = st.text_area('覚えておく内容', value=candidate['thought'], key=f"remember_text{candidate['id']}")
                            st.caption('確認した内容だけ、これからの対話で参照します。')
                            remember = st.form_submit_button('覚えておく')
                            dismiss = st.form_submit_button('今回は覚えない')
                            if remember:
                                attempt(lambda: store.approve(candidate['id'], thought, '', '本人が対話中に確認した回答'),
                                        '覚えました。これからの対話で参考にします。')
                            if dismiss:
                                attempt(lambda: store.reject(candidate['id']), '会話だけを残し、記憶には追加しませんでした。')
                elif candidate['status'] == 'approved':
                    st.caption('保存した回答です。現在の記憶は「覚えていること」で確認できます。')
        with st.chat_message('assistant'):
            body = json.loads(response['body'])
            st.caption('Geminiの返答 · 推測を含みます' if body.get('provider') == 'gemini' else '以前のモック・固定応答')
            st.write(body['interpretation'])
            if body['question']:
                st.write(body['question'])
            refs = json.loads(response['refs'])
            if refs:
                with st.expander('この返答で参照したこと'):
                    for ref in refs:
                        st.write(ref['thought'])
                    st.caption('返答した時点の記録です。後から忘れた内容が当時の会話に残ることがあります。')
