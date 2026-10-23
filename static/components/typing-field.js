/* 入力欄。物理キーの英字を字母にして（keymap）、ハングルに組み立てて（composer）見せる。

   日本語や英語の入力モードのまま打てるように、ブラウザの IME は使わず keydown を自分で受ける。
   そのため <input> ではなく div に描き、フォーカスは透明な <input> で受ける（キーイベントとフォーカスの枠のため）。
   中身（確定した文字・カーソル・組み立て中の音節）は ComposeBuffer が持ち、ここは描くのとキーの振り分けだけをする。

   キー: ← → でカーソル移動、Home / End で先頭・末尾、Backspace は字母を 1 つずつ、Delete は後ろの 1 文字。
   文字をクリックすると、その位置にカーソルを置く。
   なぞり（setTarget）のときはカーソルを末尾に固定する（次のキーのガイドが末尾を前提にするため）。

   TypingField.create(container, { keymap, composer, keyboard, onSubmit, onChange })
     → { value(), jamos(), reset(), setTarget(text), focus(), setEnabled(on), isComplete(), element } */
"use strict";

const TypingField = (() => {
  function create(container, { keymap, composer, keyboard = null, onSubmit = () => {}, onChange = () => {}, placeholder = "" }) {
    container.classList.add("tf");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "tf-capture";
    input.setAttribute("aria-label", "入力欄");
    input.autocomplete = "off";
    input.spellcheck = false;
    const view = document.createElement("div");
    view.className = "tf-view";
    container.append(view, input);

    const buf = ComposeBuffer.create(composer);
    let target = null; // なぞりのとき: 打つべき字母の列
    let enabled = true;

    const value = () => ComposeBuffer.value(buf);
    const jamos = () => composer.decompose(value());

    function render() {
      const composed = value();
      view.replaceChildren();
      if (target) renderTrace(composed);
      else renderEdit();
      if (!composed.length) {
        const hint = document.createElement("span");
        hint.className = "tf-placeholder";
        hint.textContent = placeholder;
        view.append(hint);
      }
      updateGuide();
      onChange(composed);
    }

    function charSpan(ch, index) {
      const span = document.createElement("span");
      span.className = "tf-char";
      span.dataset.i = String(index);
      span.textContent = ch;
      return span;
    }

    function caretSpan() {
      const caret = document.createElement("span");
      caret.className = "tf-caret";
      return caret;
    }

    function renderEdit() {
      const { before, composing, after } = ComposeBuffer.parts(buf);
      const beforeChars = [...before];
      beforeChars.forEach((ch, i) => view.append(charSpan(ch, i)));
      if (composing) {
        const span = document.createElement("span");
        span.className = "tf-composing";
        span.textContent = composing;
        view.append(span);
      }
      view.append(caretSpan());
      [...after].forEach((ch, i) => view.append(charSpan(ch, beforeChars.length + i)));
    }

    /** なぞり: 目標と一致している部分と、違っている部分を色分けする */
    function renderTrace(composed) {
      const expected = composer.compose(target);
      const ok = jamosMatchPrefix();
      let common = 0;
      while (common < composed.length && common < expected.length && composed[common] === expected[common]) common += 1;
      const good = document.createElement("span");
      good.className = "tf-ok";
      good.textContent = ok ? composed : composed.slice(0, common);
      view.append(good);
      if (!ok) {
        const bad = document.createElement("span");
        bad.className = "tf-bad";
        bad.textContent = composed.slice(common);
        view.append(bad);
      }
      view.append(caretSpan());
      if (ok) {
        const rest = document.createElement("span");
        rest.className = "tf-rest";
        rest.textContent = expected.slice(composed.length);
        view.append(rest);
      }
    }

    function jamosMatchPrefix() {
      if (!target) return true;
      const typed = jamos();
      return typed.length <= target.length && typed.every((j, i) => j === target[i]);
    }

    function updateGuide() {
      if (!keyboard) return;
      if (!target) {
        keyboard.guide(null);
        return;
      }
      if (!jamosMatchPrefix()) {
        keyboard.guide("backspace");
        return;
      }
      const next = target[jamos().length];
      if (next === undefined) {
        keyboard.guide("enter");
        return;
      }
      const key = keymap.keyOf(next);
      if (key) keyboard.guide(key.key, key.shift);
      else keyboard.guide(next === " " ? " " : null);
    }

    const MOVES = { ArrowLeft: ComposeBuffer.left, ArrowRight: ComposeBuffer.right, Home: ComposeBuffer.home, End: ComposeBuffer.end };

    function onKeyDown(event) {
      if (!enabled) return;
      if (keyboard) {
        keyboard.pressed(event.key, true);
        keyboard.setShift(event.shiftKey);
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "Enter") {
        event.preventDefault();
        ComposeBuffer.commit(buf);
        onSubmit(value());
        return;
      }
      if (MOVES[event.key]) {
        event.preventDefault();
        if (!target) {
          MOVES[event.key](buf);
          render();
        }
        return;
      }
      if (event.key === "Backspace") {
        event.preventDefault();
        ComposeBuffer.backspace(buf);
        render();
        return;
      }
      if (event.key === "Delete") {
        event.preventDefault();
        if (!target) {
          ComposeBuffer.deleteForward(buf);
          render();
        }
        return;
      }
      if (event.key === "Shift" || event.key === "Tab" || event.key === "Escape") return;
      const jamo = keymap.jamoOf(event.key, event.shiftKey);
      if (jamo) {
        event.preventDefault();
        ComposeBuffer.typeJamo(buf, jamo);
        render();
        return;
      }
      // 空白・記号（. ? !）と、ハングルを直接入れられる環境で来た文字はそのまま入れる
      if (event.key.length === 1) {
        event.preventDefault();
        ComposeBuffer.insertText(buf, event.key);
        render();
      }
    }

    function onKeyUp(event) {
      if (!keyboard) return;
      keyboard.pressed(event.key, false);
      keyboard.setShift(event.shiftKey);
    }

    /** クリックした文字の左半分ならその前、右半分ならその後ろにカーソルを置く。文字のない所なら末尾 */
    function placeCaret(event) {
      if (target || !enabled) return;
      const span = event.target.closest(".tf-char");
      if (span) {
        const rect = span.getBoundingClientRect();
        const index = Number(span.dataset.i) + (event.clientX > rect.left + rect.width / 2 ? 1 : 0);
        ComposeBuffer.setCaret(buf, index);
      } else if (!event.target.closest(".tf-composing")) {
        ComposeBuffer.end(buf);
      }
      render();
    }

    input.addEventListener("keydown", onKeyDown);
    input.addEventListener("keyup", onKeyUp);
    input.addEventListener("blur", () => {
      if (keyboard) keyboard.setShift(false);
      container.classList.remove("tf-focus");
    });
    input.addEventListener("focus", () => container.classList.add("tf-focus"));
    input.addEventListener("paste", (event) => {
      event.preventDefault();
      ComposeBuffer.insertText(buf, (event.clipboardData || window.clipboardData).getData("text"));
      render();
    });
    view.addEventListener("mousedown", (event) => {
      event.preventDefault();
      placeCaret(event);
      input.focus();
    });

    function reset() {
      ComposeBuffer.reset(buf);
      target = null;
      render();
    }

    function setTarget(textTarget) {
      target = textTarget ? composer.decompose(textTarget) : null;
      render();
    }

    function setEnabled(on) {
      enabled = on;
      input.disabled = !on;
      container.classList.toggle("tf-disabled", !on);
    }

    function focus() {
      input.focus({ preventScroll: true });
    }

    function isComplete() {
      return target !== null && jamos().length === target.length && jamosMatchPrefix();
    }

    render();
    return { value, jamos, reset, setTarget, focus, setEnabled, isComplete, element: container };
  }

  return { create };
})();
