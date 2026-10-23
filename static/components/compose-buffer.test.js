"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const B = require("./compose-buffer.js");
const composer = require("../langs/ko/composer.js");
const keymap = require("../langs/ko/keymap.js");

function typeKeys(state, letters) {
  for (const ch of letters) {
    const jamo = keymap.jamoOf(ch, ch !== ch.toLowerCase());
    if (jamo) B.typeJamo(state, jamo);
    else B.insertText(state, ch);
  }
}

function make(letters) {
  const s = B.create(composer);
  typeKeys(s, letters);
  return s;
}

test("末尾に打つと今までどおり組み立てる", () => {
  const s = make("gkrtoddldpdy");
  assert.equal(B.value(s), "학생이에요");
  assert.ok(B.atEnd(s));
});

test("組み立て中なのは最後の音節だけ", () => {
  const s = make("rkd");
  assert.deepEqual(B.parts(s), { before: "", composing: "강", after: "" });
  typeKeys(s, "k");
  assert.deepEqual(B.parts(s), { before: "가", composing: "아", after: "" });
});

test("← で戻って 1 字母だけ直す（애 → 에）", () => {
  const s = make("gkrtoddldody"); // 학생이애요
  assert.equal(B.value(s), "학생이애요");
  B.left(s); // 요 の前へ
  assert.deepEqual(B.parts(s), { before: "학생이애", composing: "", after: "요" });
  B.backspace(s); // 애 → ㅇ
  assert.deepEqual(B.parts(s), { before: "학생이", composing: "ㅇ", after: "요" });
  typeKeys(s, "p"); // ㅔ
  assert.equal(B.value(s), "학생이에요");
  B.end(s);
  assert.ok(B.atEnd(s));
  assert.equal(B.value(s), "학생이에요");
});

test("途中に音節を足しても後ろの文字とくっつかない", () => {
  const s = make("dkdy"); // 아요
  B.home(s);
  typeKeys(s, "rk"); // 가
  assert.equal(B.value(s), "가아요");
  typeKeys(s, "d"); // 강（組み立て中の音節だけが変わる）
  assert.equal(B.value(s), "강아요");
});

test("Backspace は字母を 1 つずつ消す", () => {
  const s = make("dhk"); // 와
  B.backspace(s);
  assert.equal(B.value(s), "오");
  B.backspace(s);
  assert.equal(B.value(s), "ㅇ");
  B.backspace(s);
  assert.equal(B.value(s), "");
  B.backspace(s);
  assert.equal(B.value(s), "");
});

test("確定した文字の上の Backspace（複合終声）", () => {
  const s = make("dlfr dl"); // 읽 이
  B.setCaret(s, 1); // 읽 の後ろ
  B.backspace(s);
  assert.equal(B.value(s), "일 이");
});

test("Delete はカーソルの後ろを消す", () => {
  const s = make("rkdy");
  B.home(s);
  B.deleteForward(s);
  assert.equal(B.value(s), "요");
});

test("空白と記号はカーソルの位置に入る", () => {
  const s = make("rkdy");
  B.left(s);
  B.insertText(s, " ");
  assert.equal(B.value(s), "가 요");
  B.end(s);
  B.insertText(s, ".");
  assert.equal(B.value(s), "가 요.");
});

test("カーソルは端からはみ出さない", () => {
  const s = make("rk");
  B.right(s);
  B.right(s);
  assert.ok(B.atEnd(s));
  B.home(s);
  B.left(s);
  assert.equal(s.caret, 0);
  B.setCaret(s, 99);
  assert.equal(s.caret, 1);
});
