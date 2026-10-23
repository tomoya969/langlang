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
    if (f.state && w.state !== f.state) return false;
    if (f.q && !w.lemma.toLowerCase().includes(f.q) && !w.meaning.toLowerCase().includes(f.q)) return false;
    return true;
  });
  document.getElementById("f-count").textContent = `${rows.length} 語`;
  const list = document.getElementById("word-list");
  list.replaceChildren();
  if (!rows.length) {
    list.append(el("p", { class: "muted", text: "当てはまる単語がありません" }));
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
        el("span", { class: "chip", text: w.pos }),
        el("span", { class: `state ${w.state}`, text: STATE_LABELS[w.state] || w.state }),
      ),
    );
  }
}

async function select(id) {
  selected = id;
  renderList();
  const detail = document.getElementById("detail");
  detail.hidden = false;
  detail.replaceChildren(el("p", { class: "muted", text: "読み込んでいます…" }));
  let w;
  try {
    w = await api.get(`/api/words/${encodeURIComponent(id)}?language=${LANGUAGE}`);
  } catch (err) {
    detail.replaceChildren(el("p", { class: "muted", text: `読み込みに失敗しました: ${err.message}` }));
    return;
  }
  const speak = el("button", { type: "button", class: "speak-btn", "aria-label": "読み上げる", onClick: () => Speak.speak(w.tts_text, { lang: "ko-KR" }) }, "🔊");
  detail.replaceChildren(
    el("div", { class: "detail-lemma", lang: "ko" }, w.lemma, speak),
    el("div", { class: "detail-meaning", text: w.meaning }),
    el("div", { class: "row" }, el("span", { class: "chip", text: w.pos }), el("span", { class: "chip", text: w.origin }), w.hanja ? el("span", { class: "chip accent", text: `漢字: ${w.hanja}` }) : null, el("span", { class: "chip", text: `L${w.level} ${w.unit}` }), ...w.tags.map((t) => el("span", { class: "chip", text: t }))),
    el("div", {}, el("h2", { text: "面ごとの状態" }), el("div", { class: "faces" }, ...FACES.map(([key, label]) => faceRow(label, w.faces[key])))),
    w.confusable_words.length ? el("div", {}, el("h2", { text: "取り違えやすい語" }), el("div", { class: "row" }, ...w.confusable_words.map((c) => el("button", { type: "button", class: "chip", lang: "ko", text: `${c.lemma} ${c.meaning}`, onClick: () => select(c.id) })))) : null,
    w.homograph_words.length ? el("div", {}, el("h2", { text: "同じ綴りの別の語" }), el("div", { class: "row" }, ...w.homograph_words.map((c) => el("button", { type: "button", class: "chip", lang: "ko", text: `${c.lemma} ${c.meaning}`, onClick: () => select(c.id) })))) : null,
    el("div", {}, el("h2", { text: `出てくる文（${w.sentences.length}）` }), el("div", { class: "detail-sentences" }, ...(w.sentences.length ? w.sentences.map((s) => el("div", { class: "detail-sentence" }, el("span", { class: "ko", lang: "ko", text: s.ko }), el("span", { class: "ja", text: s.ja }))) : [el("p", { class: "muted small", text: "まだありません" })]))),
    el("div", {}, el("h2", { text: "履歴" }), el("p", { class: "muted small", text: w.history.length ? "" : "記録の仕組みを入れるまでは、ここは空です" })),
  );
}

function faceRow(label, face) {
  if (!face) return el("div", { class: "face-row" }, el("span", { text: label }), el("div", { class: "meter" }, el("span", { style: "width:0%" })), el("span", { class: "muted", text: "まだ出していません" }));
  const pct = Math.min(100, Math.round((face.stability / 21) * 100));
  return el("div", { class: "face-row" }, el("span", { text: label }), el("div", { class: "meter" }, el("span", { style: `width:${pct}%` })), el("span", { class: "muted", text: `安定度 ${face.stability} 日` }));
}

async function load() {
  units = await api.get(`/api/units?language=${LANGUAGE}`);
  allWords = await api.get(`/api/words?language=${LANGUAGE}`);
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

document.addEventListener("DOMContentLoaded", async () => {
  await checkApiVersion();
  try {
    await load();
  } catch (err) {
    toast(`読み込みに失敗しました: ${err.message}`, { type: "error" });
  }
});
