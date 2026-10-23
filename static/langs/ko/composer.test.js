"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { compose, decompose } = require("./composer.js");
const Keymap = require("./keymap.js");

const type = (letters) => compose([...letters].map((ch) => Keymap.jamoOf(ch, ch !== ch.toLowerCase()) ?? ch));

test("基本の音節を組み立てる", () => {
  assert.equal(type("rk"), "가");
  assert.equal(type("rkdy"), "가요");
  assert.equal(type("gksrnr"), "한국");
});

test("終声は次の母音が来たら初声に移る", () => {
  assert.equal(type("rkd"), "강");
  assert.equal(type("rkdy"), "가요");
  assert.equal(type("dkswk"), "안자");
});

test("複合母音と複合終声", () => {
  assert.equal(type("dhk"), "와");
  assert.equal(type("dnjs"), "원");
  assert.equal(type("dlfr"), "읽");
  assert.equal(type("dlfrdj"), "읽어");
  assert.equal(type("ekfrl"), "달기");
  assert.equal(type("dksgdk"), "않아");
});

test("Shift で濃音と ㅒㅖ", () => {
  assert.equal(type("Qkd"), "빵");
  assert.equal(type("rkTdj"), "갔어");
  assert.equal(type("dP"), "예");
});

test("単独の字母と空白", () => {
  assert.equal(type("r"), "ㄱ");
  assert.equal(type("rr"), "ㄱㄱ");
  assert.equal(type("k"), "ㅏ");
  assert.equal(type("rk dy"), "가 요");
  assert.equal(compose(["ㄱ", "ㅏ", ".", "ㅇ", "ㅛ"]), "가.요");
});

test("分解して組み立てると元に戻る", () => {
  for (const text of ["안녕하세요", "저는 다나카예요.", "만나서 반갑습니다", "읽었어요", "괜찮아요", "의사", "ㅘ"]) {
    assert.equal(compose(decompose(text)), text, text);
  }
});

test("分解は複合字母を 2 つに分ける", () => {
  assert.deepEqual(decompose("와"), ["ㅇ", "ㅗ", "ㅏ"]);
  assert.deepEqual(decompose("읽"), ["ㅇ", "ㅣ", "ㄹ", "ㄱ"]);
  assert.deepEqual(decompose("a 가"), ["a", " ", "ㄱ", "ㅏ"]);
});

test("字母からキーを引ける", () => {
  assert.deepEqual(Keymap.keyOf("ㅃ"), { key: "q", shift: true });
  assert.deepEqual(Keymap.keyOf("ㅏ"), { key: "k", shift: false });
  assert.equal(Keymap.keyOf("ㅘ"), null);
  assert.equal(Keymap.jamoOf("Enter", false), null);
});
