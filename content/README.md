# 教材

`content/<言語>/` に JSON で置く。形式は `docs/plan.md` の 6.2・6.3。

**今ある `ko/` の中身は、画面を作るためのテストデータ**（3 ユニット・50 語ほど）。
本番の教材は、UI が固まってから `tools/` のコマンドで作る。そのとき id の付け方は引き継ぐ。

| ファイル | 内容 |
| --- | --- |
| `units.json` | ユニット（レベル、場面、順） |
| `words.json` | 単語（1 語 1 オブジェクト） |
| `grammar.json` | レベルごとの文法 |
| `sentences/<ユニット>.json` | 文（ユニットごと） |
| `sources/` | 元の語彙リスト（git 管理外） |

`uv run langlang validate` で整合を確かめる。
