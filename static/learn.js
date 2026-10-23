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

const pack = languagePack(LANGUAGE);
const stage = document.getElementById("stage");
const kbdArea = document.getElementById("kbd-area");
const keyboard = Keyboard.create(document.getElementById("keyboard"), pack.keymap);

const state = {
  session: null,
  settings: null,
  roundIndex: -1,
  items: [], // 今のラウンドの問題
  index: 0, // 今のラウンドで次に出す問題（単語ラウンド以外）
  game: null, // 単語ラウンドの列（ArrowGame）
  scene: null,
  timers: new Set(),
  // まとめに使う記録（記録の仕組みを入れるまでは画面の中だけ）
  log: { words: [], sentences: [], traces: [] },
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
  const btn = el("button", { type: "button", class: `speak-btn${large ? " large" : ""}`, title: "読み上げる（Space）", "aria-label": "読み上げる" }, "🔊");
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

function hint(...parts) {
  return el("div", { class: "q-hint" }, ...parts.map((p) => el("span", {}, ...p)));
}

function head(...chips) {
  return el("div", { class: "q-head" }, ...chips.filter(Boolean).map((c) => (typeof c === "string" ? el("span", { class: "chip", text: c }) : c)));
}

function updateProgress() {
  const rounds = document.getElementById("rounds");
  rounds.replaceChildren(
    ...state.session.rounds.map((r, i) =>
      el("li", { class: i < state.roundIndex ? "done" : i === state.roundIndex ? "current" : "" }, `${r.label} ${r.count}`),
    ),
  );
  const total = state.session.items.length;
  const before = state.session.rounds.slice(0, Math.max(0, state.roundIndex)).reduce((n, r) => n + r.count, 0);
  const inRound = state.game ? ArrowGame.progress(state.game).done : state.index;
  const done = Math.min(total, before + inRound);
  document.getElementById("progress-fill").style.width = `${total ? (done / total) * 100 : 0}%`;
  document.getElementById("progress-text").textContent = `${done} / ${total}`;
}

// ---- 流れ ----

async function start() {
  const params = new URLSearchParams(location.search);
  state.settings = await api.get("/api/settings");
  keyboard.showLatin(state.settings.keyboard_show_latin);
  Speak.setOnMissing(() => toast("この言語の読み上げの声が見つかりません。OS に韓国語の音声を追加してください", { type: "warn", sticky: true }));
  state.session = await api.post("/api/session/start", { language: LANGUAGE, unit: params.get("unit") || null });
  state.startedAt = Date.now();
  nextRound();
}

function nextRound() {
  state.roundIndex += 1;
  state.game = null;
  state.index = 0;
  const round = state.session.rounds[state.roundIndex];
  if (!round) {
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
        title: head("綴り", el("span", { class: "chip accent", text: item.word.pos })),
        prompt: (box) => {
          box.append(el("div", { class: "ja-big", text: item.word.meaning }), speakBtn(item.tts));
        },
        expected: item.expected,
        body: { type: "word_spell", word_id: item.word.id },
        placeholder: "意味と音を手がかりに、韓国語で打つ",
      });
    case "sentence_intro":
      return sentenceIntroScene(item);
    case "sentence_listen_choose":
      return listenChooseScene(item);
    case "sentence_cloze":
      return clozeScene(item);
    case "sentence_dictation":
      return typingScene(item, {
        title: head("書き取り", el("span", { class: "chip", text: item.sentence.register })),
        prompt: (box) => {
          box.append(speakBtn(item.sentence.ko, { large: true }));
        },
        expected: item.expected,
        body: { type: "sentence_dictation", sentence_id: item.sentence.id },
        placeholder: "聞こえたとおりに打つ",
        reveal: (box) => box.append(el("div", { class: "ja-mid", text: item.sentence.ja })),
      });
    case "sentence_ja_to_ko":
      return typingScene(item, {
        title: head("日本語 → 韓国語", el("span", { class: "chip accent", text: item.sentence.register }), el("span", { class: "chip", text: item.sentence.scene })),
        prompt: (box) => {
          box.append(el("div", { class: "ja-big", text: item.sentence.ja }));
        },
        expected: item.expected,
        body: { type: "sentence_ja_to_ko", sentence_id: item.sentence.id },
        placeholder: `${item.sentence.register}で書く`,
        aiGraded: true,
      });
    case "sentence_compose":
      return typingScene(item, {
        title: head("応用作文", el("span", { class: "chip accent", text: item.required })),
        prompt: (box) => {
          box.append(el("div", { class: "ja-big", text: item.task }), el("div", { class: "ja-mid", text: `例: ${item.sentence.ko}` }));
        },
        expected: item.sentence.ko,
        body: { type: "sentence_compose", sentence_id: item.sentence.id },
        placeholder: "自分のことを書く",
        aiGraded: true,
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

// ---- 場面: ラウンドの始まり ----

function roundIntroScene(round) {
  return {
    render(box) {
      box.append(
        el(
          "div",
          { class: "round-intro q" },
          el("span", { class: "label", text: `ラウンド ${state.roundIndex + 1} / ${state.session.rounds.length}` }),
          el("h2", { text: round.label }),
          el("p", { class: "muted", text: `${round.count} 問 ・ ${ROUND_HINT[round.key] || ""}` }),
          el("button", { type: "button", class: "btn primary big", onClick: () => nextItem() }, "始める ", el("kbd", { text: "⏎" })),
        ),
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
        el(
          "div",
          { class: "q" },
          head("はじめての単語"),
          el(
            "div",
            { class: "intro-card" },
            el("div", { class: "ko-big", lang: "ko", text: w.lemma }),
            el("div", { class: "intro-meaning", text: w.meaning }),
            el("div", { class: "intro-meta" }, el("span", { class: "chip", text: w.pos }), w.hanja ? el("span", { class: "chip accent", text: `漢字: ${w.hanja}` }) : null, el("span", { class: "chip", text: w.origin })),
            btn,
          ),
          hint(["矢印キーで次へ"], [el("kbd", { text: "Space" }), " もう一度聞く"]),
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
    if (correct) {
      correctEl.classList.add("is-correct");
      later(() => finishItem(true, { elapsed, rating }), 420);
      return;
    }
    if (picked) optionEls[dir].classList.add("is-wrong");
    correctEl.classList.add("is-reveal");
    const answerLine = grid.querySelector(".arrow-answer");
    answerLine.replaceChildren(
      el("span", { class: "ko", lang: "ko", text: item.word.lemma }),
      " ＝ ",
      el("strong", { text: item.word.meaning }),
      gaveUp ? el("span", { class: "muted", text: "（わからない）" }) : dir ? "" : el("span", { class: "muted", text: "（時間切れ）" }),
    );
    Speak.speak(item.tts, { lang: pack.tts, rate: state.settings.tts_rate });
    later(() => finishItem(false, { elapsed, rating, gaveUp }), 1300);
  }

  return {
    render(box) {
      const center = el("div", { class: "arrow-center" });
      if (item.prompt.text) center.append(el("div", { class: isKo ? "ja-big" : "ko-big", lang: isKo ? "ja" : "ko", text: item.prompt.text }));
      if (item.prompt.tts) {
        btn = speakBtn(item.prompt.tts, { large: !item.prompt.text });
        center.append(btn);
      }
      const timerBar = el("div", { class: "timer run", style: `--timeout: ${state.settings.timeout_sec}s` });
      center.append(timerBar);
      grid = el("div", { class: "arrow" }, center);
      for (const dir of ArrowGame.DIRECTIONS) {
        const opt = placed[dir];
        const node = el("div", { class: `opt opt-${dir}${isKo ? " ko" : ""}`, lang: isKo ? "ko" : "ja", role: "button", tabindex: "-1", onClick: () => choose(dir) });
        if (opt) node.append(el("span", { class: "dir", text: DIR_GLYPH[dir] }), el("span", { text: opt.label }));
        optionEls[dir] = node;
        grid.append(node);
      }
      grid.append(el("div", { class: "arrow-answer" }));
      const faceLabel = { meaning: "意味", listen: "聞き取り", reverse: "逆引き" }[item.face];
      box.append(el("div", { class: "q" }, head(faceLabel, el("span", { class: "chip", text: item.word.pos })), grid, hint(["↑ → ↓ ← で選ぶ"], [el("kbd", { text: "⏎" }), " わからない"], [el("kbd", { text: "Space" }), " もう一度聞く"])));
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
      line.append(el("span", { class: "token blank", text: "____" }));
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
        el(
          "div",
          { class: "q" },
          head("新しい文", el("span", { class: "chip accent", text: s.register }), el("span", { class: "chip", text: s.scene })),
          el("div", { class: "sentence" }, tokensView(s), el("div", { class: "ja-mid", text: s.ja }), btn),
          el("div", { class: "grammar-list" }, ...s.grammar.map((g) => el("span", { class: "chip", text: g }))),
          hint(["単語を押すとその語だけ読み上げます。下線は新しい単語"], [el("kbd", { text: "⏎" }), " 次へ"], [el("kbd", { text: "Space" }), " もう一度聞く"]),
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
    state.log.sentences.push({ id: item.id, type: item.type, correct, elapsed: (performance.now() - shownAt) / 1000 });
    if (correct) optionEls[correctDir].classList.add("is-correct");
    else {
      if (picked) optionEls[dir].classList.add("is-wrong");
      optionEls[correctDir].classList.add("is-reveal");
    }
    grid.querySelector(".arrow-answer").replaceChildren(el("span", { class: "ko", lang: "ko", text: item.sentence.ko }));
    later(() => finishItem(correct), correct ? 900 : 1800);
  }

  return {
    render(box) {
      btn = speakBtn(item.sentence.ko, { large: true });
      const center = el("div", { class: "arrow-center" }, btn);
      grid = el("div", { class: "arrow" }, center);
      for (const dir of ArrowGame.DIRECTIONS) {
        const opt = placed[dir];
        const node = el("div", { class: `opt opt-${dir}`, role: "button", tabindex: "-1", onClick: () => choose(dir) });
        if (opt) node.append(el("span", { class: "dir", text: DIR_GLYPH[dir] }), el("span", { text: opt.label }));
        optionEls[dir] = node;
        grid.append(node);
      }
      grid.append(el("div", { class: "arrow-answer" }));
      box.append(el("div", { class: "q" }, head("聞いて意味を選ぶ", el("span", { class: "chip", text: item.sentence.register })), grid, hint(["↑ → ↓ ← で選ぶ"], [el("kbd", { text: "⏎" }), " わからない"], [el("kbd", { text: "Space" }), " もう一度聞く"])));
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
  return typingScene(item, {
    title: head("穴埋め", el("span", { class: "chip", text: s.register })),
    prompt: (box) => {
      box.append(
        el("div", { class: "sentence" }, tokensView(s, { blankEojeol: item.cloze.eojeol }), el("div", { class: "blank-hint", text: `____ ＝ ${item.cloze.hint_ja}` }), el("div", { class: "ja-mid", text: s.ja })),
      );
    },
    expected: item.expected,
    body: { type: "sentence_cloze", sentence_id: s.id },
    placeholder: "空欄に入る語を打つ",
    speakText: s.ko,
  });
}

// ---- 場面: 入力して採点（綴り・穴埋め・書き取り・日→韓・応用作文） ----

function typingScene(item, { title, prompt, expected, body, placeholder, aiGraded = false, reveal = null, speakText = null }) {
  let field;
  let resultBox;
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
    } catch (err) {
      waiting = false;
      toast(`採点に失敗しました: ${err.message}`, { type: "error" });
      return;
    }
    waiting = false;
    if (attempts === 1) state.log.sentences.push({ id: item.id, type: item.type, correct: judgement.verdict !== "incorrect", verdict: judgement.verdict });
    renderResult(judgement);
  }

  function renderResult(j) {
    resultBox.replaceChildren();
    const ok = j.verdict === "correct";
    const notes = j.verdict === "correct_with_notes";
    const cls = ok ? "ok" : notes ? "notes" : "ng";
    const titleText = ok ? "正解" : notes ? "正解（注意つき）" : attempts >= 2 ? "不正解 ― 答え" : "不正解 ― 直してみましょう";
    const box = el("div", { class: `result ${cls}` }, el("div", { class: "result-title", text: titleText }));
    if (j.comment_ja && (ok || notes || attempts >= 2)) box.append(el("div", { text: j.comment_ja }));
    for (const issue of j.issues || []) {
      box.append(
        el(
          "div",
          { class: "issue" },
          el("div", {}, el("span", { class: "chip warn", text: issue.tag }), " ", el("span", { class: "span", lang: "ko", text: issue.span })),
          attempts >= 2 || ok || notes ? el("div", { class: "muted", text: issue.note + (issue.suggestion ? ` → ${issue.suggestion}` : "") }) : null,
        ),
      );
    }
    if (!ok && !notes) {
      if (j.diff) box.append(diffView(j.diff, attempts < 2));
      if (attempts >= 2 && j.corrected) box.append(el("div", { class: "corrected", lang: "ko", text: j.corrected }));
    }
    if (ok || notes || attempts >= 2) {
      finished = true;
      field.setEnabled(false);
      if (reveal) reveal(box);
      if (speakText) Speak.speak(speakText, { lang: pack.tts, rate: state.settings.tts_rate });
      box.append(el("div", { class: "q-hint" }, el("span", {}, el("kbd", { text: "⏎" }), " 次へ")));
      if (!ok && !notes && j.source === "placeholder") box.append(el("div", { class: "muted small", text: "AI 採点はまだ作っていません（仮の判定）" }));
    } else {
      box.append(el("div", { class: "q-hint" }, el("span", {}, "直して ", el("kbd", { text: "⏎" }))));
      field.focus();
    }
    resultBox.append(box);
  }

  return {
    keyboard: true,
    render(box) {
      const promptBox = el("div", { class: "sentence" });
      prompt(promptBox);
      const fieldBox = el("div");
      field = TypingField.create(fieldBox, { keymap: pack.keymap, composer: pack.composer, keyboard, onSubmit: submit, placeholder });
      resultBox = el("div");
      box.append(el("div", { class: "q" }, title, promptBox, el("div", { class: "answer-area" }, fieldBox, resultBox), aiGraded ? el("p", { class: "muted small", style: "text-align:center;margin:0", text: "模範解答と一致しないときは AI が判定します（今は仮の判定）" }) : null));
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
}

function diffView(diff, maskMissing) {
  const node = el("div", { class: "diff", lang: "ko" });
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
  let btn;

  function finish() {
    if (done) return;
    done = true;
    const seconds = Math.max(0.1, (performance.now() - startedAt) / 1000);
    const jamoCount = pack.composer.decompose(s.ko).length;
    const perMin = Math.round((jamoCount / seconds) * 60);
    state.log.traces.push({ id: item.id, seconds, perMin });
    statsBox.replaceChildren(el("span", {}, el("strong", { text: `${perMin}` }), " 字母/分"), el("span", {}, el("strong", { text: seconds.toFixed(1) }), " 秒"), el("span", {}, el("kbd", { text: "⏎" }), " 次へ"));
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
        onChange: () => {
          if (!startedAt && field.jamos().length) startedAt = performance.now();
        },
      });
      field.setTarget(s.ko);
      statsBox = el("div", { class: "trace-stats" }, el("span", { class: "muted", text: "薄い字をなぞって打ちます。光っているキーが次のキー" }));
      box.append(el("div", { class: "q" }, head("なぞりタイピング", el("span", { class: "chip", text: s.register })), el("div", { class: "sentence" }, el("div", { class: "ja-mid", text: s.ja }), btn), el("div", { class: "answer-area" }, fieldBox, statsBox)));
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
        el(
          "div",
          { class: "summary q" },
          el("div", { class: "round-intro" }, el("span", { class: "label", text: "今日の学習" }), el("h2", { text: "おつかれさまでした" }), el("p", { class: "muted", text: `${state.session.unit.title} ・ 約 ${minutes} 分` })),
          el(
            "div",
            { class: "summary-grid" },
            tile(`${firstCorrect} / ${words.length}`, "単語 ― 1 回目で正解"),
            tile(`${retries}`, "単語 ― やり直し"),
            tile(`${sentences.filter((s) => s.correct).length} / ${sentences.length}`, "文 ― 正解"),
            tile(avgSpeed === null ? "–" : `${avgSpeed}`, "なぞり ― 字母/分"),
          ),
          el("p", { class: "muted small", style: "text-align:center", text: "記録の仕組みを入れるまでは、この結果は保存されません" }),
          el("div", { class: "row", style: "justify-content:center" }, el("a", { class: "btn primary big", href: "/" }, "ホームへ ", el("kbd", { text: "⏎" })), el("a", { class: "btn big", href: location.href }, "もう一度")),
        ),
      );
    },
    onKey(e) {
      if (e.key === "Enter") location.href = "/";
    },
  };
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
      if (dialog.returnValue === "quit") location.href = "/";
    },
    { once: true },
  );
  dialog.showModal();
}

document.getElementById("btn-quit").addEventListener("click", askQuit);

document.addEventListener("DOMContentLoaded", async () => {
  await checkApiVersion();
  try {
    await start();
  } catch (err) {
    stage.replaceChildren(el("p", { class: "muted", text: `学習を始められませんでした: ${err.message}` }));
    toast(err.message, { type: "error" });
  }
});
