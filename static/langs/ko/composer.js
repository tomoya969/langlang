/* ハングルの組み立て（字母の列 → 文字列）と、その逆（文字列 → 打鍵する字母の列）。

   入力欄（components/typing-field.js）は「打った字母の列」だけを持ち、表示のたびに compose() で文字列にする。
   Backspace は列の最後を 1 つ消すだけで済み、「どこまで打ったか」もなぞり（打鍵列との比較）で簡単に分かる。
   組み立ての規則は一般的な 2 벌식 の IME と同じ（終声が次の音節の初声に移る、ㅗ+ㅏ=ㅘ、ㄹ+ㄱ=ㄺ など）。 */
"use strict";

const KoComposer = (() => {
  const CHO = [..."ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"];
  const JUNG = [..."ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"];
  const JONG = ["", ..."ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"];
  const JUNG_COMBINE = { "ㅗㅏ": "ㅘ", "ㅗㅐ": "ㅙ", "ㅗㅣ": "ㅚ", "ㅜㅓ": "ㅝ", "ㅜㅔ": "ㅞ", "ㅜㅣ": "ㅟ", "ㅡㅣ": "ㅢ" };
  const JONG_COMBINE = {
    "ㄱㅅ": "ㄳ", "ㄴㅈ": "ㄵ", "ㄴㅎ": "ㄶ", "ㄹㄱ": "ㄺ", "ㄹㅁ": "ㄻ", "ㄹㅂ": "ㄼ",
    "ㄹㅅ": "ㄽ", "ㄹㅌ": "ㄾ", "ㄹㅍ": "ㄿ", "ㄹㅎ": "ㅀ", "ㅂㅅ": "ㅄ",
  };
  const SPLIT = {};
  for (const table of [JUNG_COMBINE, JONG_COMBINE]) {
    for (const [pair, compound] of Object.entries(table)) SPLIT[compound] = [...pair];
  }
  const SYLLABLE_BASE = 0xac00;
  const SYLLABLE_END = 0xd7a3;

  const isCho = (ch) => CHO.includes(ch);
  const isJung = (ch) => JUNG.includes(ch);
  const isJong = (ch) => ch !== "" && JONG.includes(ch);
  const isConsonant = (ch) => isCho(ch) || isJong(ch);
  const isSyllable = (ch) => {
    const code = ch.codePointAt(0);
    return code >= SYLLABLE_BASE && code <= SYLLABLE_END;
  };

  function syllable(cho, jung, jong) {
    return String.fromCharCode(SYLLABLE_BASE + (CHO.indexOf(cho) * 21 + JUNG.indexOf(jung)) * 28 + JONG.indexOf(jong || ""));
  }

  function render(cur) {
    if (cur.cho && cur.jung) return syllable(cur.cho, cur.jung, cur.jong);
    return cur.cho || cur.jung || "";
  }

  /** 字母（と、空白などの字母でない文字）の列を文字列にする。最後の音節は組み立て途中でもそのまま出す。 */
  function compose(jamos) {
    let out = "";
    let cur = { cho: "", jung: "", jong: "" };
    const flush = () => {
      out += render(cur);
      cur = { cho: "", jung: "", jong: "" };
    };
    for (const ch of jamos) {
      if (isConsonant(ch)) {
        if (!cur.cho && !cur.jung) {
          cur.cho = ch;
        } else if (cur.cho && !cur.jung) {
          flush();
          cur.cho = ch;
        } else if (!cur.cho && cur.jung) {
          flush();
          cur.cho = ch;
        } else if (!cur.jong) {
          if (isJong(ch)) cur.jong = ch;
          else {
            flush();
            cur.cho = ch;
          }
        } else {
          const compound = JONG_COMBINE[cur.jong + ch];
          if (compound) cur.jong = compound;
          else {
            flush();
            cur.cho = ch;
          }
        }
      } else if (isJung(ch)) {
        if (!cur.cho && !cur.jung) {
          cur.jung = ch;
        } else if (cur.cho && !cur.jung) {
          cur.jung = ch;
        } else if (!cur.cho && cur.jung) {
          const compound = JUNG_COMBINE[cur.jung + ch];
          if (compound) cur.jung = compound;
          else {
            flush();
            cur.jung = ch;
          }
        } else if (!cur.jong) {
          const compound = JUNG_COMBINE[cur.jung + ch];
          if (compound) cur.jung = compound;
          else {
            flush();
            cur.jung = ch;
          }
        } else {
          // 終声は次の音節の初声になる（複合終声なら後ろの字母だけ）
          const [stay, move] = SPLIT[cur.jong] || ["", cur.jong];
          cur.jong = stay;
          flush();
          cur.cho = move;
          cur.jung = ch;
        }
      } else {
        flush();
        out += ch;
      }
    }
    return out + render(cur);
  }

  /** 文字列を、打鍵する字母の列にする。複合母音・複合終声は 2 つの字母に分ける。字母でない文字はそのまま。 */
  function decompose(text) {
    const result = [];
    for (const ch of text) {
      if (isSyllable(ch)) {
        const index = ch.codePointAt(0) - SYLLABLE_BASE;
        const cho = CHO[Math.floor(index / 28 / 21)];
        const jung = JUNG[Math.floor(index / 28) % 21];
        const jong = JONG[index % 28];
        result.push(cho, ...(SPLIT[jung] || [jung]));
        if (jong) result.push(...(SPLIT[jong] || [jong]));
      } else if (SPLIT[ch]) {
        result.push(...SPLIT[ch]);
      } else {
        result.push(ch);
      }
    }
    return result;
  }

  return { compose, decompose, isSyllable, isJung, isConsonant, CHO, JUNG, JONG };
})();

if (typeof module !== "undefined") module.exports = KoComposer;
