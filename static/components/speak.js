/* 読み上げ。speak(text, { lang, rate }) の 1 か所から呼ぶ。中身は Web Speech API（speechSynthesis）。

   声の一覧は遅れて届くことがあるので voiceschanged も待つ。その言語の声がなければ onMissing で画面に知らせる。
   次のカードに移ったら前の読み上げを止める（stop）。声の質が足りなければ、このモジュールの中身だけを差し替える。 */
"use strict";

const Speak = (() => {
  const synth = window.speechSynthesis || null;
  let voices = [];
  let missingNotified = new Set();
  let onMissing = () => {};
  let defaultRate = 1.0;

  function refresh() {
    if (!synth) return;
    voices = synth.getVoices();
  }

  function voiceFor(lang) {
    const base = lang.split("-")[0].toLowerCase();
    const exact = voices.filter((v) => v.lang.replace("_", "-").toLowerCase() === lang.toLowerCase());
    const loose = voices.filter((v) => v.lang.toLowerCase().startsWith(base));
    const candidates = exact.length ? exact : loose;
    // ローカルの声を優先する（オンラインの声は遅れることがある）
    return candidates.find((v) => v.localService) || candidates[0] || null;
  }

  function available(lang) {
    return Boolean(synth) && voiceFor(lang) !== null;
  }

  function speak(text, { lang = "ko-KR", rate = defaultRate, onEnd } = {}) {
    if (!synth || !text) return false;
    stop();
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = voiceFor(lang);
    if (voice) utterance.voice = voice;
    else if (!missingNotified.has(lang)) {
      missingNotified.add(lang);
      onMissing(lang);
    }
    utterance.lang = lang;
    utterance.rate = rate;
    if (onEnd) utterance.onend = onEnd;
    synth.speak(utterance);
    return true;
  }

  function stop() {
    if (synth && (synth.speaking || synth.pending)) synth.cancel();
  }

  function setDefaultRate(rate) {
    defaultRate = rate;
  }

  function setOnMissing(fn) {
    onMissing = fn;
  }

  function list(lang) {
    const base = lang.split("-")[0].toLowerCase();
    return voices.filter((v) => v.lang.toLowerCase().startsWith(base)).map((v) => ({ name: v.name, lang: v.lang, local: v.localService }));
  }

  if (synth) {
    refresh();
    synth.addEventListener("voiceschanged", refresh);
  }
  return { speak, stop, available, setDefaultRate, setOnMissing, list, supported: Boolean(synth) };
})();
