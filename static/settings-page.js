"use strict";

const form = document.getElementById("settings-form");

function fill(values) {
  for (const input of form.elements) {
    if (!input.name || !(input.name in values)) continue;
    input.value = String(values[input.name]);
  }
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

async function load() {
  const current = Settings.get();
  for (const radio of document.querySelectorAll('input[name="theme"]')) {
    radio.checked = radio.value === current.theme;
    radio.addEventListener("change", () => Settings.set({ theme: radio.value }));
  }
  fill(await api.get("/api/settings"));
  const voices = Speak.list("ko-KR");
  document.getElementById("voice-info").textContent = Speak.supported ? (voices.length ? `声: ${voices.map((v) => v.name).join("、")}` : "韓国語の声が見つかりません（声の一覧が遅れて届くことがあります）") : "このブラウザは読み上げに対応していません";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const stateEl = document.getElementById("save-state");
  stateEl.textContent = "保存しています…";
  try {
    fill(await api.put("/api/settings", collect()));
    stateEl.textContent = "保存しました";
    toast("設定を保存しました", { type: "success" });
  } catch (err) {
    stateEl.textContent = "";
    toast(`保存に失敗しました: ${err.message}`, { type: "error" });
  }
});

document.getElementById("btn-test-voice").addEventListener("click", () => {
  const rate = Number(form.elements.tts_rate.value);
  if (!Speak.speak("안녕하세요. 만나서 반갑습니다.", { lang: "ko-KR", rate })) toast("読み上げを再生できません", { type: "warn" });
});

document.addEventListener("DOMContentLoaded", async () => {
  await checkApiVersion();
  try {
    await load();
  } catch (err) {
    toast(`読み込みに失敗しました: ${err.message}`, { type: "error" });
  }
});
