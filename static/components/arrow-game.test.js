"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const G = require("./arrow-game.js");

const items = () => [{ id: "a" }, { id: "b" }, { id: "c" }];

test("正解は終わった側へ、不正解は最後尾へ", () => {
  const s = G.createQueue(items());
  G.answer(s, true);
  assert.deepEqual(s.queue.map((i) => i.id), ["b", "c"]);
  G.answer(s, false);
  assert.deepEqual(s.queue.map((i) => i.id), ["c", "b"]);
  assert.equal(s.retries, 1);
  G.answer(s, true);
  G.answer(s, true);
  assert.ok(G.isDone(s));
  assert.deepEqual(G.progress(s), { done: 3, total: 3, remaining: 0 });
});

test("評価に残るのは最初の解答だけ", () => {
  const s = G.createQueue(items());
  G.answer(s, false, { elapsed: 5 });
  G.answer(s, true);
  G.answer(s, true);
  G.answer(s, true); // a の 2 回目
  assert.deepEqual(s.first.get("a"), { correct: false, elapsed: 5 });
  assert.equal(s.first.size, 3);
});

test("見ただけ（初見カード）は評価に残らない", () => {
  const s = G.createQueue([{ id: "intro" }]);
  G.answer(s, null);
  assert.equal(s.first.size, 0);
  assert.ok(G.isDone(s));
});

test("選択肢は 4 方向に 1 つずつ置かれる", () => {
  const placed = G.placeOptions([1, 2, 3, 4], () => 0.99);
  assert.deepEqual(new Set(Object.values(placed)), new Set([1, 2, 3, 4]));
  assert.deepEqual(Object.keys(placed), ["up", "right", "down", "left"]);
  const three = G.placeOptions([1, 2, 3], () => 0);
  assert.equal(Object.values(three).filter((v) => v === null).length, 1);
});

test("反応時間から評価を決める", () => {
  assert.equal(G.rate(false, 1), "again");
  assert.equal(G.rate(true, 1), "easy");
  assert.equal(G.rate(true, 2), "good");
  assert.equal(G.rate(true, 5), "hard");
});
