"""AI に渡すプロンプトと、返してもらう JSON スキーマ。プロンプトの文面を変えたいときはこのモジュールだけを触る。

採点（翻訳・作文）のスキーマは docs/plan.md の 5.6 の形。プロンプトの文面は AI 採点を入れる段階（M5）で書く。
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "あなたは langlang（語学学習アプリ）の教材作成・採点エンジンです。"
    "ユーザーのメッセージに含まれる指示に従い、指定された JSON スキーマどおりの結果だけを返します。"
    "ファイルの作成・編集やコマンドの実行は行いません。"
)

# 誤りのタグ（docs/plan.md 5.5）。採点の issues[].tag と、記録の集計で使う
ERROR_TAGS = ["助詞", "活用", "時制", "否定", "語順", "語彙の選択", "받침", "띄어쓰기", "綴り", "文体", "訳抜け", "その他"]

GRADE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "correct_with_notes", "incorrect"]},
        "meaning_ok": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "axis": {"type": "string", "enum": ["meaning", "grammar", "naturalness", "register", "orthography"]},
                    "tag": {"type": "string", "enum": ERROR_TAGS},
                    "span": {"type": "string"},
                    "note": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "word_id": {"type": ["string", "null"]},
                },
                "required": ["axis", "tag", "span", "note"],
            },
        },
        "corrected": {"type": "string"},
        "comment_ja": {"type": "string"},
    },
    "required": ["verdict", "meaning_ok", "issues", "corrected", "comment_ja"],
}
