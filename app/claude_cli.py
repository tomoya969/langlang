"""`claude -p` を subprocess で呼ぶ唯一の場所（suburi から移植）。

差し替えポイント: `claude -p` が使えなくなったら、このモジュールの `ask()` の中身だけを入れ替える。
呼び出し側は prompt と JSON スキーマを渡して dict（スキーマどおりの結果）を受け取るだけで、呼び方には依存しない。

呼ばれた側の Claude には何もさせず、JSON を返すだけにする:

- `--tools ""`                 組み込みツール（ファイル編集、コマンド実行など）をすべて無効化
- `--strict-mcp-config`        `--mcp-config` を渡さないので MCP サーバーも無効化
- `--disable-slash-commands`   スキルを無効化
- `--system-prompt`            Claude Code 既定のシステムプロンプトを短い役割説明に置き換える
- `--no-session-persistence`   セッションをディスクに残さない
- cwd を空の一時ディレクトリにして、リポジトリの CLAUDE.md や設定を読ませない

モデルは必ず `--model` で明示する。claude の既定のモデルはアカウントや版で変わり、Pro プランの利用枠に
入らない（追加課金になる）モデルが選ばれることもあるため。
優先順位は「用途別の環境変数 > 全体の環境変数 > 用途別の既定 > opus」。

用途（purpose）と既定:

- `tag`      語彙候補の粗い付与。量が多いので速さを優先（sonnet / low）
- `enrich`   詳しい付与と文の生成。事前に作るので質を優先（opus / claude の既定）
- `verify`   教材の検算。誤りを見逃さないため（opus / medium）
- `grade`    採点（機械で決まらなかった答え）。学習中なので速さを優先（sonnet / low）
- `explain`  解説。誤りを教えないよう正確さを優先し、保存して使い回す（opus / medium）

環境変数:

- `LANGLANG_CLAUDE_BIN`      使うバイナリ。未設定なら PATH 上の `claude`
- `LANGLANG_CLAUDE_MODEL`    すべての用途のモデル（例: sonnet、opus）
- `LANGLANG_CLAUDE_EFFORT`   すべての用途の effort（low / medium / high / xhigh / max）
- `LANGLANG_<用途>_MODEL` / `LANGLANG_<用途>_EFFORT`  用途だけの上書き（TAG / ENRICH / VERIFY / GRADE / EXPLAIN）
- 値を `default` にすると、モデルはアプリの既定（上の優先順位で次の候補）、effort は claude の既定に戻る
- `ANTHROPIC_API_KEY`        設定されていたら中断する（API 課金に切り替わるため）

失敗したときの ClaudeError は、str() が画面に出せる短い文（認証切れなら /login の案内など）、
`detail` が claude の生の出力（ログや折りたたみ表示用）、`kind` が失敗の種類（教材づくりで、
やり直すか止めるかを決めるのに使う）。
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.prompts import SYSTEM_PROMPT

log = logging.getLogger("langlang.claude")

ENV_BIN = "LANGLANG_CLAUDE_BIN"
ENV_MODEL = "LANGLANG_CLAUDE_MODEL"
ENV_EFFORT = "LANGLANG_CLAUDE_EFFORT"
ENV_API_KEY = "ANTHROPIC_API_KEY"
DEFAULT_TIMEOUT_SEC = 600

USE_CLAUDE_DEFAULT = "default"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Fable は Pro プランの利用枠に入らず追加課金になるので、既定にしない
DEFAULT_MODEL = "opus"
EXTRA_BILLING_MODELS = ("fable",)

PURPOSES = ("tag", "enrich", "verify", "grade", "explain")
PURPOSE_ENV = {p: (f"LANGLANG_{p.upper()}_MODEL", f"LANGLANG_{p.upper()}_EFFORT") for p in PURPOSES}
PURPOSE_DEFAULTS: dict[str, tuple[str, str | None]] = {
    "tag": ("sonnet", "low"),
    "enrich": (DEFAULT_MODEL, None),
    "verify": (DEFAULT_MODEL, "medium"),
    "grade": ("sonnet", "low"),
    "explain": (DEFAULT_MODEL, "medium"),
}

AskFn = Callable[[str, dict], dict[str, Any]]


KIND_AUTH = "auth"
KIND_USAGE_LIMIT = "usage_limit"
KIND_OVERLOADED = "overloaded"
KIND_MODEL = "model"
KIND_NETWORK = "network"
# 時間をおくか設定を直すまで、何度呼んでも失敗する種類
STOPPING_KINDS = (KIND_AUTH, KIND_USAGE_LIMIT, KIND_MODEL)


class ClaudeError(Exception):
    """claude の呼び出しに失敗した。str() は画面に出せる短い文、detail は生の出力（なければ None）、
    kind は失敗の種類（KIND_*。分からなければ None）。"""

    def __init__(self, message: str, detail: str | None = None, kind: str | None = None):
        super().__init__(message)
        self.detail = detail
        self.kind = kind


@dataclass(frozen=True)
class ClaudeSettings:
    model: str
    effort: str | None


def settings_for(purpose: str) -> ClaudeSettings:
    """用途に応じたモデルと effort を決める。モデルは必ず決まる（None にならない）。"""
    env_model, env_effort = PURPOSE_ENV.get(purpose, (None, None))
    default_model, default_effort = PURPOSE_DEFAULTS.get(purpose, (DEFAULT_MODEL, None))
    model = _env(env_model) or _env(ENV_MODEL) or default_model or DEFAULT_MODEL
    effort = _pick(env_effort, ENV_EFFORT, default_effort)
    if effort is not None and effort not in EFFORT_LEVELS:
        raise ClaudeError(f"effort は {', '.join(EFFORT_LEVELS)} のいずれかです: {effort}")
    return ClaudeSettings(model=model, effort=effort)


def ask_for(purpose: str) -> AskFn:
    """用途に応じた設定を固定した ask() を返す。"""
    settings = settings_for(purpose)
    return functools.partial(ask, model=settings.model, effort=settings.effort)


def resolve_binary() -> str:
    custom = os.environ.get(ENV_BIN)
    if custom:
        path = Path(custom).expanduser()
        if not path.is_file():
            raise ClaudeError(f"{ENV_BIN} のパスが見つかりません: {custom}")
        return str(path)
    found = shutil.which("claude")
    if not found:
        raise ClaudeError(
            "claude コマンドが見つかりません。ネイティブ版 Claude Code をインストールするか、"
            f"{ENV_BIN} でバイナリの場所を指定してください"
        )
    return found


def build_command(
    binary: str, schema: dict[str, Any], model: str | None = None, effort: str | None = None
) -> list[str]:
    """`claude -p` のコマンドラインを組み立てる。プロンプトは stdin で渡す。"""
    cmd = [
        binary,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False),
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        SYSTEM_PROMPT,
    ]
    cmd += ["--model", model or DEFAULT_MODEL]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def ask(
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str | None = None,
    effort: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """prompt を claude に渡し、schema どおりの結果（structured_output）を dict で返す。"""
    if os.environ.get(ENV_API_KEY):
        raise ClaudeError(
            f"{ENV_API_KEY} が設定されています。API 課金に切り替わるため中断します。"
            "unset してから実行してください"
        )
    binary = resolve_binary()
    model = model or _env(ENV_MODEL) or DEFAULT_MODEL
    effort = effort or _env(ENV_EFFORT)
    if any(name in model.lower() for name in EXTRA_BILLING_MODELS):
        log.warning("モデル %s は Pro プランの利用枠に入らず、追加課金になります", model)
    if effort is not None and effort not in EFFORT_LEVELS:
        raise ClaudeError(f"effort は {', '.join(EFFORT_LEVELS)} のいずれかです: {effort}")
    cmd = build_command(binary, schema, model, effort)

    log.info(
        "claude を起動: %s（model=%s、effort=%s、プロンプト %d 文字、タイムアウト %d 秒）",
        binary, model, effort or "既定", len(prompt), timeout,
    )
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="langlang-claude-") as cwd:
        try:
            proc = subprocess.run(cmd, input=prompt, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except OSError as exc:
            log.error("claude を起動できません: %s", exc)
            raise ClaudeError(f"claude を起動できませんでした: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            log.error("claude がタイムアウト（%d 秒）", timeout)
            raise ClaudeError(f"claude が {timeout} 秒以内に応答しませんでした") from exc

    elapsed = time.monotonic() - started
    log.info("claude 終了: code=%d 所要=%.1f 秒 出力=%d 文字", proc.returncode, elapsed, len(proc.stdout))
    if proc.returncode != 0:
        raw = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
        log.error("claude の失敗出力:\n%s", raw[:4000])
        raise failure(f"claude が終了コード {proc.returncode} で失敗しました", raw)
    return parse_result(proc.stdout)


def parse_result(stdout: str) -> dict[str, Any]:
    """`--output-format json` の出力から structured_output を取り出す。"""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise failure("claude の出力が JSON ではありません", stdout) from exc
    # 古い版は複数メッセージの配列で返すことがあるので、result メッセージを探す
    if isinstance(data, list):
        results = [m for m in data if isinstance(m, dict) and m.get("type") == "result"]
        data = results[-1] if results else {}
    if not isinstance(data, dict):
        raise failure("claude の出力の形が想定と違います", stdout)
    if data.get("is_error"):
        raise failure("claude がエラーを返しました", stdout)
    structured = data.get("structured_output")
    if not isinstance(structured, dict):
        raise failure("claude の応答に結果（structured_output）がありません", stdout)
    return structured


# ---- 失敗の説明 ----

_FAILURE_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"failed to authenticate|authentication_error|invalid api key|oauth token has expired"
            r"|not logged in|please run /login|\b401\b",
            re.IGNORECASE,
        ),
        KIND_AUTH,
        "claude にログインしていないか、ログインの期限が切れています。ターミナルで claude を起動して /login してください",
    ),
    (
        re.compile(r"usage limit|rate[ _]limit|limit reached|\b429\b", re.IGNORECASE),
        KIND_USAGE_LIMIT,
        "Claude の利用枠の上限に達しました。上限がリセットされてから、もう一度実行してください",
    ),
    (
        re.compile(r"overloaded|\b529\b", re.IGNORECASE),
        KIND_OVERLOADED,
        "Anthropic のサーバーが混み合っています。少し待ってから、もう一度実行してください",
    ),
    (
        re.compile(r"not_found_error|model.{0,40}(not found|not available|invalid)|invalid model", re.IGNORECASE),
        KIND_MODEL,
        "指定したモデルを使えません。LANGLANG_CLAUDE_MODEL などのモデルの設定を確認してください",
    ),
    (
        re.compile(r"ENOTFOUND|ECONNREFUSED|ETIMEDOUT|connection error|fetch failed|network", re.IGNORECASE),
        KIND_NETWORK,
        "Anthropic に接続できません。ネットワークを確認してください",
    ),
]


def explain_failure(raw: str) -> str | None:
    found = _classify(raw)
    return found[1] if found else None


def _classify(raw: str) -> tuple[str, str] | None:
    for pattern, kind, hint in _FAILURE_HINTS:
        if pattern.search(raw):
            return kind, hint
    return None


def failure(what: str, raw: str) -> ClaudeError:
    """生の出力を detail に残し、画面向けには短い文だけを持つ ClaudeError を作る。"""
    raw = (raw or "").strip()
    summary = _result_text(raw) or raw
    found = _classify(summary) or _classify(raw)
    if found:
        kind, message = found
    else:
        kind = None
        message = f"{what}: {_one_line(summary, 160)}" if summary else what
    return ClaudeError(message, detail=raw[:4000] or None, kind=kind)


# ---- helpers ----


def _result_text(raw: str) -> str:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ""
    if isinstance(data, list):
        results = [m for m in data if isinstance(m, dict) and m.get("type") == "result"]
        data = results[-1] if results else {}
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        return data["result"].strip()
    return ""


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit] + "…"


def _env(name: str | None) -> str | None:
    """環境変数を読む。未設定・空・'default' は None。"""
    if not name:
        return None
    value = os.environ.get(name, "").strip()
    if not value or value == USE_CLAUDE_DEFAULT:
        return None
    return value


def _pick(purpose_env: str | None, global_env: str, default: str | None) -> str | None:
    """effort を、用途別の環境変数 > 全体の環境変数 > 用途別の既定、の順で決める。

    環境変数が明示的に 'default' のときは、既定も使わず claude の既定に戻す。
    """
    for name in (purpose_env, global_env):
        if name and os.environ.get(name, "").strip():
            return _env(name)
    return default
