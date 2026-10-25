# 受入テスト仕様書

現行の**チャット1画面と、確認した本人回答の記憶**を対象にします。代替応答器・通信で検証するデータ境界と、実際のAPI接続・画面表示・対話品質を区別します。

## テストの前提と判定

自動テストは一時的な本人用DBを使用し、実際のキー・個人データを使いません。通常画面はVitest + Testing Library（APIは代替）、HTTP APIはFastAPIのTestClient（応答器・分類器・文字起こしは代替）で検証します。検証用src/lab.pyのAppTestはStreamlit導入時だけ実行。skipは合格ではありません。自動部分のみ通ったケースは、UIまで合格と表現しません。

FR-018,019に対応するAT-032,033の番号は維持。AT-001〜031は過去の検証用・共通バックエンドの補助テストとして番号を留保し、現在の製品UIの合格判定に流用しません。

## 現行の受入ケース

最新の実施状況は[実施記録](#実施記録)を正本とします。以前の未確認・失敗は当時の記録として保持し、追加検証で解消した項目と区別します。

|ID・対応要件|事前条件・入力|手順|期待結果|自動／手動・実施状況|
|---|---|---|---|---|
|AT-032 / FR-018,NFR-011,012|空の本人用DB、代替応答器、キーなしのUI|通常入口を開く→送信未確認で実行→確認後に相談|サンプルなし、シナリオ・評価・領域切替なし。未確認では呼出しなし、会話が継続。任意の文章分析はAT-045|境界は自動成功。画面の最新結果は実施記録を参照|
|AT-033 / FR-019,NFR-004,005|発言「家族との時間を大切にしたい」とpending候補|保存前の次回入力→承認→接続を閉じ再接続→相談→同じ候補を再承認|承認前は長期記録なし、承認後だけ次回に含む、再接続でも保持、二重承認を拒否|自動成功。ボタン操作の目視は未実施|
|AT-034 / FR-020,NFR-008,013|現在・過去・未選択の記録、代替API|送信データを検査→実在ID／架空IDを返す|現在の記憶だけを渡す。根拠の本文はDBの写し。未送信IDは保存しない|自動成功。文章内での実際の出典利用の品質は未評価|
|AT-035 / FR-021,NFR-010|記憶、会話、過去の引用あり|拒否を確認→記憶を保存→忘れる→次回送信|拒否・削除したものは新しい長期根拠に入らない。会話と当時の写しは残る|自動成功。削除チェックの目視は未実施|
|AT-036 / FR-022,NFR-004,010|会話、候補、承認済み記憶、旧評価あり|会話を削除→再送信|会話関連4テーブルは空、records/meta維持、次の会話を開始できる|自動成功。画面操作は未実施|
|AT-037 / FR-023,NFR-008|空白発言、送信未確認、キーなし、無効モデル|各条件で送信を試す|不備は通信前に拒否、入力無効の案内、設定ありを疎通成功と表示しない|境界は自動成功。UIは未実施|
|AT-038 / FR-023,NFR-007〜009|ダミーキー、Git、代替通信|HTTPと保存内容を検査、check-ignoreで.env/DBと文書を確認|キーはヘッダーだけ。URL・DB・出力に含まれない。機微ファイルは非追跡、見本・文書は追跡|自動・追跡一覧確認成功。実キーの認証結果ではない|
|AT-039 / FR-018,024,NFR-005,006,009|HTTP 400/401/403/404/429/500/302、タイムアウト、不正JSON、途中終了、失敗トリガー|各異常を注入→内容と件数確認→失敗を解消して再試行|安全な通知、再試行なし、API失敗で新会話・候補なし、DB途中更新は全体ロールバック|自動成功。通常UIの通知・実ネットワーク障害の復旧操作は未確認|
|AT-040 / FR-018,023,NFR-001,002|Docker、.env、利用可能なGeminiキー|build/up→ps/health→ブラウザ→送信確認→短い接続テスト|アプリ起動、画面表示、確認後にAPI返答。3段階を別に判定|ユーザー提供ログでビルド・コンテナ作成成功。ユーザー実機で返答と次の会話の記憶参照を確認。エージェントの直接目視・health検査は未確認|
|AT-041 / NFR-003|会話100往復、記憶100件|同じPCで10回の保存・表示を測定、API待ち時間を分離|中央値・最大・環境を記録し暫定目標と比較|手動、未実施。性能保証なし|
|AT-042 / NFR-004|保存済み記憶・会話・候補|別Pythonプロセスで再取得→Dockerでも再作成後に確認|同じ内容が残る。Dockerの通常downでボリュームが残る|別プロセス検証成功。Docker再作成による保持は未確認|
|AT-043 / NFR-011|通常UI、同梱風景|1440px・390pxで会話・保存・参照・サイドバー操作|写真上でも読みやすい、過剰な管理操作なし、モバイルでも入力・確認可能|React移行後、架空データでヘッドレスEdgeの1366px・390pxの静止画面を確認。実ブラウザでの操作・コントラスト測定は未実施|
|AT-044 / FR-024,NFR-007〜009|ダミーキー、資格情報を含むプロキシ設定、生エラーを含む代替通信|接続診断で403とURLError、キー未設定を再現|キー・プロキシURL・生エラーは出さず、分類と設定有無だけ表示。キーなしなら送信しない|tests/test_connection_check.pyの3条件成功。実コンテナでの診断結果待ち|

### AT-045：文章トーンの任意分析

|対応要件|事前条件|手順|期待結果|実施状況|
|---|---|---|---|---|
|FR-025 / NFR-007,008,011|本人発言、未設定環境、代替分類器、取得済み実モデル|未設定表示→手動分析→成功・失敗→会話削除・ID再利用。別コンテナでネットワークを無効化して実モデルを実行|未設定時は無効。自動分析なし。結果は非保存・非送信で、再読み込み・会話削除で消失。安全な失敗通知。実モデルがローカルだけで動作|代替分類器の境界・画面テスト成功。実モデル推論はStreamlit版で成功（React移行後の実モデル画面確認は未実施）。精度評価と実ブラウザ目視は未実施|

## 実装・自動テストとの対応

### AT-046：音声入力

|対応要件|事前条件・手順|期待結果|検証方法|
|---|---|---|---|
|FR-026 / NFR-006〜010,012|モデル未設定で起動、録音→文字起こし→編集→送信確認→送信|手入力は継続可能。文字起こしだけではDB保存・API呼出しなし。編集した文字列だけを送信し、候補はpendingのまま|frontend/src/App.test.tsx（代替録音・代替API）とtests/test_api.py::test_voice_transcription_never_sends_or_stores|
|FR-026 / NFR-006,009|空・不正・切断・無音・長すぎる・形式違いの録音、推論と遅延走査の失敗|モデル呼出し前の境界検証、安全な通知。生エラー・録音・部分結果を表示しない|tests/test_voice.py|
|FR-026 / NFR-005,010|新録音・破棄・送信成功・送信失敗・会話削除|古い下書きを無効化。成功送信は一度だけ、失敗では下書き保持。会話削除で下書きも消失|frontend/src/App.test.tsx|
|FR-026 / NFR-008|事前取得後、ネットワークを切ってモデル読み込み・短い架空音声を文字起こし|ローカルファイルだけで推論。外部音声送信なし|実モデル確認は実施記録を参照。マイク権限・実ブラウザ録音・日本語認識精度は別判定|

AT-045 / FR-025,NFR-007,008,011：保存済み本人発言について、モデル未設定で分析ボタン無効・APIも分類器を呼ばない、設定時も手動クリック前は分析しないことを確認。代替分析器の成功・失敗を表示し、会話削除・ID再利用で古い結果を出さず、全DB内容が分析前後で不変で、状態APIに結果が含まれないことを確認。tests/test_api.py::test_tone_is_manual_ephemeral_and_does_not_modify_storage とfrontend/src/App.test.tsxのtone analysis、分類器境界はtests/test_sentiment.pyで検証。実モデルの精度・実ダウンロードとは分けて判定。

|ケース|主なテスト（tests/配下）|
|---|---|
|032|test_simple_chat.py::test_personal_chat_without_consent_does_not_call_model / test_api.py::test_initial_state_is_empty_without_samples / test_consent_and_blank_input_are_checked_before_the_model / frontend App.test.tsx「shows only the conversation…」「requires consent…」|
|033|test_simple_chat.py::test_answers_only_become_memory_after_user_confirmation / test_api.py::test_answer_becomes_memory_only_after_approval_and_only_once / frontend「remembers an edited answer…」|
|034|test_gemini.py::test_only_selected_current_records_are_sent_and_refs_are_db_snapshots / test_invalid_remote_response_does_not_persist|
|035|test_simple_chat.py::test_rejected_and_forgotten_answers_are_not_long_term_context / test_persistence.py::test_new_responses_exclude_changed_and_deleted_records / test_api.py::test_rejected_and_forgotten_answers_leave_long_term_context|
|036|test_persistence.py::test_clear_conversations_preserves_approved_records / test_api.py::test_clearing_conversation_keeps_memories / frontend「forgets a memory and clears the conversation…」|
|037|test_gemini.py::test_missing_key_consent_timeout_and_model_validation / test_simple_chat.py::test_personal_chat_without_consent_does_not_call_model|
|038|test_gemini.py::test_gemini_conversation_context_and_source_separation / test_integrity.py::test_git_excludes_private_files_but_not_docs_or_samples|
|039|test_gemini.py::test_http_errors_are_redacted_without_partial_save / test_invalid_remote_response_does_not_persist / test_integrity.py::test_approval_failure_rolls_back_record_and_historical_flag / test_api.py::test_api_failure_is_redacted_and_saves_nothing / test_storage_errors_use_safe_messages|
|042|test_persistence.py::test_records_conversation_and_feedback_survive_new_process / test_simple_chat.py::test_answers_only_become_memory_after_user_confirmation|
|045|test_api.py::test_tone_is_manual_ephemeral_and_does_not_modify_storage / frontend「tone analysis」 / test_sentiment.py。実モデルのネットワーク無効化推論は実施記録を参照|
|046|test_voice.py / test_api.py::test_voice_transcription_never_sends_or_stores / frontend「voice input」。実モデルと実マイクの確認は実施記録を参照|
|NFR-002|test_api.py::test_only_local_browser_requests_are_accepted（Host・Originの拒否）|

040,041,043の実環境部分を自動テスト成功から推定しません。検証用src/lab.pyの画面テストが通っても、通常UIの表示確認とは分けます。

## 思考深化と文書化の将来受入案

以下は[将来要件FFR/FNFR](../requirements/thinking-and-writing.md)の受入案です。**すべて未実装・未実施**で、既存のテスト成功数に含めません。API・DB・画面の仕様確定後に、境界の自動テストと本人による対話・文章の評価を具体化します。

|ID・将来要件|確認する場面|期待する結果|
|---|---|---|
|FAT-001 / FFR-001|テーマ未設定で話す→論点分岐→保留→後日再開|入力を強制せず、元の問いを見失わない。再開時は当時の立場と今の考えを区別する|
|FAT-002 / FFR-002|理由が曖昧な意見→具体例→質問を飛ばす・変える|発言に沿って原則1つの中心の問いを出す。答えを踏まえ、反復や動機の断定を避ける。本人が問いを変えられる|
|FAT-003 / FFR-003|意見に対する別解・反例を提案→本人が却下|理由と仮説であることを示し、却下した提案を本人の経験・結論・記憶に混ぜない|
|FAT-004 / FFR-004|仮まとめを修正・却下・保留→考えの変化を確認|本人確認前の長期保存なし。未決点を残し、誤入力修正と立場の変化を区別する|
|FAT-005 / FFR-005|未承認・拒否・過去・削除済み記録を含む履歴から素材を選ぶ|自動収集しない。本人が用途を確認した素材だけを使い、過去の考えは当時の立場と明示。原文変更・削除後は再確認。外部送信範囲を確認できる|
|FAT-006 / FFR-006|留保と不足情報を含む素材→構成案→本文→部分却下|確認順序を守り、経験・出典・結論を創作しない。根拠をたどれ、未決点を断定へ変えない。対話に戻れ、本人の記憶を自動更新しない|
|FAT-007 / FFR-007|内部メモや個人情報を含む下書きを取り出す|選んだ本文の範囲をプレビュー・確認でき、内部情報を自動混入させない。noteの認証・投稿・公開予約は呼ばない|
|FAT-008 / FFR-008|本文の改稿→原文削除→再生成→下書き削除|版と時点を区別し、削除済み素材を新たに使わない。残る本文・写し・書き出しと削除範囲を説明し、長期記憶との削除を混同しない|

品質評価では、本人が理由や前提を説明できるか、別の見方を検討できるか、未決点や次の問いを持てるか、文章が本人の意図に合うかを確認します。質問数・文字数・トーン分類・生成物の長さだけで思考深化を合格判定しません。

## 実施記録

### 自動レビュー実行器（2026-10-25）

製品FR/NFR/ATの変更はありません。`scripts/review.py`と出力スキーマを追加し、一括検証のJSON結果とGit差分・規約・関連仕様をCodex CLIへ渡します。[実行仕様・制限・記録](../development/harness-plan.md#自動レビュー実行器の仕様)を参照してください。Python129件成功・7件スキップ、画面15件成功、ビルド・起動成功。実CLIは未ログインのため実モデルでのレビュー成功は未確認です。模擬CLI連携、失敗・不正応答・未検証・入力変更・タイムアウトの扱いを確認し、未ログイン時の失敗レポートも実CLIで確認しました。

### 開発ハーネスの一括検証（2026-10-25）

製品FR/NFR/ATの追加・変更はありません。開発用の `python scripts/verify.py` を追加しました。[実行仕様と結果](../development/harness-plan.md#一括検証の実行仕様)を参照してください。Python 98件成功・7件スキップ（Streamlit未導入）、画面15件成功、型チェックを含むビルドと一時DBでの起動確認成功。スキップを完全成功と扱わず終了コード2でした。実ブラウザ・Docker・実API・実モデルは今回未確認です。

### 通常画面のReact移行（2026-10-25）

feature/react-frontendで通常画面をStreamlitからReact（Vite・TypeScript）とFastAPIへ移行。業務処理・DB・応答器・モデル連携は変更していません。旧画面のAppTest（通常入口のtest_simple_chat・test_sentiment_ui・test_voice_ui）はAPIテストと画面テストへ置き換えました。

- Python：Windows / Python 3.13.7 / FastAPI 0.162.0。99成功、1失敗、スキップなし。失敗はtest_integrity.py::test_document_paths_and_relative_links_existで、同時期に別作業で追加されたdocs/development/harness-plan.mdが期待する文書一覧にないためです。React移行の変更による失敗ではありませんが、未解消として記録します。
- 画面：Node.js 24.13.1 / React 19.3.1 / Vitest 5.0.5で15成功。TypeScript 7.0.2の型チェック成功。
- 起動：ビルドした画面を `python src/app.py` で配信し、画面・/api/health・風景画像のHTTP 200を確認。架空データの一時DBでヘッドレスEdgeの1366px・390px表示を目視し、狭い画面のはみ出しと最新の返答が入力欄に隠れる問題を修正しました。
- Docker：検証用タグでイメージのビルド成功（Node段で画面をビルド）。一時コンテナでhealthy、画面200、別Hostの403、別サイトOriginの削除要求403、キー未設定時の送信が安全な文言の502で保存なしを確認。利用者のComposeプロジェクト・ボリュームは使っていません。
- 利用者の実機確認：React移行後の画面でGeminiと対話できたと報告を受けました。エージェントの直接確認ではありません。音声入力の成功報告は別ブランチ（Streamlit版）での確認であり、React版の音声入力の確認ではありません。
- 未確認：React版の実ブラウザでのマイク録音（MediaRecorderからWAVへの変換）と文字起こし、実モデルのトーン分析の再確認、PC・モバイルの実機操作、コントラスト測定。

```powershell
$env:PYTHONPATH = "$PWD/.test-deps"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q --basetemp=.test-temp-react-final4 -p no:cacheprovider --tb=line
npm --prefix frontend test
npm --prefix frontend run typecheck
```

代替API・代替録音での画面テスト成功を、実マイクの動作や対話品質の検証とは扱いません。

### 音声入力の追加（2026-10-25）

feature/voice-inputでFR-026 / AT-046を追加。Windows / Python 3.13.7 / Streamlit 1.66.1で、永続化・境界・状態遷移・通常入口のAppTestを含め全98件成功、スキップなし。録音・文字起こしだけではAPI呼出しや会話保存が起きず、編集して確認した文章だけが送信・保存されること、送信確認、送信成功後の再表示、下書きの破棄・録音変更・会話削除・失敗時保持を検証しました。

```powershell
$env:PYTHONPATH = "$PWD/.test-deps"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q --basetemp=.test-temp-voice-final -p no:cacheprovider --tb=short --show-capture=no
```

初回は巨大な音声バイト列がpytestのケース名に入り、一時ファイルの準備で失敗したため、短い識別名を指定して解消。破棄ボタンのテストも、クリック前に擬似録音を消してボタンが描画されなくなる操作を修正しました。録音の解除時に下書きを破棄する処理を追加し、全件を再実行して成功しています。代替文字起こし・代替応答器のテストは実モデルの認識精度や実マイク動作の検証ではありません。

### 文章トーン分析の追加（2026-10-25）

現在の判定：FR-025 / AT-045の自動テスト、実モデルのオフライン推論、実モデルを使う画面部品のAppTest、Docker起動・healthは成功。分類の正確さを保証する評価は未実施です。モデル・配置の仕様は[内部設計](../design/internal-design.md#通常画面の文章トーン分析)を参照してください。

追加の実モデル検証：DockerイメージにCPU版PyTorch 2.14.1+cpu / Transformers 4.57.6を導入し、固定リビジョンのモデルを専用sentiment-modelsボリュームへ取得。ネットワークを無効化し、モデルを読み取り専用マウントした一時コンテナで推論成功。配布元の英語・日本語例文では公表例と同じポジティブ判定とスコアになりました。一方、架空サンプル「今日はとても嬉しいです。」はネガティブ、「明日の会議は十時からです。」はポジティブ、「悲しくてつらいです。」はネガティブでした。短い明確な文でも直感に合わない結果があり、日本語精度を保証できません。これは動作確認であり、体系的な精度評価ではありません。

同じネットワーク無効の環境で実モデルを用いたAppTest（分析ボタン→結果表示→再表示で結果消失）が成功。アプリを再作成し、healthyおよびHTTP health=200を確認。モデルと会話・記憶は別ボリュームで保持し、個人の発言は検証に使っていません。以下の初回検証時の「Docker・実モデル未確認」は、この追加確認で解消済みです。実ブラウザの目視と体系的な分類精度評価は引き続き未実施です。

feature/sentiment-analysisでFR-025 / AT-045を追加。Windows / Python 3.13.7 / Streamlit 1.66.1で、AppTestを含む全78件成功、スキップなし。モデル未設定・代替分析器の成功・失敗、手動実行、非永続化、再表示・削除・ID再利用を確認しました。FR/NFR/ATの対応は[文書一覧](../README.md)へ反映済みです。

検証用依存はGit対象外の.test-depsに導入。通常権限での通信・依存へのアクセスと、既存一時フォルダの権限衝突で初回検証は失敗したため、新しい専用一時フォルダで再実行しました。インストール時に既存グローバルパッケージとの依存競合警告がありましたが、検証用依存は専用フォルダに隔離しています。外部pytestプラグインの自動ロードは無効にしました。

```powershell
$env:PYTHONPATH = "$PWD/.test-deps"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q --basetemp=.test-temp-tone-final -p no:cacheprovider --tb=short -rs
```

Streamlitを一時DB・APIキーなし・127.0.0.1:18507で起動し、healthとページのHTTP 200を確認後に停止。検証用起動ではglobal.developmentMode=falseを指定（初回は開発モードとポート指定の競合で失敗）。Dockerはエンジンに接続できず未確認。実ブラウザの目視、実モデル取得・推論、日本語分類精度は未確認です。代替分類器のテスト成功を感情理解や実モデル精度の検証とは扱いません。

### 自動検証

開発環境：Windows / Python 3.13.7。現行文書への整理後に実行し、57 passed / 8 skipped（3.12秒）。スキップはエージェント側の開発環境にStreamlitが未導入のためで、画面の合格扱いにしていません。7文書の配置とファイルへの相対リンク、FR-018〜024、NFR-001〜013、AT-032〜043の定義と対応を確認しました。ユーザー環境のコンテナへの依存導入成功とは別の記録です。

```powershell
python -m pytest -q --basetemp=.test-temp-doc-current --tb=short -rs
```

このテストは保存・状態遷移・API入出力の境界を検証します。実Geminiの理解力や対話品質、センチメント精度、モデル重みの学習の検証ではありません。

### 実環境の証拠と制限

- ユーザー提供のDockerログでは、依存導入、イメージのビルド、コンテナ作成が成功しています。これはユーザー環境からの報告であり、エージェント側でのhealthや画面確認とは別です。
- 現在の.envは所定のプロジェクト直下に存在し、キーが空ではないことだけを確認しました。値は表示していません。設定の存在だけではGoogle側の認証成功を意味しません。
- エージェント環境からのDocker APIはアクセス拒否。短い合成テキストによるGeminiの接続確認も通信失敗となり、実際の認証・モデル利用可否は確定できていません。個人の会話・記憶を接続テストに使っていません。
- ユーザー環境では、モデル情報の取得がHTTP 200（0.2秒）で成功し、その後にチャットの返答と、覚えた回答を次の会話で参照する動作を確認したと報告されています。これはユーザーによる実機確認として記録します。
- エージェントの実ブラウザ操作、PC・モバイル両方の目視、health、Docker再作成での保持、性能測定、他OSは未確認です。

### 整合確認の観点

要件・外部設計はSCR-004のチャット1画面を正本とし、シナリオ・評価・管理画面を通常製品の必須機能に含めないことを確認します。文章トーンの任意分析はFR-025に従います。通常の入口はsrc/app.py、従来機能はsrc/lab.py。回答の学習は確認済み記憶の参照であり、再訓練ではないことを全書類で統一します。

### 残件

ユーザー実機でGeminiの返答と記憶参照は確認済みです。体系的なPC・モバイル目視、Dockerのhealthとボリューム保持、性能測定は残っています。未実装は要件定義書の対象外と未決事項に集約し、現在仕様と混在させません。

接続切り分けの追加確認：ユーザー環境でGoogleへのDNS/TCP/TLS接続テストはHTTPS OK。これはAPIのPOST・認証・モデルの成功とは別です。scripts/check_gemini.pyを追加し、秘密の非出力テスト3条件と文書リンク検査の計4件が成功しました。実コンテナでの診断は利用者の実行結果を待っています。

ユーザーの初回API診断はPOSTのTimeoutError。診断を「15秒のモデル情報GET」と、明示指定時だけの生成POSTへ分離し、アプリの待ち時間を120秒既定で設定可能にしました。関連テスト27成功・画面1スキップ。ユーザーの追加診断はモデルGETがHTTP 200で成功し、その後に返答と記憶参照の成功報告を得ています。初回タイムアウトの原因を生成遅延と断定したものではありません。

修正後の全体回帰：`python -m pytest -q --basetemp=.test-temp-timeout-final --tb=short -rs`で67成功、8スキップ（3.23秒）。スキップは引き続き開発環境のStreamlit不足による画面テストです。実APIの解消確認とは区別します。
