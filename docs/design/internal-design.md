# 内部設計書

通常製品の実装を説明します。画面は[外部設計](external-design.md)、機能の受入条件は[機能要件](../requirements/functional-requirements.md)を正本とします。アーキテクチャ図は後日作成予定で、今回は追加しません。

## 構成と責務

思考深化・note向け文書化の[将来要件](../requirements/thinking-and-writing.md)について、API・DB・モデルへの指示・版管理方式は未設計です。既存テーブルへの保存や外部サービスへの投稿が実装済みとは扱いません。

|場所|責務・主な依存|
|---|---|
|src/app.py|通常入口。uvicornでapi.create_appを起動（既定127.0.0.1:8501、アクセスログ無効）|
|src/self_dialogue_lab/api.py|FastAPIのHTTP API。リクエストごとにStoreを開閉し、service/storeを呼ぶ。例外を安全な文言とHTTPコードへ変換。ビルド済み画面と風景画像を配信|
|frontend/src/App.tsx|1画面チャット、送信確認（ページのメモリ）、通知、入力欄。APIの結果で画面状態を置き換える|
|frontend/src/components/|Conversation（会話・回答の承認/拒否・トーン・参照）、Sidebar（接続案内・記憶・会話削除）、VoiceInput（録音・下書き）|
|frontend/src/api.ts / recorder.ts|API呼出しとエラー文言の取り出し / ブラウザ録音を16kHzモノラルWAVへ変換|
|sentiment.py|ローカル3分類。結果の保存・対話への送信なし|
|voice.py|WAV検証とローカル文字起こし。音声を保存・外部送信しない|
|service.py|入力・送信確認、現在の記憶選択、会話文脈、応答呼出し、一括保存|
|store.py|SQLite初期化・移行、記憶・候補の状態遷移、履歴・削除・データ取得|
|gemini.py|Gemini REST通信、出力・参照ID検証、安全なエラー分類。UI/DBに依存しない|
|responder.py|Replyと応答契約、検証用固定応答。通常画面は固定応答を呼ばない|
|assets/|ローカルの風景PNG（画面の背景、/media/landscape.png）と検証用画面のCSS|
|tests/test_api.py|現行製品のAPI境界（送信確認・承認・削除範囲・トーン・音声・ローカル限定）|
|frontend/src/App.test.tsx|画面の操作と表示（Vitest + Testing Library、APIは代替）|
|tests/test_simple_chat.py, test_gemini.py, test_integrity.py, test_persistence.py|業務処理・API・DBの共通境界と回帰テスト|
|Dockerfile / compose.yaml|Node段で画面をビルドし、Python段で起動。キーの実行時注入、DBボリューム|

通常の呼出しは `React画面 → POST /api/messages → converse_personal → converse_gemini → GeminiResponder`。保存はStoreで行い、APIは主要更新にapprove/reject/delete_record/clear_conversationsを使います。画面はDBへ直接触れず、更新系APIは更新後の画面状態を返します。不要な学習基盤・ベクトルDB・追加の抽象層は置きません。

## 対話と記憶のデータの流れ

1. APIはリクエストごとにpersonal.sqlite3を開いて閉じる。サンプルを投入しない。
2. 発言を受け取るとconverse_personalがcurrent_records()の全IDを取得する。
3. converse_geminiが送信確認、空白、IDの有効性を検証し、Gemini履歴の直近10往復を取得する。
4. GeminiResponderへ発言、現在の記憶、会話文脈を渡す。候補テーブル・評価・画像は渡さない。
5. 生成結果の形式と参照IDを検証する。通過後に発言・返答・候補を同じトランザクションで保存。
6. 本人が後で候補を承認したときだけrecordsへ追加する。次回の手順2から記憶として含まれる。

会話文脈は当時のやり取りで、未承認候補の元発言も含み得ます。長期記憶と同じ扱いにはしない指示をAPIへ付けます。拒否した発言を会話から消す操作ではない点に注意します。

## HTTP API

画面とサーバーの契約です。JSONはUTF-8。更新系は成功時に `GET /api/state` と同じ形の状態を返し、画面はそれで表示を置き換えます。

|メソッドとパス|入力|処理・出力|
|---|---|---|
|GET /api/state|なし|configured / voiceConfigured / toneConfigured（設定の有無だけ。値は返さない）、exchanges（応答ID昇順の発言・候補の状態・返答・参照の写しの考え）、memories（現在の記憶）|
|POST /api/messages|text, consent|converse_personal。未確認・空白は400で応答器を呼ばない|
|POST /api/candidates/{id}/approve|thought|Store.approve。理由は空、文脈は定型文。処理済み・空白は400|
|POST /api/candidates/{id}/reject|なし|Store.reject。処理済みは400|
|DELETE /api/memories/{id}|なし|Store.delete_record。見つからなければ400|
|DELETE /api/conversations|なし|Store.clear_conversations。記憶は残す|
|POST /api/exchanges/{id}/tone|なし|保存済み発言をsentiment.analyzeへ。分類名だけ返し、保存しない|
|POST /api/voice/transcribe|audio/wavの本文|最大1,924,096バイトまで受け取りvoice.transcribeへ。文字列だけ返す|
|GET /api/health|なし|稼働確認。API認証やDBの正常性は確認しない|

|例外|HTTP|画面の表示|
|---|---|---|
|ValueError（入力不備・処理済み等）|400|業務処理の文言|
|GeminiError|502|gemini.pyの固定文言|
|SentimentError / VoiceError|422|各モジュールの固定文言|
|保存JSONの形式不備|500|「保存データの形式を確認してください。」|
|sqlite3.Error / OSError|500|「保存データにアクセスできません。…」|

ローカル限定の防御として、Hostが127.0.0.1・localhost以外の要求を403で拒否し（DNSリバインディング対策）、GET/HEAD以外でOriginがHostと一致しない要求も403で拒否します（クロスサイトの更新対策）。CORSは許可しません。OpenAPIの自動ドキュメントは無効です。

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
|INSTALL_SENTIMENT|Composeのビルド引数。trueでCPU版PyTorchとsentiment追加依存を導入。既定false|
|SENTIMENT_MODEL_PATH|分析用モデルのローカルディレクトリ。未設定なら分析操作を無効化。Dockerの設定例は/app/models/sentiment|
|INSTALL_VOICE|Composeのビルド引数。trueでvoice追加依存を導入。既定false|
|VOICE_MODEL_PATH|音声モデルのローカルディレクトリ。Dockerの設定例は/app/models/voice。未設定でも手入力可能|

Dockerはnode:24-slimの段で `npm ci` と画面のビルドを行い、生成した静的ファイルだけをPython 3.12の実行イメージへコピーします。非root実行、コンテナ内は0.0.0.0:8501で待ち受け、ホストへは127.0.0.1:8501だけを公開、app-dataを/app/dataへマウント。healthcheckは/api/healthの稼働確認で、APIキーの認証や画面操作の成功確認ではありません。`.dockerignore`は必要なソース・画面ソースと設定だけを許可し、node_modulesとローカルのビルド結果は除きます。画面は外部の画像・フォント・スクリプト・利用統計を読み込みません。

|設定|用途|
|---|---|
|SELF_DIALOGUE_HOST / SELF_DIALOGUE_PORT|待受先。直接起動の既定は127.0.0.1:8501、Dockerは0.0.0.0:8501|

## 初期化と移行

起動で必要なディレクトリ・テーブルを用意し、既存DBにcandidates.previous_idとrecords.supersededがなければ追加。既存の変化リンクから過去状態を補います。旧recordsがAUTOINCREMENTでなければ、FKを保つテーブル再構築とforeign_key_checkで移行します。移行前に既に削除されていた最大IDの履歴は復元できません。

通常画面とAPIはseed()を呼びません。検証用サンプルは別DBへ一括投入し、meta.seededで再投入を防ぎます。既存lab.sqlite3の自動取り込みはしません。

## 例外とログ

入力不備・処理済み等はValueError、API障害はGeminiErrorの固定メッセージへ変換。APIの例外ハンドラーが想定内のSQLite/OSErrorと形式エラーを安全な文言に変換し（[HTTP API](#http-api)）、画面はその文言だけを表示します。サーバーに届かない場合は画面側の固定文言を出します。Geminiの生エラー・入力・キー・SQLパラメータを出力せず、業務ログファイルは作りません。uvicornのアクセスログは無効です。DB接続はリクエストごとにfinallyで閉じます。未知のプログラム障害はフレームワークの例外扱いで、完全な秘匿保証対象外です。

手動の切り分けにはscripts/check_gemini.pyを使います。標準入力でコンテナへ渡すので診断の追加だけで再ビルド不要。既定は15秒の認証付きモデル情報GETで、文章は生成しません。--generateを明示した場合のみ、モデル取得後に短い合成テキストを1回生成し、最大120秒を待ちます。DBは開きません。設定有無、HTTPコード、エラー分類、通信例外の型、経過時間だけを表示し、キー・プロキシURL・生エラー・個人の会話は表示しません。TLSやプロキシを無効化しません。モデル取得成功と生成成功は別判定です。

## 検証用機能

入口は `src/lab.py → lab_ui.py`。Streamlitで動き、依存は任意の `lab` 追加依存です（通常の起動・Dockerイメージには含めません）。モックシナリオA〜E、サンプル領域、詳細な記録編集・変化リンク、候補管理、応答評価、JSON出力、手動参照選択、任意センチメントが残っています。通常UIからのリンクやモード切替はなく、通常の利用に不要です。

関連コードはlab_ui.py、chat_ui.py、responder.pyのMockResponder、sentiment.py。サンプルは架空JSONで、通常DBへ投入しません。センチメントは任意依存と事前取得モデルを使うローカル推論で、結果をDBやGeminiへ渡しません。通常画面でも任意の文章トーン分析として利用します（[FR-025](../requirements/functional-requirements.md#fr-025-文章のトーンを分析する)）。

Store.exportの検証用出力はUTF-8のJSON配列で、recordsのid/thought/reason/context/occurred/previous_id/supersededを一覧順に出します。空は[]。会話・候補・評価は含みません。

## 通常画面の文章トーン分析

### モデルと配置

|項目|実装仕様|
|---|---|
|モデル|lxyuan/distilbert-base-multilingual-cased-sentiments-student|
|固定リビジョン|50406a7df25e4130306d6663e4c9c2ad78093b6e|
|方式|Transformersのtext-classificationによるCPU推論。生成LLMへの分析依頼ではない|
|出力|positive / neutral / negativeを日本語の3分類へ変換。最大スコアの1分類を表示|
|取得対象|設定・トークナイザー・model.safetensors・モデル説明等。重みは約541MB。pickle形式の重みは取得しない|
|取得方法|明示的なsentiment --prepareのみ。リモートコード実行を許可しない|
|配置|Dockerはsentiment-modelsを/app/modelsへマウント。会話・記憶のapp-dataと分離|
|DB|スキーマ変更なし。分類結果のテーブル・保存候補は作らない|

モデル仕様の出典は[配布元のモデルカード](https://huggingface.co/lxyuan/distilbert-base-multilingual-cased-sentiments-student)。採用モデルとリビジョンはsentiment.pyの定数を正本とします。依存の許容バージョンはpyproject.toml、導入済みバージョンと動作確認結果は[受入テストの実施記録](../testing/acceptance-tests.md#文章トーン分析の追加2026-10-25)を参照してください。

### 呼び出し・保存・送信の境界

画面の「文章のトーンを分析」→ POST /api/exchanges/{id}/tone → sentiment.analyze。APIは保存済みの発言本文だけを分類器へ渡し、分類名だけを返します（スコアは返さず、確率として表示しません）。SENTIMENT_MODEL_PATHのローカルモデルを使用し、推論時はlocal_files_only=True。モデル取得は明示的な事前セットアップだけで行います。結果は画面部品の状態だけで扱い、DB・Gemini入力を更新しません。部品は会話削除ごとに増える世代番号と応答IDで区別するため、会話削除後にIDが再利用されても古い分析結果を引き継ぎません。再読み込みでも消えます。未設定・失敗時に代替分類しません。設定手順は[README](../../README.md#文章のトーン分析任意)を参照。

モデルとパイプラインはプロセス内でキャッシュしますが、分析結果はキャッシュしません。入力は対象発言だけで、長期記憶や会話履歴は分類器へ渡しません。空白入力・不正なラベル・非有限または範囲外のスコアを拒否し、依存や推論の例外本文は画面へ出しません。

## 音声入力

VoiceInput → recorder.ts → POST /api/voice/transcribe → voice.transcribe。ブラウザのMediaRecorderで録音し、Web Audio（decodeAudioData・OfflineAudioContext）で16kHzモノラル16bit PCMのWAVへ変換して同じPCのAPIへ送ります。60秒で自動停止します。APIはContent-Typeと大きさを読み込み中にも確認し、超過時は推論前に拒否します。マイク権限が必要で、localhostまたはHTTPSで利用します。操作の仕様は[外部設計](external-design.md#音声で入力任意)を参照。

|項目|仕様|
|---|---|
|モデル|Systran/faster-whisper-small、リビジョン536b0662742c02347bc0e980a01041f333bce120|
|実行|faster-whisper / CTranslate2、CPU int8、local_files_only=True、日本語・transcribe固定|
|事前取得|voice --prepareからHugging Faceへ接続し、config.json / model.bin / tokenizer.json / vocabulary.txt等を取得。model.binはCTranslate2の重み形式|
|配置|既存のモデル用sentiment-modelsボリューム内/app/models/voice。トーンモデルとは別ディレクトリ、DBとも分離|
|入力境界|モノラル16bit PCM・16kHz WAV、0秒超〜60秒、最大1,924,096バイト。ヘッダー・実データ長・ほぼ無音を検査|
|推論|beam_size=5、vad_filter=True、condition_on_previous_text=False。遅延イテレーターの走査も例外境界内。空結果・過大な文字起こしは拒否|
|保持|モデルだけプロセスキャッシュ。録音はブラウザのメモリと、APIのリクエスト処理中のメモリだけ。下書きは画面部品の状態。音声のファイル保存・DB列追加なし|
|送信|確認した文字列だけsend_message → converse_personal。既存の送信確認・現在の記憶・会話文脈・保存候補承認の規則を適用|

「録音する／録音し直す」で以前の録音と下書きをクリア。成功送信・「録音と下書きを破棄」で部品の状態を消し、会話削除では世代番号を上げて部品ごと作り直します。部品が消えるときは録音中のマイクも解放します。失敗した送信では下書きを残し、自動再試行しません。ブラウザやOSの録音バッファの完全消去は保証しません。

依存はpyproject.tomlのvoice追加依存。faster-whisperのデコーダーとの互換性のためPyAVを14以上17未満に制限します（19.0.2ではmetadata_errors引数の非対応を確認）。Dockerfileとcompose.yamlで任意導入し、初回取得後はオフラインで文字起こし可能です。設定手順は[README](../../README.md#音声入力任意)。公式資料：[MediaRecorder](https://developer.mozilla.org/ja/docs/Web/API/MediaRecorder)、[OfflineAudioContext](https://developer.mozilla.org/ja/docs/Web/API/OfflineAudioContext)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[モデル配布元](https://huggingface.co/Systran/faster-whisper-small)。認識精度・実マイク確認は[受入結果](../testing/acceptance-tests.md)と区別します。
