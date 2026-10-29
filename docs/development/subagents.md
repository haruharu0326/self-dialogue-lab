# 開発用サブエージェント

2026-10-29。Claude Codeで開発を分担するサブエージェントの構成と使い方です。製品機能ではなく開発手順の一部です。製品の実LLM/API・マルチエージェントの対象範囲は変更しません。定義ファイルは`.claude/agents/`にあります。

## 構成

|名前|役割|編集|モデル|
|---|---|:---:|:---:|
|`planner`|関連FR/NFR/AT・担当文書・実装箇所の特定、手順と完了条件への分解|不可|sonnet|
|`be-engineer`|api.py・service.py・store.py・responder.py等の実装とpytest|可|opus|
|`fe-engineer`|frontend/srcのReact実装とVitest|可|sonnet|
|`reviewer`|差分の正しさとAGENTS.mdの設計境界のレビュー|不可|opus|
|`tester`|テストが完了条件・ATを証明しているかの確認と関係テストの実行（テストは書かない）|不可|opus|
|`refactorer`|指定範囲の振る舞いを変えない整理。変更前後でテスト結果を比べる。候補の列挙のみも可|可|opus|
|`doc-keeper`|対応表・要件・設計・受入テスト・READMEへの波及確認。指示があればdocs配下とREADME.mdのみ更新|文書のみ|sonnet|

「編集不可」は`tools:`でEdit・Writeを外して強制しています。reviewerとtesterはgit・テスト実行のためにBashを持つため、Bashでの書込み禁止は指示による制約です。doc-keeperの編集範囲も指示による制約です。秘密・個人データの保護は後述のhookで全員に強制しています。

## 標準の流れ

ブランチの規則（ユーザーの決定）: 要件（課題）ごとにブランチを分け、`main`から作ります。各ブランチで実装・テスト・`reviewer`のレビューを通してからPRにします。

1. `planner`で計画を作る。仕様変更なら文書初稿の更新を最初の手順にする。
2. 文書初稿を更新する（メインまたは`doc-keeper`）。
3. 層に応じて`be-engineer`・`fe-engineer`が実装とテストを書く。APIの契約変更を伴う場合はbe→feの順にする。
4. `tester`で完了条件の充足と不足ケースを確認し、`reviewer`で差分をレビューする。両者は読み取り中心のため並行してよい。
5. 指摘を担当へ戻して修正する。修正ループは2回までとし、未解決事項は人へ返す。
6. メインが`python scripts/verify.py`で一括検証と起動確認を行い、`doc-keeper`で対応表と関連文書を更新する。

小さな変更では全工程を通さず、必要な担当だけを呼びます。

リファクタリングは機能変更と分けて行います。メインが対象を指定して`refactorer`を呼び、終了後に`reviewer`で振る舞いが変わっていないかを確認します。`refactorer`はテストのassertを変えず、契約や仕様の変更が必要なものは自分で直さずに報告します。報告された案件は上記1の計画から扱います。差分だけを対象にした整理には、Claude Code組み込みの`/simplify`も使えます。

## 運用上の注意

- サブエージェントから別のサブエージェントは呼べません。段取りと指摘の記録はメインが持ちます。
- サブエージェントは途中でユーザーに質問できません。方針の確認はメインが行います。
- サーバー起動を伴う`scripts/verify.py`はメインだけが実行します。サブエージェントのpytestは`--basetemp=.test-temp-<役割>`で一時ディレクトリを分けます。
- AGENTS.mdと製品文書の衝突（[mainレビューの引き継ぎ](harness-plan.md#次回対応への引き継ぎ2026-10-25-mainレビュー)の方針未決事項など）は、どの担当も自分で解消せず報告します。
- 各担当の出力は「結論3行・入力・本文・未確認事項」の形に揃えます。スキップや未確認を成功と区別します。
- 差分レビューの自動実行器`scripts/review.py`（Codex CLI）とは独立しています。使い分けは[開発ハーネス](harness-plan.md)を参照してください。

## hook

`.claude/settings.json`で次のhookを設定しています。指示ではなく機械的に働き、メインとすべてのサブエージェントに適用されます。

|hook|契機|動作|
|---|---|---|
|`.claude/hooks/guard_private.py`|ファイル操作・Bash・PowerShellの実行前|`.env`（`.env.example`を除く）、DB・鍵ファイル、`secrets.toml`、`data/`・`private/`・`exports/`への操作と、`git add -f`・`git push --force`を拒否する。hook自体が起動できない場合も拒否側に倒す（`settings.json`の`onFailure: "block"`により、起動失敗・例外終了・timeoutでも拒否。Claude Code v2.1.295以降の仕様で、実際に失敗させた動作確認は未実施）|
|`.claude/hooks/check_docs.py`|`docs/`配下の`.md`と`README.md`の編集後|`tests/test_integrity.py`の文書一覧・相対リンク・Git除外のテストだけを実行し、失敗をその場で返す。pytestが入ったPythonが見つからない場合は警告のみ|
|`.claude/hooks/log_activity.py`|`PreToolUse`・`PostToolUse`・`SubagentStart`・`SubagentStop`・`UserPromptSubmit`・`Stop`（非同期）|開発チャット用の作業記録を`.claude/activity/events.jsonl`へ1行ずつ追記する。拒否はせず、失敗しても作業を止めず常に正常終了する。`.claude/activity/`がなければ何もしない。詳細は[作業記録と開発チャット](#作業記録と開発チャット)|

コマンド文字列の判定は文字列照合のため、変数経由などの回避は防げません。実行中のテスト用一時DB（pytestの`tmp_path`）はコマンドに現れないため影響しません。拒否された操作が必要な場合は、ユーザーが手動で行います。hookの確認・無効化はClaude Codeの`/hooks`で行えます。

## 作業記録と開発チャット

サブエージェントへの依頼・作業・報告を、依頼ごとのスレッドとして画面で見るための開発用の仕組みです。製品のAPI・DB・画面とは独立しています。

### 記録する内容としない内容

- 記録するもの: イベントの種類、時刻、セッションID、担当の種類、ツール名、対象の要約、識別子（`agent_id`・`tool_use_id`・`subagent_type`等）。
- `UserPromptSubmit`（ユーザーの入力）では、本文を記録しません。「新しい指示が届いた」という事実と時刻だけが残ります。
- ただし、メインがサブエージェントへ渡す依頼文（最大4000字）と、サブエージェントの報告（最大8000字）は記録されます。メインが依頼文にユーザーの文章を引用した場合、その部分も残ります。「ユーザー入力が一切残らない」わけではありません。
- 通常のツール（読み取り・編集・検索・コマンド実行など）は、名前と対象（ファイル名、コマンドの1行目の先頭60字、検索パターンなど）だけを記録し、ファイルの中身や出力は残しません。
- 次の要約は、秘密らしい部分を`***`に置き換えて記録します（`log_activity.py`の`brief()`・`redact()`）。処理は「空白をまとめる → 300字で切る → 伏せる → 切り詰め」の順です。

  |対象|最終の長さ|
  |---|---|
  |Bash・PowerShellのコマンド1行目、WebFetchのURL|60字|
  |Grep・Glob・WebSearchの要約|40字|

  - 伏せるもの:
    - URLの認証情報（`user:pass@`、トークンだけの`TOKEN@`も。`***@`になる）、URLのクエリとフラグメント（`?`・`#`以降）
    - 名前に`api-key`・`api_key`・`apikey`・`token`・`secret`・`password`・`passwd`・`auth`・`credential`・`cookie`を含むヘッダーの値（`Authorization:`、`X-Api-Key:`等）、`Bearer 値`
    - `$env:NAME = 値`、`NAME=値`、名前が秘密らしい変数の代入（`$apiKey = '…'`、`@{Authorization = "…"}`）
    - 名前に`token`・`key`・`secret`・`password`・`passwd`・`pwd`・`auth`・`credential`を含むオプションの値（`=`・空白・`:`区切り。`-Password:値`も）
    - 引用符付きのキーの値（`@{'X-Api-Key'='…'}`、JSON本文`{"token":"…"}`、`os.environ['TOKEN']=…`の添字形式も）。キー名の語はオプションと同じ`token`・`key`・`secret`・`password`・`passwd`・`pwd`・`auth`・`credential`
    - 閉じていない引用符や連結した値は、まとめて伏せます。
  - 伏せすぎる例（許容）: `ssh://git@host/x`のユーザー名、`--author=…`、`tokenizer: x`、`$monkey = 1`のように、該当語を含むだけのもの。外側の引用符の中の代入では、閉じ引用符とそれ以降（次の`"`まで、なければ行末まで）が`***`に含まれることがある（`python -c "os.environ['TOKEN']='abc'" && run`の` && run`も消える）。
  - 拾えないもの（パターン照合による best effort であり、「伏せるから安全」ではありません。コマンドに秘密を直接書かない運用が前提です）:
    - 区切りなしの形（`mysql -pSecret123`）、メソッド引数（`[Environment]::SetEnvironmentVariable("KEY","v")`）、`Set-Item Env:NAME 値`
    - 名前が秘密らしくない変数・引数・位置引数（`$x = 'sk-abc'`、`python app.py sk-abc`、curlの`-u user:pass`）、名前が秘密らしくないヘッダー（`X-Custom: abc`）
    - 引用符なしの値は空白と`;`・`|`・`&`・`)`・`}`で止まり、それ以降は伏せない（`TOKEN=ab|cd`の`cd`）
    - 引用符で囲まれていても、名前に該当語を含まないキー（`{"session": "abc"}`）。エスケープした引用符のキー（`"{\"token\":\"abc\"}"`）
    - URLのパスに埋め込まれた秘密、`://`のない形式
    - 2行目以降（そもそも記録しません）
    - Agentのdescription、依頼文、報告本文（伏せ処理を掛けません）
- 保存先は`.claude/activity/events.jsonl`です。`.gitignore`済みでGitには入りません。ファイルが約2MBを超えると、新しい3000行だけを残して古い行を切り詰めます。
- 伏せ処理は要約にだけ掛け、依頼文・報告には掛けないため、そこに含まれる情報は伏せられません。個人データや秘密を依頼文へ貼らない運用が必要です。
- 伏せ処理を入れる前に`events.jsonl`へ書かれた記録は伏せられていません。必要なら`.claude/activity/`を削除してください（止め方は後述）。

### 開発チャットの起動

```
python scripts/agent_chat.py [--open] [--port 8765]
```

- `127.0.0.1`だけで待ち受けます。標準ライブラリのみで動き、追加のインストールは不要です。`--open`で起動後にブラウザを開きます。ポートの既定は8765です。
- 初回の起動で`.claude/activity/`が作られ、以後`log_activity.py`が記録を始めます。起動前の作業は記録されません。
- 表示は記録だけから組み立てます。台詞や報告を生成せず、製品の「モック・固定応答」とも無関係です。

### 記録の止め方

- 開発チャットのサーバー（Ctrl+C）を止めても、記録は続きます。記録するのは`log_activity.py`であり、サーバーではないためです。
- 記録を止めるには、`.claude/activity/`フォルダを削除します。これまでの記録も消えます。再び起動すると、再度記録が始まります。
- 起動時に、この止め方を標準出力へ表示します。

## 呼び方の例

```
planner で「音声入力と手入力の送信を排他制御する」の計画を立てて
reviewer に今の差分をレビューさせて
tester で今回の変更がAT-046を満たしているか確認して
refactorer で store.py の改善候補だけ挙げて
```
