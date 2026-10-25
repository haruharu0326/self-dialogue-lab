"""Chat presentation shared by mock and Gemini modes."""

import json
import os
import streamlit as st

from .gemini import DEFAULT_MODEL, GeminiResponder
from .service import converse_gemini


def render_history(store, attempt, on_correct, *, correction_enabled=True, demo=False):
    for response in store.rows('SELECT r.*,m.body AS source FROM responses r JOIN messages m ON m.id=r.message_id ORDER BY r.id'):
        with st.chat_message('user'):
            st.caption('試用者が入力・選択した発言' if demo else '本人の発言')
            st.write(response['source'])
            with st.expander('発言のトーンを振り返る（任意）'):
                st.caption('ポジティブ・中立・ネガティブの推定です。本人の気持ちや人格の断定ではなく、長期記録やGeminiには渡しません。')
                if not os.environ.get('SENTIMENT_MODEL_PATH'):
                    st.caption('ローカルのセンチメントモデルは未設定です。READMEの任意セットアップで有効化できます。')
                elif st.button('この発言のトーンを推定', key=f"sentiment{response['id']}"):
                    from .sentiment import SentimentError, analyze
                    try:
                        with st.spinner('この発言だけをローカルで分析しています…'):
                            result = analyze(response['source'])
                        st.session_state[f"tone{response['id']}"] = result
                    except SentimentError as error:
                        st.error(str(error))
                tone = st.session_state.get(f"tone{response['id']}")
                if tone:
                    st.write(f"推定：{tone['label']} ／ モデルのスコア：{tone['score']:.0%}")
                    st.caption('スコアはモデル内の分類の重みであり、本人の感情が正しい確率ではありません。長文は先頭部分を対象にします。')
        with st.chat_message('assistant'):
            body = json.loads(response['body'])
            if body.get('correction_of') is not None:
                st.caption(f"応答 #{body['correction_of']} への訂正を反映")
            is_gemini = body.get('provider') == 'gemini'
            st.caption('Gemini APIの応答 · 推測を含み、確定した事実ではありません' if is_gemini else 'モック・固定応答（解釈の表示例） · 確定した事実ではありません')
            if is_gemini:
                st.caption('モデル：' + str(body.get('model', '未記録')))
            st.write(body['interpretation'])
            if body['question']:
                st.markdown('**問いかけ**')
                st.write(body['question'])
            with st.expander('参照した本人の記録'):
                refs = json.loads(response['refs'])
                if not refs:
                    st.write('関連記録なし')
                for ref in refs:
                    st.markdown(f"**記録 #{ref['id']} · {ref['occurred']}**")
                    st.write(ref['thought'])
                    st.caption(f"理由：{ref['reason']} ／ 文脈：{ref['context']}")
                st.caption(('架空サンプル領域の記録です。' if demo else '') + '応答時点の記録の写しです。後の修正・削除は反映されません。外部の事実は検証していません。')
            with st.form(f"feedback{response['id']}"):
                previous = store.rows('SELECT labels FROM feedback WHERE response_id=?', (response['id'],))
                labels = st.multiselect('この応答を評価', ['理解が正確', '有益な問い', '決めつけがある'], default=json.loads(previous[0]['labels']) if previous else [])
                if st.form_submit_button('評価を保存'):
                    attempt(lambda: store.save_feedback(response['id'], labels), '評価を保存しました')
            with st.expander('解釈を訂正する'):
                with st.form(f"correction{response['id']}"):
                    correction = st.text_area('実際の考え・解釈と違う点', key=f"correction_text{response['id']}")
                    if st.form_submit_button('訂正を送信', disabled=not correction_enabled):
                        attempt(lambda: on_correct(correction, response['id']))


def render_gemini_chat(store, attempt, demo):
    st.subheader('話しながら、考えをほどく。')
    configured = bool(os.environ.get('GEMINI_API_KEY', '').strip())
    st.caption('モデル：' + (os.environ.get('GEMINI_MODEL') or DEFAULT_MODEL))
    if not configured:
        st.info('GEMINI_API_KEYが未設定です。Google AI Studioで発行し、ローカルの.envへ設定してコンテナを再作成してください。キーはチャットに貼らないでください。')
        st.link_button('Google AI StudioでAPIキーを作成', 'https://aistudio.google.com/apikey')
    current = {r['id']: r for r in store.current_records()}
    selected = st.multiselect('今回の会話で参照する記録（未選択でも会話できます）', list(current),
                             format_func=lambda id: f"#{id} · {current[id]['thought']}")
    include_history = st.checkbox('直近10往復のGemini会話を文脈として送信', value=True)
    with st.expander('Googleへ送信する情報を確認'):
        st.write('今回の入力発言、下記の選択記録、チェックした場合は直近のGemini会話を送ります。訂正時は対象応答の本文も送ります。')
        st.write('長期記録の参照：' + ('なし' if not selected else f'{len(selected)}件'))
        for id in selected:
            st.write(current[id])
        history = store.gemini_history() if include_history else []
        st.caption(f'会話文脈：{len(history) // 2}往復。候補一覧・評価・画像・APIキーは本文に含めません。')
        if history:
            st.json(history)
        st.caption('会話文脈には未承認候補の元になった発言も含まれますが、長期記録や固定した信念とは区別します。送信後のGoogle側の取扱いは利用条件に従います。')
    consent = st.checkbox('上記の範囲をGoogleのGemini APIへ送信することを確認しました')

    def send(text, correction_of=None):
        with st.spinner('Geminiが応答を考えています…'):
            converse_gemini(store, GeminiResponder(), text, reference_ids=selected, include_history=include_history,
                            consent=consent, demo=demo, correction_of=correction_of)

    render_history(store, attempt, lambda text, id: send(text, id),
                   correction_enabled=configured and consent, demo=demo)
    if message := st.chat_input('いま考えていることを話す', disabled=not configured or not consent):
        attempt(lambda: send(message))
