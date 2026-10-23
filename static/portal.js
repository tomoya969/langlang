"use strict";

function languageCard(summary) {
  const lang = summary.language;
  const home = `/${encodeURIComponent(lang.code)}`;
  if (!summary.available) {
    const head = el("div", { class: "lc-head" }, el("span", { class: "lc-name", text: lang.label }), el("span", { class: "lc-native", lang: lang.code, text: lang.native }));
    return el("section", { class: "language-card unavailable" }, head, el("p", { class: "muted small", text: "教材がまだありません" }));
  }
  const head = el("div", { class: "lc-head" }, el("a", { class: "lc-name", href: home, text: lang.label }), el("span", { class: "lc-native", lang: lang.code, text: lang.native }), icon("chevron"));
  const total = summary.levels.reduce((n, lv) => n + lv.total, 0);
  const mastered = summary.levels.reduce((n, lv) => n + lv.mastered, 0);
  const pct = total ? Math.round((mastered / total) * 100) : 0;
  return el(
    "section",
    { class: "language-card" },
    head,
    summary.unit ? el("div", { class: "lc-unit" }, "次のユニット: ", el("strong", { text: summary.unit.title }), ` ・ ${summary.unit.id}`) : null,
    el(
      "div",
      { class: "lc-stats" },
      stat(summary.review_count, "復習"),
      stat(summary.new_word_count, "新出の単語"),
      stat(summary.estimate_min, "目安（分）"),
    ),
    el(
      "div",
      { class: "lc-progress" },
      el("div", { class: "lc-progress-label" }, el("span", { text: "定着した単語" }), el("span", { text: `${mastered} / ${total} 語` })),
      el("div", { class: "meter" }, el("span", { style: `width: ${pct}%` })),
    ),
    el("div", { class: "lc-actions" }, el("a", { class: "btn primary", href: `${home}/learn`, text: "今日の学習を始める" })),
  );
}

function stat(value, label) {
  return el("div", { class: "lc-stat" }, el("strong", { text: String(value) }), el("span", { text: label }));
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadMeta();
  const cards = document.getElementById("language-cards");
  try {
    const summaries = await api.get("/api/portal");
    cards.replaceChildren(...summaries.map(languageCard));
  } catch (err) {
    cards.replaceChildren(el("p", { class: "muted", text: `読み込みに失敗しました: ${err.message}` }));
    toast(`読み込みに失敗しました: ${err.message}`, { type: "error" });
  }
});
