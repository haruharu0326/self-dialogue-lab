# Self Dialogue Lab

**話しながら、自分の考えを整理する。**

Geminiと対話し、残したい自分の回答だけ「覚えておく」。覚えた回答を次の対話で参照します。「学習」はモデルの再訓練ではなく、この記憶の仕組みです。

通常画面はチャット1画面です。シナリオ、分析、評価、細かな設定を並べません。自然の風景を画面全体に敷き、会話を半透明のパネルで読みます。

## 起動

Docker Desktopを起動し、次をPowerShellで実行します。

```powershell
cd C:\Users\16326\projects\self-dialogue-lab
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

[Google AI Studio](https://aistudio.google.com/apikey)で発行したキーを、`.env` の `GEMINI_API_KEY=` の右に設定して保存します。キーはチャットに貼らないでください。[Googleの設定案内](https://ai.google.dev/gemini-api/docs/api-key)も参照できます。

```powershell
docker compose up --build -d
```

http://127.0.0.1:8501 を開き、会話・覚えた回答をGoogleへ送ることを確認すると話せます。初回のビルドにはネット接続が必要です。利用枠・料金はGoogle側の設定に依存します。

停止は `docker compose down`。記憶と会話は名前付きボリュームに残ります。`down -v` はデータも消すため通常は使いません。エンジンに接続できない場合はDocker Desktopの起動状態を確認してください。

### 接続できない場合

HTTPS接続が通っていても、API認証・プロキシ・モデル・リクエストの問題は別です。PowerShellで次を実行すると、キーや会話を表示せずに切り分けできます。再ビルドは不要です。

```powershell
Get-Content -Raw .\scripts\check_gemini.py | docker compose exec -T app python -
```

モデル情報を取得するだけで、文章生成はしません。`API key configured: False` は起動中コンテナにキーがない状態。`Model lookup: passed.` はモデル情報を取得できたことを示し、文章生成の成功とは別です。`Network error type` は通信例外型。キー、プロキシURL、生エラー本文は出力しません。

モデル取得が成功した後に生成も確認する場合だけ、次を使います。固定の短い合成文を1回送り、既定で最大120秒待ちます。

```powershell
Get-Content -Raw .\scripts\check_gemini.py | docker compose exec -T app python - --generate
```

アプリの待ち時間はGEMINI_TIMEOUT_SECONDS（5〜300、既定120秒）で調整できます。アプリコードの更新を反映するには `docker compose up --build -d` が必要です。タイムアウトだけから、キーが正しい・Google側が遅い・ネットワーク障害のどれかを断定はしません。

## 使い方

1. 迷っていることや、考えていることを話します。
2. 残したい自分の回答で「この回答を覚えておく」を開きます。
3. 必要なら内容を整えて「覚えておく」を押します。次の対話から参考にします。

覚えない回答は会話だけに残ります。「今回は覚えない」を選ぶこともできます。AIの解釈や一時的な感情を勝手に信念として保存しません。誤った解釈には、そのままチャットで訂正してください。

覚えた回答はサイドバーの「覚えていること」で見返し、不要なら忘れさせられます。会話履歴の削除は別の操作です。記憶を消しても当時の会話は残り、会話を消しても記憶は残ります。

## データと制約

- 通常画面は自分用DBだけを使い、架空データを投入しません。既存のデータも削除しません。
- Geminiへ送るのは直近10往復と、確認して覚えた現在の回答です。未承認候補の元発言は短期会話に残り得ますが、長期記憶とは区別します。
- DBは直接起動時 `data/personal.sqlite3`、Dockerでは `/app/data/personal.sqlite3`。環境変数 `SELF_DIALOGUE_PERSONAL_DB` で変更できます。
- `.env`、DB、個人書き出し、モデルはGit対象外。APIキーをDBや画面へ保存しません。送信した情報のGoogle側での取扱いは利用条件に従います。
- 推測を含む返答であり、本人の人格・意識の再現や正確な理解を保証しません。意味検索やモデル重みの学習はありません。
- 風景はAI生成。[素材と生成条件](src/self_dialogue_lab/assets/provenance.json)を同梱し、画像・フォントを外部取得しません。

## 開発・検証

ホストで直接起動する場合：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# GEMINI_API_KEYを環境変数へ設定してから起動（.envは直接起動では自動読込しません）
.\.venv\Scripts\python.exe -m streamlit run src/app.py
```

テスト：`python -m pytest -q --basetemp=.test-temp`

従来の管理・モック・分析機能は検証用の `streamlit run src/lab.py` に分離しました。通常利用では不要です。構成・詳細要件・過去機能の仕様は[文書一覧](docs/README.md)、確認済みと未確認の区別は[受入テスト](docs/testing/acceptance-tests.md)を参照してください。

## 文章のトーン分析（任意）

各本人発言の「文章のトーン（任意）」から3分類を実行できます。本人の気持ちの断定ではなく文章からの推定です。結果は保存・Gemini送信せず、画面の再表示で消えます。モデルのスコアは感情の確率として表示しません。

Dockerでは `.env` に次を追加します（APIキーは変更不要）。

```dotenv
INSTALL_SENTIMENT=true
SENTIMENT_MODEL_PATH=/app/models/sentiment
```

```powershell
docker compose build app
docker compose run --rm --no-deps app python -m self_dialogue_lab.sentiment --prepare
docker compose up -d --force-recreate app
```

初回の依存・モデル取得には通信とディスク容量が必要です。取得処理は会話を読みません。モデルは専用ボリュームに保存され、分析時はローカルファイルだけを使用します。取得に失敗した場合は設定・通信・保存先を確認して同じ取得コマンドを再実行してください。

Python直接起動の場合：

```powershell
python -m pip install -e ".[dev,sentiment]"
$env:SENTIMENT_MODEL_PATH = "$PWD/models/sentiment"
python -m self_dialogue_lab.sentiment --prepare
python -m streamlit run src/app.py
```

モデルは既存の [multilingual sentiment student](https://huggingface.co/lxyuan/distilbert-base-multilingual-cased-sentiments-student) を固定リビジョンで取得します。実際の日本語分類精度は未評価です。長文は先頭512トークンまでを対象とします。

## 音声入力（任意）

「音声で入力（任意）」を開いてマイクを許可し、60秒以内の日本語を録音してください。「文字起こし」後に文章を確認・編集し、「この文章を送信」を押します。録音だけで自動送信されません。音声はPC内で処理し、ファイルやDBへ保存しません。送信した文章は通常の会話として保存・Gemini送信します。誤認識は必ず確認してください。

Dockerでは `.env` に次を追加し、既存のAPIキー・分析設定は維持します。

```dotenv
INSTALL_VOICE=true
VOICE_MODEL_PATH=/app/models/voice
```

```powershell
docker compose build app
docker compose run --rm --no-deps app python -m self_dialogue_lab.voice --prepare
docker compose up -d --force-recreate app
```

初回は依存と約486MBのモデルを取得します。取得処理は会話・録音を読みません。モデルはモデル用ボリュームに保持され、文字起こし時に外部へ音声を送りません。利用するのは[Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)の固定リビジョンです。

直接起動の場合は `python -m pip install -e ".[dev,voice]"`、`$env:VOICE_MODEL_PATH = "$PWD/models/voice"`、`python -m self_dialogue_lab.voice --prepare` を実行してからStreamlitを起動します。

マイクは `http://localhost:8501` または `http://127.0.0.1:8501` で使用してください。リモート接続はHTTPSとブラウザのマイク権限が必要です。認識できない場合は短く録音し直すか手入力を使えます。「録音と下書きを破棄」でやり直せます。文字起こしはCPUで動くため、録音の長さやPCにより待ち時間が変わります。
