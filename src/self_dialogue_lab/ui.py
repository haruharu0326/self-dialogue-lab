"""The product entry point: one conversation, with optional remembered answers."""

from pathlib import Path
import os
import sqlite3

import streamlit as st

from .gemini import GeminiError, GeminiResponder
from .presentation import nature_stylesheet
from .simple_chat import render_conversation
from .store import Store
from .service import converse_personal
from .voice_ui import clear_voice, render_voice_input


def _render():
    st.set_page_config(page_title='Self Dialogue Lab', page_icon='◌', layout='centered')
    st.markdown(nature_stylesheet(), unsafe_allow_html=True)
    st.caption('SELF DIALOGUE LAB')
    st.title('話しながら、自分の考えを見つける。')
    st.caption('答えを急がず、ひとつずつ。覚えておいてほしい回答だけ、残せます。')
    root = Path(__file__).resolve().parents[2]
    path = os.environ.get('SELF_DIALOGUE_PERSONAL_DB') or str(root/'data'/'personal.sqlite3')
    configured = bool(os.environ.get('GEMINI_API_KEY', '').strip())

    def attempt(fn, notice=None):
        try:
            fn()
        except (ValueError, GeminiError) as error:
            st.error(str(error))
        else:
            if notice:
                st.session_state['simple_notice'] = notice
            st.rerun()

    store = Store(path)
    try:
        st.sidebar.caption('SELF DIALOGUE LAB')
        with st.sidebar.expander('接続と送信について', expanded=not configured):
            st.write('Geminiへ、この会話の直近10往復と、あなたが覚えておくと決めた現在の記録を送ります。画像やAPIキーを会話本文には含めません。')
            st.caption('「覚える」は保存した回答を次回に参照する方式です。モデルを再訓練するものではありません。')
            if not configured:
                st.write('ローカルの.envにGEMINI_API_KEYを設定し、Dockerを再作成してください。キーをチャットに貼らないでください。')
                st.link_button('GeminiのAPIキーを設定する', 'https://aistudio.google.com/apikey')
            if st.button('送信の確認をやり直す'):
                st.session_state['simple_consent'] = False
                st.rerun()
            st.caption('背景はAI生成の風景です。外部の画像サイトへは接続しません。')

        memories = store.current_records()
        with st.sidebar.expander(f'覚えていること（{len(memories)}件）'):
            if not memories:
                st.caption('まだありません。会話の中の「この回答を覚えておく」から残せます。')
            for memory in memories:
                st.write(memory['thought'])
                with st.container(border=True):
                    st.caption('忘れても、当時の会話は残ります。次回の返答の参照対象からは外れます。')
                    confirmed = st.checkbox('この内容を忘れてよい', key=f"forget_confirm{memory['id']}")
                    if st.button('忘れる', key=f"forget{memory['id']}", disabled=not confirmed):
                        attempt(lambda: store.delete_record(memory['id']), 'この内容を記憶から外しました。')

        with st.sidebar.expander('会話を消す'):
            st.caption('会話を消しても、覚えた回答は残ります。元には戻せません。')
            confirmed = st.checkbox('会話履歴を削除してよい')
            if st.button('会話履歴を削除', disabled=not confirmed):
                def clear_conversation():
                    store.clear_conversations()
                    clear_voice()
                attempt(clear_conversation, '会話履歴を削除しました。覚えた回答は残っています。')

        if notice := st.session_state.pop('simple_notice', None):
            st.success(notice)
        if not configured:
            st.info('Geminiの接続設定が必要です。左の「接続と送信について」から設定できます。')
        if not st.session_state.get('simple_consent', False):
            if st.checkbox('この会話と覚えた回答をGeminiへ送信して対話する'):
                st.session_state['simple_consent'] = True
                st.rerun()

        render_conversation(store, attempt)
        if not store.rows('SELECT id FROM responses LIMIT 1'):
            st.write('いま迷っていることや、うまく言葉にならないことから、話してみてください。')

        consent = st.session_state.get('simple_consent', False)
        def send_message(message):
            with st.spinner('考えを整理しています…'):
                converse_personal(store, GeminiResponder(), message, consent=consent)

        render_voice_input(send_message, attempt, enabled=configured and consent)
        if message := st.chat_input('いま、どんなことを考えていますか？', disabled=not configured or not consent):
            attempt(lambda: send_message(message))
    finally:
        store.db.close()


def run():
    try:
        _render()
    except (sqlite3.Error, OSError):
        st.error('保存データにアクセスできません。保存先と起動状態を確認して、もう一度開いてください。')
    except (ValueError, KeyError):
        st.error('保存データの形式を確認してください。')
