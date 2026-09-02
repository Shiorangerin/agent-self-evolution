#!/usr/bin/env python3
"""Isolated smoke tests for hook registration and transcript normalization."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "scripts" / "hook_config.py"

spec = importlib.util.spec_from_file_location("hook_config", HELPER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 scripts/hook_config.py")
hook_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook_config)


def run(command: List[str], env: Dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def prepare_env(base: Path, fake_codex: bool = True) -> Tuple[Path, Path, Dict[str, str]]:
    base.mkdir(parents=True, exist_ok=True)
    home = base / "home"
    se_root = base / "se root & 'quote'"
    bin_dir = base / "bin"
    home.mkdir()
    bin_dir.mkdir()
    os.symlink(sys.executable, str(bin_dir / "python3"))
    if fake_codex:
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\necho fake codex failure >&2\nexit 42\n")
        codex.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "SE_ROOT": str(se_root),
            "PATH": os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]),
        }
    )
    return home, se_root, env


def codex_config(home: Path) -> Path:
    return home / ".codex" / "config.toml"


def codex_hook_path(se_root: Path) -> Path:
    return se_root / "platforms" / "codex" / "hooks" / "collect.sh"


def codex_legacy_paths(se_root: Path, home: Path) -> List[Path]:
    return [
        home / ".codex" / "hooks" / "collect.sh",
        home / ".codex" / "hooks" / "agent-self-evolution" / "collect.sh",
        Path.home() / ".config" / "agent-self-evolution" / "platforms" / "codex" / "hooks" / "collect.sh",
        codex_hook_path(se_root),
    ]


def claude_hook_path(home: Path) -> Path:
    return home / ".claude" / "hooks" / "agent-self-evolution" / "collect.sh"


def claude_commands(path: Path) -> List[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    commands = []
    for group, hook in hook_config.stop_hooks(data):
        commands.append(hook.get("command", ""))
    return commands


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_repository_urls() -> None:
    official = 0
    fork = 0
    for path in REPO_ROOT.rglob("*.md"):
        if not path.is_file() or ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        official += text.count(
            "https://github.com/Shiorangerin/agent-self-evolution.git"
        )
        fork += text.count("R03montia")
    require(official == 10, f"官方 clone URL 数量应为 10，实际 {official}")
    require(fork == 0, f"发现贡献者 fork 字符串 {fork} 次")
    print("✓ 仓库 URL 安全审计")


def test_normalize_codex(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    transcript = base / "codex-transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "assistant text"},
                                {
                                    "type": "function_call_output",
                                    "output": "nested tool output",
                                },
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "output": "top-level tool output",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "output": {"content": "structured tool output"},
                        },
                    }
                ),
                "not json",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run(
        [
            sys.executable,
            str(REPO_ROOT / "platforms" / "codex" / "hooks" / "normalize_codex.py"),
            str(transcript),
        ],
        os.environ.copy(),
    )
    require(result.returncode == 0, result.stderr)
    entries = [json.loads(line) for line in result.stdout.splitlines() if line]
    require(entries[0] == {"role": "assistant", "text": "assistant text"}, "嵌套 message 文本错误")
    require(entries[1] == {"role": "toolResult", "isError": False, "text": "nested tool output"}, "嵌套工具结果错误")
    require(entries[2]["text"] == "top-level tool output", "顶层工具结果错误")
    require(entries[3]["text"] == "structured tool output", "结构化工具结果错误")
    require(len(entries) == 4, f"归一化输出数量错误: {len(entries)}")
    print("✓ Codex transcript 归一化")


def test_codex_fresh_and_idempotent(base: Path) -> None:
    home, se_root, env = prepare_env(base)
    result = run(["bash", str(REPO_ROOT / "install.sh"), "codex"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    config = codex_config(home)
    hook = codex_hook_path(se_root)
    import tomllib

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    commands = [hook_item.get("command", "") for _, hook_item in hook_config.stop_hooks(data)]
    require(sum(hook_config.is_own_command(c, hook, codex_legacy_paths(se_root, home)) for c in commands) == 1, "Codex hook 数量错误")
    require(any(c == hook_config.shell_command(hook) for c in commands), "Codex 命令未使用引号安全路径")
    second = run(["bash", str(REPO_ROOT / "install.sh"), "codex"], env)
    require(second.returncode == 0, second.stdout + second.stderr)
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    commands = [hook_item.get("command", "") for _, hook_item in hook_config.stop_hooks(data)]
    require(len(commands) == 1, "重复安装产生了 Codex 重复 hook")
    print("✓ Codex fresh/idempotent 安装")


def test_codex_existing_and_bad_configs(base: Path) -> None:
    home, se_root, env = prepare_env(base)
    config = codex_config(home)
    config.parent.mkdir()
    config.write_text(
        """
        [features]
        hooks = true

        [[hooks.Stop]]
        hooks = [
          { type = "command", command = "echo keep-me", async = false }
        ]
        """,
        encoding="utf-8",
    )
    result = run(["bash", str(REPO_ROOT / "install.sh"), "codex"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    import tomllib

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    require(len(data["hooks"]["Stop"]) == 2, "合法其他 hook 场景未追加")

    hook = codex_hook_path(se_root)
    own_command = hook_config.shell_command(hook)
    config.write_text(
        f"""
        [[hooks.Stop]]
        hooks = [
          {{ type = "command", command = {hook_config.toml_basic_string(own_command)}, async = false }}
        ]
        """,
        encoding="utf-8",
    )
    result = run(["bash", str(REPO_ROOT / "install.sh"), "codex"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    require(len(data["hooks"]["Stop"]) == 1, "已有 Codex own hook 被重复注册")

    old_table = 'model = "test"\n\n[hooks.Stop]\ncommand = "legacy"\n'
    config.write_text(old_table, encoding="utf-8")
    result = run(["bash", str(REPO_ROOT / "install.sh"), "codex"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(config.read_text(encoding="utf-8") == old_table, "旧式 [hooks.Stop] 被修改")

    bad_toml = "this is not = [ valid\n"
    config.write_text(bad_toml, encoding="utf-8")
    result = run(["bash", str(REPO_ROOT / "install.sh"), "codex"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(config.read_text(encoding="utf-8") == bad_toml, "坏 TOML 被修改")
    print("✓ Codex existing/bad config 防护")


def test_claude_registration(base: Path) -> None:
    # Fresh install must use an absolute, namespaced path.
    home, se_root, env = prepare_env(base, fake_codex=False)
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    hook = claude_hook_path(home)
    settings = home / ".claude" / "settings.json"
    commands = claude_commands(settings)
    require(commands == [hook_config.shell_command(hook)], f"fresh Claude hook 错误: {commands}")
    require("${CLAUDE_PROJECT_DIR}" not in settings.read_text(encoding="utf-8"), "用户级配置残留占位符")

    # Existing generic file must never be overwritten.
    generic = home / ".claude" / "hooks" / "collect.sh"
    generic.write_text("user custom hook\n", encoding="utf-8")
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(generic.read_text(encoding="utf-8") == "user custom hook\n", "通用 collect.sh 被覆盖")

    # A similarly named user hook is not mistaken for this project's hook.
    settings.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["bash"]},
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash /opt/custom/hooks/collect.sh",
                                }
                            ]
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    commands = claude_commands(settings)
    require("bash /opt/custom/hooks/collect.sh" in commands, "用户自定义 hook 被误改")
    require(hook_config.shell_command(hook) in commands, "未注册本系统 hook")

    # Existing placeholder is recognized and migrated, then stays idempotent.
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash ${CLAUDE_PROJECT_DIR}/.claude/hooks/collect.sh",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(claude_commands(settings) == [hook_config.shell_command(hook)], "legacy 占位符未迁移")
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(len(claude_commands(settings)) == 1, "Claude hook 重复注册")
    print("✓ Claude fresh/migration/custom-hook 防护")


def test_claude_duplicate_and_invalid(base: Path) -> None:
    home, se_root, env = prepare_env(base, fake_codex=False)
    hook = claude_hook_path(home)
    local = home / ".claude" / "settings.local.json"
    settings = home / ".claude" / "settings.json"
    local.parent.mkdir(parents=True)
    local.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": hook_config.shell_command(hook)}]}]}}),
        encoding="utf-8",
    )
    settings.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": hook_config.shell_command(hook)}]}]}}),
        encoding="utf-8",
    )
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(len(claude_commands(local)) == 1, "local hook 被误删")
    require(claude_commands(settings) == [], "settings.json duplicate 未移除")

    invalid = "{bad json"
    settings.write_text(invalid, encoding="utf-8")
    before_local = local.read_text(encoding="utf-8")
    result = run(["bash", str(REPO_ROOT / "install.sh"), "claude-code"], env)
    require(result.returncode == 0, result.stdout + result.stderr)
    require(settings.read_text(encoding="utf-8") == invalid, "非法 JSON 被修改")
    require(local.read_text(encoding="utf-8") == before_local, "非法 JSON 场景修改了另一文件")
    print("✓ Claude duplicate/invalid JSON 防护")


def main() -> int:
    test_repository_urls()
    with tempfile.TemporaryDirectory(prefix="ase-hook-tests-") as tmp:
        base = Path(tmp)
        test_normalize_codex(base / "normalize")
        test_codex_fresh_and_idempotent(base / "codex-fresh")
        test_codex_existing_and_bad_configs(base / "codex-existing")
        test_claude_registration(base / "claude")
        test_claude_duplicate_and_invalid(base / "claude-dup")
    print("\n全部 hook 安装测试通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
