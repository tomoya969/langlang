# CLAUDE.md

langlang は、ゲーム感覚の反復で日常会話の語彙まで到達するためのローカルの語学学習アプリ。最初は韓国語。
設計は `docs/plan.md`。決めたことの経緯は `docs/design.md` に残す。

## 進め方

- 画面のたたき台ができたので、L1 の本番の教材を `tools/`（`uv run langlang-build`）で作って `content/ko/` に入れた段階。手順と決めたことは `content/README.md` と `docs/design.md`
- 教材は `content/ko/work/`（途中のデータ）を直して `langlang-build export` で書き出す。`content/ko/*.json` は書き出しのたびに作り直すので手で直さない
- 学習の記録は `records/langlang.db`（SQLite・FSRS、`app/records.py`）。単語の面と文（段階）、AI の判定と解説、なぞりの速さ、取り違えを持つ。苦手は記録からその場で数える（`app/weak.py`。`docs/design.md`「学習の記録」「文の記録」「苦手と取り違え」）

## AI の呼び出し方

- AI の呼び出しは `claude -p` を subprocess 経由で行う。呼び出すのは `app/claude_cli.py` だけ（差し替えポイント）
- Anthropic SDK と API キー（`ANTHROPIC_API_KEY`）は使わない。`--bare` は付けない
- 呼ばれた側の Claude にはファイル編集やコマンド実行をさせない。JSON を返すだけにする
- プロンプトと JSON スキーマは `app/prompts.py` に集める
- AI は押したときだけ呼び、結果は保存して使い回す。機械で確かめられるものは先に機械で確かめる
- 本物の `claude` を呼ぶ動作確認は最小限にする（Pro の利用枠を節約する）
- 教材づくりは `claude` を数百回呼ぶ。プロンプトを変えたら `*_STYLE` を上げ、`--units` などで少量を試してから全体を流す

## 開発

- Python 環境は uv。`uv sync`、`uv run langlang serve`、`uv run pytest`
- 画面は `static/`（素の HTML/CSS/JS、ビルド不要。React などは使わない）。画面の部品のロジック（ハングルの合成、矢印ゲームの列）は画面から切り離した関数にし、`node --test 'static/**/*.test.js'` で確かめる
- 言語に依存する処理は言語パックに閉じ込める（サーバー側 `app/langs/`、画面側 `static/langs/`）
- 画面の URL は `/`（ポータル）、`/settings`、`/{言語}/...`。言語ごとの画面のリンクは `data-lang-path` で書き、JS が今の言語に書き換える。API は言語を必ず受け取る（既定の言語を持たない）
- サーバーは `127.0.0.1` のみで待ち受ける。変えない
- `claude` の呼び出しはテストではモックにする
- `records/` は個人の学習データなので git 管理しない
- API を変えたら `app/server.py` の `API_VERSION` と画面の `REQUIRED_API_VERSION` を両方上げる

## コードコメント

コメントは、これからコードを読む人に「今の実装がなぜこうなっているか」を伝えるために書く。過去の経緯は書かない。

- まずコメントがなくても読めるコードにする。コードを読めば分かることを言い換えるコメントは書かない
- 書くのは「なぜそうする必要があるか」がコードから読み取れないときだけ（仕様上の制約、順序の理由、見落としやすいエッジケース）
- 変更の経緯（「以前は」「今回変更」）は書かない。経緯はコミットメッセージと `docs/design.md` に残す
- 実装を変えたら関係するコメントも見直す。TODO は何が残っているかを具体的に書く

## コミットメッセージ

- `feat:` `fix:` `docs:` `chore:` などのプレフィックス ＋ 日本語の要約

## 秘密情報

- API キー、パスワード、社内の情報はコミットしない
