/* 設定の画面。表示（テーマ）は全体でブラウザに、学習の設定は言語ごとにサーバー（records/settings.json）に残す。

   どの言語の設定を開くかは ?language= で決める（言語の画面の「設定」から来たときはその言語）。なければ最初の言語。 */
"use strict";

const form = document.getElementById("settings-form");
let languages = [];
let current = null; // 今開いている言語（/api/meta の languages の 1 つ）
let dirty = false;

function fill(values) {
  for (const input of form.elements) {
    if (!input.name || !(input.name in values)) continue;
    input.value = String(values[input.name]);
  }
  dirty = false;
}

function collect() {
  const out = {};
  for (const input of form.elements) {
    if (!input.name) continue;
    if (input.name === "keyboard_show_latin") out[input.name] = input.value === "true";
    else out[input.name] = Number(input.value);
  }
  return out;
}

function renderTabs() {
  const tabs = document.getElementById("lang-tabs");
  tabs.replaceChildren(
    ...languages.map((lang) =>
      el("button", { type: "button", role: "tab", class: "seg", "aria-selected": lang.code === current.code ? "true" : "false", onClick: () => openLanguage(lang.code) }, lang.label),
    ),
  );
}

function renderVoiceInfo() {
  const voices = Speak.list(current.tts_lang);
  document.getElementById("voice-info").textContent = !Speak.supported
    ? "このブラウザは読み上げに対応していません"
    : voices.length
      ? `声: ${voices.map((v) => v.name).join("、")}`
      : `${current.label}の声が見つかりません（声の一覧が遅れて届くことがあります）`;
}

async function openLanguage(code) {
  if (dirty && !window.confirm("保存していない変更があります。破棄してほかの言語を開きますか？")) return;
  current = languages.find((l) => l.code === code) || languages[0];
  const url = new URL(location.href);
  url.searchParams.set("language", current.code);
  history.replaceState(null, "", url);
  document.getElementById("lang-home").href = `/${encodeURIComponent(current.code)}`;
  document.getElementById("lang-home").textContent = `${current.label}のホームへ`;
  renderTabs();
  renderVoiceInfo();
  document.getElementById("save-state").textContent = "";
  fill(await api.get(`/api/settings/${encodeURIComponent(current.code)}`));
}

form.addEventListener("input", () => {
  dirty = true;
  document.getElementById("save-state").textContent = "未保存";
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const stateEl = document.getElementById("save-state");
  stateEl.textContent = "保存しています…";
  try {
    fill(await api.put(`/api/settings/${encodeURIComponent(current.code)}`, collect()));
    stateEl.textContent = "保存しました";
    toast(`${current.label}の設定を保存しました`, { type: "success" });
  } catch (err) {
    stateEl.textContent = "未保存";
    toast(`保存に失敗しました: ${err.message}`, { type: "error" });
  }
});

document.getElementById("btn-test-voice").addEventListener("click", () => {
  const rate = Number(form.elements.tts_rate.value);
  if (!Speak.speak(current.tts_sample, { lang: current.tts_lang, rate })) toast("読み上げを再生できません", { type: "warn" });
});

document.addEventListener("DOMContentLoaded", async () => {
  for (const radio of document.querySelectorAll('input[name="theme"]')) {
    radio.checked = radio.value === Settings.get().theme;
    radio.addEventListener("change", () => Settings.set({ theme: radio.value }));
  }
  const meta = await loadMeta();
  if (!meta) return;
  languages = meta.languages;
  try {
    await openLanguage(new URLSearchParams(location.search).get("language") || languages[0].code);
  } catch (err) {
    toast(`読み込みに失敗しました: ${err.message}`, { type: "error" });
  }
});
