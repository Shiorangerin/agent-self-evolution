# 候选审查细则

适用：进化流程第二步。`$SE_ROOT/candidates/` 非空时阅读本文件。

## 候选结构

每个候选是一个子目录，含 `SKILL.md` 与 `meta.md`。`meta.md` 记录来源会话与工具调用、错误次数，是价值判断的主要依据。

## 一、格式校验

先跑预检脚本，再做人工复核：

```bash
python3 $SE_ROOT/scripts/candidate_preflight.py [候选名 ...]
```

脚本完成格式、大小、截断、同名查重的机械检查。硬伤必须修复或淘汰，警示项人工判断。脚本结果仅供参考，启用决策由人工作出。

校验项：

- frontmatter 含 `name`：小写字母、数字、连字符，长度 1 至 64 字符。
- frontmatter 含 `description`：≤1024 字符，写明了何时使用。
- `SKILL.md` 正文含 frontmatter 不超过 8000 字符。多个候选同时超限且内容重叠时，先合并压缩到限内再启用，不因超限直接全淘汰。

注意事项：

- 校验 frontmatter 不要依赖 `import yaml`：多数环境未预装 pyyaml，导入失败会被技能使用统计记为一次失败，产生假失败记录。用正则或肉眼检查即可，例如 `rg '^name:|^description:' SKILL.md`。
- 检查代码围栏是否闭合，被截断的候选文件不得启用。

## 二、查重

与 `$SE_ROOT/skills/` 下已启用技能对比（名称与语义）。语义重复或高度重叠的，合并进现有技能或淘汰，禁止重复启用。

## 三、价值评估

至少满足一条才值得启用：

- 这类任务以后会重复出现。
- 步骤明确且可复用。
- 包含真实注意点与解法。

一次性的琐碎问答与闲聊直接淘汰。

## 四、处置

每个候选无论启用、并入还是淘汰，都要在其 `meta.md` 末尾追加 `candidate-verdict: enabled|merged|rejected` 与一句原因，然后删除候选目录。候选区不保留已处理目录，否则下次进化会重复审查。

### 启用

```bash
mkdir -p $SE_ROOT/skills/<name>
cp $SE_ROOT/candidates/<slug>/SKILL.md $SE_ROOT/skills/<name>/SKILL.md
ln -sfn $SE_ROOT/skills/<name> ~/.pi/agent/skills/<name>   # Pi 平台：挂到技能加载目录
```

在 `$SE_ROOT/logs/experience-log.md` 追加一行：

```
| 时间 | <slug> | 启用 | <一句话摘要> | skills/<name>/ |
```

最后删除候选目录。

### 并入现有技能

用编辑工具把候选中有价值的内容合并进目标技能的 `SKILL.md`，同步更新 description 与正文，然后删除候选目录。若技能使用统计里记录了被并入的旧技能名，在该技能条目登记为别名，保持统计可追溯。

### 淘汰

在 `meta.md` 末尾追加 `candidate-verdict: rejected` 与原因后删除候选目录。质量过差的直接删除并记日志。
