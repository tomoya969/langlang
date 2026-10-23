/* 右下の通知（トースト）。情報と成功は下端の線が縮みきったら消える。マウスを乗せている間とフォーカスがある間は止まる。
   止めるのも数え直すのも style.css の .toast-timer のアニメーションが行い、ここは縮みきったとき（animationend）に消すだけ。
   エラーと sticky は × を押すまで残す。 */
"use strict";

function toast(text, { type = "info", sticky = false } = {}) {
  const box = document.createElement("div");
  box.className = `toast ${type}`;
  if (type === "error") box.setAttribute("role", "alert");
  const message = document.createElement("span");
  message.textContent = text;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "閉じる");
  close.textContent = "×";
  close.addEventListener("click", () => box.remove());
  box.append(message, close);
  if (!sticky && type !== "error") {
    const timer = document.createElement("span");
    timer.className = "toast-timer";
    timer.setAttribute("aria-hidden", "true");
    timer.addEventListener("animationend", () => box.remove());
    box.append(timer);
  }
  document.getElementById("toasts").append(box);
  return box;
}
