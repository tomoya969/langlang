/* 入力欄。物理キーの英字を字母にして（keymap）、ハングルに組み立てて（composer）見せる。

   日本語や英語の入力モードのまま打てるように、ブラウザの IME は使わず keydown を自分で受ける。
   そのため <input> ではなく div に描き、フォーカスは透明な <input> で受ける（キーイベントとフォーカスの枠のため）。
   持つのは「打った字母の列」（jamos）だけ。表示は毎回 composer.compose() で作る。

   TypingField.create(container, { keymap, composer, keyboard, onSubmit, onChange })
     → { value(), jamos(), reset(), setTarget(text), focus(), setEnabled(on), element } */
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
    const text = document.createElement("span");
    text.className = "tf-text";
    const caret = document.createElement("span");
    caret.className = "tf-caret";
    const hint = document.createElement("span");
    hint.className = "tf-placeholder";
    hint.textContent = placeholder;
    view.append(text, caret, hint);
    container.append(view, input);

    let jamos = [];
    let target = null; // なぞりのとき: 打つべき字母の列
    let enabled = true;

    function value() {
      return composer.compose(jamos);
    }

    function render() {
      const composed = value();
      if (target) {
        renderTrace(composed);
      } else {
        text.textContent = composed;
      }
      hint.hidden = composed.length > 0;
      updateGuide();
      onChange(composed);
    }

    /** なぞり: 目標と一致している部分と、違っている部分を色分けする */
    function renderTrace(composed) {
      const expected = composer.compose(target);
      let common = 0;
      while (common < composed.length && common < expected.length && composed[common] === expected[common]) common += 1;
      // 組み立て途中の最後の音節は、目標の字母の列の途中なら「合っている」とみなす
      const typedPrefixOk = jamosMatchPrefix();
      text.replaceChildren();
      const ok = document.createElement("span");
      ok.className = "tf-ok";
      ok.textContent = typedPrefixOk ? composed : composed.slice(0, common);
      text.append(ok);
      if (!typedPrefixOk) {
        const bad = document.createElement("span");
        bad.className = "tf-bad";
        bad.textContent = composed.slice(common);
        text.append(bad);
      }
      const rest = document.createElement("span");
      rest.className = "tf-rest";
      rest.textContent = typedPrefixOk ? expected.slice(composed.length) : "";
      text.append(rest);
    }

    function jamosMatchPrefix() {
      if (!target) return true;
      if (jamos.length > target.length) return false;
      return jamos.every((j, i) => j === target[i]);
    }

    function updateGuide() {
      if (!keyboard) return;
      if (!target || !jamosMatchPrefix()) {
        keyboard.guide(jamos.length && target ? "backspace" : null);
        if (target && jamos.length && !jamosMatchPrefix()) keyboard.guide("backspace");
        return;
      }
      const next = target[jamos.length];
      if (next === undefined) {
        keyboard.guide("enter");
        return;
      }
      const key = keymap.keyOf(next);
      if (key) keyboard.guide(key.key, key.shift);
      else keyboard.guide(next === " " ? " " : null);
    }

    function onKeyDown(event) {
      if (!enabled) return;
      if (keyboard) {
        keyboard.pressed(event.key, true);
        keyboard.setShift(event.shiftKey);
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "Enter") {
        event.preventDefault();
        onSubmit(value());
        return;
      }
      if (event.key === "Backspace") {
        event.preventDefault();
        jamos.pop();
        render();
        return;
      }
      if (event.key === " ") {
        event.preventDefault();
        jamos.push(" ");
        render();
        return;
      }
      if (event.key === "Shift" || event.key === "Tab" || event.key === "Escape") return;
      const jamo = keymap.jamoOf(event.key, event.shiftKey);
      if (jamo) {
        event.preventDefault();
        jamos.push(jamo);
        render();
        return;
      }
      // ハングルをそのまま貼り付けたときや、記号（. ? !）はそのまま入れる
      if (event.key.length === 1) {
        event.preventDefault();
        if (composer.isSyllable(event.key)) jamos.push(...composer.decompose(event.key));
        else jamos.push(event.key);
        render();
      }
    }

    function onKeyUp(event) {
      if (!keyboard) return;
      keyboard.pressed(event.key, false);
      keyboard.setShift(event.shiftKey);
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
      const pasted = (event.clipboardData || window.clipboardData).getData("text");
      jamos.push(...composer.decompose(pasted));
      render();
    });
    view.addEventListener("mousedown", (event) => {
      event.preventDefault();
      input.focus();
    });

    function reset() {
      jamos = [];
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

    render();
    return { value, jamos: () => [...jamos], reset, setTarget, focus, setEnabled, element: container, isComplete: () => target !== null && jamos.length === target.length && jamosMatchPrefix() };
  }

  return { create };
})();
