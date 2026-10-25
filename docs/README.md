# 文書一覧

現在の製品は、**対話を中心に、自分の回答を覚えて次の対話に活かすチャットボット**です。通常入口は `src/app.py`（FastAPIのAPIサーバー）で、画面は `frontend/` のReactです。この7文書を現在仕様の正本とし、以前の多機能画面を前提とした仕様への追記は残しません。

## 読む順序と各文書の役割

|順序|文書|詳細を記載する範囲|
|---|---|---|
|1|[要件定義書](requirements/requirements-definition.md)|目的、利用者、用語、対象範囲、将来と未決事項|
|2|[機能要件書](requirements/functional-requirements.md)|FRごとの入力・処理・異常・保存・受入条件|
|3|[非機能要件書](requirements/non-functional-requirements.md)|NFRごとの制約、適用範囲、確認方法|
|4|[外部設計書](design/external-design.md)|1画面の構成、入力・操作・表示・削除範囲|
|5|[内部設計書](design/internal-design.md)|モジュール、SQLite、API、状態遷移、設定|
|6|[受入テスト仕様書](testing/acceptance-tests.md)|手順・期待結果・自動テスト対応・実施状況|

起動・キー設定は[プロジェクトREADME](../README.md)、開発方針は[AGENTS.md](../AGENTS.md)を参照してください。詳細仕様の重複を避け、他文書からは担当文書へリンクします。

将来の製品方向は[思考を深める対話と文書化](requirements/thinking-and-writing.md)を参照してください。note向けの下書きに備え、思考深化・素材選択・構成案・下書き・公開前確認の要件を定義しています。未実装の将来要件であり、現在使える機能とは分けて管理します。

## 要件・設計・実装・テストの対応

開発環境の改善は[開発ハーネスの現状と導入案](development/harness-plan.md)を参照してください。製品機能とは分けて、現状の不足・規約との不整合・検証結果・導入順を記載しています。

現行FR-018,019とAT-032,033の番号は維持しています。新規の番号を追加し、旧番号を別機能へ再利用しません。

|要件|外部設計|実装・内部設計|受入テスト|
|---|---|---|---|
|FR-018 対話|SCR-004・入力と履歴|App.tsx / Conversation.tsx / api.py POST /api/messages / service.converse_personal / gemini.py|AT-032,039,040|
|FR-019 回答を覚える|本人発言の折りたたみ|Conversation.tsx / api.py approve, reject / Store.approve, reject|AT-033|
|FR-020 参照の確認|返答の参照欄|Conversation.tsx / GeminiResponder / responses.refs|AT-034|
|FR-021 記憶を見る・忘れる|サイドバーの記憶|Sidebar.tsx / api.py DELETE /api/memories / Store.current_records, delete_record|AT-035|
|FR-022 会話を消す|サイドバーの削除|Sidebar.tsx / api.py DELETE /api/conversations / Store.clear_conversations|AT-036|
|FR-023 接続と送信確認|接続案内・確認チェック|App.tsx / Sidebar.tsx / api.py / compose.yaml|AT-037,038,040|
|FR-024 エラー通知|エラー表示|GeminiError / api.pyの例外ハンドラー / api.ts / scripts/check_gemini.py|AT-037,039,044|
|FR-025 文章トーン3分類|本人発言の任意操作|Conversation.tsx / api.py POST /api/exchanges/{id}/tone / sentiment.py / Dockerfile / compose.yaml|AT-045|
|FR-026 音声入力|録音→文字起こし→確認編集→送信|VoiceInput.tsx / recorder.ts / api.py POST /api/voice/transcribe / voice.py / Dockerfile / compose.yaml|AT-046|
|NFR-001,002 実行環境・ローカル|起動・設定|Dockerfile / compose.yaml / app.py / api.pyのHost・Origin確認|AT-040|
|NFR-003 性能|通常操作|未測定|AT-041|
|NFR-004,005 永続性・整合性|覚える・忘れる・削除|SQLite / Store.transaction|AT-033,035,036,042|
|NFR-006,009 エラー・ログ|共通通知|gemini.py / api.py / app.py（アクセスログ無効）|AT-039|
|NFR-007,008 秘密・外部送信|送信範囲案内・分析結果の非送信|.gitignore / GeminiResponder / sentiment.py|AT-037,038,045|
|NFR-010 削除の範囲|記憶と会話の別操作|records / 会話関連テーブル|AT-035,036|
|NFR-011 分かりやすさ|SCR-004・自然背景・任意分析|frontend/src/styles.css / components / assets/lake-dawn.png|AT-032,043,045|
|NFR-012,013 分離・交換性|対象外|frontend / api / service / store / GeminiResponder|AT-032〜034,039|

音声入力の非保存・送信確認・エラー・下書き状態の境界はNFR-006〜010,012とAT-046にも対応します。モデルや設定の詳細は[内部設計の音声入力](design/internal-design.md#音声入力)、手順は[プロジェクトREADME](../README.md#音声入力任意)を参照してください。

結果の正本は[実施記録](testing/acceptance-tests.md#実施記録)です。コードが存在すること、代替通信のテストが通ること、実際の接続や対話品質を確認したことは区別します。

## 将来要件との対応（未実装）

詳細の正本は[将来要件](requirements/thinking-and-writing.md)、受入案の正本は[将来受入案](testing/acceptance-tests.md#思考深化と文書化の将来受入案)です。FFR/FNFR/FATは将来用の番号で、現行FR/NFR/ATの実装済み扱いには含めません。

|将来要件|内容|受入案|設計・実装・実施状態|
|---|---|---|---|
|FFR-001 / FNFR-001,005|テーマと問いの保持・再開|FAT-001|未設計・未実装・未実施|
|FFR-002 / FNFR-001,005|理由・前提・経験の掘り下げ|FAT-002|未設計・未実装・未実施|
|FFR-003 / FNFR-001,002|別の見方・反例|FAT-003|未設計・未実装・未実施|
|FFR-004 / FNFR-001,002,004|本人確認による仮まとめ・未決点|FAT-004|未設計・未実装・未実施|
|FFR-005 / FNFR-002〜004|記事素材の選択・確認|FAT-005|未設計・未実装・未実施|
|FFR-006 / FNFR-001〜005|構成案・下書きの確認編集|FAT-006|未設計・未実装・未実施|
|FFR-007 / FNFR-002,003,005|公開前確認・手動転記や書き出し|FAT-007|未設計・未実装・未実施|
|FFR-008 / FNFR-002,004|版・時点・削除範囲|FAT-008|未設計・未実装・未実施|

## 通常製品と検証用機能

通常製品はチャット1画面で、サンプルを投入しません。シナリオ、評価、JSON出力、詳細な履歴管理は通常画面に表示しません。文章トーンの任意分析は[FR-025](requirements/functional-requirements.md#fr-025-文章のトーンを分析する)を参照してください。従来のコードとデータは削除せず、開発者向けの `src/lab.py` に分離しています。その位置付けは[内部設計の検証用機能](design/internal-design.md#検証用機能)に集約します。

## 未決事項と未確認事項

|ID|内容|担当箇所|
|---|---|---|
|OD-001|記憶が増えたときの意味検索・自動要約・送信量制限|[将来拡張](requirements/requirements-definition.md#将来拡張と未決事項)|
|OD-002|入力文字数・保存件数・性能目標の確定と測定|[NFR-003](requirements/non-functional-requirements.md#nfr-003-性能)|
|OD-003|暗号化・バックアップ・復元方針|[未決事項](requirements/non-functional-requirements.md#未決事項)|
|OD-004|実API・Docker・ブラウザ・他OSの動作確認|[実施記録](testing/acceptance-tests.md#実施記録)|
|OD-005|通常画面での記憶の訂正・変化の扱い|[対象範囲](requirements/requirements-definition.md#対象範囲)|
|OD-006|日本語トーン分類の精度評価・モデル再選定|[将来拡張と未決事項](requirements/requirements-definition.md#将来拡張と未決事項)|
|OD-007|思考テーマ、素材確認、文書の版・保持期間・削除関係|[将来要件の未決事項](requirements/thinking-and-writing.md#未決事項)|
|OD-008|note向けの出力形式・出典・公開前確認・評価方法|[将来要件の未決事項](requirements/thinking-and-writing.md#未決事項)|

アーキテクチャ図は今後作成する予定です。図の作成までは[内部設計](design/internal-design.md)の実装構成とデータの流れを参照してください。
