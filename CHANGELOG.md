# 更新日志（Changelog）

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。版本号从公开发布版开始记起。

## [0.2.0] - 2026-08-14

### 新增
- **跨平台技能使用统计**：新增平台无关的 `core/track_usage.py`（纯规则、零 LLM 成本），
  Claude Code / Codex 的 Stop hook 在归一化轨迹后自动调用，写入 `usage.json`，
  与 Pi 平台的 `skill-usage.ts` 扩展共享同一份数据——三平台技能体检数据源首次对齐。
- **三线技能体检**：Codex `AGENTS.md`、Claude Code `CLAUDE.md` 的进化流程
  从「仅闲置归档」升级为完整三线体检（闲置 ≥60 天 / 问题技能健康度 / 优质技能），
  与 Pi 版 `self-evolve` 技能对齐。

### 修复
- **skill-usage.ts（Pi）误归因**：审查/盘点类会话（一次性批量读取 ≥5 个 SKILL.md）
  不再把会话内无关错误（如 `cat -A` 报错、体检脚本 KeyError）归因到单个技能，
  改为跳过结果归因；`track_usage.py` 同步该逻辑。
- **usage.json 旧数据兼容**：补齐旧条目缺失的 `outcomes`/`failReasons` 字段，
  防止进化体检遍历时 KeyError（TS 与 Python 两实现均有）。
- **强信号误匹配**：技能路径匹配从 `skills/<slug>` 收紧为 `skills/<slug>/`（带尾斜杠/文件名），
  避免 `foo` 前缀误匹配 `skills/foobar`。
- **采集失败死循环**：`self-evolve.ts` 在 LLM 调用失败 / 返回空 / 异常时也推进采集点
  （此前失败不推进，LLM 后端故障时每次 `agent_settled` 都会重试同一段白耗成本）；
  原因照常记入 `rejections` 与经验日志，可追溯不丢诊断信息。

### 文档
- README：支持平台表新增「使用统计」列，说明各平台 usage 数据来源。
- docs/DESIGN.md：补充使用统计的实现分布与误判防护（字段补齐 / 精确匹配 / 审查类跳过）。

---

## [0.1.0] - 2026-08-11

### 新增
- 公开发布版：跨平台（Pi / Claude Code / Codex）AI 助手自我进化系统。
- 核心采集器 `core/collect.py`：轨迹 → LLM 草拟 → 候选技能（增量采集、查重双保险、失败可诊断）。
- Pi 扩展 `self-evolve.ts` / `skill-usage.ts`；Claude Code、Codex 平台 hook 适配。
- `install.sh` 一键安装（pi / claude-code / codex / all）。
- 进化流程五步：审查候选 → 启用/并入/淘汰 → 技能体检 → 维护记忆 → 收尾提交。
- 文档：README / INSTALL / docs（DESIGN / SECURITY / TROUBLESHOOTING）。
