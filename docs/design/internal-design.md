# 内部設計書

通常製品の実装を説明します。画面は[外部設計](external-design.md)、機能の受入条件は[機能要件](../requirements/functional-requirements.md)を正本とします。アーキテクチャ図は後日作成予定で、今回は追加しません。

## 構成と責務

|場所|責務・主な依存|
|---|---|
|src/app.py|通常入口。ui.runを呼ぶ|
|src/self_dialogue_lab/ui.py|1画面チャット、接続・送信確認、記憶一覧・削除、会話削除。Storeとserviceを呼ぶ|
|simple_chat.py|会話と参照の描画、本人回答の承認・拒否|
|service.py|入力・送信確認、現在の記憶選択、会話文脈、応答呼出し、一括保存|
|store.py|SQLite初期化・移行、記憶・候補の状態遷移、履歴・削除・データ取得|
|gemini.py|Gemini REST通信、出力・参照ID検証、安全なエラー分類。UI/DBに依存しない|
|responder.py|Replyと応答契約、検証用固定応答。通常UIは固定応答を呼ばない|
|presentation.py / assets/|ローカルの風景PNG・CSS。data URL化したCSSをキャッシュ|
|tests/test_simple_chat.py|現行製品の対話・記憶境界と通常画面の確認|
|tests/test_gemini.py, test_integrity.py, test_persistence.py|API・DBの共通境界と回帰テスト|
|Dockerfile / compose.yaml|ローカル起動、キーの実行時注入、DBボリューム|

通常の呼出しは `ui → converse_personal → converse_gemini → GeminiResponder`。保存はStoreで行い、描画側からも主要更新にapprove/reject/delete_record/clear_conversationsを使います。単純な一覧取得はStore.rowsを利用します。不要な学習基盤・ベクトルDB・追加の抽象層は置きません。

## 対話と記憶のデータの流れ

1. 通常UIはpersonal.sqlite3を開く。サンプルを投入しない。
2. 発言を受け取るとconverse_personalがcurrent_records()の全IDを取得する。
3. converse_geminiが送信確認、空白、IDの有効性を検証し、Gemini履歴の直近10往復を取得する。
4. GeminiResponderへ発言、現在の記憶、会話文脈を渡す。候補テーブル・評価・画像は渡さない。
5. 生成結果の形式と参照IDを検証する。通過後に発言・返答・候補を同じトランザクションで保存。
6. 本人が後で候補を承認したときだけrecordsへ追加する。次回の手順2から記憶として含まれる。

会話文脈は当時のやり取りで、未承認候補の元発言も含み得ます。長期記憶と同じ扱いにはしない指示をAPIへ付けます。拒否した発言を会話から消す操作ではない点に注意します。

## SQLiteのテーブル

全接続でforeign_keys=ON。日時はローカル・タイムゾーンなしのISO文字列、分単位。JSONはTEXT。以下にNOT NULLと書いていない列は、宣言上NULL可です。通常の業務処理では必須入力・状態を別途検証します。

|テーブル|列とSQLite型|制約と用途|
|---|---|---|
|records|id INTEGER|PRIMARY KEY AUTOINCREMENT。以後の削除済みIDを再利用しない|
||thought TEXT|NOT NULL。承認時に空白禁止|
||reason TEXT, context TEXT, occurred TEXT|理由・文脈・日時。通常UIでは理由空、文脈は本人確認の定型文|
||previous_id INTEGER|FK records.id、ON DELETE SET NULL。旧データの変化リンクを維持|
||superseded INTEGER|NOT NULL DEFAULT 0。現在0、過去1|
|messages|id INTEGER|PRIMARY KEY|
||role TEXT, body TEXT|通常role=user、bodyは入力原文|
|responses|id INTEGER|PRIMARY KEY|
||message_id INTEGER|FK messages.id、既定NO ACTION|
||body TEXT|interpretation, question, correction_of, provider, modelのJSON|
||refs TEXT|実際に参照したrecordsの写しのJSON配列|
|candidates|id INTEGER|PRIMARY KEY|
||message_id INTEGER|FK messages.id、既定NO ACTION。根拠の本人発言|
||thought TEXT, reason TEXT, context TEXT|候補と保存時の編集内容|
||status TEXT|DEFAULT 'pending'。有効な遷移は業務処理が制御|
||previous_id INTEGER|FKなし。旧機能の変更元ID。削除されたIDを保持して承認を止める|
|feedback|response_id INTEGER|PRIMARY KEY、FK responses.id、既定NO ACTION。検証用|
||labels TEXT|検証用評価ラベルのJSON|
|meta|key TEXT|PRIMARY KEY。検証用のseeded投入マーカー|

recordsとmessagesは独立して保持します。候補はmessage_idで根拠に結び付き、承認で記録を追加しますが、候補に承認先record IDを保持する列はありません。そのため会話の「保存した回答」という表示は当時の承認状態であり、現在有効な記憶はrecords側から確認します。

旧応答のprovider省略はmock扱い。通常UIでも旧データを削除せず、生成元を正しく表示します。responses.refsとbody.correction_ofはJSON内の業務上の関連で、DBのFKではありません。

## 現在の記憶

current_records()はsuperseded=0の行を日時・ID降順で返します。通常UIでは新規に覚える・忘れるだけを提供。既存の過去扱い行を自動復活させません。検証用の変化処理が作ったprevious_idやsupersededも維持します。

通常UIの「忘れる」は行削除で、次のAPI入力から除外します。過去の会話本文や参照の写しは保持するため、過去の会話内には同じ内容が残り得ます。「削除した記憶を新しい根拠に渡さない」と「過去の会話を完全に消す」は別です。

## 状態遷移とトランザクション

候補は `pending → approved` または `pending → rejected` のみ。approved/rejectedからの再承認・再拒否はエラーです。

承認：BEGIN IMMEDIATE → pending取得 → 旧データに変更元があれば実在確認 → records追加（必要なら旧行を過去化）→ 編集内容とapproved保存 → COMMIT。例外時はすべてロールバック。

拒否：pending条件のUPDATEが1件でなければエラー。拒否に思考内容の検証は不要。会話の発言・返答・候補も一括トランザクションで保存し、API失敗時は保存処理へ進みません。

会話削除：feedback → candidates → responses → messagesの順で一括削除し、records/metaは残します。記憶削除：対象recordsだけ削除し、派生行のprevious_idはSET NULL。候補のprevious_idは残り、変更元がない候補の承認は拒否します。

## Geminiの内部契約

`GeminiResponder.respond(message, scenario, records, correction_of=None, change_from=None, history=None, demo=False) → Reply`。

Replyはinterpretation（本文）、question（問い）、references（DB由来の記録写し）。通常のconverse_personalはdemo=Falseで呼び、scenario選択や明示訂正IDをユーザーに求めません。訂正は通常の発言として会話文脈へ入ります。

RESTのPOST先は `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`。標準ライブラリurllibを使い、キーはx-goog-api-keyヘッダー、モデルは形式検証します。リダイレクトは追従せず、待ち時間はGEMINI_TIMEOUT_SECONDS（既定120秒、5〜300秒）、再試行なし。これはソケットの待ち時間で、処理全体の絶対時間や応答性能の保証ではありません。出力上限8192トークン、受信上限1MiB。

JSONでinterpretation（非空、最大20000文字）、question（文字列、最大5000文字）、reference_ids（整数配列）を要求。finishReason=STOP、型、IDの集合を検証し、本文の引用情報はモデルが作った記録ではなく送信したDBの写しから組み立てます。型不備・途中終了・未送信IDを含む応答は保存しません。実際の文章での出典利用や事実の正しさまでは機械的に保証しません。

公式の参照先は[Gemini API仕様](https://ai.google.dev/api/generate-content)。本書のパラメータは現在のコードを説明するもので、実接続が成功したという記録ではありません。

## 設定と起動

`.env.example` は空の見本、`.env` は利用者の実設定でGit対象外。値をドキュメントやログへ転記しません。Composeの実行時注入を使い、イメージへキーをコピーしません。キー変更後はコンテナを再作成します。Python直接起動では.envの自動読込はなく、環境変数へ設定します。

|設定|用途|
|---|---|
|GEMINI_API_KEY|認証。未設定なら入力を無効にして設定案内|
|GEMINI_MODEL|モデル。省略時はコードのDEFAULT_MODEL。モデルの利用可否はアカウントに依存|
|GEMINI_TIMEOUT_SECONDS|API待ち時間。省略120秒、5〜300の有限値だけを許可|
|SELF_DIALOGUE_PERSONAL_DB|本人用DB。直接起動はdata/personal.sqlite3、Dockerは/app/data/personal.sqlite3|

Dockerは非root実行、ホスト127.0.0.1:8501公開、app-dataを/app/dataへマウント。healthcheckは/_stcore/healthの稼働確認で、APIキーの認証や画面操作の成功確認ではありません。`.dockerignore`は必要なソースと設定だけを許可します。`.streamlit/config.toml`で統計送信を無効化します。

## 初期化と移行

起動で必要なディレクトリ・テーブルを用意し、既存DBにcandidates.previous_idとrecords.supersededがなければ追加。既存の変化リンクから過去状態を補います。旧recordsがAUTOINCREMENTでなければ、FKを保つテーブル再構築とforeign_key_checkで移行します。移行前に既に削除されていた最大IDの履歴は復元できません。

通常UIはseed()を呼びません。検証用サンプルは別DBへ一括投入し、meta.seededで再投入を防ぎます。既存lab.sqlite3の自動取り込みはしません。

## 例外とログ

入力不備・処理済み等はValueError、API障害はGeminiErrorの固定メッセージへ変換。UIは想定内のSQLite/OSErrorと形式エラーを安全な通知にします。APIの生エラー・入力・キー・SQLパラメータを出力せず、業務ログファイルは作りません。DB接続はrerunを含めfinallyで閉じます。未知のプログラム障害はフレームワークの例外扱いで、完全な秘匿保証対象外です。

手動の切り分けにはscripts/check_gemini.pyを使います。標準入力でコンテナへ渡すので診断の追加だけで再ビルド不要。既定は15秒の認証付きモデル情報GETで、文章は生成しません。--generateを明示した場合のみ、モデル取得後に短い合成テキストを1回生成し、最大120秒を待ちます。DBは開きません。設定有無、HTTPコード、エラー分類、通信例外の型、経過時間だけを表示し、キー・プロキシURL・生エラー・個人の会話は表示しません。TLSやプロキシを無効化しません。モデル取得成功と生成成功は別判定です。

## 検証用機能

入口は `src/lab.py → lab_ui.py`。モックシナリオA〜E、サンプル領域、詳細な記録編集・変化リンク、候補管理、応答評価、JSON出力、手動参照選択、任意センチメントが残っています。通常UIからのリンクやモード切替はなく、通常の利用に不要です。

関連コードはlab_ui.py、chat_ui.py、responder.pyのMockResponder、sentiment.py。サンプルは架空JSONで、通常DBへ投入しません。センチメントは任意依存と事前取得モデルを使うローカル推論で、結果をDBやGeminiへ渡しません。通常機能へ昇格する要件ではありません。

Store.exportの検証用出力はUTF-8のJSON配列で、recordsのid/thought/reason/context/occurred/previous_id/supersededを一覧順に出します。空は[]。会話・候補・評価は含みません。
