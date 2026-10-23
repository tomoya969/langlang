from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from app import claude_cli
from app.claude_cli import ClaudeError, ask, build_command, parse_result, settings_for
from app.prompts import SYSTEM_PROMPT

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def make_fake_claude(tmp_path: Path, stdout: str, exit_code: int = 0) -> Path:
    script = tmp_path / "fake-claude"
    log = tmp_path / "fake-claude.log"
    stdin_file = tmp_path / "fake-claude.stdin"
    quoted = stdout.replace("'", "'\\''")
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > '{log}'\n"
        f"cat > '{stdin_file}'\n"
        f"printf '%s' '{quoted}'\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (claude_cli.ENV_API_KEY, claude_cli.ENV_BIN, claude_cli.ENV_MODEL, claude_cli.ENV_EFFORT):
        monkeypatch.delenv(name, raising=False)
    for model_env, effort_env in claude_cli.PURPOSE_ENV.values():
        monkeypatch.delenv(model_env, raising=False)
        monkeypatch.delenv(effort_env, raising=False)


def test_abort_when_api_key_is_set(monkeypatch):
    monkeypatch.setenv(claude_cli.ENV_API_KEY, "sk-ant-dummy")
    with pytest.raises(ClaudeError, match="ANTHROPIC_API_KEY"):
        ask("hi", SCHEMA)


def test_build_command_disables_tools_and_sets_model():
    cmd = build_command("/bin/claude", SCHEMA, model="sonnet", effort="low")
    assert cmd[:2] == ["/bin/claude", "-p"]
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert "--no-session-persistence" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == SYSTEM_PROMPT
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--effort") + 1] == "low"
    assert "--bare" not in cmd


def test_settings_for_purposes(monkeypatch):
    assert settings_for("tag") == claude_cli.ClaudeSettings("sonnet", "low")
    assert settings_for("enrich") == claude_cli.ClaudeSettings("opus", None)
    monkeypatch.setenv(claude_cli.ENV_MODEL, "haiku")
    assert settings_for("grade").model == "haiku"
    monkeypatch.setenv("LANGLANG_GRADE_MODEL", "opus")
    monkeypatch.setenv("LANGLANG_GRADE_EFFORT", "default")
    assert settings_for("grade") == claude_cli.ClaudeSettings("opus", None)


def test_ask_parses_structured_output(tmp_path, monkeypatch):
    out = json.dumps({"type": "result", "is_error": False, "structured_output": {"answer": "ok"}})
    fake = make_fake_claude(tmp_path, out)
    monkeypatch.setenv(claude_cli.ENV_BIN, str(fake))
    assert ask("prompt text", SCHEMA, model="sonnet") == {"answer": "ok"}
    assert (tmp_path / "fake-claude.stdin").read_text(encoding="utf-8") == "prompt text"
    args = (tmp_path / "fake-claude.log").read_text(encoding="utf-8").splitlines()
    assert "--model" in args and args[args.index("--model") + 1] == "sonnet"


def test_ask_failure_is_short_message_with_detail(tmp_path, monkeypatch):
    fake = make_fake_claude(tmp_path, "Failed to authenticate. Please run /login", exit_code=1)
    monkeypatch.setenv(claude_cli.ENV_BIN, str(fake))
    with pytest.raises(ClaudeError) as info:
        ask("x", SCHEMA)
    assert "/login" in str(info.value)
    assert "Failed to authenticate" in info.value.detail


def test_parse_result_errors():
    with pytest.raises(ClaudeError, match="JSON ではありません"):
        parse_result("not json")
    with pytest.raises(ClaudeError, match="structured_output"):
        parse_result(json.dumps({"type": "result", "result": "text only"}))
    with pytest.raises(ClaudeError, match="利用枠"):
        parse_result(json.dumps({"type": "result", "is_error": True, "result": "usage limit reached"}))
