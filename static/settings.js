/* 画面の表示の設定（テーマ）。すべての画面の <head> で読む。

   読み込んだときに <html> の属性へ反映する。<head> で読むのは、本文を描く前に反映して、
   読み込みのたびに一瞬だけ違うテーマで描かれないようにするため。
   表示の好みなのでこのブラウザの localStorage に残し、サーバー（records/settings.json）には送らない。 */
"use strict";

const Settings = (() => {
  const STORAGE_KEY = "langlang.settings";
  const THEMES = ["system", "light", "dark"];
  const DEFAULTS = { theme: "system" };
  const systemDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const listeners = new Set();
  let current = load();

  function load() {
    try {
      return normalize(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"));
    } catch {
      return { ...DEFAULTS };
    }
  }

  function normalize(raw) {
    return { theme: THEMES.includes(raw.theme) ? raw.theme : DEFAULTS.theme };
  }

  function apply() {
    const root = document.documentElement;
    if (current.theme === "system") delete root.dataset.theme;
    else root.dataset.theme = current.theme;
  }

  function changed() {
    apply();
    for (const listener of listeners) listener(get());
  }

  function get() {
    return { ...current };
  }

  function set(changes) {
    current = normalize({ ...current, ...changes });
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
    } catch {
      // 保存できなくても、開いている画面には反映する
    }
    changed();
  }

  function isDark() {
    return current.theme === "dark" || (current.theme === "system" && Boolean(systemDark && systemDark.matches));
  }

  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    current = load();
    changed();
  });
  if (systemDark && systemDark.addEventListener) {
    systemDark.addEventListener("change", () => {
      if (current.theme === "system") changed();
    });
  }

  apply();
  return { get, set, isDark, onChange: (fn) => listeners.add(fn) };
})();
