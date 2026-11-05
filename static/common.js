/* すべての画面で使う小さな道具: API の呼び出し、API の版の確認、上部のナビ、言語のパック、アイコン。

   言語ごとの画面（<body data-scope="language">）は、URL の最初の部分（/ko/learn の ko）を言語として読む。
   HTML のリンクには /ko/... を書いておき（JS が動く前もたどれるように）、data-lang-path を持つリンクを
   applyLanguage() が今の言語の URL に書き換える。 */
"use strict";

const REQUIRED_API_VERSION = 5;

const LANGUAGE = document.body.dataset.scope === "language" ? decodeURIComponent(location.pathname.split("/")[1] || "") : null;

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
  /** ジョブ（AI の採点など）が終わるまで待って結果を返す。失敗したら ApiError を投げる */
  async waitJob(job, intervalMs = 500) {
    while (job.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      job = await api.get(`/api/jobs/${encodeURIComponent(job.id)}`);
    }
    if (job.status === "error") throw new ApiError(job.error || "失敗しました", 500, job);
    return job.result;
  },
};

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/* 言語の画面側のパック（キー配列、組み立て）。static/langs/<言語>/pack.js が登録する */
const LANGUAGE_PACKS = {};

function registerLanguagePack(code, pack) {
  LANGUAGE_PACKS[code] = { code, ...pack };
}

function languagePack(code) {
  const pack = LANGUAGE_PACKS[code];
  if (!pack) throw new Error(`この言語の画面の部品がありません: ${code}`);
  return pack;
}

/** /api/meta を読み、API の版を確かめる。言語ごとの画面では、今の言語の情報（表示名・読み上げの言語）も返す */
async function loadMeta() {
  let meta;
  try {
    meta = await api.get("/api/meta");
  } catch (err) {
    toast(`サーバーに接続できません: ${err.message}`, { type: "error" });
    return null;
  }
  if (meta.api_version !== REQUIRED_API_VERSION) {
    toast("サーバーが古い版のままです。langlang serve を Ctrl+C して起動し直してください", { type: "error", sticky: true });
  }
  meta.current = LANGUAGE ? meta.languages.find((l) => l.code === LANGUAGE) || null : null;
  if (meta.current) applyLanguage(meta.current);
  markCurrentNav();
  return meta;
}

function applyLanguage(language) {
  for (const link of document.querySelectorAll("[data-lang-path]")) {
    const sub = link.dataset.langPath;
    const query = link.dataset.langQuery;
    link.href = `/${encodeURIComponent(language.code)}${sub ? `/${sub}` : ""}${query ? `?${query}` : ""}`;
  }
  for (const node of document.querySelectorAll("[data-lang-label]")) node.textContent = language.label;
  for (const link of document.querySelectorAll("[data-settings-link]")) link.href = `/settings?language=${encodeURIComponent(language.code)}`;
  const title = document.querySelector("title");
  if (title && title.dataset.page) title.textContent = `${title.dataset.page} – ${language.label} – langlang`;
}

function markCurrentNav() {
  const here = location.pathname.replace(/\/$/, "") || "/";
  for (const link of document.querySelectorAll(".nav a")) {
    const target = new URL(link.href, location.href).pathname.replace(/\/$/, "") || "/";
    if (target === here) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

/** 言語ごとの画面の URL */
function languageUrl(sub = "", query = "") {
  const path = `/${encodeURIComponent(LANGUAGE)}${sub ? `/${sub}` : ""}`;
  return query ? `${path}?${query}` : path;
}

/* 線で描くアイコン。絵文字は OS で見た目が変わり、大きくするとぼやけるので使わない */
const ICONS = {
  speaker: '<path d="M4 9.5h3l4.5-4v13L7 14.5H4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/><path d="M18.5 6.5a8 8 0 0 1 0 11"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
};

function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
  return t.content.firstChild;
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
