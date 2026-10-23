/* すべての画面で使う小さな道具: API の呼び出し、API の版の確認、上部のナビ、言語のパック。 */
"use strict";

const REQUIRED_API_VERSION = 1;
const LANGUAGE = "ko"; // 言語を足すときは URL か設定から決める

const api = {
  async get(path) {
    return api.request("GET", path);
  },
  async post(path, body) {
    return api.request("POST", path, body);
  },
  async put(path, body) {
    return api.request("PUT", path, body);
  },
  async request(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) {
      const detail = data && data.detail;
      const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("、") : `${res.status} ${res.statusText}`;
      throw new ApiError(message, res.status, data);
    }
    return data;
  },
};

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/** 言語の画面側のパック（キー配列、組み立て、読み上げの言語） */
function languagePack(code) {
  if (code === "ko") return { code, keymap: KoKeymap, composer: KoComposer, tts: "ko-KR" };
  throw new Error(`未対応の言語です: ${code}`);
}

async function checkApiVersion() {
  try {
    const meta = await api.get("/api/meta");
    if (meta.api_version !== REQUIRED_API_VERSION) {
      toast("サーバーが古い版のままです。langlang serve を Ctrl+C して起動し直してください", { type: "error" });
    }
    return meta;
  } catch (err) {
    toast(`サーバーに接続できません: ${err.message}`, { type: "error" });
    return null;
  }
}

function markCurrentNav() {
  const here = location.pathname.replace(/\/$/, "") || "/";
  for (const link of document.querySelectorAll(".nav a")) {
    const target = link.getAttribute("href").replace(/\/$/, "") || "/";
    if (target === here) link.setAttribute("aria-current", "page");
  }
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

document.addEventListener("DOMContentLoaded", markCurrentNav);
