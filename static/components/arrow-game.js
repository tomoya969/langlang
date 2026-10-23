/* 矢印ゲームの列（画面から切り離したロジック）。

   - 列の先頭を出題し、正解なら終わった側へ、不正解なら最後尾へ回す。列が空になったら終了
   - 1 問につき最初の解答だけを「評価」として残す（最後尾に回ったあとの正解は終了条件にだけ数える）
   - 選択肢の置き場所（上右下左）は出題のたびに決め直す（方向で答えを覚えないように） */
"use strict";

const ArrowGame = (() => {
  const DIRECTIONS = ["up", "right", "down", "left"];
  const KEY_TO_DIRECTION = { ArrowUp: "up", ArrowRight: "right", ArrowDown: "down", ArrowLeft: "left" };

  function createQueue(items) {
    return { queue: [...items], done: [], total: items.length, first: new Map(), retries: 0 };
  }

  function current(state) {
    return state.queue[0] || null;
  }

  function isDone(state) {
    return state.queue.length === 0;
  }

  function progress(state) {
    return { done: state.done.length, total: state.total, remaining: state.queue.length };
  }

  /** 先頭の問題に答える。correct=null は「見ただけ」（初見カード）。最初の解答だけ first に残す。 */
  function answer(state, correct, detail = {}) {
    const item = state.queue.shift();
    if (!item) return state;
    if (correct !== null && !state.first.has(item.id)) state.first.set(item.id, { correct, ...detail });
    if (correct === false) {
      state.queue.push(item);
      state.retries += 1;
    } else {
      state.done.push(item);
    }
    return state;
  }

  /** 選択肢を上右下左に割り当てる。rng は 0 以上 1 未満を返す関数 */
  function placeOptions(options, rng = Math.random) {
    const shuffled = [...options];
    for (let i = shuffled.length - 1; i > 0; i -= 1) {
      const j = Math.floor(rng() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    const placed = {};
    DIRECTIONS.forEach((dir, i) => {
      placed[dir] = shuffled[i] || null;
    });
    return placed;
  }

  /** 反応時間から評価を決める（docs/plan.md 4.4）。 */
  function rate(correct, elapsedSec, { fast = 1.5, slow = 4.0 } = {}) {
    if (!correct) return "again";
    if (elapsedSec < fast) return "easy";
    if (elapsedSec > slow) return "hard";
    return "good";
  }

  return { DIRECTIONS, KEY_TO_DIRECTION, createQueue, current, isDone, progress, answer, placeOptions, rate };
})();

if (typeof module !== "undefined") module.exports = ArrowGame;
