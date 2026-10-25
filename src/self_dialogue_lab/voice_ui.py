"""Record, transcribe, review, then explicitly send through the normal chat."""

from hashlib import sha256
import os

import streamlit as st

from .voice import MAX_BYTES, VoiceError, transcribe


def clear_voice():
    epoch = st.session_state.get('voice_epoch', 0)
    for key in list(st.session_state):
        if key.startswith('voice_'):
            del st.session_state[key]
    st.session_state['voice_epoch'] = epoch + 1


def render_voice_input(send, attempt, *, enabled):
    with st.expander('音声で入力（任意）'):
        st.caption('60秒以内の日本語を録音できます。音声はこのPC内で文字起こしし、ファイルやDBに保存しません。')
        st.caption('文字起こしには誤りがあります。内容を確認・編集してから送信してください。送信した文章は通常の会話として保存し、Geminiへ送ります。')
        configured = bool(os.environ.get('VOICE_MODEL_PATH', '').strip())
        if not configured:
            st.info('音声モデルは未設定です。READMEの「音声入力」の手順で有効化できます。手入力は引き続き使えます。')
        epoch = st.session_state.get('voice_epoch', 0)
        audio = st.audio_input('録音する', sample_rate=16000, key=f'voice_audio_{epoch}', disabled=not configured)
        if audio is None or not configured:
            st.session_state.pop('voice_digest', None)
            st.session_state.pop(f'voice_draft_{epoch}', None)
            return
        data = audio.getvalue()
        if len(data) > MAX_BYTES:
            st.error('録音は60秒以内にして、もう一度録音してください。')
            # A rejected replacement recording must invalidate the previous draft too.
            st.session_state.pop('voice_digest', None)
            st.session_state.pop(f'voice_draft_{epoch}', None)
            return
        digest = sha256(data).hexdigest()
        draft_key = f'voice_draft_{epoch}'
        if st.session_state.get('voice_digest') != digest:
            st.session_state['voice_digest'] = digest
            st.session_state[draft_key] = ''
        if st.button('文字起こし', key=f'voice_transcribe_{epoch}'):
            try:
                with st.spinner('このPC内で文字起こししています…'):
                    st.session_state[draft_key] = transcribe(data)
            except VoiceError as error:
                st.error(str(error))
        text = st.text_area('送信する文章（確認・編集）', key=draft_key)
        if not enabled:
            st.caption('送信にはGeminiの接続設定と、会話の送信確認が必要です。')
        if st.button('この文章を送信', key=f'voice_send_{epoch}', disabled=not enabled or not text.strip()):
            def deliver():
                send(text.strip())
                clear_voice()
            attempt(deliver)
        if st.button('録音と下書きを破棄', key=f'voice_discard_{epoch}'):
            clear_voice()
            st.rerun()
