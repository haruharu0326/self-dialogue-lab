"""Optional tone display; no storage or conversation context updates."""

import os

import streamlit as st

from .sentiment import SentimentError, analyze


def render_tone(text, response_id):
    with st.expander('文章のトーン（任意）'):
        st.caption('本人の気持ちの断定ではなく、文章からの推定です。中立は「感情がない」という意味ではありません。')
        st.caption('分析はPC内で実行し、結果を記憶やGeminiへ渡しません。結果はこの表示だけで、再表示すると消えます。')
        configured = bool(os.environ.get('SENTIMENT_MODEL_PATH', '').strip())
        if not configured:
            st.caption('分析モデルは未設定です。READMEの「文章のトーン分析」の手順で有効化できます。')
        if st.button('文章のトーンを分析', key=f'product_tone_{response_id}', disabled=not configured):
            try:
                with st.spinner('この発言をPC内で分析しています…'):
                    result = analyze(text)
            except SentimentError as error:
                st.error(str(error))
            else:
                st.write(f"文章のトーンの推定：{result['label']}")
                st.caption('長文は先頭512トークンまでが対象です。複数の感情や皮肉を正しく分類できない場合があります。')
