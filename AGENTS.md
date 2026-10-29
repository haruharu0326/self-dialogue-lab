# 開発方針

- Python（FastAPI）/ React（Vite・TypeScript）/ SQLite / pytest・Vitest による1人用ローカルアプリを維持する。検証用のsrc/lab.pyだけStreamlitを任意依存で残す。
- 応答器は既定を固定応答、Geminiは本人が明示的に有効化したときだけ使う二重モードとする。表示・切替の詳細はdocs/requirements/functional-requirements.mdのFR-028（実装は今後）を参照。固定応答は自由入力を理解したと装わない。
- 架空サンプルとユーザーの実情報を混ぜない。サンプルは専用DBへ一度だけ投入する。
- 画面、データ操作、応答器を分離し、将来の応答器はResponderを実装して交換する。
- 未承認・拒否候補を長期記録や参照対象に含めない。承認は原子的で二重処理不可にする。
- 誤入力修正と考えの変化を区別する。旧記録や削除済み記録を現在の立場として参照しない。
- 会話削除と記録削除を分け、削除範囲を画面に説明する。
- docs/requirements/requirements-definition.mdの将来要件を維持する。Gemini以外の実API、クラウド、マルチエージェント等は初版の対象外。
- 仕様変更は文書初稿を先に更新し、実装後に関連する要件・設計・受入テストを更新する。docs/README.mdの対応表でFR/NFR/ATと実装の整合を確認する。
- 詳細仕様は担当文書に集約し、他文書から相対リンクで参照する。初版・将来構想・未決事項を明確に分ける。
- 実装はsrc/self_dialogue_lab、画面はfrontend、起動入口はsrc/app.py、テストはtestsとfrontend/src配下に置く。文書一覧と読む順序はdocs/README.md。
- 個人データ、DB、書き出し、秘密情報はGitへ追加しない。
- 永続化・境界・状態遷移テスト、APIテスト、変更に対応した画面テスト（Vitest）を実行する。起動確認も行い、失敗・スキップは明示する。
- 固定応答の結果をLLMの理解力・対話品質の検証と表現しない。
- 起動はREADMEを参照。テストは `python -m pytest -q --basetemp=.test-temp` と `npm --prefix frontend test`。

