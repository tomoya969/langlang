"use strict";

const STATE_LABELS = { new: "未学習", learning: "学習中", mastered: "定着", weak: "苦手" };
const FACES = [
  ["meaning", "意味"],
  ["listen", "聞き取り"],
  ["reverse", "逆引き"],
  ["spell", "綴り"],
  ["context", "文脈"],
];

let allWords = [];
let units = [];
let selected = null;
// 面の安定度の線を、定着とみなす安定度で満たす
let masteredDays = 21;

function filters() {
  return {
    q: document.getElementById("f-q").value.trim().toLowerCase(),
    level: document.getElementById("f-level").value,
    unit: document.getElementById("f-unit").value,
    state: document.getElementById("f-state").value,
  };
}

function renderList() {
  const f = filters();
  const rows = allWords.filter((w) => {
    if (f.level && String(w.level) !== f.level) return false;
    if (f.unit && w.unit !== f.unit) return false;
    if (f.state === "weak" ? !w.weak : f.state && w.state !== f.state) return false;
    if (f.q && !w.lemma.toLowerCase().includes(f.q) && !w.meaning.toLowerCase().includes(f.q)) return false;
    return true;
  });
  document.getElementById("f-count").textContent = `${rows.length} 語`;
  document.getElementById("btn-weak-practice").hidden = !(f.state === "weak" && rows.length);
  // 選んでいた単語が絞り込みで一覧から消えたら、詳細も空に戻す（一覧にない単語の詳細が残らないように）
  if (selected && !rows.some((w) => w.id === selected)) {
    selected = null;
    document.getElementById("detail").replaceChildren(el("p", { class: "detail-empty", text: "単語を選ぶと、ここに詳細が出ます" }));
  }
  const list = document.getElementById("word-list");
  list.replaceChildren();
  if (!rows.length) {
    list.append(el("p", { class: "muted small", text: "当てはまる単語がありません" }));
    return;
  }
  let lastUnit = null;
  for (const w of rows) {
    if (w.unit !== lastUnit) {
      const unit = units.find((u) => u.id === w.unit);
      list.append(el("div", { class: "unit-head" }, el("strong", { text: unit ? unit.title : w.unit }), el("span", { text: w.unit })));
      lastUnit = w.unit;
    }
    list.append(
      el(
        "button",
        { type: "button", class: "word-row", "aria-current": selected === w.id ? "true" : null, onClick: () => select(w.id) },
        el("span", { class: "word-lemma", lang: "ko", text: w.lemma }),
        el("span", { class: "word-meaning", text: w.meaning }),
        el("span", { class: "word-pos", text: w.pos }),
        el("span", { class: "word-chips" }, w.weak ? el("span", { class: "chip state-weak", text: STATE_LABELS.weak }) : null, el("span", { class: `chip state-${w.state}`, text: STATE_LABELS[w.state] || w.state })),
      ),
    );
  }
}

async function select(id) {
  selected = id;
  renderList();
  const detail = document.getElementById("detail");
  detail.replaceChildren(el("p", { class: "detail-empty", text: "読み込んでいます…" }));
  let w;
  try {
    w = await api.get(`/api/words/${encodeURIComponent(id)}?language=${encodeURIComponent(LANGUAGE)}`);
  } catch (err) {
    detail.replaceChildren(el("p", { class: "detail-empty", text: `読み込みに失敗しました: ${err.message}` }));
    return;
  }
  // 読み込みの間に別の単語を選んだか、絞り込みで外れた
  if (selected !== id) return;
  const speak = el("button", { type: "button", class: "speak-btn", title: "読み上げる", "aria-label": "読み上げる", onClick: () => Speak.speak(w.tts_text, { lang: ttsLang }) }, icon("speaker"));
  const wordChips = (words) => el("div", { class: "row" }, ...words.map((c) => el("button", { type: "button", class: "chip", lang: "ko", text: `${c.lemma} ${c.meaning}`, onClick: () => select(c.id) })));
  // replaceChildren は null を "null" という文字にするので、出さない節は先に除く
  detail.replaceChildren(
    ...[
      el(
        "div",
        { class: "detail-head" },
        el("div", { class: "detail-lemma", lang: "ko" }, w.lemma, speak),
        el("div", { class: "detail-meaning", text: w.meaning }),
        w.meanings.length > 1 ? el("div", { class: "detail-others", text: `ほかの意味: ${w.meanings.filter((m) => !m.primary).map((m) => m.ja).join("／")}` }) : null,
        el("div", { class: "row" }, el("span", { class: "chip", text: w.pos }), el("span", { class: "chip", text: w.origin }), w.hanja ? el("span", { class: "chip", text: `漢字 ${w.hanja}` }) : null, el("span", { class: "chip", text: `L${w.level} ・ ${w.unit}` }), ...w.tags.map((t) => el("span", { class: "chip", text: t }))),
      ),
      w.weak ? section("苦手", el("p", { class: "note", text: `${w.weak_reasons.join("・")}。苦手枠で、期限の前でも出します` })) : null,
      section("面ごとの状態", el("div", { class: "faces" }, ...FACES.map(([key, label]) => (key === "context" ? contextRow(label, w.context_count) : faceRow(label, w.faces[key]))))),
      w.confused_with.length ? section("取り違えた相手", el("div", { class: "row" }, ...w.confused_with.map((c) => el("button", { type: "button", class: "chip warn", lang: "ko", text: `${c.lemma} ${c.meaning} ・ ${c.times} 回`, onClick: () => select(c.id) })))) : null,
      w.synonym_words.length ? section("類語・意味の近い語（矢印ゲームのダミーに出さない語）", wordChips(w.synonym_words)) : null,
      w.confusable_words.length ? section("取り違えやすい語", wordChips(w.confusable_words)) : null,
      w.homograph_words.length ? section("同じ綴りの別の語", wordChips(w.homograph_words)) : null,
      section(
        `出てくる文（${w.sentences.length}）`,
        w.sentences.length ? el("div", {}, ...w.sentences.map((s) => el("div", { class: "detail-sentence" }, el("span", { class: "ko", lang: "ko", text: s.ko }), el("span", { class: "ja", text: s.ja })))) : el("p", { class: "note", text: "まだありません" }),
      ),
      section("履歴", w.history.length ? el("ol", { class: "history" }, ...w.history.map(historyRow)) : el("p", { class: "note", text: "まだ出していません" })),
    ].filter(Boolean),
  );
}

function section(title, ...children) {
  return el("section", { class: "detail-section" }, el("h3", { text: title }), ...children);
}

function faceRow(label, face) {
  if (!face) return el("div", { class: "face-row" }, el("span", { text: label }), el("div", { class: "meter" }, el("span", { style: "width:0%" })), el("span", { class: "note", text: "まだ出していません" }));
  const pct = Math.min(100, Math.round((face.stability / masteredDays) * 100));
  return el("div", { class: "face-row" }, el("span", { text: label }), el("div", { class: "meter" }, el("span", { style: `width:${pct}%` })), el("span", { class: "note", text: `安定度 ${face.stability} 日 ・ 次は ${shortDate(face.due)}` }));
}

/** 文脈の面は FSRS を動かさず、文の問題で出会った回数だけを持つ */
function contextRow(label, count) {
  return el("div", { class: "face-row" }, el("span", { text: label }), el("span"), el("span", { class: "note", text: count ? `文の問題で ${count} 回` : "まだ出していません" }));
}

const RATING_LABELS = { again: "もう一度", hard: "難しい", good: "ふつう", easy: "簡単" };

function historyRow(h) {
  const face = (FACES.find(([key]) => key === h.face) || [h.face, h.face])[1];
  return el(
    "li",
    { class: h.correct ? "ok" : "ng" },
    el("span", { class: "history-date", text: shortDate(h.reviewed_at, true) }),
    el("span", { text: face }),
    el("span", { class: "history-rating", text: RATING_LABELS[h.rating] || h.rating }),
    h.counted ? null : el("span", { class: "note", text: "評価に使わない（同じ日の 2 回目以降）" }),
  );
}

function shortDate(iso, withTime = false) {
  const d = new Date(iso);
  const date = `${d.getMonth() + 1}/${d.getDate()}`;
  return withTime ? `${date} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : date;
}

async function load() {
  masteredDays = (await api.get(`/api/settings/${encodeURIComponent(LANGUAGE)}`)).mastered_days || masteredDays;
  units = await api.get(`/api/units?language=${encodeURIComponent(LANGUAGE)}`);
  allWords = await api.get(`/api/words?language=${encodeURIComponent(LANGUAGE)}`);
  const levelSel = document.getElementById("f-level");
  for (const level of [...new Set(units.map((u) => u.level))]) levelSel.append(el("option", { value: String(level), text: `L${level}` }));
  const unitSel = document.getElementById("f-unit");
  for (const u of units) unitSel.append(el("option", { value: u.id, text: `${u.id} ${u.title}` }));
  const params = new URLSearchParams(location.search);
  if (params.get("weak")) document.getElementById("f-state").value = "weak";
  if (params.get("unit")) unitSel.value = params.get("unit");
  renderList();
  for (const id of ["f-q", "f-level", "f-unit", "f-state"]) document.getElementById(id).addEventListener("input", renderList);
}

let ttsLang = null;

document.addEventListener("DOMContentLoaded", async () => {
  const meta = await loadMeta();
  ttsLang = meta && meta.current ? meta.current.tts_lang : null;
  try {
    await load();
  } catch (err) {
    toast(`読み込みに失敗しました: ${err.message}`, { type: "error" });
  }
});
