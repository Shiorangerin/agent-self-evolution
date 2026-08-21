# 更新日志（Changelog）

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。版本号从公开发布版开始记起。

## [0.3.0] - 2026-08-21

### 新增
- **采集器全链路防线**（三平台同步）：截断启发式（代码围栏不闭合 / 尾部中断即丢弃残缺草稿）、
  frontmatter 首行与长度保险丝、候选同名防覆盖（内容相同判重复采集，不同以 -N 变体落盘）、
  同会话拒绝记忆（抑制「先拒后生」的 LLM 判断抖动）、自我管理会话熔断（进化期间跳过采集防自耗）、
  候选区容量计数去杂物。
- **审查工具三件套**：`scripts/candidate_preflight.py`（零 token 候选预检：格式 / 大小 /
  截断启发式 / 同名与 description 相似度查重）、`scripts/skill_scorecard.py`（技能记分卡：
  新鲜度 / 使用度 / 可靠性三维评分，六档分级，元技能豁免）、`scripts/healthcheck.sh`
  （一键体检：核心编译 + 预检 + 治理概览）。
- **Pi 平台**：共享纯函数库 `extensions/lib/evolution-core.ts` + 23 个单元测试
  （bun test），双扩展改为引用共享库。
- **流程规范**：超长技能压缩省 token 流程（低成本模型起草 + 人工审 diff）；
  六段式固定进化报告模板（含关键命令留痕与待决策清单）；「技能体检」轻量触发入口。

### 变更
- SKILL.md 长度软上限 5000 → 8000 字符（知识密集技能不再被苛待；元技能豁免不变）。
- 使用统计：盘点 / 审查类会话（强信号 ≥5）整体跳过记录，防止 count 膨胀与 lastUsedAt 污染。
- 删除「总结一天的工作」工作总结部分：「进化」为唯一完整入口，「技能体检」为纯只读诊断入口。

### 修复
- Pi 平台 skill-usage 轨迹扫描去除 O(技能×条目) 重复字符串化（长会话性能）。

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
