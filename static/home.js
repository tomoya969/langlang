"use strict";

const LEVEL_NAMES = { 1: "やさしい", 2: "ふつう", 3: "むずかしい" };

async function loadHome() {
  const today = await api.get(`/api/today?language=${encodeURIComponent(LANGUAGE)}`);
  document.getElementById("hero-title").textContent = today.unit ? today.unit.title : "教材がありません";
  document.getElementById("hero-unit").textContent = today.unit ? `L${today.unit.level} ・ ${today.unit.id} ・ ${today.unit.scene}` : "";
  document.getElementById("stat-review").textContent = today.review_count;
  document.getElementById("stat-new").textContent = today.new_word_count;
  document.getElementById("stat-sentences").textContent = today.new_sentence_count;
  document.getElementById("stat-min").textContent = today.estimate_min;
  document.getElementById("stat-weak").textContent = today.weak_count;

  const levels = document.getElementById("levels");
  levels.replaceChildren(
    ...today.levels.map((lv) => {
      const pct = lv.total ? Math.round(((lv.mastered + lv.learning * 0.5) / lv.total) * 100) : 0;
      return el(
        "div",
        { class: "level-row" },
        el("span", { class: "level-name", text: `L${lv.level} ${LEVEL_NAMES[lv.level] || ""}` }),
        el("div", { class: "meter" }, el("span", { style: `width: ${pct}%` })),
        el("span", { class: "level-count", text: `${lv.mastered} / ${lv.total} 語 定着` }),
      );
    }),
  );

  // 記録がまだないので、状態は「今日」と「未着手」だけ
  const units = document.getElementById("units");
  units.replaceChildren(
    ...today.units.map((u) => {
      const isToday = today.unit && today.unit.id === u.id;
      return el(
        "li",
        {},
        el(
          "a",
          { class: "unit", href: languageUrl("learn", `unit=${encodeURIComponent(u.id)}`) },
          el("span", { class: "unit-id", text: u.id }),
          el("span", { class: "unit-title" }, u.title, el("span", { class: "unit-scene", text: u.scene })),
          el("span", { class: "unit-meta", text: `${u.word_count} 語 ・ ${u.sentence_count} 文` }),
          el("span", { class: isToday ? "chip accent" : "chip", text: isToday ? "今日" : "未着手" }),
          icon("chevron"),
        ),
      );
    }),
  );
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadMeta();
  try {
    await loadHome();
  } catch (err) {
    toast(`読み込みに失敗しました: ${err.message}`, { type: "error" });
    document.getElementById("hero-title").textContent = "読み込みに失敗しました";
  }
});
