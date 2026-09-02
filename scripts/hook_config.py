#!/usr/bin/env python3
"""Shared, conservative helpers for registering agent-self-evolution hooks."""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from copy import deepcopy
from typing import Iterable, List, Optional, Tuple


def shell_command(hook_path: Path) -> str:
    """Return a shell command whose path is safe even if it contains spaces."""
    return "bash " + shlex.quote(str(hook_path))


def toml_basic_string(value: str) -> str:
    """Encode a Python string as a TOML basic string."""
    return json.dumps(value, ensure_ascii=False)


def _resolved_candidates(raw_path: str) -> List[Path]:
    candidates = [Path(raw_path)]
    if "~" in raw_path or "$" in raw_path:
        candidates.append(Path(os.path.expanduser(os.path.expandvars(raw_path))))
    resolved = []
    for candidate in candidates:
        try:
            resolved.append(candidate.resolve())
        except OSError:
            continue
    return resolved


def is_own_command(
    command: object,
    hook_path: Path,
    legacy_paths: Optional[Iterable[Path]] = None,
) -> bool:
    """Match only commands that invoke one of this project's hook scripts.

    A generic command merely containing ``hooks/collect.sh`` must not match.
    """
    if not isinstance(command, str):
        return False

    # This is the project-level settings template. Claude expands it before
    # invoking the hook; user-level installers rewrite it to an absolute path.
    if command.strip() in {
        "bash ${CLAUDE_PROJECT_DIR}/.claude/hooks/collect.sh",
        "bash ${CLAUDE_PROJECT_DIR}/.claude/hooks/agent-self-evolution/collect.sh",
    }:
        return True

    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) < 2 or Path(tokens[0]).name not in ("bash", "sh"):
        return False

    wanted = {Path(hook_path).resolve()}
    for path in legacy_paths or ():
        wanted.add(Path(path).resolve())
    return any(path in wanted for path in _resolved_candidates(tokens[1]))


def stop_hooks(data: object) -> List[Tuple[dict, dict]]:
    """Yield (group, hook) pairs for hooks.Stop without accepting loose data."""
    if not isinstance(data, dict):
        return []
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get("Stop")
    if not isinstance(groups, list):
        return []

    pairs: List[Tuple[dict, dict]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        inner = group.get("hooks")
        if not isinstance(inner, list):
            continue
        for hook in inner:
            if isinstance(hook, dict):
                pairs.append((group, hook))
    return pairs


def _prune_own_hooks(
    data: dict,
    hook_path: Path,
    legacy_paths: Iterable[Path],
    keep_first: bool,
) -> int:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    groups = hooks.get("Stop")
    if not isinstance(groups, list):
        return 0

    removed = 0
    kept = 0
    new_groups = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            new_groups.append(group)
            continue
        new_inner = []
        for hook in group["hooks"]:
            if (
                isinstance(hook, dict)
                and is_own_command(hook.get("command"), hook_path, legacy_paths)
                and (keep_first and kept > 0 or not keep_first)
            ):
                removed += 1
                continue
            if isinstance(hook, dict) and is_own_command(
                hook.get("command"), hook_path, legacy_paths
            ):
                kept += 1
            new_inner.append(hook)
        if new_inner:
            group["hooks"] = new_inner
            new_groups.append(group)
    if new_groups:
        hooks["Stop"] = new_groups
    else:
        hooks.pop("Stop", None)
        if not hooks:
            data.pop("hooks", None)
    return removed


def dedupe_own_hooks(data: dict, hook_path: Path, legacy_paths: Iterable[Path]) -> int:
    """Remove duplicate own hooks in one JSON document, keeping the first."""
    return _prune_own_hooks(data, hook_path, legacy_paths, keep_first=True)


def remove_own_hooks(data: dict, hook_path: Path, legacy_paths: Iterable[Path]) -> int:
    """Remove every own hook from one JSON document."""
    return _prune_own_hooks(data, hook_path, legacy_paths, keep_first=False)


def rewrite_own_hook_commands(
    data: dict,
    command: str,
    hook_path: Path,
    legacy_paths: Iterable[Path],
) -> int:
    changed = 0
    for _, hook in stop_hooks(data):
        if is_own_command(hook.get("command"), hook_path, legacy_paths):
            if hook.get("command") != command or hook.get("type") != "command":
                hook["type"] = "command"
                hook["command"] = command
                changed += 1
    return changed


def has_own_hook(data: object, hook_path: Path, legacy_paths: Iterable[Path]) -> bool:
    return any(
        is_own_command(hook.get("command"), hook_path, legacy_paths)
        for _, hook in stop_hooks(data)
    )


def append_own_hook(data: dict, command: str) -> None:
    hooks = data.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    stop.append({"hooks": [{"type": "command", "command": command}]})


def load_json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_if_changed(path: Path, original: object, data: dict) -> bool:
    if data == original:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def install_claude(root: Path) -> int:
    hook_path = root / "hooks" / "agent-self-evolution" / "collect.sh"
    legacy_paths = [
        root / "hooks" / "collect.sh",
        hook_path,
    ]
    command = shell_command(hook_path)
    files = [root / "settings.local.json", root / "settings.json"]

    loaded = []
    original_data = {}
    for path in files:
        if not path.exists():
            continue
        try:
            data = load_json_file(path)
            if not isinstance(data, dict):
                raise ValueError("JSON 根节点必须是对象")
            loaded.append((path, data))
        except Exception as exc:
            print(f"警告：无法解析 {path}: {exc}", file=sys.stderr)
            return 2

    local_path, settings_path = files
    original_data = {path: deepcopy(data) for path, data in loaded}
    local_data = next((data for path, data in loaded if path == local_path), None)
    settings_data = next((data for path, data in loaded if path == settings_path), None)

    if local_data is not None:
        dedupe_own_hooks(local_data, hook_path, legacy_paths)
    if settings_data is not None:
        dedupe_own_hooks(settings_data, hook_path, legacy_paths)

    local_has = local_data is not None and has_own_hook(
        local_data, hook_path, legacy_paths
    )
    settings_has = settings_data is not None and has_own_hook(
        settings_data, hook_path, legacy_paths
    )
    if local_has and settings_has:
        remove_own_hooks(settings_data, hook_path, legacy_paths)

    # Preserve a hook that already exists in either file; only rewrite its path.
    if not local_has and not settings_has:
        target_data = local_data if local_data is not None else settings_data
        if target_data is None:
            target_path = settings_path
            target_data = {}
            original_data[target_path] = {}
            loaded.append((target_path, target_data))
        else:
            target_path = local_path if target_data is local_data else settings_path
        append_own_hook(target_data, command)
    else:
        for data in (local_data, settings_data):
            if data is not None:
                rewrite_own_hook_commands(data, command, hook_path, legacy_paths)

    changed = []
    for path, data in loaded:
        if isinstance(data, dict) and write_json_if_changed(
            path, original_data[path], data
        ):
            changed.append(path.name)
    if changed:
        print("已更新 Stop hook 到 " + ", ".join(changed))
    else:
        print("Stop hook 已存在，跳过")
    return 0


def install_codex(config_path: Path, hook_path: Path) -> int:
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    legacy_paths = [
        Path.home() / ".codex" / "hooks" / "collect.sh",
        Path.home() / ".codex" / "hooks" / "agent-self-evolution" / "collect.sh",
        Path.home()
        / ".config"
        / "agent-self-evolution"
        / "platforms"
        / "codex"
        / "hooks"
        / "collect.sh",
        hook_path,
    ]
    command = shell_command(hook_path)
    command_toml = toml_basic_string(command)

    try:
        import tomllib
    except ModuleNotFoundError:
        tomllib = None

    if tomllib is not None and text.strip():
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            print(f"错误：无法解析 {config_path}: {exc}", file=sys.stderr)
            return 1
        hooks = data.get("hooks")
        if isinstance(hooks, dict) and "Stop" in hooks:
            if not isinstance(hooks["Stop"], list):
                print(
                    "检测到旧式 [hooks.Stop] 表；为避免 TOML 结构冲突，已跳过自动注册，请手动迁移",
                    file=sys.stderr,
                )
                return 2
            if has_own_hook(data, hook_path, legacy_paths):
                print("Stop hook 已存在，跳过")
                return 0
    elif command in text:
        print("Stop hook 已存在，跳过")
        return 0
    elif tomllib is None and text.strip():
        print(
            "当前 Python 缺少 tomllib，无法安全校验已有 config.toml；已跳过自动注册，请使用 Python 3.11+ 或手动迁移",
            file=sys.stderr,
        )
        return 2

    block = f"""

[[hooks.Stop]]
hooks = [
  {{ type = "command", command = {command_toml}, async = false }}
]
"""
    new_text = text + block
    if tomllib is not None:
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            print(
                f"错误：追加 hook 后 {config_path} 无法解析，已放弃写入: {exc}",
                file=sys.stderr,
            )
            return 1
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(new_text, encoding="utf-8")
    print("已在 config.toml 注册 Stop hook")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="platform", required=True)

    claude = subparsers.add_parser("claude")
    claude.add_argument("root", type=Path)

    codex = subparsers.add_parser("codex")
    codex.add_argument("config", type=Path)
    codex.add_argument("hook", type=Path)

    args = parser.parse_args()
    if args.platform == "claude":
        return install_claude(args.root)
    return install_codex(args.config, args.hook)


if __name__ == "__main__":
    raise SystemExit(main())
