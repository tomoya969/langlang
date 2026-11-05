# 教材

`content/<言語>/` に JSON で置く。形式は `docs/plan.md` の 6.2・6.3。

`ko/` は本番の教材（今は L1。L2・L3 は同じ手順で作る）。`tools/` の教材づくりの CLI（`uv run langlang-build`）で作る。
`work/` 以外のファイルは書き出し（`langlang-build export`）のたびに作り直すので、直すときは `work/` を直してから書き出す。

| ファイル | 内容 |
| --- | --- |
| `units.json` | ユニット（レベル、場面、順） |
| `words.json` | 単語（1 語 1 行）。学習に出すのは status が approved の語だけ。要確認の語は `review` に 2 つの案を持つ |
| `grammar.json` | レベルごとの文法と、例文に使ってよい最初のユニット |
| `sentences/<ユニット>.json` | 文（ユニットごと）。学習に出すのは approved で、使う単語もすべて approved の文だけ |
| `work/` | 教材づくりの途中のデータ（AI の結果、単語の id など）と報告（`work/report.md`）。Git で管理する |
| `work/decisions.json` | 人が決めたこと（要確認の単語の決着）。AI の付与と検算より優先する |
| `sources/` | 元の語彙リスト（Git 管理外） |

## 元の語彙リスト

国立国語院「한국어 학습용 어휘 목록」（2003 年、5,965 語）。
<https://www.korean.go.kr/front_eng/down/down_02V.do?etc_seq=70> の「한국어 학습용 어휘 목록.txt」を `ko/sources/nikl.txt` として置く。
取り込み（`langlang-build import`）のときだけ読む。

## 作り方

```text
uv run langlang-build all       # 取り込みから書き出しまで順に（済んだところは飛ばす）
uv run langlang-build status    # どこまで済んだか
uv run langlang validate        # 教材の整合を確かめる
```

段階ごとにも実行できる（`import` → `supplement` → `tag` → `levels` → `units` → `grammar` → `enrich` → `verify-words` → `sentences` → `variants` → `export`）。
`units` から `variants` までは `--level 2` のようにレベルを指定する（既定は 1）。L2 の文は L1 の単語と文法も使うので、前のレベルを作り終えてから作る。
`export` はユニット分けまで済んだすべてのレベルを書き出す。
AI を使う段階は `claude -p` を呼ぶので、Claude の利用枠を使う。上限に当たったら止まり、時間をおいて同じコマンドを実行すると続きから進む。
文は `--units L1-U01,L1-U02` で一部のユニットだけ作れる。機械の検算（`tools/ko/morph.py`）を直したら、
`--recheck` で機械の検算で要確認になった文だけを確かめ直せる。
今の L1 の文は `LANGLANG_ENRICH_EFFORT=medium uv run langlang-build sentences` で作った（既定の effort だと 1 回に 4〜17 分かかるため。`docs/design.md`）。
許容例（採点で AI を呼ばずに正解にする別の言い方）は、文ができたあとに `variants` で作って検算する。文の中身かプロンプトの版
（`VARIANTS_STYLE`・`VERIFY_VARIANTS_STYLE`）が変わった文だけを作り直す。今の L1 は `LANGLANG_ENRICH_EFFORT=medium uv run langlang-build variants` で作った。

要確認の直し方（`docs/design.md`「L1 の要確認の直し」）:

- 単語は `work/decisions.json` に、id ごとに決めた品詞・意味・漢字・語種となぜそう決めたかを書いて、`export` する
- 文は `work/sentences/<ユニット>.json` を直し、`uv run langlang-build reopen ko-s-L1-U02-008 ...` で機械の検算を通してから、
  `uv run langlang-build sentences --units L1-U02` で AI の検算だけをやり直す。中身が変わった文は `variants` で許容例を作り直し、`export` する
