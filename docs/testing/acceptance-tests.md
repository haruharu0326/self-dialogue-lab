# 受入テスト仕様書

現行の**チャット1画面と、確認した本人回答の記憶**を対象にします。代替応答器・通信で検証するデータ境界と、実際のAPI接続・画面表示・対話品質を区別します。

## テストの前提と判定

自動テストは一時的な本人用DBを使用し、実際のキー・個人データを使いません。AppTestはStreamlit導入時だけ実行。skipは合格ではありません。自動部分のみ通ったケースは、UIまで合格と表現しません。

FR-018,019に対応するAT-032,033の番号は維持。AT-001〜031は過去の検証用・共通バックエンドの補助テストとして番号を留保し、現在の製品UIの合格判定に流用しません。

## 現行の受入ケース

|ID・対応要件|事前条件・入力|手順|期待結果|自動／手動・実施状況|
|---|---|---|---|---|
|AT-032 / FR-018,NFR-011,012|空の本人用DB、代替応答器、キーなしのUI|通常入口を開く→送信未確認で実行→確認後に相談|サンプルなし、シナリオ・分析・評価・領域切替なし。未確認では呼出しなし、会話が継続|境界は自動成功。AppTestは未実施（依存不足）|
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
|AT-043 / NFR-011|通常UI、同梱風景|1440px・390pxで会話・保存・参照・サイドバー操作|写真上でも読みやすい、過剰な管理操作なし、モバイルでも入力・確認可能|素材単体確認のみ。実画面・コントラスト測定は未実施|
|AT-044 / FR-024,NFR-007〜009|ダミーキー、資格情報を含むプロキシ設定、生エラーを含む代替通信|接続診断で403とURLError、キー未設定を再現|キー・プロキシURL・生エラーは出さず、分類と設定有無だけ表示。キーなしなら送信しない|tests/test_connection_check.pyの3条件成功。実コンテナでの診断結果待ち|

## 実装・自動テストとの対応

|ケース|主なテスト（tests/配下）|
|---|---|
|032|test_simple_chat.py::test_personal_chat_without_consent_does_not_call_model / test_product_screen_has_no_lab_controls_or_sample_records|
|033|test_simple_chat.py::test_answers_only_become_memory_after_user_confirmation|
|034|test_gemini.py::test_only_selected_current_records_are_sent_and_refs_are_db_snapshots / test_invalid_remote_response_does_not_persist|
|035|test_simple_chat.py::test_rejected_and_forgotten_answers_are_not_long_term_context / test_persistence.py::test_new_responses_exclude_changed_and_deleted_records|
|036|test_persistence.py::test_clear_conversations_preserves_approved_records|
|037|test_gemini.py::test_missing_key_consent_timeout_and_model_validation / test_simple_chat.py::test_personal_chat_without_consent_does_not_call_model|
|038|test_gemini.py::test_gemini_conversation_context_and_source_separation / test_integrity.py::test_git_excludes_private_files_but_not_docs_or_samples|
|039|test_gemini.py::test_http_errors_are_redacted_without_partial_save / test_invalid_remote_response_does_not_persist / test_integrity.py::test_approval_failure_rolls_back_record_and_historical_flag|
|042|test_persistence.py::test_records_conversation_and_feedback_survive_new_process / test_simple_chat.py::test_answers_only_become_memory_after_user_confirmation|

040,041,043の実環境部分を自動テスト成功から推定しません。検証用src/lab.pyの画面テストが通っても、通常UIの表示確認とは分けます。

## 実施記録

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

要件・外部設計はSCR-004のチャット1画面を正本とし、シナリオ・評価・分析・管理画面を通常製品の必須機能に含めないことを確認します。通常の入口はsrc/app.py、従来機能はsrc/lab.py。回答の学習は確認済み記憶の参照であり、再訓練ではないことを全書類で統一します。

### 残件

ユーザー実機でGeminiの返答と記憶参照は確認済みです。体系的なPC・モバイル目視、Dockerのhealthとボリューム保持、性能測定は残っています。未実装は要件定義書の対象外と未決事項に集約し、現在仕様と混在させません。

接続切り分けの追加確認：ユーザー環境でGoogleへのDNS/TCP/TLS接続テストはHTTPS OK。これはAPIのPOST・認証・モデルの成功とは別です。scripts/check_gemini.pyを追加し、秘密の非出力テスト3条件と文書リンク検査の計4件が成功しました。実コンテナでの診断は利用者の実行結果を待っています。

ユーザーの初回API診断はPOSTのTimeoutError。診断を「15秒のモデル情報GET」と、明示指定時だけの生成POSTへ分離し、アプリの待ち時間を120秒既定で設定可能にしました。関連テスト27成功・画面1スキップ。ユーザーの追加診断はモデルGETがHTTP 200で成功し、その後に返答と記憶参照の成功報告を得ています。初回タイムアウトの原因を生成遅延と断定したものではありません。

修正後の全体回帰：`python -m pytest -q --basetemp=.test-temp-timeout-final --tb=short -rs`で67成功、8スキップ（3.23秒）。スキップは引き続き開発環境のStreamlit不足による画面テストです。実APIの解消確認とは区別します。
