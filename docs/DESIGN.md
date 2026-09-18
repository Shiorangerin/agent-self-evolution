# 架构设计（DESIGN.md）

本文档说明 agent-self-evolution 的设计决策、模块划分与关键机制。

## 1. 设计目标

1. **经验沉淀闭环**：任务 → 轨迹 → 候选 → 审查 → 启用 → 复用；
2. **零打扰**：采集全自动但安静，进化完全手动；
3. **零污染**：自动生成内容在审查通过前不进上下文；
4. **低成本**：增量采集、低推理强度、节流、上限；
5. **可移植**：核心平台无关，适配层薄；
6. **可追溯**：明文文件 + 日志 + git。

## 2. 模块划分

```
core/                平台无关核心
  collect.py         采集器：轨迹→LLM→候选（Python 标准库）
  init.py            数据目录初始化
  templates/         初始文件模板
docs/flow/           进化流程细则（安装到 <SE_ROOT>/docs/，按需读取）
  candidate-review.md  候选审查与处置
  skill-health.md      技能体检阈值与归档/压缩
  report-template.md   报告模板
scripts/             零 token 工具链
  evolve_brief.sh      进化一次探测（状态/候选/体检/草稿/日志）
  candidate_preflight.py  候选预检
  skill_scorecard.py      技能记分卡
  healthcheck.sh          一键体检
platforms/           平台适配层（薄）
  pi/                TS 扩展（采集 + 使用统计）+ 进化技能
  claude-code/       Stop hook + CLAUDE.md
  codex/             Stop hook + AGENTS.md
install.sh          一键安装
```

**分层原则**：业务逻辑（触发条件、增量、查重、格式校验、状态管理）全部在 core；平台适配只做两件事——① 把平台专属 transcript 归一化为统一 JSONL；② 注册 hook 调用 core。

## 3. 统一轨迹协议

平台 hook 将 transcript 归一化为逐行 JSON 的统一 JSONL，协议如下：

```json
{"role": "user", "text": "用户的请求"}
{"role": "assistant", "text": "助手的文本输出"}
{"role": "assistant", "toolCall": {"name": "Bash", "args": {"command": "..."}}}
{"role": "toolResult", "isError": true, "text": "错误输出"}
{"role": "bashExecution", "command": "...", "cancelled": false}
```

`core/collect.py` 只解析此协议，不感知任何平台的原始格式。新增平台 = 新写一个归一化脚本 + hook，核心零改动。

## 4. 采集器状态机

```
agent_settled / Stop hook 触发
  → 读 state.json（collectedUpTo 定位上次采集点）
  → 归一化轨迹 → 统计 toolCalls / errors
  → 条件不满足？ → 推进采集点，结束（零 LLM 成本）
  → 候选区已满？ → 结束
  → 节流中？    → 结束
  → 解析采集链（钉扎项 + 按价格自动挑（免费优先）+ 当前主模型兜底，逐项探测凭证）
  → 链为空？    → 写「采集失败」+ state.collectorUnavailable 标记，结束（不再静默）
  → LLM 草拟（低推理强度 + 截断 + 输出预算）
  → SKIP / 无 name / 同名冲突 → 记录 rejection，结束
  → 写入 candidates/<slug>/（SKILL.md + meta.md），推进采集点
```

**增量采集**：`state.collectedUpTo[<session>]` 记录上次处理到的位置（Pi 为 entry id，通用版为行数）。同一会话多次触发只分析新增部分，长程对话不重复计算、不丢数据。

**查重双保险**：① prompt 注入已启用技能清单，要求 LLM 输出 SKIP；② 代码层 slug 完全同名直接拒绝。LLM 不遵守规则时兜底拦截。

**采集链不写死**：模型可达性（provider 是否存在、凭证是否有效）会随时间变化，所以链是从运行时来源推导的：`collector.models`（显式钉扎）→ 当前模型表里已配凭证的模型按价格排序（免费优先）→ 会话当前主模型兜底（它一定在表里，所以永不为空）→ 静态常量。逐项 `getApiKeyAndHeaders` 探测，失败项写入日志的「丢弃」列表；结果按候选池指纹缓存 6 小时（模型表/价格/当前模型/配置任一变化即重算），链变化时写一行 `采集链` 日志。

**失败可诊断**：LLM 调用失败/空输出/格式不符 → 原因写 `state.json#rejections` 与 `experience-log.md`，但**不打扰用户**。任何「链不可用」类早退分支都必须留痕（否则会出现“扩展心跳正常、实际采集停摆”的静默断流）。

## 5. 进化流程（手动）

触发词：「总结一天的工作」/「进化」（各平台流程文档定义）。

五步：
1. 探测：跑 `scripts/evolve_brief.sh` 一次拿到状态摘要、候选清单、启用区计数与超长清单、待处理画像草稿、日志尾部与记分卡分级；
2. 审查候选：格式校验（name/description/大小）→ 查重 → 价值评估 → 启用（mkdir+cp+ln）/ 并入 / 淘汰（meta.md 记 verdict）；
3. 技能体检（三线）：usage.json 的 outcomes/failReasons → 闲置（≥60 天未用）/ 问题（失败率高）/ 优质（成功率高）三级处置，征求用户决定；
4. 维护记忆：USER.md（纯净条目）+ LESSONS.md（格式模板）；
5. 收尾：state.json 计数 + 经验日志 + git 提交 + 三节报告。

**关键设计**：① 进化依赖 agent 的 LLM 判断（审查本身是认知任务），流程文档（SKILL.md / CLAUDE.md / AGENTS.md）只保留路由与护栏，把判定閈值与命令模板放在 `docs/flow/` 按需读取，既不常驻上下文又不丢严谨性；② 流程本身也受成本纪律约束：一次探测脚本代替逐步扫描，禁止整文件读取会话轨迹，状态文件只取摘要。

## 6. 使用统计（反馈回路）

纯规则零成本：扫描轨迹文本，命中技能路径（强信号）或 slug（弱信号）即记录，并对强信号技能做
**结果归因**（成功/失败/未知 + 失败原因原文片段）。用于「技能体检」三线处置（闲置/问题/优质），
支撑归档、补问题与淘汰决策。**决策权永远在用户**。

实现：Pi 平台为 TS 扩展 `skill-usage.ts`（agent_settled 触发）；Claude Code / Codex 平台为
Python 等价实现 `core/track_usage.py`（hook 归一化轨迹后调用），两者写同一份 `usage.json`。

**误判防护**（启发式归因的副作用，两实现均有）：
- 补齐旧条目缺失的 `outcomes`/`failReasons` 字段，防进化体检 KeyError；
- 强信号匹配带尾斜杠/文件名（`skills/<slug>/` 而非 `skills/<slug>`），避免 `foo` 误匹配 `foobar`；
- 审查/盘点类会话（一次性批量读取 ≥5 个 SKILL.md）跳过结果归因，避免无关错误被记到单个技能头上。

## 7. 成本控制矩阵

| 环节 | 成本 | 控制手段 |
| --- | --- | --- |
| 采集（每次任务） | 1 次低成本 LLM 调用 | 阈值 5 次工具调用；摘要截断 2500 字符；reasoningEffort minimal；maxTokens 2000；无缓存 |
| 采集链解析（每次采集） | 0（纯规则） | 只读注册表 + 凭证探测；按候选池指纹缓存 6 小时；链上按由廉到贵排序（免费优先） |
| 采集（不满足条件） | 0（纯规则） | 先统计后调用 |
| 进化（手动） | 深度（预期） | 仅手动触发；候选有上限；流程本身受成本纪律约束（一次探测、细则按需读、轨迹禁整读） |
| 使用统计 | 0 | 纯规则 |

## 8. 已知权衡

- **通用版采集依赖 CLI 登录态**（claude/codex）：多一层外部依赖，但免去用户管理第二个 API Key；失败静默。
- **Codex transcript 格式漂移**：新旧格式兼容 + 兜底定位 + 失败静默；代价是归一化代码稍复杂。
- **行数增量 vs entry id 增量**：通用版用行数（简单可靠）；Pi 版用 entry id（精确）。行数方案的 edge case（并发追加）在单用户场景可忽略。
