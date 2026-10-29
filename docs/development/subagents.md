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
|`doc-keeper`|対応表・要件・設計・受入テスト・READMEへの波及確認。指示があればdocs配下とREADME.mdのみ更新|文書のみ|sonnet|

「編集不可」は`tools:`でEdit・Writeを外して強制しています。reviewerとtesterはgit・テスト実行のためにBashを持つため、Bashでの書込み禁止は指示による制約です。doc-keeperの編集範囲も指示による制約です。秘密・個人データの保護は後述のhookで全員に強制しています。

## 標準の流れ

1. `planner`で計画を作る。仕様変更なら文書初稿の更新を最初の手順にする。
2. 文書初稿を更新する（メインまたは`doc-keeper`）。
3. 層に応じて`be-engineer`・`fe-engineer`が実装とテストを書く。APIの契約変更を伴う場合はbe→feの順にする。
4. `tester`で完了条件の充足と不足ケースを確認し、`reviewer`で差分をレビューする。両者は読み取り中心のため並行してよい。
5. 指摘を担当へ戻して修正する。修正ループは2回までとし、未解決事項は人へ返す。
6. メインが`python scripts/verify.py`で一括検証と起動確認を行い、`doc-keeper`で対応表と関連文書を更新する。

小さな変更では全工程を通さず、必要な担当だけを呼びます。

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
|`.claude/hooks/guard_private.py`|ファイル操作・Bash・PowerShellの実行前|`.env`（`.env.example`を除く）、DB・鍵ファイル、`secrets.toml`、`data/`・`private/`・`exports/`への操作と、`git add -f`・`git push --force`を拒否する。hook自体が起動できない場合も拒否側に倒す|
|`.claude/hooks/check_docs.py`|`docs/`配下の`.md`と`README.md`の編集後|`tests/test_integrity.py`の文書一覧・相対リンク・Git除外のテストだけを実行し、失敗をその場で返す。pytestが入ったPythonが見つからない場合は警告のみ|

コマンド文字列の判定は文字列照合のため、変数経由などの回避は防げません。実行中のテスト用一時DB（pytestの`tmp_path`）はコマンドに現れないため影響しません。拒否された操作が必要な場合は、ユーザーが手動で行います。hookの確認・無効化はClaude Codeの`/hooks`で行えます。

## 呼び方の例

```
planner で「音声入力と手入力の送信を排他制御する」の計画を立てて
reviewer に今の差分をレビューさせて
tester で今回の変更がAT-046を満たしているか確認して
```
