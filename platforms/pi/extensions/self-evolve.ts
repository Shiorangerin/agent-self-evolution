/**
 * agent-self-evolution —— 经验采集器（Pi 平台适配）
 *
 * 每次 agent 运行结束（agent_settled）时，后台轻量分析本次会话轨迹：
 * - 统计工具调用次数、错误修复次数
 * - 满足触发条件（工具调用 ≥5 次 / 出现错误并修复）时，
 *   用低成本 LLM 调用草拟一份 SKILL.md 候选，写入 <SE_ROOT>/candidates/
 * - 候选区不进入运行上下文，待用户手动触发「进化流程」时审查启用
 *
 * 进化完全由用户手动触发（手动模式），本扩展只负责安静地记录候选，
 * 不做任何自动唤醒 / 定时触发。
 *
 * 手动触发：/evolve-collect 命令（绕过节流，立即分析当前会话并草拟候选）。
 *
 * 省 token 策略：
 * - 轨迹摘要截断，只保留关键信息
 * - reasoningEffort: "minimal"（注意：部分 OpenAI 兼容中转不接受 "off"，会 400）
 * - maxTokens: 2000（要给推理模型留思考空间 + 输出 SKILL.md 正文）
 * - cacheRetention: "none"（不产生缓存开销）
 * - 同一会话只触发一次 + 全局节流（可配置）+ 候选区上限
 *
 * 所有失败静默处理，绝不打搅用户；但会记录详细原因（errorMessage）供排查。
 */

import { complete } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { mkdirSync, writeFileSync, appendFileSync, readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const EVO_DIR = process.env.SE_ROOT || join(homedir(), ".config", "agent-self-evolution");
const CANDIDATES_DIR = join(EVO_DIR, "candidates");
const LOG_FILE = join(EVO_DIR, "logs", "experience-log.md");
const STATE_FILE = join(EVO_DIR, "state.json");
const PI_SKILLS_DIR = join(homedir(), ".pi", "agent", "skills"); // pi 的技能加载目录（平台机制）

const MIN_TOOL_CALLS = Number(process.env.SE_MIN_TOOL_CALLS ?? 5); // 工具调用触发阈值
const MAX_CANDIDATES = Number(process.env.SE_MAX_CANDIDATES ?? 20); // 候选区堆积上限
const THROTTLE_MS = Number(process.env.SE_THROTTLE_MS ?? 0); // 全局节流（默认关闭：增量采集不丢数据）
const MAX_TRACE_CHARS = Number(process.env.SE_MAX_TRACE_CHARS ?? 2500); // 轨迹摘要上限
const MAX_OUTPUT_TOKENS = Number(process.env.SE_MAX_OUTPUT_TOKENS ?? 2000); // 草拟 skill 的输出预算

// 会话文件 → 状态，防止同一会话重复/并发触发
const busy = new Map<string, "collecting" | "done">();

function extractText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const block of content) {
		if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
			const text = (block as { text?: unknown }).text;
			if (typeof text === "string") parts.push(text);
		}
	}
	return parts.join("\n");
}

function readState(): any {
	try {
		return JSON.parse(readFileSync(STATE_FILE, "utf8"));
	} catch {
		return { stats: { sessionsAnalyzed: 0, candidatesCreated: 0 } };
	}
}

function writeState(state: any) {
	try {
		writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), "utf8");
	} catch {
		/* 静默 */
	}
}

function nowIso(): string {
	return new Date().toISOString();
}

function nowLocal(): string {
	return new Date().toLocaleString("zh-CN", { hour12: false });
}

function slugify(name: string): string {
	return (
		name
			.toLowerCase()
			.replace(/[^a-z0-9-]+/g, "-")
			.replace(/^-+|-+$/g, "")
			.replace(/-{2,}/g, "-")
			.slice(0, 60) || "untitled-skill"
	);
}

/** 收集本次会话轨迹摘要 */
function buildTraceSummary(entries: any[]): { toolCalls: number; errors: number; summary: string } {
	let toolCalls = 0;
	let errors = 0;
	const userParts: string[] = [];
	const bashParts: string[] = [];
	const errorParts: string[] = [];

	for (const e of entries) {
		if (e.type !== "message" || !e.message) continue;
		const m = e.message;
		const role = m.role;

		if (role === "user") {
			const t = extractText(m.content).trim();
			if (t && !t.startsWith("/")) userParts.push(t.slice(0, 300));
		} else if (role === "assistant") {
			const content = m.content;
			if (Array.isArray(content)) {
				for (const block of content) {
					if (block && typeof block === "object" && (block as any).type === "toolCall") {
						toolCalls++;
						const args = (block as any).arguments ?? {};
						const name = String((block as any).name ?? "").toLowerCase();
						if (name === "bash" || name === "bash_command" || name === "command") {
							const cmd = typeof args === "object" ? String(args.command ?? args.cmd ?? "") : "";
							if (cmd) bashParts.push(cmd.slice(0, 200));
						} else if (name === "edit" || name === "write" || name === "read") {
							const p = typeof args === "object" ? String(args.path ?? "") : "";
							if (p) bashParts.push(`${name} ${p}`);
						}
					}
				}
			}
		} else if (role === "toolResult") {
			if (m.isError) {
				errors++;
				errorParts.push(extractText(m.content).slice(0, 400));
			}
		} else if (role === "bashExecution") {
			if (m.command && !m.cancelled) bashParts.push(m.command.slice(0, 200));
		}
	}

	const lines: string[] = [];
	if (userParts.length) lines.push("【用户请求】\n" + userParts.slice(-5).join("\n"));
	if (bashParts.length) lines.push("【执行操作】\n" + bashParts.slice(-25).join("\n"));
	if (errorParts.length) lines.push("【出现的错误】\n" + errorParts.slice(-3).join("\n---\n"));
	const summary = lines.join("\n\n").slice(0, MAX_TRACE_CHARS);

	return { toolCalls, errors, summary };
}

/** 读取已启用技能清单（name + 一句话描述），供采集 prompt 查重与代码层拦截 */
function listEnabledSkills(): { name: string; desc: string }[] {
	const skills: { name: string; desc: string }[] = [];
	try {
		for (const entry of readdirSync(PI_SKILLS_DIR, { withFileTypes: true })) {
			if (entry.name.startsWith(".")) continue;
			if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
			const skillFile = join(PI_SKILLS_DIR, entry.name, "SKILL.md");
			if (!existsSync(skillFile)) continue;
			let content = "";
			try {
				content = readFileSync(skillFile, "utf8").slice(0, 3000);
			} catch {
				continue;
			}
			const nameMatch = content.match(/^name\s*:\s*["']?([^"'\r\n]+)["']?\s*$/m);
			const descMatch = content.match(/^description\s*:\s*(.+)$/m);
			const name = nameMatch ? nameMatch[1].trim() : entry.name;
			const desc = descMatch ? descMatch[1].trim().replace(/\s+/g, " ").slice(0, 120) : "";
			skills.push({ name, desc });
		}
	} catch {
		/* 静默 */
	}
	return skills.sort((a, b) => a.name.localeCompare(b.name));
}

/** 记录一条经验日志 */
function appendLog(line: string) {
	try {
		appendFileSync(LOG_FILE, line + "\n", "utf8");
	} catch {
		/* 静默 */
	}
}

/** 记录一条「不值得沉淀/失败」的原因（state.rejections 保留最近 20 条，供用户查看） */
function recordRejection(state: any, sessionFile: string, reason: string) {
	const rejections = state.rejections ?? [];
	rejections.push({
		at: nowIso(),
		session: sessionFile.split("/").pop(),
		reason: reason.slice(0, 300),
	});
	state.rejections = rejections.slice(-20);
}

/** 推进采集位置：把该会话的采集点更新到当前最后一条 entry（增量采集核心） */
function advanceCollection(state: any, shortName: string, entries: any[]) {
	const last = entries[entries.length - 1];
	if (last?.id) {
		state.collectedUpTo = state.collectedUpTo ?? {};
		state.collectedUpTo[shortName] = last.id;
	}
}

/** 保存 LLM 原始输出草稿供排查 */
function saveDraftDump(sessionFile: string, toolCalls: number, errors: number, raw: string, extra = "") {
	const draftDir = join(EVO_DIR, "logs", "rejected-drafts");
	mkdirSync(draftDir, { recursive: true });
	const draftFile = join(draftDir, `${Date.now()}.md`);
	writeFileSync(
		draftFile,
		`# 被拒草稿（${nowIso()}）\n来源会话: ${sessionFile.split("/").pop()}\n工具调用: ${toolCalls} 次 / 错误: ${errors} 次\n${extra ? `备注: ${extra}\n` : ""}--- 以下为 LLM 原始输出 ---\n\n${raw || "（空）"}`,
		"utf8",
	);
	return draftFile;
}

/**
 * 核心采集逻辑：分析当前会话轨迹 → LLM 判断并草拟候选技能。
 * @param force 手动触发时 true（绕过 busy 检查）
 * @returns 结果描述字符串（供汇报）
 */
async function collect(pi: ExtensionAPI, ctx: any, force = false): Promise<string> {
	try {
		const sessionFile = ctx.sessionManager.getSessionFile();
		if (!sessionFile) return "无会话文件";

		if (!force && busy.get(sessionFile) === "collecting") {
			return "本会话正在采集中，跳过";
		}

		// 候选区堆积检查
		let candidateCount = 0;
		try {
			candidateCount = existsSync(CANDIDATES_DIR) ? readdirSync(CANDIDATES_DIR).length : 0;
		} catch { /* ignore */ }
		if (candidateCount >= MAX_CANDIDATES) return `候选区已满（${candidateCount} 个），请先运行进化流程审查`;

		const state = readState();

		// 全局节流（手动触发 force 时跳过）
		if (!force && THROTTLE_MS > 0) {
			const last = state.lastCollectionAt ? new Date(state.lastCollectionAt).getTime() : 0;
			if (Date.now() - last < THROTTLE_MS) {
				const waitMin = Math.ceil((THROTTLE_MS - (Date.now() - last)) / 60000);
				return `节流中（距上次采集 ${waitMin} 分钟后可再触发，或使用 /evolve-collect 手动强制）`;
			}
		}

		// 统计本次会话轨迹（增量采集：只分析上次采集点之后的新内容，长程对话可多次采集）
		const entries = (ctx.sessionManager.getBranch() as any[]) ?? [];
		const shortName = sessionFile.split("/").pop() ?? sessionFile;
		const lastId = force ? undefined : state.collectedUpTo?.[shortName];
		let fromIndex = -1;
		if (lastId) {
			const idx = entries.findIndex((e: any) => e.id === lastId);
			if (idx >= 0 && idx === entries.length - 1) {
				writeState(state);
				return "本会话已采集到最新，无新内容";
			}
			fromIndex = idx;
		}
		const window = fromIndex >= 0 ? entries.slice(fromIndex + 1) : entries;
		const { toolCalls, errors, summary } = buildTraceSummary(window);
		if (!summary.trim()) return "会话无可分析内容";

		// 更新统计（不满足条件也算分析过）
		state.stats = state.stats ?? {};
		state.stats.sessionsAnalyzed = (state.stats.sessionsAnalyzed ?? 0) + 1;

		if (toolCalls < MIN_TOOL_CALLS && errors === 0) {
			advanceCollection(state, shortName, entries);
			writeState(state);
			return `条件不满足（工具调用 ${toolCalls} 次、无错误），不值得调用 LLM`;
		}

		// 满足触发条件 → 调用 LLM 判断并草拟候选技能
		const model = ctx.model;
		if (!model) return "当前无模型上下文";
		const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
		if (!auth?.ok || !auth.apiKey) return "无法获取模型凭证（auth 不可用）";
		if (!force) busy.set(sessionFile, "collecting");

		// 查重：注入已启用技能清单，LLM 草拟前先比对，避免重复生成
		const enabledSkills = listEnabledSkills();
		const skillsBlock = enabledSkills.length
			? [
					"【已启用技能清单（查重参考）】以下技能已存在于系统中：",
					...enabledSkills.map((s) => `- ${s.name}${s.desc ? "：" + s.desc : ""}`),
					"若本次轨迹与其中任何一个语义重复（同类流程/同类场景/同类坑点），必须输出 SKIP: 与已有技能 <name> 重复，禁止重复生成。",
			  ].join("\n")
			: "";

		const prompt = [
			"你是「agent-self-evolution 经验采集器」。根据下面这次任务的执行轨迹，判断是否值得沉淀为一个可复用的技能（SKILL.md）。",
			"",
			"值得沉淀的标准（至少满足一条）：",
			"1. 这类任务以后会重复出现（部署、排错、特定工具链、特定流程、多步骤操作）",
			"2. 轨迹里有明确的步骤、经验、坑点可以复用",
			"3. 不是一次性的琐碎问答或闲聊",
			"",
			skillsBlock,
			"",
			"输出格式（严格遵守，不要输出其他内容）：",
			"- 如果值得沉淀：直接输出完整 SKILL.md 全文，不要用代码块包裹，不要加任何解释。",
			"- frontmatter 必须以此开头：第一行 --- ，第二行必须是 name: <小写字母数字连字符>（不带引号，冒号后直接跟值），第三行 description: <中文，≤1024字符，写明『何时使用』>，最后一行 --- 结束。",
			"- 正文用中文，包含适用场景、步骤流程、常见坑点与修复方法；总长 ≤ 5000 字符。",
			"- 如果不值得沉淀：只输出一行，以 SKIP: 开头并说明原因。",
			"- 如果与已启用技能清单中的技能语义重复：必须输出 SKIP: 与已有技能 <name> 重复（严禁重复生成）。",
			"",
			"执行轨迹如下：",
			"---",
			summary,
			"---",
		].join("\n");

		try {
			const response = await complete(
				model,
				{
					messages: [
						{
							role: "user",
							content: [{ type: "text", text: prompt }],
							timestamp: Date.now(),
						},
					],
				},
				{
					apiKey: auth.apiKey,
					headers: auth.headers,
					env: auth.env,
					reasoningEffort: "minimal", // 注意：部分 OpenAI 兼容中转不接受 "off"（400）
					maxTokens: MAX_OUTPUT_TOKENS,
					cacheRetention: "none",
					sessionId: crypto.randomUUID(),
					signal: ctx.signal,
				},
			);

			const blocks = (response.content ?? []) as any[];
			const raw = blocks
				.filter((c): c is { type: "text"; text: string } => c.type === "text")
				.map((c) => c.text)
				.join("")
				.trim();
			const stopReason = (response as any).stopReason ?? "unknown";
			const errorMessage = ((response as any).errorMessage ?? "") as string;

			// LLM 调用失败或空输出 → 记录真实原因（暂时性失败：不推进采集点，修复后可重试补采）
			if (stopReason === "error" || !raw) {
				const reason =
					stopReason === "error" && errorMessage
						? `LLM 调用失败: ${errorMessage.slice(0, 200)}`
						: `LLM 返回空内容（stopReason=${stopReason}），maxTokens=${MAX_OUTPUT_TOKENS} 可能不足`;
				let draftPath = "";
				try {
					draftPath = saveDraftDump(sessionFile, toolCalls, errors, raw, reason);
				} catch { /* ignore */ }
				state.stats.candidatesRejected = (state.stats.candidatesRejected ?? 0) + 1;
				state.lastCollectionAt = nowIso();
				recordRejection(state, sessionFile, draftPath ? `${reason}（草稿已存: ${draftPath}）` : reason);
				writeState(state);
				appendLog(`| ${nowLocal()} | ${sessionFile.split("/").pop()} | 采集失败 | ${reason.slice(0, 100)} | - |`);
				return `❌ ${reason}`;
			}

			if (raw.startsWith("SKIP:")) {
				const reason = raw.replace(/^SKIP:\s*/i, "").trim() || "未提供原因";
				state.lastCollectionAt = nowIso();
				state.stats.candidatesRejected = (state.stats.candidatesRejected ?? 0) + 1;
				recordRejection(state, sessionFile, reason);
				advanceCollection(state, shortName, entries);
				writeState(state);
				appendLog(
					`| ${nowLocal()} | ${sessionFile.split("/").pop()} | 拒绝沉淀 | ${reason.slice(0, 100)} | - |`,
				);
				return `拒绝沉淀: ${reason}`;
			}

			// 提取 name 作为 slug（宽容匹配：容忍引号、冒号前空格、字段顺序、代码块包裹）
			const rawClean = raw.replace(/```(?:ya?ml|markdown)?\s*/gi, "").trim();
			const nameMatch = rawClean.match(/^name\s*:\s*["']?([^"'\r\n]+)["']?\s*$/m);
			const name = nameMatch ? nameMatch[1].trim() : "";
			const slug = slugify(name || "untitled-skill");
			if (!name) {
				const reason = "LLM 草稿缺少合法 name（frontmatter 格式不符）";
				let draftPath = "";
				try {
					draftPath = saveDraftDump(sessionFile, toolCalls, errors, raw);
				} catch { /* ignore */ }
				state.stats.candidatesRejected = (state.stats.candidatesRejected ?? 0) + 1;
				state.lastCollectionAt = nowIso();
				recordRejection(state, sessionFile, draftPath ? `${reason}（原始草稿已存: ${draftPath}）` : reason);
				advanceCollection(state, shortName, entries);
				writeState(state);
				appendLog(`| ${nowLocal()} | ${sessionFile.split("/").pop()} | 拒绝沉淀 | ${reason} | - |`);
				return `❌ ${reason}`;
			}

			// 代码层查重：slug 与已启用技能完全同名 → 拒绝（LLM 未遵守查重规则的保险丝）
			if (enabledSkills.some((s) => s.name === slug)) {
				const reason = `与已启用技能 ${slug} 完全同名（查重拦截，LLM 未遵守查重规则）`;
				let draftPath = "";
				try {
					draftPath = saveDraftDump(sessionFile, toolCalls, errors, raw, reason);
				} catch { /* ignore */ }
				state.stats.candidatesRejected = (state.stats.candidatesRejected ?? 0) + 1;
				state.lastCollectionAt = nowIso();
				recordRejection(state, sessionFile, draftPath ? `${reason}（草稿已存: ${draftPath}）` : reason);
				advanceCollection(state, shortName, entries);
				writeState(state);
				appendLog(`| ${nowLocal()} | ${sessionFile.split("/").pop()} | 拒绝沉淀 | ${reason.slice(0, 100)} | - |`);
				return `❌ ${reason}`;
			}

			const targetDir = join(CANDIDATES_DIR, slug);
			mkdirSync(targetDir, { recursive: true });
			writeFileSync(join(targetDir, "SKILL.md"), raw, "utf8");

			// 记录来源
			const meta = [
				`---`,
				`candidate-source-session: ${sessionFile.split("/").pop()}`,
				`candidate-tool-calls: ${toolCalls}`,
				`candidate-errors: ${errors}`,
				`candidate-created: ${nowIso()}`,
				`---`,
			].join("\n");
			writeFileSync(join(targetDir, "meta.md"), meta + "\n", "utf8");

			// 更新统计与日志
			state.stats.candidatesCreated = (state.stats.candidatesCreated ?? 0) + 1;
			state.lastCollectionAt = nowIso();
			advanceCollection(state, shortName, entries);
			writeState(state);
			appendLog(
				`| ${nowLocal()} | ${sessionFile.split("/").pop()} | 候选生成 | 工具${toolCalls}次/错误${errors}次 → ${slug} | candidates/${slug}/ |`,
			);
			return `🎉 已生成候选技能: ${slug}（工具${toolCalls}次/错误${errors}次）`;
		} catch (e) {
			// 暂时性失败（LLM 异常）：不推进采集点，修复后可重试补采
			const reason = `LLM 调用异常: ${String(e).slice(0, 200)}`;
			state.stats.candidatesRejected = (state.stats.candidatesRejected ?? 0) + 1;
			state.lastCollectionAt = nowIso();
			recordRejection(state, sessionFile, reason);
			writeState(state);
			appendLog(`| ${nowLocal()} | ${sessionFile.split("/").pop()} | 采集失败 | ${reason.slice(0, 100)} | - |`);
			return `❌ ${reason}`;
		} finally {
			if (!force) busy.delete(sessionFile);
		}
	} catch (e) {
		return `采集异常: ${String(e).slice(0, 200)}`;
	}
}

export default function (pi: ExtensionAPI) {
	// 自动触发：每轮 agent 结束
	pi.on("agent_settled", async (_event, ctx) => {
		try {
			// 心跳：每次 agent 结束都记录时间戳，用户可随时确认扩展是否活着
			try {
				const hb = readState();
				hb.lastSeenAt = nowIso();
				writeState(hb);
			} catch { /* ignore */ }
			await collect(pi, ctx, false);
		} catch {
			/* 任何异常都不打扰用户 */
		}
	});

	// 手动触发：/evolve-collect（立即采集当前会话，绕过节流）
	pi.registerCommand("evolve-collect", {
		description: "手动触发经验采集：立即分析当前会话并草拟候选技能（绕过节流）",
		handler: async (args, ctx) => {
			try {
				const result = await collect(pi, ctx, true);
				appendLog(`| ${nowLocal()} | 手动触发 | 采集 | ${result.replace(/\|/g, "/").slice(0, 100)} | - |`);
				try {
					ctx.ui.notify(`[自我进化] ${result}`, "info");
				} catch { /* 非交互模式可能无 ui */ }
			} catch {
				/* 静默 */
			}
		},
	});
}
