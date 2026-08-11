# 故障排查（TROUBLESHOOTING.md）

按症状查找。排查前先确认三件事：

```bash
echo $SE_ROOT                       # 数据目录（默认 ~/.config/agent-self-evolution）
ls ~/.config/agent-self-evolution/  # 目录是否初始化
cat ~/.config/agent-self-evolution/state.json   # 系统状态
```

## 症状 1：候选区从不增长

按顺序检查：

1. **LLM 后端是否可用**：
   ```bash
   python3 core/collect.py --transcript /dev/null --session test --force
   # 若输出「未找到可用的 LLM 后端」→ 配置 SE_LLM_CMD / 安装 claude 或 codex CLI / 配置 SE_API_*
   ```
2. **是否被节流/上限挡住**：看 `state.json` 的 `lastCollectionAt` 与候选区数量（上限 20）；
3. **是否条件不满足**：多数任务工具调用 <5 次且无错误，属于正常；`logs/experience-log.md` 有每次采集的流水（「条件不满足」「拒绝沉淀」「候选生成」）；
4. **是否全部被 LLM 拒绝**：`state.json#rejections` 记录了最近 20 条拒绝原因；
5. **hook 是否真的触发**：见症状 2。

## 症状 2：hook 不触发

### Claude Code

- 检查配置位置：用户级 `~/.claude/settings.json` / 项目级 `.claude/settings.json`（优先级用户级 > 项目级，两者会合并，**重复注册会重复执行**）；
- 检查 JSON 语法：`python3 -m json.tool ~/.claude/settings.json`；
- 检查 command 路径：用户级配置里 `${CLAUDE_PROJECT_DIR}` 占位符不生效，必须用绝对路径；
- 检查 hook 是否被 permission 拦截：Claude Code 首次运行自定义 hook 可能要求确认；
- 临时验证：手动执行 `echo '{"session_id":"t","transcript_path":"/path/to/transcript.jsonl"}' | bash ~/.claude/hooks/collect.sh`，看输出。

### Codex

- 确认 `~/.codex/config.toml` 有 `[features] codex_hooks = true`；
- 确认 `~/.codex/hooks.json` 存在且 JSON 合法；
- 确认 hook 已通过 trust 确认（首次运行会在终端提示，接受即可；被跳过可运行 `codex hooks trust` 类命令或删除 hooks.json 重新注册）；
- Codex hooks 处于快速迭代期，升级 CLI 后协议可能变化，检查是否报错被忽略。

### Pi

- 扩展文件在 `~/.pi/agent/extensions/`，执行 `/reload` 热重载；
- `state.json#lastSeenAt` 每次 agent 结束都会更新——如果它不更新，扩展没加载；
- 语法检查：`bun build <file> --no-bundle --target=bun`。

## 症状 3：LLM 调用失败（experience-log 里「采集失败」）

- **「LLM 调用异常: claude CLI 失败」** → `claude` 未登录（`claude` 命令在终端试一下）；
- **「codex CLI 失败」** → `codex exec` 不可用或未登录；Codex 多行 prompt 问题已通过 stdin 方式规避；
- **「LLM 返回空内容」** → 模型输出预算不足（调大 `SE_MAX_OUTPUT_TOKENS`）或模型拒绝任务；
- **「无法获取模型凭证」**（Pi）→ pi 模型注册表问题，检查 pi 本身可用性；
- 原始草稿在 `$SE_ROOT/logs/rejected-drafts/`。

## 症状 4：候选格式不符被拒

- 检查 `logs/rejected-drafts/` 里的原始 LLM 输出，确认是否是模型没遵守 frontmatter 格式；
- `description` 超长（>1024 字符）、`name` 含大写/空格是常见拒绝原因；
- 这是**预期行为**：格式校验是安全护栏，宁缺毋滥。

## 症状 5：启用技能后不生效（Pi）

- 启用 = 两步：`$SE_ROOT/skills/<name>/SKILL.md` 源文件 + `~/.pi/agent/skills/<name>` 软链；
- 检查软链：`ls -la ~/.pi/agent/skills/ | grep <name>`；
- 缺软链 → `ln -sfn $SE_ROOT/skills/<name> ~/.pi/agent/skills/<name>`。

## 症状 6：任务结束变慢

- 采集 hook 里的 LLM 调用耗时（claude/codex 首字节较慢）；
- 缓解：设置 `SE_THROTTLE_MS`（如 600000 = 10 分钟节流）、调高 `SE_MIN_TOOL_CALLS`、或给 hook 换更快的后端（`SE_LLM_CMD` 指定快模型）；
- hook 超时 600s 是上限，正常情况只有几秒到几十秒。

## 症状 7：磁盘占用

- `$SE_ROOT` 内容量最大的是 `logs/rejected-drafts/`（被拒草稿）与 `logs/tmp/`（归一化轨迹）；
- 定期清理：`rm -rf $SE_ROOT/logs/tmp $SE_ROOT/logs/rejected-drafts/*`（保留最近即可）；
- `candidates/` 审查后可删除已淘汰项。

## 症状 8：跨平台数据不一致

- 所有平台读写同一 `$SE_ROOT`；若你给不同平台设置了不同 `SE_ROOT`，记忆不互通（属预期）；
- 技能启用（Pi 的软链）只在 Pi 生效；Claude Code/Codex 通过流程文档读取 `skills/` 下源文件。

## 已知限制

- Codex transcript 格式随版本变化，若采集长期无产出且日志显示「会话无可分析内容」，请检查归一化脚本是否适配了新格式（提 Issue）；
- Claude Code transcript 的个别版本消息结构不同（无 `message` 字段），归一化脚本已做兼容，如遇异常同样请提 Issue。
