# 文書一覧

現在の製品は、**対話を中心に、自分の回答を覚えて次の対話に活かすチャットボット**です。通常入口は `src/app.py`。この7文書を現在仕様の正本とし、以前の多機能画面を前提とした仕様への追記は残しません。

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

## 要件・設計・実装・テストの対応

現行FR-018,019とAT-032,033の番号は維持しています。新規の番号を追加し、旧番号を別機能へ再利用しません。

|要件|外部設計|実装・内部設計|受入テスト|
|---|---|---|---|
|FR-018 対話|SCR-004・入力と履歴|ui.py / service.converse_personal / gemini.py|AT-032,039,040|
|FR-019 回答を覚える|本人発言の折りたたみ|simple_chat.py / Store.approve, reject|AT-033|
|FR-020 参照の確認|返答の参照欄|GeminiResponder / responses.refs|AT-034|
|FR-021 記憶を見る・忘れる|サイドバーの記憶|Store.current_records, delete_record|AT-035|
|FR-022 会話を消す|サイドバーの削除|Store.clear_conversations|AT-036|
|FR-023 接続と送信確認|接続案内・確認チェック|ui.py / compose.yaml|AT-037,038,040|
|FR-024 エラー通知|エラー表示|GeminiError / ui.run / scripts/check_gemini.py|AT-037,039,044|
|NFR-001,002 実行環境・ローカル|起動・設定|Dockerfile / compose.yaml|AT-040|
|NFR-003 性能|通常操作|未測定|AT-041|
|NFR-004,005 永続性・整合性|覚える・忘れる・削除|SQLite / Store.transaction|AT-033,035,036,042|
|NFR-006,009 エラー・ログ|共通通知|gemini.py / ui.py|AT-039|
|NFR-007,008 秘密・外部送信|送信範囲案内|.gitignore / GeminiResponder|AT-037,038|
|NFR-010 削除の範囲|記憶と会話の別操作|records / 会話関連テーブル|AT-035,036|
|NFR-011 分かりやすさ|SCR-004・自然背景|simple_chat.py / assets/nature.css|AT-032,043|
|NFR-012,013 分離・交換性|対象外|service / store / GeminiResponder|AT-032〜034,039|

結果の正本は[実施記録](testing/acceptance-tests.md#実施記録)です。コードが存在すること、代替通信のテストが通ること、実際の接続や対話品質を確認したことは区別します。

## 通常製品と検証用機能

通常製品はチャット1画面で、サンプルを投入しません。シナリオ、評価、センチメント分析、JSON出力、詳細な履歴管理は通常画面に表示しません。従来のコードとデータは削除せず、開発者向けの `src/lab.py` に分離しています。その位置付けは[内部設計の検証用機能](design/internal-design.md#検証用機能)に集約します。

## 未決事項と未確認事項

|ID|内容|担当箇所|
|---|---|---|
|OD-001|記憶が増えたときの意味検索・自動要約・送信量制限|[将来拡張](requirements/requirements-definition.md#将来拡張と未決事項)|
|OD-002|入力文字数・保存件数・性能目標の確定と測定|[NFR-003](requirements/non-functional-requirements.md#nfr-003-性能)|
|OD-003|暗号化・バックアップ・復元方針|[未決事項](requirements/non-functional-requirements.md#未決事項)|
|OD-004|実API・Docker・ブラウザ・他OSの動作確認|[実施記録](testing/acceptance-tests.md#実施記録)|
|OD-005|通常画面での記憶の訂正・変化の扱い|[対象範囲](requirements/requirements-definition.md#対象範囲)|

アーキテクチャ図は今後作成する予定です。図の作成までは[内部設計](design/internal-design.md)の実装構成とデータの流れを参照してください。
