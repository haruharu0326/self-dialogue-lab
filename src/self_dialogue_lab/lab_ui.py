from datetime import datetime
from pathlib import Path
import json
import os
import streamlit as st
from .store import Store
from .responder import MockResponder, ResponderError
from .service import converse
from .presentation import nature_stylesheet, page_hero, page_steps
from .gemini import GeminiError
from .chat_ui import render_history, render_gemini_chat
import sqlite3



def _render():
    st.set_page_config(page_title='Self Dialogue Lab', page_icon='◌', layout='wide')
    st.markdown(nature_stylesheet(), unsafe_allow_html=True)

    st.sidebar.title('◌ Self Dialogue Lab')
    st.sidebar.caption('自分の言葉から、次の問いへ。')


    def reset_workspace():
        # 領域切替時に入力途中のサンプル値などを別領域へ持ち越さない。
        for key in list(st.session_state):
            if key != 'workspace':
                del st.session_state[key]


    workspace = st.sidebar.selectbox('データ領域', ['架空サンプルで試す', '自分の記録（初期データなし）'], key='workspace', on_change=reset_workspace)
    demo = workspace == '架空サンプルで試す'
    database = 'demo.sqlite3' if demo else 'personal.sqlite3'
    override = os.environ.get('SELF_DIALOGUE_DB') if demo else os.environ.get('SELF_DIALOGUE_PERSONAL_DB')
    root = Path(__file__).resolve().parents[2]
    demo_path = Path(os.environ.get('SELF_DIALOGUE_DB') or root / 'data' / 'demo.sqlite3').resolve()
    personal_path = Path(os.environ.get('SELF_DIALOGUE_PERSONAL_DB') or root / 'data' / 'personal.sqlite3').resolve()
    if demo_path == personal_path:
        st.error('サンプル用と自分用に同じDBは指定できません。保存先を分けて再起動してください。')
        st.stop()
    store = Store(override or str(root / 'data' / database))
    try:
        if demo:
            store.seed()
        mode = st.sidebar.selectbox('応答モード', ['モック・固定応答', 'Geminiチャット'],
                                   index=1 if os.environ.get('GEMINI_API_KEY', '').strip() else 0)
        page = st.sidebar.radio('ワークスペース', ['対話', '考えの一覧', '保存確認'])
        st.markdown(page_hero(page), unsafe_allow_html=True)
        if mode == 'Geminiチャット':
            st.info('Gemini API ｜ 送信を確認した入力・会話・選択記録をGoogleへ送ります。応答は推測を含み、人格や意識の再現ではありません。')
        else:
            st.warning('モック・固定応答 ｜ 自由入力の意味を理解・分析しません。シナリオに沿った操作の試用です。')
        if demo:
            st.caption('架空サンプル用データ領域です。初期記録や例文は、実際のあなたについての情報ではありません。試す内容だけを入力してください。')
        else:
            st.caption('自分の記録用データ領域です。架空サンプルは登録されません。応答モードを確認して利用してください。')
        st.markdown(page_steps(page, gemini=mode == 'Geminiチャット'), unsafe_allow_html=True)
        pending = store.rows("SELECT * FROM candidates WHERE status='pending' ORDER BY id")
        st.sidebar.metric('承認待ちの候補', len(pending))
        st.sidebar.info('ローカルアプリ\n\nモックは外部送信なし。GeminiチャットのみGoogleへ送信します。サンプル領域の初期記録は架空です。')
        with st.sidebar.expander('会話履歴の削除'):
            st.caption('選択中のデータ領域の会話・評価・保存候補（承認・拒否履歴を含む）を削除します。考えの記録は残ります。')
            clear_confirmed = st.checkbox('会話履歴を削除する（元に戻せません）')
            if st.button('会話履歴だけを削除', disabled=not clear_confirmed):
                store.clear_conversations()
                for key in list(st.session_state):
                    if str(key).startswith('tone'):
                        del st.session_state[key]
                st.session_state['notice'] = '会話履歴を削除しました。考えの記録は残っています。'
                st.rerun()


        def fields(prefix, item=None):
            item = item or {}
            thought = st.text_area('考え', item.get('thought', ''), key=prefix+'t')
            reason = st.text_area('理由', item.get('reason', ''), key=prefix+'r')
            context = st.text_input('文脈', item.get('context', ''), key=prefix+'c')
            return thought, reason, context


        def attempt(fn, success=None):
            try:
                fn()
            except (ValueError, GeminiError, ResponderError) as e:
                st.error(str(e))
            else:
                if success:
                    st.session_state['notice'] = success
                st.rerun()


        def timestamp(value, key):
            day = st.date_input('日付', value.date(), key=key+'day')
            time = st.time_input('時刻', value.time(), key=key+'time')
            return datetime.combine(day, time)


        if notice := st.session_state.pop('notice', None):
            st.success(notice)

        if page == '対話' and mode == 'Geminiチャット':
            render_gemini_chat(store, attempt, demo)
        elif page == '対話':
            st.subheader('今日、どんなことを考えますか。')
            scenario = st.selectbox('モックシナリオ', ['A. 過去の考えから問い返す', 'B. AIの解釈を訂正する', 'C. 以前とは考えが変わった', 'D. 関連記録がないときに質問する', 'E. 保存候補を承認または拒否する'])
            if scenario.startswith('E.'):
                st.info('例：「仕事では安定より裁量を優先したい」と送信し、左の「保存確認」を開いてください。候補ごとに承認・拒否を試せます。拒否も試す場合は、もう一つ発言を送信してください。')
            if scenario.startswith('D.'):
                st.info('例：「地域の図書館でボランティアをすることについて考えたい」と送信します。このモックでは入力や保存済みの記録にかかわらず、関連記録0件を再現します。本人の価値観を推測せず、現在の考えを質問します。')
            if scenario.startswith('C.'):
                st.info('変更元を選び、新しい考えを入力します。「保存確認」で承認すると、以前の記録に結びついた新しい記録になります。')
                options = {r['id']: r for r in store.records()}
                if options:
                    with st.form('change_thought'):
                        previous_id = st.selectbox('変更元の記録', list(options), format_func=lambda id: f"#{id} · {options[id]['thought']}")
                        values = fields('dialogue_change')
                        if st.form_submit_button('考えの変化を保存候補にする', type='primary'):
                            attempt(lambda: converse(store, MockResponder(), values[0], scenario, previous_id=previous_id, reason=values[1], context=values[2]))
                else:
                    st.info('変更元となる記録がありません。「考えの一覧」で登録してください。')
            if scenario.startswith('B.'):
                st.info('例：「転職を迷っています」と送信 → 応答の「解釈を訂正する」で「収入ではなく、家族との時間が減ることが心配です」と入力します。訂正は自動で長期記録を変更しません。')
            if scenario.startswith('A.'):
                st.caption('例：裁量のある仕事に挑戦したいけれど、収入が不安です。応答はシナリオ別の固定文です。')
            examples = {
                'A': '裁量のある仕事に挑戦したいけれど、収入が不安です。',
                'B': '転職を迷っています。',
                'D': '地域の図書館でボランティアをすることについて考えたい。',
                'E': '仕事では安定より裁量を優先したい。',
            }
            if scenario[0] in examples and st.button('シナリオ例文を送信'):
                attempt(lambda: converse(store, MockResponder(), examples[scenario[0]], scenario))
            render_history(store, attempt,
                           lambda text, id: converse(store, MockResponder(), text, 'B. AI', correction_of=id), demo=demo)
            if not scenario.startswith('C.'):
                if text := st.chat_input('試用する発言を入力（意味解析なし・選択シナリオの固定応答）'):
                    attempt(lambda: converse(store, MockResponder(), text, scenario))

        elif page == '考えの一覧':
            st.subheader('考えの記録')
            st.write('誤入力は修正。考えの変化は、前の記録につながる新しい記録として残します。')
            st.download_button('JSONを書き出す', store.export(), 'demo-thoughts.json' if demo else 'personal-thoughts.json', 'application/json')
            with st.expander('＋ 考えを登録'):
                with st.form('new'):
                    values = fields('new')
                    occurred = timestamp(datetime.now(), 'newdate')
                    if st.form_submit_button('登録', type='primary'):
                        attempt(lambda: store.add(*values, occurred.isoformat(timespec='minutes')))
            records = store.records()
            if not records:
                st.info('まだ考えの記録はありません。上のフォームから登録できます。')
            for record in records:
                with st.expander(f"#{record['id']} · {record['thought']}"):
                    st.caption(f"{record['occurred']} · " + ('変化前の記録' if record['superseded'] else '現在の記録'))
                    if record['previous_id']:
                        st.info(f"記録 #{record['previous_id']} からの考えの変化")
                    mode = st.radio('操作', ['誤入力を修正', '今は考えが変わった'], key=f"mode{record['id']}")
                    with st.form(f"edit{record['id']}"):
                        values = fields(str(record['id']), record)
                        occurred = timestamp(datetime.now() if mode == '今は考えが変わった' else datetime.fromisoformat(record['occurred']), f"date{record['id']}{mode}")
                        if st.form_submit_button('変更を保存', type='primary'):
                            if mode == '誤入力を修正':
                                attempt(lambda: store.edit(record['id'], *values, occurred.isoformat(timespec='minutes')))
                            else:
                                attempt(lambda: store.add(*values, occurred.isoformat(timespec='minutes'), previous_id=record['id']))
                    confirmed = st.checkbox('この記録を削除する（元に戻せません）', key=f"confirm{record['id']}")
                    st.caption('削除すると派生記録とのリンクは解除されます。会話内の参照の写しは残ります。')
                    if st.button('記録を削除', key=f"delete{record['id']}", disabled=not confirmed):
                        attempt(lambda: store.delete_record(record['id']))

        else:
            st.subheader('ひとつずつ、確認する')
            st.write('候補は発言をそのまま使うモックです。承認するまで長期記録や参照対象には入りません。')
            if not pending:
                st.info('承認待ちの候補はありません。対話画面でメッセージを送ると候補が作られます。')
            for candidate in pending:
                with st.container(border=True):
                    st.subheader(f"保存候補 #{candidate['id']}")
                    if candidate['previous_id'] is not None:
                        st.info(f"考えの変化 · 変更元の記録 #{candidate['previous_id']}（元の記録は上書きしません）")
                        old = store.rows('SELECT * FROM records WHERE id=?', (candidate['previous_id'],))
                        if old:
                            st.write('以前の考え：' + old[0]['thought'])
                        else:
                            st.warning('変更元は削除済みです。この候補は承認できません。拒否して作り直してください。')
                    source = store.rows('SELECT body FROM messages WHERE id=?', (candidate['message_id'],))[0]
                    with st.expander('根拠となる本人の発言', expanded=True):
                        st.write(source['body'])
                    with st.form(f"candidate{candidate['id']}"):
                        values = fields('candidate'+str(candidate['id']), candidate)
                        approve = st.form_submit_button('編集内容を承認して保存', type='primary')
                        reject = st.form_submit_button('拒否する')
                        if approve:
                            attempt(lambda: store.approve(candidate['id'], *values), f"候補 #{candidate['id']} を承認し、長期記録に保存しました。")
                        if reject:
                            attempt(lambda: store.reject(candidate['id']), f"候補 #{candidate['id']} を拒否しました。長期記録には保存していません。")
            st.caption('承認済み：' + str(len(store.rows("SELECT id FROM candidates WHERE status='approved'"))) + ' / 拒否済み：' + str(len(store.rows("SELECT id FROM candidates WHERE status='rejected'"))))
            with st.expander('承認・拒否の履歴'):
                history = store.rows("SELECT c.*,m.body AS source FROM candidates c JOIN messages m ON m.id=c.message_id WHERE c.status IN ('approved','rejected') ORDER BY c.id DESC")
                if not history:
                    st.write('処理済みの候補はありません。')
                for item in history:
                    st.markdown(f"**候補 #{item['id']} · {'承認済み' if item['status'] == 'approved' else '拒否済み'}**")
                    st.write(item['thought'])
                    st.caption(f"理由：{item['reason']} ／ 文脈：{item['context']}")
                    st.write('根拠となる本人の発言：' + item['source'])
                st.caption('処理時の候補の履歴です。承認後の長期記録への修正・削除は反映されません。拒否した候補も確認用に残ります。')
    finally:
        store.db.close()


def run():
    try:
        _render()
    except (sqlite3.Error, OSError):
        st.error('データの読み書きに失敗しました。保存先の権限・空き容量・他の起動を確認して再試行してください。')
    except (ValueError, KeyError):
        st.error('初期データまたは保存内容の形式を確認してください。')
