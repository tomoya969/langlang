/* 韓国語のキー配列（2 벌식）。英字のキー → 字母。

   画面のキーボードの描画（components/keyboard.js）と、打った英字から字母を決めるのに使う。
   Shift を押したときに変わるのは ㅂㅈㄷㄱㅅ（→ 濃音）と ㅐㅔ（→ ㅒㅖ）だけ。 */
"use strict";

const KoKeymap = (() => {
  const BASE = {
    q: "ㅂ", w: "ㅈ", e: "ㄷ", r: "ㄱ", t: "ㅅ", y: "ㅛ", u: "ㅕ", i: "ㅑ", o: "ㅐ", p: "ㅔ",
    a: "ㅁ", s: "ㄴ", d: "ㅇ", f: "ㄹ", g: "ㅎ", h: "ㅗ", j: "ㅓ", k: "ㅏ", l: "ㅣ",
    z: "ㅋ", x: "ㅌ", c: "ㅊ", v: "ㅍ", b: "ㅠ", n: "ㅜ", m: "ㅡ",
  };
  const SHIFTED = { q: "ㅃ", w: "ㅉ", e: "ㄸ", r: "ㄲ", t: "ㅆ", o: "ㅒ", p: "ㅖ" };
  const ROWS = [
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
    ["z", "x", "c", "v", "b", "n", "m"],
  ];

  // 字母 → { key, shift }。打鍵列への分解（composer.toKeys）と、次のキーのガイドに使う
  const JAMO_TO_KEY = {};
  for (const [key, jamo] of Object.entries(BASE)) JAMO_TO_KEY[jamo] = { key, shift: false };
  for (const [key, jamo] of Object.entries(SHIFTED)) JAMO_TO_KEY[jamo] = { key, shift: true };

  /** 英字（KeyboardEvent.key）と Shift の状態から字母を返す。字母にならなければ null */
  function jamoOf(key, shift) {
    const lower = (key || "").toLowerCase();
    if (lower.length !== 1 || !(lower in BASE)) return null;
    return (shift && SHIFTED[lower]) || BASE[lower];
  }

  function keyOf(jamo) {
    return JAMO_TO_KEY[jamo] || null;
  }

  return { BASE, SHIFTED, ROWS, jamoOf, keyOf, lang: "ko-KR" };
})();

if (typeof module !== "undefined") module.exports = KoKeymap;
