/* 学習の画面。サーバーが組み立てた問題の列（/api/session/start）を、単語 → 文 → 産出 → 仕上げ の順に出す。

   画面は「場面（scene）」の切り替えで動く。場面は { render(), onKey(event), leave() } を持ち、
   キーは document で 1 か所受けて今の場面に渡す。入力欄（TypingField）はキーを自分で受けるので、
   入力欄にフォーカスがあるときは場面には渡さない（Esc だけは通す）。
   単語ラウンドの列の操作（最後尾送り、最初の解答だけを残す）は ArrowGame にある。 */
"use strict";

const DIR_GLYPH = { up: "↑", right: "→", down: "↓", left: "←" };
const ROUND_HINT = {
  words: "矢印キーで意味を選びます。間違えた単語は、あとでもう一度出ます",
  sentences: "文を聞いて、選んで、打ちます",
  output: "日本語を見て、韓国語で書きます",
  finish: "今日の文を、ガイドに沿って打ちます",
};

// 言語の部品（キー配列・組み立て・読み上げの言語）とキーボードは、/api/meta で言語を確かめてから作る（start）
let pack = null;
const stage = document.getElementById("stage");
const kbdArea = document.getElementById("kbd-area");
let keyboard = null;

const state = {
  session: null,
  settings: null,
  roundIndex: -1,
  items: [], // 今のラウンドの問題
  index: 0, // 今のラウンドで次に出す問題（単語ラウンド以外）
  game: null, // 単語ラウンドの列（ArrowGame）
  scene: null,
  timers: new Set(),
  // まとめに使う、この回の結果（単語の解答はそのつどサーバーにも記録する）
  log: { words: [], sentences: [], traces: [] },
  recordFailed: false,
  startedAt: 0,
};

// ---- 場面の切り替えと共通の部品 ----

function show(scene) {
  if (state.scene && state.scene.leave) state.scene.leave();
  for (const t of state.timers) clearTimeout(t);
  state.timers.clear();
  Speak.stop();
  state.scene = scene;
  stage.replaceChildren();
  kbdArea.hidden = !scene.keyboard;
  scene.render(stage);
}

function later(fn, ms) {
  const t = setTimeout(() => {
    state.timers.delete(t);
    fn();
  }, ms);
  state.timers.add(t);
  return t;
}

function speakBtn(text, { large = false, auto = true } = {}) {
  const btn = el("button", { type: "button", class: `speak-btn${large ? " large" : ""}`, title: "読み上げる（Space）", "aria-label": "読み上げる" }, icon("speaker"));
  const play = () => {
    btn.classList.add("playing");
    Speak.speak(text, { lang: pack.tts, rate: state.settings.tts_rate, onEnd: () => btn.classList.remove("playing") });
    later(() => btn.classList.remove("playing"), 4000);
  };
  btn.addEventListener("click", play);
  btn.play = play;
  if (auto) later(play, 150);
  return btn;
}

/** 場面の 3 段（見出し → 主役と操作 → ヒント）。見出しとヒントは空でも高さを取る */
function frame(headEl, body, hintEl) {
  return el("div", { class: "q" }, headEl || el("div", { class: "q-head" }), el("div", { class: "q-body" }, ...body), hintEl || el("div", { class: "q-hint" }));
}

function hint(...parts) {
  return el("div", { class: "q-hint" }, ...parts.map((p) => el("span", {}, ...p)));
}

/** 見出し: 問題の種類と、補足のチップ（品詞・丁寧さ・場面など） */
function head(type, ...chips) {
  return el("div", { class: "q-head" }, el("span", { class: "q-type", text: type }), ...chips.filter(Boolean).map((c) => el("span", { class: "chip", text: c })));
}

/** 答えが決まったら、下のヒントを「次へ」だけにする */
function showNextHint(hintEl) {
  hintEl.replaceChildren(el("span", {}, el("kbd", { text: "⏎" }), " 次へ"));
}

function typingHint({ plain = false } = {}, ...extra) {
  if (plain) return hint([el("kbd", { text: "⏎" }), " 送る"], ...extra, ["日本語入力をオンにして打ちます"]);
  return hint([el("kbd", { text: "⏎" }), " 送る"], [el("kbd", { text: "←" }), el("kbd", { text: "→" }), " カーソル"], ...extra, ["日本語入力はオフのままで打てます"]);
}

function updateProgress() {
  const rounds = state.session.rounds;
  const inRound = state.game ? ArrowGame.progress(state.game).done : state.index;
  document.getElementById("rounds").replaceChildren(
    ...rounds.map((r, i) => {
      const done = i < state.roundIndex ? r.count : i === state.roundIndex ? Math.min(r.count, inRound) : 0;
      return el(
        "li",
        { class: `progress-round${i < state.roundIndex ? " done" : i === state.roundIndex ? " current" : ""}` },
        el("span", { class: "progress-track" }, el("span", { class: "progress-fill", style: `width: ${r.count ? (done / r.count) * 100 : 0}%` })),
        el("span", { class: "progress-label", text: `${r.label} ${r.count}` }),
      );
    }),
  );
  const total = state.session.items.length;
  const before = rounds.slice(0, Math.max(0, state.roundIndex)).reduce((n, r) => n + r.count, 0);
  document.getElementById("progress-text").textContent = `${Math.min(total, before + inRound)} / ${total}`;
}

// ---- 流れ ----

async function start() {
  const params = new URLSearchParams(location.search);
  state.settings = await api.get(`/api/settings/${encodeURIComponent(LANGUAGE)}`);
  keyboard.showLatin(state.settings.keyboard_show_latin);
  Speak.setOnMissing(() => toast("この言語の読み上げの声が見つかりません。OS に韓国語の音声を追加してください", { type: "warn", sticky: true }));
  state.session = await api.post("/api/session/start", { language: LANGUAGE, unit: params.get("unit") || null });
  state.startedAt = Date.now();
  if (state.session.items.length === 0) {
    show(nothingTodayScene());
    return;
  }
  nextRound();
}

function nextRound() {
  state.roundIndex += 1;
  state.game = null;
  state.index = 0;
  const round = state.session.rounds[state.roundIndex];
  if (!round) {
    updateProgress();
    show(summaryScene());
    return;
  }
  state.items = state.session.items.filter((i) => i.round === round.key);
  if (state.items.length === 0) {
    nextRound();
    return;
  }
  if (round.key === "words") state.game = ArrowGame.createQueue(state.items);
  updateProgress();
  show(roundIntroScene(round));
}

function nextItem() {
  updateProgress();
  if (state.game) {
    const item = ArrowGame.current(state.game);
    if (!item) {
      nextRound();
      return;
    }
    show(sceneFor(item));
    return;
  }
  const item = state.items[state.index];
  if (!item) {
    nextRound();
    return;
  }
  show(sceneFor(item));
}

/** 解答を記録する。その日の最初の解答なら、サーバーが FSRS で次に出す日を決める（文は段階も）。テンポを優先して、記録を待たずに進む */
function record(body, path = "/api/review") {
  api.post(path, { language: LANGUAGE, ...body }).catch((err) => {
    if (state.recordFailed) return;
    state.recordFailed = true;
    toast(`解答を記録できませんでした: ${err.message}`, { type: "error", sticky: true });
  });
}

function recordWord(item, { rating, correct, elapsed = null, answer = null }) {
  record({ kind: "word", item_id: item.word.id, face: item.face, practice: item.type, rating, correct, elapsed_sec: elapsed, answer });
}

function recordSentence(item, { rating, correct, elapsed = null, answer = null, detail = null }) {
  record({ kind: "sentence", item_id: item.sentence.id, practice: item.type, rating, correct, elapsed_sec: elapsed, answer, detail });
}

/** 打つ練習の文は、1 回目の判定で記録する（自分で直したあとの正解は評価に使わない）。誤りのタグも残す */
function recordSentenceJudgement(item) {
  return (j, value) => {
    const issues = (j.issues || []).map((i) => ({ tag: i.tag, axis: i.axis, word_id: i.word_id || null }));
    recordSentence(item, { rating: j.rating, correct: j.verdict !== "incorrect", answer: value, detail: { verdict: j.verdict, source: j.source, issues } });
  };
}

function finishItem(correct, detail) {
  if (state.game) ArrowGame.answer(state.game, correct, detail);
  else state.index += 1;
  nextItem();
}

function sceneFor(item) {
  switch (item.type) {
    case "word_intro":
      return wordIntroScene(item);
    case "word_meaning":
    case "word_listen":
    case "word_reverse":
      return arrowScene(item);
    case "word_spell":
      return typingScene(item, {
        title: head("綴り", item.word.pos),
        prompt: (box) => {
          box.append(el("div", { class: "ja-lg", text: item.word.meaning }), speakBtn(item.tts));
        },
        expected: item.expected,
        body: { type: "word_spell", word_id: item.word.id },
        placeholder: "意味と音を手がかりに、韓国語で打つ",
        onFirstJudgement: (j, value) => recordWord(item, { rating: j.rating, correct: j.verdict !== "incorrect", answer: value }),
      });
    case "sentence_intro":
      return sentenceIntroScene(item);
    case "sentence_listen_choose":
      return listenChooseScene(item);
    case "sentence_cloze":
      return clozeScene(item);
    case "sentence_dictation":
      return typingScene(item, {
        title: head("書き取り", item.sentence.register),
        prompt: (box) => {
          box.append(speakBtn(item.sentence.ko, { large: true }));
        },
        expected: item.expected,
        body: { type: "sentence_dictation", sentence_id: item.sentence.id },
        placeholder: "聞こえたとおりに打つ",
        reveal: (box) => box.append(el("div", { class: "muted", text: item.sentence.ja })),
        onFirstJudgement: recordSentenceJudgement(item),
      });
    case "sentence_ja_to_ko":
      return typingScene(item, {
        title: head("日本語 → 韓国語", item.sentence.register, item.sentence.scene),
        prompt: (box) => {
          box.append(el("div", { class: "ja-lg", text: item.sentence.ja }));
        },
        expected: item.expected,
        body: { type: "sentence_ja_to_ko", sentence_id: item.sentence.id },
        placeholder: `${item.sentence.register}で書く`,
        aiHint: true,
        onFirstJudgement: recordSentenceJudgement(item),
      });
    case "sentence_ko_to_ja":
      return typingScene(item, {
        title: head("韓国語 → 日本語", item.sentence.register, item.sentence.scene),
        prompt: (box) => {
          box.append(el("div", { class: "ko-lg", lang: "ko", text: item.sentence.ko }), speakBtn(item.sentence.ko));
        },
        expected: item.expected,
        body: { type: "sentence_ko_to_ja", sentence_id: item.sentence.id },
        placeholder: "日本語に訳す",
        plain: true,
        aiHint: true,
        onFirstJudgement: recordSentenceJudgement(item),
      });
    case "sentence_compose":
      return typingScene(item, {
        title: head("応用作文", item.required),
        prompt: (box) => {
          box.append(el("div", { class: "ja-lg", text: item.task }), el("div", { class: "ja-md", lang: "ko", text: `例: ${item.sentence.ko}` }));
        },
        expected: item.sentence.ko,
        body: { type: "sentence_compose", sentence_id: item.sentence.id },
        placeholder: "自分のことを書く",
        aiHint: true,
        onFirstJudgement: recordSentenceJudgement(item),
      });
    case "sentence_trace":
      return traceScene(item);
    default:
      return {
        render(box) {
          box.append(el("p", { class: "muted", text: `未対応の問題です: ${item.type}` }));
        },
        onKey(e) {
          if (e.key === "Enter") finishItem(null);
        },
      };
  }
}

// ---- 場面: 今日の分がない ----

function nothingTodayScene() {
  return {
    render(box) {
      box.append(
        frame(null, [
          el(
            "div",
            { class: "round-intro" },
            el("h2", { text: "今日の分は終わっています" }),
            el("p", { text: "期限が来た復習も、今日の新出の枠も残っていません。ホームからユニットを選ぶと、そのユニットを練習できます" }),
            el("a", { class: "btn primary big", href: languageUrl() }, "ホームへ", el("kbd", { text: "⏎" })),
          ),
        ]),
      );
    },
    onKey(e) {
      if (e.key === "Enter") location.href = languageUrl();
    },
  };
}

// ---- 場面: ラウンドの始まり ----

function roundIntroScene(round) {
  return {
    render(box) {
      box.append(
        frame(null, [
          el(
            "div",
            { class: "round-intro" },
            el("span", { class: "label", text: `ラウンド ${state.roundIndex + 1} / ${state.session.rounds.length}` }),
            el("h2", { text: round.label }),
            el("p", { text: `${round.count} 問 ・ ${ROUND_HINT[round.key] || ""}` }),
            el("button", { type: "button", class: "btn primary big", onClick: () => nextItem() }, "始める", el("kbd", { text: "⏎" })),
          ),
        ]),
      );
    },
    onKey(e) {
      if (["Enter", " ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault();
        nextItem();
      }
    },
  };
}

// ---- 場面: 初見カード ----

function wordIntroScene(item) {
  const w = item.word;
  let btn;
  return {
    render(box) {
      btn = speakBtn(item.tts);
      box.append(
        frame(
          head("はじめての単語", w.pos),
          [
            el(
              "div",
              { class: "intro" },
              el("div", { class: "ko-xl", lang: "ko", text: w.lemma }),
              el("div", { class: "intro-meaning", text: w.meaning }),
              el("div", { class: "chips" }, w.hanja ? el("span", { class: "chip", text: `漢字 ${w.hanja}` }) : null, el("span", { class: "chip", text: w.origin })),
              btn,
            ),
          ],
          hint([el("kbd", { text: "⏎" }), " か矢印キーで次へ"], [el("kbd", { text: "Space" }), " もう一度聞く"]),
        ),
      );
    },
    onKey(e) {
      if (e.key.startsWith("Arrow") || e.key === "Enter") {
        e.preventDefault();
        finishItem(null);
      } else if (e.key === " ") {
        e.preventDefault();
        btn.play();
      }
    },
  };
}

// ---- 場面: 矢印ゲーム ----

/** 真ん中の問題と、上右下左の選択肢。optionEls に方向ごとの要素を入れる */
function arrowGrid(center, placed, optionEls, { ko = false, long = false, onChoose }) {
  const grid = el("div", { class: `arrow${long ? " long" : ""}` }, center);
  for (const dir of ArrowGame.DIRECTIONS) {
    const opt = placed[dir];
    const node = el("div", { class: `opt opt-${dir}${ko ? " ko" : ""}`, lang: ko ? "ko" : "ja", role: "button", tabindex: "-1", onClick: () => onChoose(dir) });
    if (opt) node.append(el("span", { class: "dir", text: DIR_GLYPH[dir] }), el("span", { class: "opt-label", text: opt.label }));
    optionEls[dir] = node;
    grid.append(node);
  }
  return grid;
}

function arrowScene(item) {
  const placed = ArrowGame.placeOptions(item.options);
  const optionEls = {};
  let answered = false;
  let shownAt = 0;
  let btn;
  let grid;
  let timer;
  const isKo = item.face === "reverse";

  function choose(dir, { gaveUp = false } = {}) {
    if (answered) return;
    answered = true;
    clearTimeout(timer);
    grid.classList.add("answered");
    const elapsed = (performance.now() - shownAt) / 1000;
    const picked = dir ? placed[dir] : null;
    const correct = Boolean(picked && picked.word_id === item.answer_id);
    const correctDir = Object.keys(placed).find((d) => placed[d] && placed[d].word_id === item.answer_id);
    const correctEl = optionEls[correctDir];
    const rating = ArrowGame.rate(correct, elapsed, { fast: state.settings.fast_sec, slow: state.settings.slow_sec });
    state.log.words.push({ id: item.id, word: item.word, face: item.face, correct, elapsed, gaveUp, rating, picked: picked && picked.word_id, first: !state.game.first.has(item.id) });
    recordWord(item, { rating, correct, elapsed, answer: picked ? picked.word_id : null });
    if (correct) {
      correctEl.classList.add("is-correct");
      later(() => finishItem(true, { elapsed, rating }), 420);
      return;
    }
    if (picked) optionEls[dir].classList.add("is-wrong");
    correctEl.classList.add("is-reveal");
    const why = gaveUp ? "わからない" : dir ? null : "時間切れ";
    answerLine.replaceChildren(
      ...[
        el("span", { class: "ko", lang: "ko", text: item.word.lemma }),
        el("span", { class: "eq", text: "＝" }),
        el("span", { text: item.word.meaning }),
        why ? el("span", { class: "why", text: why }) : null,
      ].filter(Boolean),
    );
    Speak.speak(item.tts, { lang: pack.tts, rate: state.settings.tts_rate });
    later(() => finishItem(false, { elapsed, rating, gaveUp }), 1300);
  }

  let answerLine;
  return {
    render(box) {
      const center = el("div", { class: "arrow-center" });
      if (item.prompt.text) center.append(el("div", { class: isKo ? "ja-lg" : "ko-lg", lang: isKo ? "ja" : "ko", text: item.prompt.text }));
      if (item.prompt.tts) {
        btn = speakBtn(item.prompt.tts, { large: !item.prompt.text });
        center.append(btn);
      }
      center.append(el("div", { class: "timer run", style: `--timeout: ${state.settings.timeout_sec}s` }));
      grid = arrowGrid(center, placed, optionEls, { ko: isKo, onChoose: choose });
      answerLine = el("div", { class: "answer-line" });
      const faceLabel = { meaning: "意味", listen: "聞き取り", reverse: "逆引き" }[item.face];
      box.append(frame(head(faceLabel, item.word.pos), [grid, answerLine], hint(["↑ → ↓ ← で選ぶ"], [el("kbd", { text: "⏎" }), " わからない"], [el("kbd", { text: "Space" }), " もう一度聞く"])));
      shownAt = performance.now();
      timer = later(() => choose(null), state.settings.timeout_sec * 1000);
    },
    onKey(e) {
      const dir = ArrowGame.KEY_TO_DIRECTION[e.key];
      if (dir) {
        e.preventDefault();
        choose(dir);
      } else if (e.key === "Enter") {
        e.preventDefault();
        choose(null, { gaveUp: true });
      } else if (e.key === " ") {
        e.preventDefault();
        if (btn) btn.play();
      }
    },
  };
}

// ---- 場面: 文の導入 ----

function tokensView(sentence, { blankEojeol = null, clickable = true } = {}) {
  const line = el("div", { class: "tokens", lang: "ko" });
  let pop = null;
  for (const token of sentence.tokens) {
    if (blankEojeol !== null && token.eojeol === blankEojeol) {
      line.append(el("span", { class: "token blank", "aria-label": "空欄" }));
      continue;
    }
    const node = el("span", { class: `token${token.is_new ? " new" : ""}`, text: token.surface });
    const words = token.words || [];
    if (clickable) {
      node.addEventListener("click", (e) => {
        e.stopPropagation();
        Speak.speak(token.surface, { lang: pack.tts, rate: state.settings.tts_rate });
        if (pop) pop.remove();
        if (!words.length) return;
        pop = el("span", { class: "token-pop", text: words.map((w) => `${w.lemma}: ${w.meaning}`).join(" / ") });
        node.append(pop);
        later(() => pop && pop.remove(), 2500);
      });
    }
    line.append(node);
  }
  return line;
}

function sentenceIntroScene(item) {
  const s = item.sentence;
  let btn;
  return {
    render(box) {
      btn = speakBtn(s.ko);
      box.append(
        frame(
          head("新しい文", s.register, s.scene),
          [el("div", { class: "sentence" }, tokensView(s), el("div", { class: "ja-md", text: s.ja })), el("div", { class: "chips" }, ...s.grammar.map((g) => el("span", { class: "chip", text: g }))), btn, explainBlock(s)],
          hint([el("kbd", { text: "⏎" }), " 次へ"], [el("kbd", { text: "Space" }), " もう一度聞く"], ["単語を押すとその語だけ読み上げます。下線は新しい単語"]),
        ),
      );
    },
    onKey(e) {
      if (e.key === "Enter" || e.key.startsWith("Arrow")) {
        e.preventDefault();
        finishItem(null);
      } else if (e.key === " ") {
        e.preventDefault();
        btn.play();
      }
    },
  };
}

/** 「解説」のボタンと、押したら出す解説。AI が作るのは初めて押したときだけで、2 回目からは保存したものを返す */
function explainBlock(sentence) {
  const panel = el("div", { class: "explain", hidden: true });
  const btn = el("button", { type: "button", class: "btn ghost explain-btn" }, "解説");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    panel.hidden = false;
    panel.replaceChildren(el("p", { class: "muted small", text: "AI が解説を作っています…（初めての文は 1 分ほどかかります）" }));
    try {
      let res = await api.post(`/api/explain/${encodeURIComponent(sentence.id)}`, { language: LANGUAGE });
      if (res.job) res = { explanation: await api.waitJob(res.job) };
      if (!panel.isConnected) return;
      renderExplanation(panel, res.explanation);
      btn.hidden = true;
    } catch (err) {
      btn.disabled = false;
      panel.hidden = true;
      toast(`解説を作れませんでした: ${err.message}`, { type: "error" });
    }
  });
  return el("div", { class: "explain-area" }, btn, panel);
}

function renderExplanation(panel, x) {
  const section = (label, ...children) => el("div", { class: "explain-section" }, el("span", { class: "explain-label", text: label }), ...children);
  panel.replaceChildren(
    ...[
      x.summary ? el("p", { text: x.summary }) : null,
      x.parts.length ? section("語節", el("dl", { class: "explain-parts" }, ...x.parts.flatMap((p) => [el("dt", { lang: "ko", text: p.surface }), el("dd", { text: p.breakdown })]))) : null,
      x.grammar.length ? section("文法", ...x.grammar.map((g) => el("div", {}, el("span", { class: "chip", lang: "ko", text: g.form }), " ", g.explanation))) : null,
      x.register ? section("文体", el("div", { text: x.register })) : null,
      x.pronunciation ? section("発音", el("div", { lang: "ko", text: x.pronunciation })) : null,
      x.tips.length ? section("ポイント", el("ul", {}, ...x.tips.map((t) => el("li", { text: t })))) : null,
    ].filter(Boolean),
  );
}

// ---- 場面: 聞いて意味を選ぶ ----

function listenChooseScene(item) {
  const placed = ArrowGame.placeOptions(item.options);
  const optionEls = {};
  let answered = false;
  let btn;
  let grid;
  let shownAt = 0;

  function choose(dir) {
    if (answered) return;
    answered = true;
    grid.classList.add("answered");
    const picked = dir ? placed[dir] : null;
    const correct = Boolean(picked && picked.sentence_id === item.answer_id);
    const correctDir = Object.keys(placed).find((d) => placed[d] && placed[d].sentence_id === item.answer_id);
    const elapsed = (performance.now() - shownAt) / 1000;
    state.log.sentences.push({ id: item.id, type: item.type, correct, elapsed });
    recordSentence(item, { rating: correct ? "good" : "again", correct, elapsed, answer: picked ? picked.sentence_id : null });
    if (correct) optionEls[correctDir].classList.add("is-correct");
    else {
      if (picked) optionEls[dir].classList.add("is-wrong");
      optionEls[correctDir].classList.add("is-reveal");
    }
    answerLine.replaceChildren(el("span", { class: "ko", lang: "ko", text: item.sentence.ko }));
    later(() => finishItem(correct), correct ? 900 : 1800);
  }

  let answerLine;
  return {
    render(box) {
      btn = speakBtn(item.sentence.ko, { large: true });
      grid = arrowGrid(el("div", { class: "arrow-center" }, btn), placed, optionEls, { long: true, onChoose: choose });
      answerLine = el("div", { class: "answer-line" });
      box.append(frame(head("聞いて意味を選ぶ", item.sentence.register), [grid, answerLine], hint(["↑ → ↓ ← で選ぶ"], [el("kbd", { text: "⏎" }), " わからない"], [el("kbd", { text: "Space" }), " もう一度聞く"])));
      shownAt = performance.now();
    },
    onKey(e) {
      const dir = ArrowGame.KEY_TO_DIRECTION[e.key];
      if (dir) {
        e.preventDefault();
        choose(dir);
      } else if (e.key === "Enter") {
        e.preventDefault();
        choose(null);
      } else if (e.key === " ") {
        e.preventDefault();
        btn.play();
      }
    },
  };
}

// ---- 場面: 穴埋め ----

function clozeScene(item) {
  const s = item.sentence;
  let line;
  return typingScene(item, {
    title: head("穴埋め", s.register),
    prompt: (box) => {
      line = tokensView(s, { blankEojeol: item.cloze.eojeol });
      box.append(el("div", { class: "sentence" }, line, el("div", { class: "ja-md", text: s.ja }), el("div", { class: "blank-hint", text: `空欄 ＝ ${item.cloze.hint_ja}` })));
    },
    expected: item.expected,
    body: { type: "sentence_cloze", sentence_id: s.id },
    placeholder: "空欄に入る語を打つ",
    speakText: s.ko,
    onFirstJudgement: recordSentenceJudgement(item),
    reveal: () => {
      const blank = line.querySelector(".token.blank");
      blank.textContent = item.expected;
      blank.removeAttribute("aria-label");
      blank.classList.add("filled");
    },
  });
}

// ---- 場面: 入力して採点（綴り・穴埋め・書き取り・日→韓・韓→日・応用作文） ----

/** 日本語を打つ入力欄（韓→日訳）。TypingField と同じ形（focus・setEnabled）で使う。
   Enter は IME の変換の確定にも使うので、変換中の Enter では送らない */
function plainField(container, { onSubmit, placeholder }) {
  const input = el("input", { type: "text", class: "plain-field", lang: "ja", placeholder, autocomplete: "off", spellcheck: "false" });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    onSubmit(input.value);
  });
  container.append(input);
  return {
    focus: () => input.focus(),
    setEnabled: (on) => {
      input.disabled = !on;
    },
  };
}

function typingScene(item, { title, prompt, expected, body, placeholder, plain = false, aiHint = false, reveal = null, speakText = null, onFirstJudgement = null }) {
  const answerLang = plain ? "ja" : "ko";
  let field;
  let resultBox;
  let hintEl;
  let attempts = 0;
  let finished = false;
  let waiting = false;

  async function submit(value) {
    if (finished) {
      finishItem(null);
      return;
    }
    if (waiting || !value.trim()) return;
    waiting = true;
    attempts += 1;
    let judgement;
    try {
      judgement = await api.post("/api/answer", { language: LANGUAGE, answer: value, ...body });
      if (judgement.job) {
        if (judgement.job.status === "running") resultBox.replaceChildren(el("div", { class: "result pending" }, el("span", { class: "result-title", text: "AI が採点しています…" })));
        judgement = await api.waitJob(judgement.job);
      }
    } catch (err) {
      waiting = false;
      attempts -= 1;
      if (state.scene !== scene) return;
      resultBox.replaceChildren();
      toast(`採点に失敗しました: ${err.message}`, { type: "error" });
      return;
    }
    waiting = false;
    // AI の採点を待つ間に中断や次の問題へ進んでいたら、結果は出さない
    if (state.scene !== scene) return;
    if (attempts === 1) {
      state.log.sentences.push({ id: item.id, type: item.type, correct: judgement.verdict !== "incorrect", verdict: judgement.verdict });
      if (onFirstJudgement) onFirstJudgement(judgement, value);
    }
    renderResult(judgement);
  }

  function renderResult(j) {
    const ok = j.verdict === "correct";
    const notes = j.verdict === "correct_with_notes";
    const done = ok || notes || attempts >= 2;
    const cls = ok ? "ok" : notes ? "notes" : "ng";
    const titleText = ok ? "正解" : notes ? "正解（注意つき）" : done ? "不正解" : "不正解 ― 直してみましょう";
    const next = done ? el("span", { class: "result-next" }, el("kbd", { text: "⏎" }), "次へ") : el("span", { class: "result-next" }, "直して", el("kbd", { text: "⏎" }));
    const box = el("div", { class: `result ${cls}` }, el("div", { class: "result-head" }, el("span", { class: "result-title", text: titleText }), next));
    if (j.comment_ja && done) box.append(el("div", { class: "small", text: j.comment_ja }));
    for (const issue of j.issues || []) {
      box.append(
        el(
          "div",
          { class: "issue" },
          el("div", {}, el("span", { class: "chip warn", text: issue.tag }), " ", el("span", { class: "span", lang: answerLang, text: issue.span })),
          done ? el("div", { class: "muted", text: issue.note + (issue.suggestion ? ` → ${issue.suggestion}` : "") }) : null,
        ),
      );
    }
    if (!ok && j.diff) box.append(diffView(j.diff, !done, answerLang));
    if (done) {
      // AI の corrected は模範解答ではなく、学習者の答えを最小限直したもの。違えば両方を見せる
      if (!ok && j.corrected && j.corrected !== expected) box.append(modelLine("直した答え", j.corrected, answerLang));
      if (expected) box.append(modelLine(plain ? "模範訳" : "模範解答", expected, answerLang));
      if (reveal) reveal(box);
      if (item.sentence) box.append(explainBlock(item.sentence));
      finished = true;
      field.setEnabled(false);
      // 答えが決まったらキーボードは要らないので畳む。打ち直しの間は配列を見たいので出したまま
      kbdArea.hidden = true;
      showNextHint(hintEl);
      if (speakText) Speak.speak(speakText, { lang: pack.tts, rate: state.settings.tts_rate });
    } else {
      field.focus();
    }
    resultBox.replaceChildren(box);
    // 画面の低いウィンドウでは、キーボードを出したままだと結果が下にはみ出すことがある
    box.scrollIntoView({ block: "nearest" });
  }

  const scene = {
    keyboard: !plain,
    render(box) {
      const promptBox = el("div", { class: "sentence" });
      prompt(promptBox);
      const fieldBox = el("div");
      field = plain ? plainField(fieldBox, { onSubmit: submit, placeholder }) : TypingField.create(fieldBox, { keymap: pack.keymap, composer: pack.composer, keyboard, onSubmit: submit, placeholder });
      resultBox = el("div");
      hintEl = typingHint({ plain }, ...(aiHint ? [["違う書き方は AI が判定"]] : []));
      const q = frame(title, [promptBox, el("div", { class: "answer-area" }, fieldBox, resultBox)], hintEl);
      q.classList.add("typing");
      box.append(q);
      field.focus();
    },
    onKey(e) {
      if (e.key === "Enter" && finished) {
        e.preventDefault();
        finishItem(null);
      } else if (e.key === " " && document.activeElement.tagName !== "INPUT" && speakText) {
        Speak.speak(speakText, { lang: pack.tts, rate: state.settings.tts_rate });
      }
    },
    leave() {
      keyboard.guide(null);
    },
  };
  return scene;
}

function modelLine(label, text, lang = "ko") {
  return el("div", { class: "model" }, el("span", { class: "model-label", text: label }), el("span", { class: "model-text", lang, text }));
}

function diffView(diff, maskMissing, lang = "ko") {
  const node = el("div", { class: "diff", lang });
  for (const part of diff) {
    if (part.kind === "missing" && maskMissing) node.append(el("span", { class: "mask", text: "＿".repeat(part.text.length) }));
    else node.append(el("span", { class: part.kind, text: part.text }));
  }
  return node;
}

// ---- 場面: なぞりタイピング ----

function traceScene(item) {
  const s = item.sentence;
  let field;
  let startedAt = 0;
  let done = false;
  let statsBox;
  let hintEl;
  let btn;

  function finish() {
    if (done) return;
    done = true;
    const seconds = Math.max(0.1, (performance.now() - startedAt) / 1000);
    const jamoCount = pack.composer.decompose(s.ko).length;
    const perMin = Math.round((jamoCount / seconds) * 60);
    state.log.traces.push({ id: item.id, seconds, perMin });
    record({ sentence_id: s.id, seconds, units: jamoCount }, "/api/trace");
    statsBox.replaceChildren(el("span", {}, el("strong", { text: `${perMin}` }), "字母/分"), el("span", {}, el("strong", { text: seconds.toFixed(1) }), "秒"), el("span", { class: "result-next" }, el("kbd", { text: "⏎" }), "次へ"));
    showNextHint(hintEl);
    field.setEnabled(false);
    keyboard.guide(null);
  }

  return {
    keyboard: true,
    render(box) {
      btn = speakBtn(s.ko);
      const fieldBox = el("div");
      field = TypingField.create(fieldBox, {
        keymap: pack.keymap,
        composer: pack.composer,
        keyboard,
        onSubmit: () => {
          if (done) finishItem(null);
          else if (field.isComplete()) finish();
        },
        // TypingField.create の中でも呼ばれる（field に代入される前）ので、field ではなく渡された値を見る
        onChange: (value) => {
          if (!startedAt && value.length) startedAt = performance.now();
        },
      });
      field.setTarget(s.ko);
      statsBox = el("div", { class: "trace-stats" });
      hintEl = hint(["薄い字をなぞって打ちます。光っているキーが次のキー"], [el("kbd", { text: "⏎" }), " 打ち終わったら送る"]);
      const q = frame(head("なぞりタイピング", s.register), [el("div", { class: "sentence" }, el("div", { class: "ja-lg", text: s.ja }), btn), el("div", { class: "answer-area" }, fieldBox, statsBox)], hintEl);
      q.classList.add("typing");
      box.append(q);
      field.focus();
    },
    onKey(e) {
      if (e.key === "Enter" && done) {
        e.preventDefault();
        finishItem(null);
      }
    },
    leave() {
      keyboard.guide(null);
    },
  };
}

// ---- 場面: まとめ ----

function summaryScene() {
  return {
    render(box) {
      const words = state.log.words.filter((w) => w.first);
      const firstCorrect = words.filter((w) => w.correct).length;
      const retries = state.game ? state.game.retries : state.log.words.length - words.length;
      const sentences = state.log.sentences;
      const traces = state.log.traces;
      const minutes = Math.round((Date.now() - state.startedAt) / 60000);
      const avgSpeed = traces.length ? Math.round(traces.reduce((n, t) => n + t.perMin, 0) / traces.length) : null;
      box.append(
        frame(
          null,
          [
            el("div", { class: "round-intro" }, el("span", { class: "label", text: "今日の学習" }), el("h2", { text: "おつかれさまでした" }), el("p", { text: `${sessionTitle()} ・ 約 ${minutes} 分` })),
            el(
              "div",
              { class: "summary-grid" },
              tile(`${firstCorrect} / ${words.length}`, "単語 ― 1 回目で正解"),
              tile(`${retries}`, "単語 ― やり直し"),
              tile(`${sentences.filter((s) => s.correct).length} / ${sentences.length}`, "文 ― 正解"),
              tile(avgSpeed === null ? "–" : `${avgSpeed}`, "なぞり ― 字母/分"),
            ),
            el("div", { class: "row" }, el("a", { class: "btn primary big", href: languageUrl() }, "ホームへ", el("kbd", { text: "⏎" })), el("a", { class: "btn big", href: location.href }, "もう一度")),
          ],
          el("div", { class: "q-hint" }, el("span", { class: "note", text: state.recordFailed ? "解答の一部を記録できませんでした" : "単語と文の結果は記録しました" })),
        ),
      );
    },
    onKey(e) {
      if (e.key === "Enter") location.href = languageUrl();
    },
  };
}

function sessionTitle() {
  const s = state.session;
  if (s.mode === "unit") return s.unit ? `${s.unit.title} の練習` : "ユニットの練習";
  return `今日の学習 ・ 新出 ${s.new_word_count} 語・${s.new_sentence_count} 文 ・ 復習 ${s.review_count}`;
}

function tile(value, label) {
  return el("div", { class: "summary-tile" }, el("strong", { text: value }), el("span", { text: label }));
}

// ---- キーと中断 ----

document.addEventListener("keydown", (e) => {
  const quitDialog = document.getElementById("quit-dialog");
  if (quitDialog.open) return;
  if (e.key === "Escape") {
    e.preventDefault();
    askQuit();
    return;
  }
  const inInput = e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA";
  if (inInput && e.key !== "Enter") return;
  if (inInput && e.key === "Enter" && !(state.scene && state.scene.keyboard)) return;
  if (inInput && e.key === "Enter") return; // 入力欄の Enter は入力欄が受ける（送る）
  if (state.scene && state.scene.onKey) state.scene.onKey(e);
});

function askQuit() {
  const dialog = document.getElementById("quit-dialog");
  dialog.returnValue = "";
  dialog.addEventListener(
    "close",
    () => {
      if (dialog.returnValue === "quit") location.href = languageUrl();
    },
    { once: true },
  );
  dialog.showModal();
}

document.getElementById("btn-quit").addEventListener("click", askQuit);

document.addEventListener("DOMContentLoaded", async () => {
  const meta = await loadMeta();
  try {
    if (!meta || !meta.current) throw new Error("言語の情報を読めませんでした");
    pack = { ...languagePack(LANGUAGE), tts: meta.current.tts_lang };
    keyboard = Keyboard.create(document.getElementById("keyboard"), pack.keymap);
    await start();
  } catch (err) {
    stage.replaceChildren(el("p", { class: "muted", text: `学習を始められませんでした: ${err.message}` }));
    toast(err.message, { type: "error" });
  }
});
