"""AI に渡すプロンプトと、返してもらう JSON スキーマ。プロンプトの文面を変えたいときはこのモジュールだけを触る。

採点のスキーマは docs/plan.md の 5.6 の形、判定の基準は 5.2・5.3。採点のプロンプトは韓国語用。
GRADE_STYLE を上げると、保存してある AI の判定を使わずに判定し直す（app/graded.py）。

教材づくり（tools/、docs/plan.md の 6 章）のプロンプトは韓国語用。*_STYLE はプロンプトの版で、保存してある結果の版が
今と違えば、まだ作っていないものとして作り直す（プロンプトを直したら上げる）。
"""

from __future__ import annotations

from typing import Any

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

GRADE_STYLE = 1

# 練習ごとの、問題の説明・不正解と注意の追加の条件・corrected の単位。
# 判定の粒度をそろえるため、条件は箇条書きで言い切り、判定は「不正解 → 注意 → 正解」の順に確かめさせる
_GRADE_PRACTICES: dict[str, dict[str, Any]] = {
    "word_spell": {
        "about": "日本語の意味を見て、単語の読み上げを聞き、その単語をハングルで書く練習です。問われているのは、その単語を正しく綴れるかです。",
        "incorrect": ["問われている単語と別の語を書いている（意味の近い語でも不正解。読み上げを聞いているため）"],
        "notes": ["問われている単語の活用した形を書いている（가다 に 가요 など）"],
        "unit": "単語だけ",
    },
    "sentence_cloze": {
        "about": (
            "韓国語の文の語節が 1 つ空欄になっていて、日本語訳と空欄の意味の手がかりを見て、空欄に入る語節をハングルで書く練習です。"
            "答えは空欄の語節だけです。答えを空欄に入れた文全体で判定してください。"
            "問われているのは、空欄の意味の語を、文に合う形で書けるかです。"
        ),
        "incorrect": ["空欄の意味の手がかりと違う意味の語を書いている", "空欄に入れると文が文法的に成り立たない"],
        "notes": [],
        "correct": ["模範解答と違う語や形でも、空欄の意味の手がかりに合い、文が文法的に正しく、文の文体に合っていれば正解"],
        "unit": "空欄の語節だけ",
    },
    "sentence_dictation": {
        "about": (
            "韓国語の文の読み上げを聞いて、聞こえたとおりにハングルで書く練習です。読み上げたのは「読み上げた文」です。"
            "問われているのは、文を聞き取れたか、聞き取った文を綴れるかです。"
        ),
        "incorrect": [
            "読み上げた文の語・助詞・語尾が抜けている、別の語・助詞・語尾になっている、読み上げにない語を足している"
            "（意味が近くても不正解。聞き取れていないため）",
        ],
        "notes": [],
        "correct": ["数を算用数字で書いている（세 개 を 3개 と書くなど）"],
        "unit": "文全体",
    },
    "sentence_ja_to_ko": {
        "about": (
            "日本語の文を見て、指定の文体の韓国語に訳す練習です。"
            "問われているのは、意味を過不足なく、文法・自然さ・文体・表記の正しい韓国語で書けるかです。"
        ),
        "incorrect": [],
        "notes": [],
        "unit": "文全体",
    },
    "sentence_compose": {
        "about": (
            "指定の表現を使って、自分のことを韓国語で 1 文書く練習です。内容は学習者の自由で、例文と違ってかまいません。"
            "問われているのは、指定の表現を正しく使った文を書けるかです。"
        ),
        "incorrect": ["指定の表現を使っていない（課題を満たしていないため）"],
        "notes": [],
        "unit": "文全体",
    },
    # 答えが日本語の練習。共通の条件と判定の例は _GRADE_NATIVE を使う（docs/plan.md 5.3「韓→日」）
    "sentence_ko_to_ja": {
        "about": (
            "韓国語の文を読んで、日本語に訳す練習です。"
            "問われているのは、韓国語の文の意味を過不足なく読み取れたかで、日本語の書き方ではありません。"
        ),
        "incorrect": [],
        "notes": [],
        "unit": "日本語訳の全体",
        "native": True,
    },
}

_GRADE_INCORRECT = [
    "意味の取り違え、訳抜け、意味が変わる付け足し",
    "意味が変わる文法の誤り（時制・否定・助詞の取り違えで主語と目的語が入れ替わる、など）",
    "綴りの誤りで、別の語・別の活用形・別の助詞・別の語尾になっている（있어요 → 없어요、해요 → 했어요、에 → 에서、는 → 를）",
    "崩れていて、何を書こうとしたのか一つに決められない",
    "場面に明らかに合わない文体（目上の人に반말、など）",
]

_GRADE_NOTES = [
    "小さな綴りの誤り。直し方が一つに決まり、直すと問われている語・形と同じになるもの"
    "（字母 1〜2 個の打ち間違い、받침の付け忘れ・付け間違い。예오 → 예요、민수능 → 민수는）",
    "띄어쓰기の誤り",
    "通じるが不自然な言い回し",
    "指定の文体と違うが、場面上は許される文体",
]

_GRADE_KOREAN = {
    "premise": (
        "この答えは、模範解答・許容例のどれとも一致せず、空白の位置だけの違いや、発音が同じになる綴りの違いでもありませんでした。\n"
        "模範解答と違うことだけを理由に、注意や不正解にしないでください。言い方が違っても、正しい韓国語なら正解です。\n"
        "文末の記号（. ? !）の有無と前後の空白は、比べる前に取り除いているので、判定にも issues にも含めないでください。"
    ),
    "incorrect": _GRADE_INCORRECT,
    "notes": _GRADE_NOTES,
    "examples": """# 判定の例（どの練習にも共通。模範解答が「민수는 누구예요?」のとき）

- 민수는 누구예오 → correct_with_notes（예오 は 예요 の打ち間違い。直し方が一つに決まり、別の形にならない）
- 민수능 누구예요 → correct_with_notes（능 は 는 の打ち間違い）
- 민수를 누구예요 → incorrect（를 は別の助詞で、文が成り立たない）
- 민수는 누구였어요 → incorrect（時制が変わる）
- 민수 누구 → incorrect（助詞と語尾が抜けて、文になっていない）""",
    "span": "学習者の答えから、誤りのある語節をそのまま抜き出す（語が抜けているときは、抜けた位置の直前の語節）",
}

# 答えが日本語の練習（韓→日訳）。日本語の書き方は問わず、意味だけを厳しく見る（docs/plan.md 5.3）
_GRADE_NATIVE = {
    "premise": (
        "この答えは、模範訳・許容訳のどれとも一致しませんでした。\n"
        "模範訳と違うことだけを理由に、注意や不正解にしないでください。"
        "日本語の言い回し・語順・表記ゆれ（漢字とかな、送り仮名、人名の書き方）・です／ます体かどうかは問いません。"
        "意味が過不足なく合っていれば正解です。\n"
        "空白と記号（句読点・かっこ・？！）は、比べる前に取り除いているので、判定にも issues にも含めないでください。"
    ),
    "incorrect": [
        "韓国語の文の意味を取り違えている（語の意味、時制、否定、疑問か平叙か、誰が誰に何をするか）",
        "韓国語の文の一部を訳していない、韓国語の文にない意味を足している（日本語として自然に補う主語や目的語は除く）",
        "崩れていて、何を書こうとしたのか一つに決められない",
    ],
    "notes": [
        "意味は合っているが、韓国語の文の丁寧さが訳から完全に消えている（丁寧に頼む文を「〜しろ」「〜くれ」と訳す、など）",
    ],
    "examples": """# 判定の例（韓国語の文が「민수는 누구예요?」、模範訳が「ミンスは誰ですか？」のとき）

- 民秀は誰ですか → correct（人名の書き方の違い）
- ミンスってどなたですか → correct（言い回しの違い）
- ミンスは誰？ → correct（です／ます体でなくても、丁寧さは問わない）
- ミンスは誰でしたか → incorrect（時制が変わる）
- ミンスはどこですか → incorrect（누구 を「どこ」と取り違えている）

韓国語の文が「물 좀 주세요.」のとき:

- 水をちょっとください → correct
- 水をくれ → correct_with_notes（意味は合っているが、丁寧に頼む言い方が命令になっている）""",
    "span": "学習者の答えから、誤りのある部分をそのまま抜き出す（訳が抜けているときは、抜けた位置の直前の部分）",
}


def build_grade_prompt(practice: str, context: dict[str, Any], answer: str) -> str:
    """採点のプロンプト。context は練習ごとの問題の中身（app/server.py の task_for が作る）。"""
    p = _GRADE_PRACTICES[practice]
    frame = _GRADE_NATIVE if p.get("native") else _GRADE_KOREAN
    incorrect = p["incorrect"] + frame["incorrect"]
    notes = p["notes"] + frame["notes"]
    problem = "\n".join(f"- {label}: {value}" for label, value in context.get("problem", []) if value)
    words = "\n".join(f"- {w['id']}: {w['lemma']}（{w['meaning']}）" for w in context.get("words", []))
    return f"""# 依頼

韓国語の学習アプリの採点です。学習者の答えを、下の手順で 3 段階に判定してください。
学習者は日本語話者で、韓国語を学んでいる途中です。

{frame["premise"]}

# 練習

{p["about"]}

# 問題

{problem}

# 問題の単語

{words or "（なし）"}

# 学習者の答え

{answer}

# 判定の手順

次の順に確かめ、最初に当てはまった段階を判定にしてください。

1. 不正解（incorrect）: 次のどれかに当てはまる
{_bullets(incorrect)}
2. 正解（注意つき）（correct_with_notes）: 不正解ではなく、次のどれかに当てはまる
{_bullets(notes)}
3. 正解（correct）: どれにも当てはまらない{_bullets_after(p.get("correct", []))}

{frame["examples"]}

# 書き方

- verdict: 上の手順で決めた判定
- meaning_ok: 学習者の答えで、問題の文の意味が伝わるか
- issues: 直すところを 1 つずつ挙げる
  - correct なら空にする。correct_with_notes と incorrect では必ず 1 つ以上挙げる
  - incorrect のときは、不正解の理由になった誤りを最初に挙げる
  - axis: meaning（意味）/ grammar（文法）/ naturalness（自然さ）/ register（文体）/ orthography（表記）
  - tag: 誤りの種類
  - span: {frame["span"]}
  - note: その誤りの説明を日本語で 1 文。不正解の理由になった誤りは、なぜ不正解なのか（意味がどう変わるか、問われていることのどれを満たさないか）が分かるように書く
  - suggestion: span を直した形
  - word_id: 誤りが「問題の単語」のどれかに関わるときはその id。なければ null
- corrected: 学習者の答えを、学習者の言い方をなるべく残して、正解になるように最小限直したもの（{p["unit"]}）。correct なら答えのまま
- comment_ja: 判定の理由を日本語で 1〜2 文。incorrect なら、なぜ不正解なのかを 1 文目に書く。correct_with_notes なら、何が合っていて、何を直すとよいか
"""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"   - {item}" for item in items)


def _bullets_after(items: list[str]) -> str:
    return "\n" + _bullets(items) if items else ""


# ---- 解説（docs/plan.md 4.9。「解説」を押したときだけ作り、保存して使い回す） ----

EXPLAIN_STYLE = 1

EXPLAIN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"surface": {"type": "string"}, "breakdown": {"type": "string"}},
                "required": ["surface", "breakdown"],
            },
        },
        "grammar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"form": {"type": "string"}, "explanation": {"type": "string"}},
                "required": ["form", "explanation"],
            },
        },
        "register": {"type": "string"},
        "pronunciation": {"type": "string"},
        "tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "parts", "grammar", "register", "pronunciation", "tips"],
}


def build_explain_prompt(sentence: dict[str, Any], words: list[dict[str, Any]], grammar: list[dict[str, Any]], level: int = 1) -> str:
    """文の解説のプロンプト。words は文の単語（lemma・pos・meaning）、grammar は文法の表示に当たる文法リストの項目。"""
    tokens = "\n".join(f"- {t['surface']}" for t in sentence["tokens"])
    word_lines = "\n".join(f"- {w['lemma']}（{w['pos']}）: {w['meaning']}" for w in words)
    grammar_lines = "\n".join(f"- {g['form']}: {g['ja']}" for g in grammar) or "\n".join(f"- {g}" for g in sentence.get("grammar", []))
    return f"""# 依頼

韓国語の学習アプリで、学習者が「解説」を押した文の解説を書いてください。
{_LEARNER + "今は" + LEVEL_STAGES[1] + "です。" if level <= 1 else _learner(level)}
解説は保存して何度も見せるので、正確さを最優先にしてください。確かでないことは書かないでください。

# 文

- 韓国語: {sentence["ko"]}
- 日本語訳: {sentence["ja"]}
- 文体: {sentence["register"]}
- 場面: {sentence["scene"]}

# 語節

{tokens}

# 文の単語（この文での意味）

{word_lines or "（なし）"}

# 文の文法

{grammar_lines or "（なし）"}

# 書き方（すべて日本語。韓国語の語や形はハングルのまま書く）

- summary: 文全体の意味と、どんな場面で誰が誰に言う文かを 1〜2 文
- parts: 語節ごとに 1 つ。surface は語節（記号を除く）、breakdown は「原形（意味）＋ 助詞・語尾（働き）」の形の分解
  （例: 먹었어요 → 「먹다（食べる）＋ -었-（過去）＋ -어요（해요체の語尾）」）。活用で形が変わるときは原形との関係も書く
- grammar: 文の文法を 1 つずつ。form は文法の形、explanation は意味と使い方を 1〜2 文。この文での使われ方が分かるように
- register: 文体（{sentence["register"]}）が、この場面でどういう丁寧さか 1 文
- pronunciation: 書いたとおりに読まない所（連音化・鼻音化・濃音化・激音化など）を「표기 → [発音]」の形で。なければ空
- tips: 間違えやすい点、似た言い方との違いなどを 0〜3 個。なければ空
"""


# ---- 教材づくり（韓国語） ----

_LEARNER = "学習者は日本語話者です。ハングルは読めて発音もできますが、韓国語の単語はほとんど知りません。"
# 学習者の今の段階（解説の書き方を合わせる）
LEVEL_STAGES = {1: "初級（ハン検 5〜4 級ほど）", 2: "初中級（ハン検 3 級ほど）", 3: "中級（ハン検準 2 級ほど）"}


def _learner(level: int) -> str:
    """学習者の説明。L2 からは、前のレベルの単語と文法を学び終えている。"""
    if level <= 1:
        return _LEARNER
    return f"学習者は日本語話者です。ハングルは読めて発音もできます。L{level - 1} までの単語と文法は学び終え、今は {LEVEL_STAGES[level]} です。"

POS_LIST = ["名詞", "依存名詞", "代名詞", "数詞", "動詞", "形容詞", "副詞", "冠形詞", "感嘆詞", "固有名詞", "表現"]
HANKEN_LEVELS = ["5級", "4級", "3級", "準2級", "2級以上"]
ORIGINS = ["固有語", "漢字語", "外来語", "混種語"]
EXCLUDE_REASONS = ["なし", "固有名詞", "古い語", "文法"]
REGISTERS = ["합니다체", "해요체", "반말", "한다체"]

SUPPLEMENT_STYLE = 1
TAG_STYLE = 1
UNITS_STYLE = 1
GRAMMAR_STYLE = 1
ENRICH_STYLE = 1
VERIFY_WORDS_STYLE = 1
SENTENCES_STYLE = 2
VERIFY_SENTENCES_STYLE = 2


def _keyed_schema(field: str, keys: list[str], item: dict) -> dict:
    """聞いたキーそのものを properties にしたスキーマ。キーを AI に書かせると取り違えることがあるため（suburi と同じ）。"""
    return {
        "type": "object",
        "properties": {
            field: {
                "type": "object",
                "properties": {key: item for key in keys},
                "required": list(keys),
                "additionalProperties": False,
            }
        },
        "required": [field],
        "additionalProperties": False,
    }


def _strings(**extra: Any) -> dict:
    return {"type": "array", "items": {"type": "string", **extra}}


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def _hint_text(item: dict) -> str:
    parts = []
    if item.get("gloss"):
        parts.append(f"補足「{item['gloss']}」")
    if item.get("hint"):
        parts.append(f"意味の手がかり「{item['hint']}」")
    return "、".join(parts)


# 補完（docs/plan.md 6.1 の 1）: 元のリストにない、あいさつの表現と現代の日常語

def supplement_schema() -> dict:
    item = _obj({"lemma": {"type": "string"}, "ja": {"type": "string"}, "pos": {"type": "string", "enum": POS_LIST}})
    return _obj({"greetings": {"type": "array", "items": item}, "modern": {"type": "array", "items": item}})


def build_supplement_prompt(existing: list[str]) -> str:
    return f"""# 依頼

日本語話者が、韓国語の日常会話に困らない語彙（約 3,000 語）を覚えるための単語リストを作っています。
{_LEARNER}
土台にするのは国立国語院の「한국어 학습용 어휘 목록」（2003 年）です。このリストにない語を、次の 2 種類挙げてください。

1. greetings: あいさつ・返事・お礼・おわびなど、そのままの形で使う決まった表現を 15 個ほど
   - 안녕하세요、감사합니다、안녕히 가세요 のように、実際に言う形で書く（辞書形にしない）
   - 韓国語を初めて学ぶ人が最初に覚える、ごく基本のものに限る
2. modern: 2003 年より後に日常会話でよく使うようになった語を 100 個ほど
   - 스마트폰、카톡 のような、スマートフォン・インターネット・SNS・キャッシュレス・配達・コンビニ・カフェなど、今の生活の語
   - 流行語・若者言葉・一時的な新語は入れない。10 年後も日常会話で使っていそうな語に限る
   - 商品名・サービス名そのもの（유튜브 など）は入れない。카톡 のように一般の語として使われているものはよい
   - リストの語の活用した形と同じになる語（SNS の「좋아요」は 좋다 の 좋아요 と同じ形）は、学習者が取り違えるので入れない

# 書き方

- lemma: 名詞はそのまま、動詞・形容詞は辞書形（-다）。greetings は実際に言う形
- ja: 日本語の意味（短く）
- pos: 品詞。greetings はすべて「表現」
- 下の「リストにある語」は挙げない（同じ語の別の書き方も挙げない）

# リストにある語

{"、".join(existing)}
"""


# 粗い付与（docs/plan.md 6.1 の 3）

def tag_schema(keys: list[str]) -> dict:
    item = _obj(
        {
            "hanken": {"type": "string", "enum": HANKEN_LEVELS},
            "origin": {"type": "string", "enum": ORIGINS},
            "pos": {"type": "string", "enum": POS_LIST},
            "ja_cognate": {"type": "boolean"},
            "exclude": {"type": "string", "enum": EXCLUDE_REASONS},
        }
    )
    return _keyed_schema("tags", keys, item)


def build_tag_prompt(items: list[dict]) -> str:
    """items: key, lemma, pos（分からなければ None）, gloss, hint。"""
    lines = []
    for item in items:
        detail = [f"品詞「{item['pos']}」" if item.get("pos") else "品詞は不明", _hint_text(item)]
        lines.append(f"- {item['key']}（{item['lemma']}）: {'、'.join(d for d in detail if d)}")
    return f"""# 依頼

日本語話者が、韓国語の日常会話に困らない語彙（約 3,000 語）を覚えるための教材を作っています。
学習用の語彙の候補（国立国語院の学習用語彙リストと、その補完）に、次の情報を付けてください。
この情報をもとに、やさしい語から順に並べてレベル（L1〜L3）に分けます。

# 付ける情報

- hanken: ハングル能力検定試験（ハン検）で、この語がどの級の出題範囲に入りそうか
  - 5級（入門）・4級（初級）・3級（初中級）・準2級（中級）・2級以上（上級）
  - 迷ったら、日常会話で早く必要になる語ほどやさしい級にする
- origin: 語種。固有語・漢字語・外来語・混種語
  - 混種語は、漢字語や外来語に固有語が付いたもの（공부하다 は 工夫＋하다 なので混種語。맛있다 は固有語）
- pos: 品詞。品詞が書いてある候補はそれをそのまま返す。「品詞は不明」の候補だけ判断する
- ja_cognate: 漢字語のうち、同じ漢字の語が日本語にもあり、意味もほぼ同じもの（도서관＝図書館、학교＝学校）は true。
  それ以外（固有語・外来語・混種語、日本語にない漢字語、意味が違う漢字語。공부＝工夫 など）は false
- exclude: 学習用の語彙から外すか
  - 固有名詞: 地名・人名・歴史上の名前・建物などの名前。ただし国名・大陸名と 서울 は日常会話で使うので「なし」
  - 古い語: 今の日常会話ではほとんど使わない語（使われなくなった機器の名前など）
  - 文法: 単独ではほとんど使わず、文法の一部（-(으)ㄹ 수 있다 の 수、-는 듯하다 の 듯 など）としてだけ使う語。
    数を数える語（개、명、번 など）と、것・때문 のように単独でも使う語は「なし」
  - なし: それ以外（ほとんどの語はこれ）

# 書き方

- tags のキーは、下の候補の「- 」の後ろのキー（数字つきの見出し）をそのまま使う
- 「補足」は元のリストの漢字や用例で、同じ綴りの別の語を見分けるためのもの

# 候補

{chr(10).join(lines)}
"""


# ユニット分け（docs/plan.md 6.1 の 7）

def units_schema(keys: list[str]) -> dict:
    unit = _obj(
        {
            "title": {"type": "string"},
            "scene": {"type": "string"},
            "keys": {"type": "array", "items": {"type": "string", "enum": keys}},
        }
    )
    return _obj({"units": {"type": "array", "items": unit}})


def build_units_prompt(level: int, words: list[dict], unit_count: int, earlier: list[dict], first: bool) -> str:
    """words: key, lemma, pos, gloss, hint, category（固定枠の区分。なければ None）。earlier: これより前のユニット（title, scene）。"""
    lines = []
    for w in words:
        detail = [w.get("pos") or "", _hint_text(w), f"区分「{w['category']}」" if w.get("category") else ""]
        lines.append(f"- {w['key']}（{w['lemma']}）: {'、'.join(d for d in detail if d)}")
    earlier_text = "\n".join(f"- {u['title']}（{u['scene']}）" for u in earlier) or "（なし）"
    first_rule = (
        "- これは L1 の最初のユニット群（あいさつ・人と物を指す語・数・数え方・基本の用言）。ユニットは学ぶ順に並べる。\n"
        "  1 つ目のユニットは、あいさつと簡単な自己紹介ができるようにする（あいさつ・返事・저・있다 など）\n"
        "- 区分は目安。数と数え方を 1 つのユニットにまとめるなど、例文を作りやすい組み合わせにしてよい\n"
        if first
        else ""
    )
    return f"""# 依頼

日本語話者が韓国語の日常会話の語彙を覚えるための教材で、L{level} の単語をユニットに分けています。
{_learner(level)}
新しい単語はユニットの順に覚え、ユニットごとに、そのユニットまでの単語だけで例文を作って練習します。

次の {len(words)} 語を、{unit_count} 個のユニットに分けてください（1 ユニット 20〜30 語）。

# 分け方

- 「カフェで注文」「一日の行動」のように、場面でまとめる。その場面で一緒に使う語を集める
- 意味の近い語ばかり（色の名前、曜日、家族の呼び方 など）を 1 つのユニットに集めすぎない。似た語を一度に覚えると取り違えやすいため
- 例文を作れるように、名詞だけ・動詞だけに偏らせない。動詞・形容詞と、それと一緒に使う名詞を同じユニットに入れる
{first_rule}- すべての語を、どれか 1 つのユニットに 1 回だけ入れる。keys には下の一覧の「- 」の後ろのキー（数字つきの見出し）をそのまま書く
- title: ユニットの名前（日本語、12 字ほどまで）。前のユニットと同じ名前にしない
- scene: どこで誰と話す場面か（日本語、20 字ほどまで。例:「カフェのカウンターで」）

# これより前のユニット

{earlier_text}

# 単語

{chr(10).join(lines)}
"""


# 文法リスト（docs/plan.md 6.3「文法は、レベルごとの文法リストの範囲内」）

# レベルごとの文法の範囲と文体（docs/plan.md 4.3）
GRAMMAR_SCOPES = {
    1: {
        "label": "ハン検 5〜4 級、TOPIK 1 級ほど",
        "range": "ハン検 5〜4 級で学ぶ文法（助詞、語尾、否定、過去、丁寧さ、よく使う文型）を 40〜60 個",
        "register": "文体は 해요체 が中心。あいさつなどの決まった表現に使う 합니다체（-ㅂ니다/습니다）も入れる。"
        "반말 と 한다체 は入れない（L2 以降で学ぶ）",
    },
    2: {
        "label": "ハン検 3 級、TOPIK 2 級ほど",
        "range": "ハン検 3 級で学ぶ文法（連体形の使い分け、理由・目的・条件・逆接・並列の接続、意図・推量・経験・変化、"
        "伝え聞きの基本、よく使う補助用言など）を 40〜60 個",
        "register": "합니다체（-ㅂ니까?、-(으)십시오 など、改まった場面の言い方）と 반말（-아/어、-자、-니?、-(이)야 など、"
        "友達・家族・年下に使う言い方）を入れる。한다체 は入れない（L3 で学ぶ）",
    },
    3: {
        "label": "ハン検準 2 級、TOPIK 3 級ほど",
        "range": "ハン検準 2 級で学ぶ文法（-(으)ㄹ 텐데、-도록、-(으)ㄴ/는 척하다、-더니、-았/었더니、-(으)ㄹ 뻔하다、"
        "-는 김에、-(으)ㄹ 만하다、-냐고 하다 など）を 40〜60 個",
        "register": "書き言葉の 한다체（-ㄴ다/는다、-았/었다、-(으)ㄹ 것이다、-는가 など。日記・説明文・記事の文体）を入れる",
    },
}


def grammar_schema(unit_ids: list[str]) -> dict:
    item = _obj(
        {
            "form": {"type": "string"},
            "ja": {"type": "string"},
            "example": {"type": "string"},
            "unit": {"type": "string", "enum": unit_ids},
        }
    )
    return _obj({"items": {"type": "array", "items": item}})


def build_grammar_prompt(level: int, units: list[dict], earlier: list[str] | None = None) -> str:
    """units: id, title, scene, lemmas（そのユニットの単語）。earlier: 前のレベルの文法の形（L2 から。どのユニットでも使える）。"""
    unit_lines = "\n".join(f"- {u['id']} {u['title']}（{u['scene']}）: {'、'.join(u['lemmas'])}" for u in units)
    scope = GRAMMAR_SCOPES[level]
    if earlier:
        basics = (
            "- 前のレベルの文法（下の一覧）は、どのユニットでも使える。このリストには入れない（同じ文法の別の形・別の使い方も入れない）"
        )
        first_unit = "  - 最初のユニットから、そのユニットの場面で使う新しい文法を 1〜3 個使えるようにする"
        earlier_text = "\n\n# 前のレベルの文法\n\n" + "、".join(earlier)
    else:
        basics = "- 이다（-예요/이에요）と 아니다（-이/가 아니에요）の形も文法として入れる"
        first_unit = "  - 1 つ目のユニットから文を作れるように、最初のユニットに基本（-예요/이에요、은/는、-아/어요 など）を置く"
        earlier_text = ""
    return f"""# 依頼

日本語話者向けの韓国語の教材で、L{level}（{scope['label']}）の文法リストを作ってください。
{_LEARNER}
例文は下のユニットごとに、そのユニットまでの単語と文法だけで作ります。このリストで、どの文法をどのユニットから使ってよいかを決めます。

# 範囲

- {scope['range']}
- {scope['register']}
{basics}

# 書き方

- form: 文法の形。助詞は「은/는」、語尾は「-아/어요」「-(으)세요」、否定は「안 -」のように書く。同じ形を 2 回入れない
- ja: 日本語での意味（短く。例:「〜は」「〜です・ます（해요체）」）
- example: その文法を使った短い例文（韓国語）
- unit: その文法を最初に例文で使ってよいユニット
{first_unit}
  - ユニットの場面で必要になる文法は、そのユニットまでに使えるようにする（注文の場面なら -(으)세요 など）
  - 難しい文法ほど後のユニットにし、1 つのユニットで新しく使えるようになる文法は 0〜3 個にして、なだらかに増やす
- items は unit の順に並べる

# ユニット（id 名前（場面）: 単語）

{unit_lines}{earlier_text}
"""


# 詳しい付与（docs/plan.md 6.1 の 8）

def enrich_schema(keys: list[str]) -> dict:
    meaning = _obj({"ja": {"type": "string"}, "primary": {"type": "boolean"}})
    item = _obj(
        {
            "meanings": {"type": "array", "items": meaning},
            "hanja": {"type": ["string", "null"]},
            "confusables": _strings(),
            "synonyms": _strings(),
            "tags": _strings(),
        }
    )
    return _keyed_schema("words", keys, item)


def build_enrich_prompt(items: list[dict]) -> str:
    """items: key, lemma, pos, origin, gloss, hint, unit（ユニットの名前）。"""
    lines = []
    for item in items:
        detail = [item["pos"], item["origin"], _hint_text(item), f"ユニット「{item['unit']}」"]
        lines.append(f"- {item['key']}（{item['lemma']}）: {'、'.join(d for d in detail if d)}")
    return f"""# 依頼

日本語話者向けの韓国語の単語帳と、意味を 4 択で選ぶゲームに使う情報を、次の単語に付けてください。
{_LEARNER}

# 書き方

- meanings: 日本語の意味を 1〜3 個。日常会話でいちばんよく使う意味 1 つだけ primary を true にする（ほかは false）
  - 4 択の選択肢に出すので短く（12 字ほどまで）。辞書の説明文ではなく、日本語でいちばん近い語にする
  - 動詞・形容詞は日本語の終止形（食べる、高い）、名詞は名詞、副詞は副詞で書く
  - 誤解しやすいときだけ（ ）で補う（비싸다 →「（値段が）高い」、반갑다 →「（会えて）うれしい」、저 →「私（へりくだって）」）
  - 日本語では 2 つの語に分かれるが韓国語では 1 つの語なら、primary の意味を「・」でまとめる（있다 →「ある・いる」、주다 →「あげる・くれる」）
  - 「補足」は、同じ綴りの別の語と見分けるための漢字や用例。その補足に合う意味を書く
  - 表現（あいさつなど）は、日本語で同じ場面に言う言葉（안녕하세요 →「こんにちは」）
- hanja: 漢字語・混種語の、漢字の部分を日本の字体で書く（圖書館 ではなく 図書館、공부하다 → 工夫）。固有語・外来語は null
- confusables: 形や発音が似ていて取り違えやすい韓国語の語（사다 と 싸다、차다 と 짜다 など）。0〜3 個、辞書形で
- synonyms: 意味がほぼ同じで、4 択に一緒に出ると正解が 2 つになってしまう韓国語の語（이것 と 이거、저 と 나 など）。0〜3 個、辞書形で
- tags: 場面や分野のタグを 1〜2 個（食事、買い物、時間、人、家族、移動、天気、気持ち、仕事、学校、体、家、趣味 など）
- words のキーは、下の「- 」の後ろのキー（数字つきの見出し）をそのまま使う

# 単語

{chr(10).join(lines)}
"""


# 単語の検算（docs/plan.md 6.1 の 9）

def verify_words_schema(keys: list[str]) -> dict:
    item = _obj(
        {
            "meaning_ok": {"type": "boolean"},
            "hanja_ok": {"type": "boolean"},
            "origin_ok": {"type": "boolean"},
            "suggested_meaning": {"type": "string"},
            "suggested_hanja": {"type": "string"},
            "suggested_origin": {"type": "string", "enum": ["", *ORIGINS]},
            "note": {"type": "string"},
        }
    )
    return _keyed_schema("words", keys, item)


def build_verify_words_prompt(items: list[dict]) -> str:
    """items: key, lemma, pos, origin, meanings（[{ja, primary}]）, hanja, gloss, hint。"""
    lines = []
    for item in items:
        primary = next((m["ja"] for m in item["meanings"] if m.get("primary")), "")
        others = [m["ja"] for m in item["meanings"] if not m.get("primary")]
        detail = [
            item["pos"],
            f"主な意味「{primary}」",
            f"ほかの意味「{'／'.join(others)}」" if others else "",
            f"漢字「{item['hanja']}」" if item.get("hanja") else "漢字なし",
            f"語種「{item['origin']}」",
            _hint_text(item),
        ]
        lines.append(f"- {item['key']}（{item['lemma']}）: {'、'.join(d for d in detail if d)}")
    return f"""# 依頼

日本語話者向けの韓国語の単語データを検算してください。別の担当が付けた、日本語の意味・漢字・語種が正しいかを確かめます。
単語は、意味を 4 択で選ぶゲームと単語帳に使います。誤りがあると、学習者は誤りを覚えてしまいます。

# 確かめること

- meaning_ok: 「主な意味」が、この語の日常会話での主な意味として正しいか
  - 4 択の選択肢に出すので短くしてある。言い回しの好みや「もっと良い訳がある」程度なら true にして、note に書く
  - 意味が違う、同じ綴りの別の語の意味になっている（「補足」の漢字や用例と合わない）、日本語として誤解を招く、なら false
- hanja_ok: 漢字が正しいか。漢字語・混種語は、漢字の部分を日本の字体で書く（図書館、공부하다 → 工夫）。固有語・外来語は漢字なしが正しい
  - 旧字体（圖・學 など）や韓国でしか使わない字体のまま、漢字が違う、漢字語なのに漢字がない、なら false
- origin_ok: 語種（固有語・漢字語・外来語・混種語）が正しいか
- false にしたものは、正しいものを suggested_* に書く（漢字が要らないなら suggested_hanja は「なし」）。true のものは空文字
- note: 気づいたこと（なければ空文字）
- words のキーは、下の「- 」の後ろのキーをそのまま使う

# 単語

{chr(10).join(lines)}
"""


# 文の生成（docs/plan.md 6.3）

def sentences_schema(word_ids: list[str], grammar_forms: list[str]) -> dict:
    token = _obj({"surface": {"type": "string"}, "word_ids": {"type": "array", "items": {"type": "string", "enum": word_ids}}})
    sentence = _obj(
        {
            "ko": {"type": "string"},
            "ja": {"type": "string"},
            "register": {"type": "string", "enum": REGISTERS},
            "scene": {"type": "string"},
            "tokens": {"type": "array", "items": token},
            "grammar": {"type": "array", "items": {"type": "string", "enum": grammar_forms}},
            "cloze": _obj({"eojeol": {"type": "integer"}, "answer": {"type": "string"}, "hint_ja": {"type": "string"}}),
            "variants": _obj({"ko": _strings(), "ja": _strings()}),
        }
    )
    return _obj({"sentences": {"type": "array", "items": sentence}})


def _word_line(w: dict) -> str:
    return f"{w['id']}: {w['lemma']}（{w['pos']}）{w['meaning']}"


def build_sentences_prompt(
    unit: dict,
    count: int,
    unit_words: list[dict],
    earlier_words: list[dict],
    grammar: list[dict],
    register_rule: str,
    retry: list[dict] | None = None,
    must_use: list[dict] | None = None,
    keep: list[str] | None = None,
) -> str:
    """unit: id, title, scene。*_words: id, lemma, pos, meaning。grammar: form, ja, new（このユニットから使えるか）。

    初めて作るときは retry も keep も渡さない。作り直すときは retry（ko と problems）を渡す。
    まだどの文にも出てこない単語の文を足すときは、retry を渡さずに must_use と keep を渡す。
    must_use は必ず使う単語、keep はほかに残る文（同じ文を作らないように見せる）。
    """
    earlier_text = "\n".join(_word_line(w) for w in earlier_words) or "（なし）"
    grammar_text = "\n".join(f"- {g['form']}: {g['ja']}" for g in grammar)
    new_grammar = [g["form"] for g in grammar if g.get("new")]
    new_grammar_text = f"\nこのユニットから使えるようになった文法: {'、'.join(new_grammar)}（これを使う文を 1 つ以上入れる）\n" if new_grammar else ""
    kept = "\n".join(f"- {ko}" for ko in keep or []) or "（なし）"
    must = "、".join(w["lemma"] for w in must_use or [])
    if retry:
        problems = "\n".join(f"- {r['ko']}\n  問題: {' / '.join(r['problems'])}" for r in retry)
        must_text = f"\n次の単語は、作り直す文のどれかで必ず使う: {must}\n" if must else ""
        task = f"""ユニット {unit['id']}「{unit['title']}」（場面: {unit['scene']}）の例文のうち、次の文には問題がありました。
問題を直して、代わりの文を {count} 文作ってください（同じ文を直してもよいし、別の文にしてもよい）。

{problems}
{must_text}
ほかに次の文があるので、これらと同じ文は作らない:

{kept}"""
    elif keep is not None:
        task = f"""ユニット {unit['id']}「{unit['title']}」（場面: {unit['scene']}）の例文に、まだ出てこない単語があります。
次の単語を使う例文を {count} 文、追加で作ってください。どの単語も 1 文以上で使う: {must}

ほかに次の文があるので、これらと同じ文は作らない:

{kept}"""
    else:
        task = f"""ユニット {unit['id']}「{unit['title']}」（場面: {unit['scene']}）の例文を {count} 文作ってください。
このユニットの単語は、どれも 1 文以上で使ってください。ユニットの場面で実際に交わす会話の文を中心にしてください。"""
    return f"""# 依頼

日本語話者向けの韓国語の教材の例文を作っています。{_learner(unit.get("level", 1))}
学習者が知っているのは、このユニットまでの単語だけです。例文は、聞いて意味を選ぶ・穴埋め・書き取り・日本語から韓国語への作文の練習に使います。

{task}

# 決まり（重要）

- 使える単語は「このユニットの単語」と「前のユニットまでの単語」だけ。一覧にない名詞・動詞・形容詞・副詞・代名詞・数詞などは使わない
  - 人名だけは一覧になくてよい。名前は母音で終わるもの（민수、유나、다나카 など）にする（지은이 のように 이 が付くと別の語と紛れるため）。
    地名・店名・商品名などの名前は使わない
  - 助詞・語尾・이다 は文法なので一覧にない。使える文法は「使える文法」の範囲だけ
  - 品詞が「表現」の語（あいさつなど）は、一覧の形のまま使う（活用させない・語尾を変えない）。表現の中の語尾は「使える文法」になくてよい
- 1 つの文に入れる「このユニットの単語」は 1〜3 語
- 日常会話で実際に言う、自然で短い文にする（2〜6 語節ほど）。その文だけで意味が分かるようにする。同じ文型ばかりにしない
- 1 つの例文は 1〜2 文まで。文と文を「,」でつながない。2 文にするときは「.」で区切る（「처음 뵙겠습니다. 저는 민수예요.」）
- 文体: {register_rule}
- 数は算用数字ではなくハングルで書く。ローマ字や記号（%、~ など）も使わない

# 書き方

- ko: 韓国語の文。分かち書きは標準どおり。文末は「.」か「?」
- ja: 自然な日本語訳。해요체・합니다체の文は「です・ます」で、반말の文はくだけた話し言葉（〜だよ、〜する？）で、한다체の文は「だ・である」で訳す
- register: 文体
- scene: 誰がどこで言うか（日本語、15 字ほどまで。例:「カフェで店員に」）
- tokens: ko を空白で区切った語節を、前から順にすべて並べる。surface は語節の表記（句読点を除く）。
  word_ids はその語節に含まれる単語の id（一覧の id。助詞・語尾・人名には付けない）。単語がない語節は空のリスト
- grammar: この文で使っている文法を、「使える文法」の形で大事なものから 1〜3 個
- cloze: 穴埋めにする語節を 1 つ。このユニットの単語を含む語節を選ぶ。eojeol は tokens の何番目か（0 から数える）、
  answer はその語節の表記、hint_ja はその語節の日本語訳
- variants.ko: 同じ意味・同じ文体で言える、別の自然な言い方（0〜3 個。助詞の省略、語順の入れ替え、同じ意味の別の語尾など）。
  分かち書きだけが違うものは入れない。使える単語と文法の範囲で
- variants.ja: 訳の別の言い方で、正解として受け入れてよいもの（1〜3 個）

# このユニットの単語（id: 単語（品詞）意味）

{chr(10).join(_word_line(w) for w in unit_words)}

# 前のユニットまでの単語

{earlier_text}

# 使える文法（形: 意味）

{grammar_text}
{new_grammar_text}"""


# 文の検算（docs/plan.md 6.3「文の検算」）

def verify_sentences_schema(keys: list[str], grammar_forms: list[str]) -> dict:
    item = _obj(
        {
            "ok": {"type": "boolean"},
            "problems": _strings(),
            "grammar": {"type": "array", "items": {"type": "string", "enum": grammar_forms}},
            "bad_ko_variants": _strings(),
            "bad_ja_variants": _strings(),
        }
    )
    return _keyed_schema("sentences", keys, item)


def build_verify_sentences_prompt(unit: dict, items: list[dict], grammar: list[dict]) -> str:
    """items: key, ko, ja, register, grammar, words（[{lemma, pos, meaning}]）, cloze（answer, hint_ja）, variants。"""
    blocks = []
    for item in items:
        words = "、".join(f"{w['lemma']}（{w['pos']}）＝{w['meaning']}" for w in item["words"]) or "（なし）"
        cloze = item.get("cloze")
        blocks.append(
            f"""## {item['key']}

- ko: {item['ko']}
- ja: {item['ja']}
- register: {item['register']}
- grammar: {'、'.join(item['grammar']) or '（なし）'}
- 単語: {words}
- 穴埋め: {f"answer「{cloze['answer']}」 hint_ja「{cloze['hint_ja']}」" if cloze else "（なし）"}
- variants.ko: {' / '.join(item['variants'].get('ko', [])) or '（なし）'}
- variants.ja: {' / '.join(item['variants'].get('ja', [])) or '（なし）'}"""
        )
    grammar_text = "\n".join(f"- {g['form']}: {g['ja']}" for g in grammar)
    return f"""# 依頼

日本語話者向けの韓国語の教材の例文を検算してください。別の担当が作った例文です。
学習者はこの例文を聞いて・読んで・書いて覚えるので、誤りがあると誤りを覚えてしまいます。
ユニット {unit['id']}「{unit['title']}」（場面: {unit['scene']}）の例文です。

# 確かめること

次のどれかに当てはまれば ok を false にして、problems に何が問題かを日本語で短く書く（ok が true なら problems は空）。

- ko が韓国語として正しく自然か（文法・語の選び方・分かち書き・綴り・句読点）。実際の会話でそう言うか（한다체 の書き言葉の文は、実際にそう書くか）
- ja が ko の意味を過不足なく訳しているか
- register（文体）の表示が ko と合っているか（あいさつなどの決まった表現が別の文体なのはよい）
- ko が「使える文法」にない語尾や文型を使っていないか
  （助詞の省略など、話し言葉で自然な形はよい。品詞が「表現」の語（あいさつなど）の中の語尾は、決まった形なので問わない）
- 「単語」が、ko の中のその語と同じ語か（同じ綴りの別の語を指していないか。차＝お茶 の文で 차＝車 を指している など）。
  日本語の意味の書き方の違い（あげる／くれる、ある／いる など）は問わない
- 穴埋めの hint_ja が answer の意味と合っているか

次のものは ok を false にせず、直すものとして書く。
- grammar: ko で使っている文法を、「使える文法」の形で大事なものから 0〜3 個（例文の grammar の表示が合っていてもいなくても、正しいものを書く）
- variants.ko のうち、ko と意味や文体が違うもの、不自然なもの → bad_ko_variants（そのままの文字列で）
- variants.ja のうち、訳として受け入れられないもの → bad_ja_variants（そのままの文字列で）

sentences のキーは、下の「## 」の後ろのキーをそのまま使う。

# 使える文法

{grammar_text}

# 例文

{chr(10).join(blocks)}
"""


# 許容例（docs/plan.md 5.4・6.3「許容例」）
#
# 採点は、答えが模範解答か許容例に一致すれば AI を呼ばずに正解にする。誤った許容例は誤りを正解として覚えさせるので、
# 作る呼び出しと検算する呼び出しを分ける

VARIANTS_STYLE = 1
VERIFY_VARIANTS_STYLE = 1


def variants_schema(keys: list[str]) -> dict:
    return _keyed_schema("sentences", keys, _obj({"ko": _strings(), "ja": _strings(), "cloze": _strings()}))


def _variant_block(item: dict) -> str:
    cloze = item.get("cloze")
    lines = [
        f"## {item['key']}",
        "",
        f"- ko（模範解答）: {item['ko']}",
        f"- ja: {item['ja']}",
        f"- 文体: {item['register']}",
        f"- 場面: {item['scene']}",
    ]
    if cloze:
        lines += [
            f"- 穴埋め: 空欄つきの文「{cloze['blanked']}」、空欄の意味の手がかり「{cloze['hint_ja']}」、答え「{cloze['answer']}」",
        ]
    else:
        lines.append("- 穴埋め: なし")
    return "\n".join(lines)


def build_variants_prompt(unit: dict, items: list[dict]) -> str:
    """items: key, ko, ja, register, scene, cloze（blanked, hint_ja, answer。なければ None）, variants（今ある ko・ja・cloze）。"""
    blocks = []
    for item in items:
        have = item["variants"]
        blocks.append(
            _variant_block(item)
            + f"\n- 今ある ko の許容例: {' / '.join(have['ko']) or '（なし）'}"
            + f"\n- 今ある ja の許容例: {' / '.join(have['ja']) or '（なし）'}"
            + (f"\n- 今ある穴埋めの許容例: {' / '.join(have['cloze']) or '（なし）'}" if item.get("cloze") else "")
        )
    return f"""# 依頼

日本語話者向けの韓国語の教材で、例文の「許容例」を作っています。{_learner(unit.get("level", 1))}
学習者の答えが模範解答か許容例と一致すると、その場で正解になります。一致しない答えは、別に AI が採点します。
学習者が書きそうな、正しい別の言い方を集めてください。ユニット {unit['id']}「{unit['title']}」（場面: {unit['scene']}）の例文です。
「今ある許容例」は残るので、挙げなくてかまいません（挙げても重複は除きます）。

# 作るもの

## ko: 日本語から韓国語への作文の許容例

学習者は ja と文体と場面を見て、韓国語で書きます。模範解答（ko）と違っても正解にしてよい韓国語の文を挙げてください。

- ja と意味が同じで、文体が同じで、韓国語として正しく自然なもの
- 学習者が書きそうなものから、次のような違いを挙げる
  - 助詞の省略・付け足し（話し言葉で自然な範囲。커피 있어요 と 커피가 있어요）
  - 主語の省略・付け足し（저는 を言う・言わない）
  - 縮約した形と縮約しない形（저는 と 전、이것은 と 이건、무엇 と 뭐）
  - 語順の入れ替え
  - 同じ意味の別の語・別の語尾
  - あいさつ・お礼・おわびなどの決まった表現の、합니다 形と 해요 形（미안합니다 と 미안해요、감사합니다 と 고마워요）。
    文の文体が 해요체 でも、決まった表現はどちらの形でもよい
  - 2 文の例文では、それぞれの文の言い方の組み合わせ
- 0〜8 個。ほかに正しい言い方がなければ空にする
- 入れないもの
  - 意味が変わるもの、文体が違うもの（決まった表現を除く）、不自然なもの
  - 分かち書きだけが違うもの
  - 綴りだけが違うもの（뭐예요 に対する 뭐에요 は綴りの誤り）
  - 数字・ローマ字を使うもの
- 文末は「.」か「?」。分かち書きは標準どおり

## ja: 韓国語から日本語への訳の許容例

ko の訳として正解にしてよい日本語を 0〜5 個（ja と違うもの）。言い回し・語順・「です・ます」の有無の違いなど。

## cloze: 穴埋めの空欄の許容例

学習者は空欄つきの文と ja と空欄の意味の手がかりを見て、空欄の語節を書きます。答えのほかに、空欄に入れて正解にしてよい語節を挙げてください。

- 空欄に入れた文が ja と手がかりの意味に合い、文法的に正しく自然で、文体に合うもの（決まった表現は 합니다 形と 해요 形のどちらでもよい）
- 空白を含まない 1 つの語節。0〜4 個。穴埋めがない例文は空にする
- 綴りだけが違うもの、分かち書きが違うものは入れない

sentences のキーは、下の「## 」の後ろのキーをそのまま使う。

# 例文

{chr(10).join(blocks)}
"""


def verify_variants_schema(keys: list[str]) -> dict:
    bad = _obj({"kind": {"type": "string", "enum": ["ko", "ja", "cloze"]}, "text": {"type": "string"}, "reason": {"type": "string"}})
    return _keyed_schema("sentences", keys, _obj({"bad": {"type": "array", "items": bad}}))


def build_verify_variants_prompt(unit: dict, items: list[dict]) -> str:
    """items: key, ko, ja, register, scene, cloze（blanked, hint_ja, answer。なければ None）, candidates（ko・ja・cloze の候補）。"""
    blocks = []
    for item in items:
        c = item["candidates"]
        parts = [_variant_block(item), _listed("ko の許容例", c["ko"]), _listed("ja の許容例", c["ja"])]
        if item.get("cloze"):
            parts.append(_listed("穴埋めの許容例", c["cloze"]))
        blocks.append("\n".join(parts))
    return f"""# 依頼

日本語話者向けの韓国語の教材の「許容例」を検算してください。別の担当が作ったものです。
学習者の答えが許容例と一致すると、AI の採点を通さずにそのまま正解になります。
誤りが紛れていると、学習者は誤りを正解だと覚えてしまうので、少しでも疑わしいものは受け入れないでください。
ユニット {unit['id']}「{unit['title']}」（場面: {unit['scene']}）の例文です。

# 受け入れる条件

- ko の許容例: ja を、指定の文体で韓国語にした文として正しく自然か
  - 意味が ja と同じか（足りない意味・足した意味がないか）
  - 文体が同じか（あいさつ・お礼・おわびなどの決まった表現の、합니다 形と 해요 形の違いはよい）
  - 文法・語の選び方・綴り・分かち書き・句読点が正しいか
- ja の許容例: ko の訳として、意味が過不足ないか
- 穴埋めの許容例: 空欄に入れた文が正しく自然で、ja と空欄の意味の手がかりに合い、文体に合うか（決まった表現の 합니다 形と 해요 形の違いはよい）

# 書き方

bad に、受け入れないものを 1 つずつ挙げる。text はそのままの文字列、kind は種類（ko / ja / cloze）、reason は理由（日本語で短く）。
すべて受け入れるなら空にする。sentences のキーは、下の「## 」の後ろのキーをそのまま使う。

# 例文

{chr(10).join(blocks)}
"""


def _listed(label: str, values: list[str]) -> str:
    return f"- {label}:" + "".join(f"\n  - {v}" for v in values) if values else f"- {label}: （なし）"

