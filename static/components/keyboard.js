/* 画面のキーボード。押したキーが沈む表示と、次に押すキーのガイド（なぞりタイピング）を出す。

   入力そのものは受け持たない（typing-field.js が keydown を受けて字母を組み立てる）。
   ここは見せるだけ: Keyboard.create(container, keymap) → { pressed(key, down), guide(key, shift), setShift(on), showLatin(on) } */
"use strict";

const Keyboard = (() => {
  // 特別なキーの幅は style.css が段のずれと合わせて決める
  const SPECIAL = {
    shiftL: { label: "Shift", key: "shift" },
    shiftR: { label: "Shift", key: "shift" },
    backspace: { label: "⌫", key: "backspace" },
    enter: { label: "⏎", key: "enter" },
    space: { label: "space", key: " " },
  };

  function create(container, keymap) {
    container.classList.add("kbd");
    container.setAttribute("aria-hidden", "true");
    const keys = new Map();
    let shiftOn = false;

    const makeKey = (key, { label, latin } = {}) => {
      const el = document.createElement("div");
      el.className = "kbd-key";
      el.dataset.key = key;
      const main = document.createElement("span");
      main.className = "kbd-main";
      main.textContent = label || "";
      el.append(main);
      if (latin) {
        const sub = document.createElement("span");
        sub.className = "kbd-latin";
        sub.textContent = latin;
        el.append(sub);
      }
      keys.set(key, el);
      return el;
    };

    const rows = [
      ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "backspace"],
      ["a", "s", "d", "f", "g", "h", "j", "k", "l", "enter"],
      ["shiftL", "z", "x", "c", "v", "b", "n", "m", "shiftR"],
      ["space"],
    ];
    for (const row of rows) {
      const rowEl = document.createElement("div");
      rowEl.className = "kbd-row";
      for (const key of row) {
        if (SPECIAL[key]) {
          const spec = SPECIAL[key];
          const el = makeKey(key, { label: spec.label });
          el.classList.add("kbd-special");
          el.dataset.role = spec.key;
          rowEl.append(el);
        } else {
          rowEl.append(makeKey(key, { label: keymap.BASE[key], latin: key }));
        }
      }
      container.append(rowEl);
    }

    function relabel() {
      for (const [key, el] of keys) {
        if (SPECIAL[key]) continue;
        el.querySelector(".kbd-main").textContent = (shiftOn && keymap.SHIFTED[key]) || keymap.BASE[key];
        el.classList.toggle("kbd-shifted", shiftOn && Boolean(keymap.SHIFTED[key]));
      }
      for (const name of ["shiftL", "shiftR"]) keys.get(name).classList.toggle("kbd-active", shiftOn);
    }

    function setShift(on) {
      if (shiftOn === on) return;
      shiftOn = on;
      relabel();
    }

    /** 物理キーの keydown / keyup を見せる。key は KeyboardEvent.key */
    function pressed(key, down) {
      const targets = [];
      const lower = key.length === 1 ? key.toLowerCase() : key;
      if (keys.has(lower)) targets.push(keys.get(lower));
      else if (key === "Shift") targets.push(keys.get("shiftL"), keys.get("shiftR"));
      else if (key === "Backspace") targets.push(keys.get("backspace"));
      else if (key === "Enter") targets.push(keys.get("enter"));
      else if (key === " ") targets.push(keys.get("space"));
      for (const el of targets) el.classList.toggle("kbd-down", down);
    }

    /** 次に押すキーを光らせる。null で消す。shift が要るときは Shift も光らせる */
    function guide(key, shift = false) {
      for (const el of keys.values()) el.classList.remove("kbd-guide");
      if (!key) return;
      const target = key === " " ? keys.get("space") : keys.get(key);
      if (target) target.classList.add("kbd-guide");
      if (shift) for (const name of ["shiftL", "shiftR"]) keys.get(name).classList.add("kbd-guide");
    }

    function showLatin(on) {
      container.classList.toggle("kbd-no-latin", !on);
    }

    return { pressed, guide, setShift, showLatin, element: container };
  }

  return { create };
})();
