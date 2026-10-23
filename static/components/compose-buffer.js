/* 入力欄の中身（画面から切り離したロジック）。確定した文字の列・カーソル・組み立て中の音節を持つ。

   ふつうの IME と同じく、組み立て中なのはカーソルの直前の 1 音節だけ（buffer に字母で持つ）。
   字母を足して 2 文字になったら、前の文字を確定してカーソルの前に入れる（강 + ㅏ → 가 を確定、아 を組み立て中）。
   カーソルを動かすと組み立て中の音節は確定する。
   Backspace は字母を 1 つずつ消す。確定した文字の上でも、その文字を組み立て中に戻して最後の字母を消す
   （애 の後ろで Backspace → ㅇ、続けて ㅔ → 에。途中の 1 字母だけを直せるように）。

   言語ごとの組み立ては composer（compose / decompose）に任せる。 */
"use strict";

const ComposeBuffer = (() => {
  function create(composer) {
    return { composer, chars: [], caret: 0, buffer: [] };
  }

  function composing(state) {
    return state.buffer.length ? state.composer.compose(state.buffer) : "";
  }

  function commit(state) {
    if (!state.buffer.length) return;
    const text = [...composing(state)];
    state.chars.splice(state.caret, 0, ...text);
    state.caret += text.length;
    state.buffer = [];
  }

  function typeJamo(state, jamo) {
    const result = [...state.composer.compose([...state.buffer, jamo])];
    if (result.length <= 1) {
      state.buffer.push(jamo);
      return;
    }
    const done = result.slice(0, -1);
    state.chars.splice(state.caret, 0, ...done);
    state.caret += done.length;
    state.buffer = state.composer.decompose(result[result.length - 1]);
  }

  /** 字母でない文字（空白・記号・貼り付けた文字列）をカーソルの位置に入れる */
  function insertText(state, text) {
    commit(state);
    const chars = [...text];
    state.chars.splice(state.caret, 0, ...chars);
    state.caret += chars.length;
  }

  function backspace(state) {
    if (state.buffer.length) {
      state.buffer.pop();
      return;
    }
    if (state.caret === 0) return;
    const [ch] = state.chars.splice(state.caret - 1, 1);
    state.caret -= 1;
    state.buffer = state.composer.decompose(ch).slice(0, -1);
  }

  function deleteForward(state) {
    commit(state);
    state.chars.splice(state.caret, 1);
  }

  function setCaret(state, index) {
    commit(state);
    state.caret = Math.max(0, Math.min(state.chars.length, index));
  }

  // 組み立て中の音節は確定してから動かす。← は確定した音節の前へ行く（ふつうの IME と同じ）
  const left = (state) => {
    commit(state);
    setCaret(state, state.caret - 1);
  };
  const right = (state) => {
    commit(state);
    setCaret(state, state.caret + 1);
  };
  const home = (state) => setCaret(state, 0);
  const end = (state) => {
    commit(state);
    setCaret(state, state.chars.length);
  };

  /** 表示用に、カーソルの前・組み立て中・カーソルの後ろに分ける */
  function parts(state) {
    return {
      before: state.chars.slice(0, state.caret).join(""),
      composing: composing(state),
      after: state.chars.slice(state.caret).join(""),
    };
  }

  function value(state) {
    const p = parts(state);
    return p.before + p.composing + p.after;
  }

  function atEnd(state) {
    return state.caret === state.chars.length;
  }

  function reset(state) {
    state.chars = [];
    state.caret = 0;
    state.buffer = [];
  }

  return { create, typeJamo, insertText, backspace, deleteForward, left, right, home, end, setCaret, parts, value, atEnd, reset, commit };
})();

if (typeof module !== "undefined") module.exports = ComposeBuffer;
