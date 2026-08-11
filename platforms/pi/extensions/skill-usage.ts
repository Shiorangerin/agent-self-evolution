/**
 * agent-self-evolution —— 技能使用统计扩展（Pi 平台适配）
 *
 * 目的：给启用技能补上「使用反馈回路」。每次 agent 运行结束（agent_settled）时，
 * 用纯规则（零 LLM 成本、零 token）扫描会话轨迹，记录哪些技能被「疑似使用」，
 * 数据写入 <SE_ROOT>/usage.json，供进化流程报告「长期未使用技能」给用户决定归档。
 *
 * 信号定义（启发式，仅供参考，最终决策权在用户）：
 * - 强信号：轨迹中读取/触碰了 pi 技能加载目录下 <name>/SKILL.md 或 <SE_ROOT>/skills/<name> 路径
 * - 弱信号：技能 slug（如 brew-cleanup-optimize）出现在轨迹文本中（用户消息/助手文本/工具参数）
 *
 * 同一会话去重：按会话文件短名记录，同一会话多次触发只计数一次。
 * 所有失败静默处理，绝不打搅用户。
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const EVO_DIR = process.env.SE_ROOT || join(homedir(), ".config", "agent-self-evolution");
const USAGE_FILE = join(EVO_DIR, "usage.json");
const SKILLS_DIR = join(homedir(), ".pi", "agent", "skills"); // pi 的技能加载目录（平台机制）

/** 读取已启用技能名（slug）列表 */
function listSkillNames(): string[] {
	const names: string[] = [];
	try {
		for (const entry of readdirSync(SKILLS_DIR, { withFileTypes: true })) {
			if (entry.name.startsWith(".")) continue;
			if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
			if (!existsSync(join(SKILLS_DIR, entry.name, "SKILL.md"))) continue;
			names.push(entry.name);
		}
	} catch {
		/* 静默 */
	}
	return names.sort();
}

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

/** 收集本次会话轨迹的全部文本（用户消息 + 助手文本 + 工具调用名/参数） */
function buildTraceText(entries: any[]): string {
	const parts: string[] = [];
	for (const e of entries) {
		if (e.type !== "message" || !e.message) continue;
		const m = e.message;
		if (m.role === "user") {
			const t = extractText(m.content).trim();
			if (t && !t.startsWith("/")) parts.push(t);
		} else if (m.role === "assistant") {
			const content = m.content;
			if (typeof content === "string") {
				parts.push(content);
			} else if (Array.isArray(content)) {
				for (const block of content) {
					if (!block || typeof block !== "object") continue;
					if ((block as any).type === "text") {
						const t = (block as { text?: unknown }).text;
						if (typeof t === "string") parts.push(t);
					} else if ((block as any).type === "toolCall") {
						const name = (block as any).name ?? "";
						const args = (block as any).arguments ?? {};
						parts.push(name);
						try {
							parts.push(typeof args === "object" ? JSON.stringify(args) : String(args));
						} catch {
							/* ignore */
						}
					}
				}
			}
		}
	}
	return parts.join("\n");
}

function readUsage(): any {
	try {
		return JSON.parse(readFileSync(USAGE_FILE, "utf8"));
	} catch {
		return { updatedAt: null, skills: {} };
	}
}

function nowIso(): string {
	return new Date().toISOString();
}

/** 核心：扫描当前会话轨迹，更新技能使用统计 */
function track(pi: ExtensionAPI, ctx: any): string {
	try {
		const sessionFile = ctx.sessionManager.getSessionFile();
		if (!sessionFile) return "无会话文件";
		const shortName = sessionFile.split("/").pop() ?? sessionFile;

		const entries = (ctx.sessionManager.getBranch() as any[]) ?? [];
		const text = buildTraceText(entries);
		if (!text.trim()) return "会话无可分析内容";

		const skillNames = listSkillNames();
		if (skillNames.length === 0) return "无已启用技能";

		const usage = readUsage();
		const skills = usage.skills ?? {};
		let hit = 0;

		for (const slug of skillNames) {
			// 会话去重：本会话已记录过则跳过
			const prev = skills[slug];
			if (prev && prev.lastSession === shortName) continue;

			// 强信号：读取了技能文件路径
			const strong = text.includes(`skills/${slug}/SKILL.md`) || text.includes(`skills/${slug}`);
			// 弱信号：slug 出现在轨迹文本中
			const weak = text.includes(slug);

			if (strong || weak) {
				skills[slug] = {
					count: (prev?.count ?? 0) + 1,
					lastUsedAt: nowIso(),
					lastSession: shortName,
					signal: strong ? "strong" : "weak",
				};
				hit++;
			}
		}

		if (hit === 0) return "无技能使用信号";
		usage.updatedAt = nowIso();
		usage.skills = skills;
		writeFileSync(USAGE_FILE, JSON.stringify(usage, null, 2), "utf8");
		return `已记录 ${hit} 个技能使用信号`;
	} catch {
		return "采集异常";
	}
}

export default function (pi: ExtensionAPI) {
	pi.on("agent_settled", async (_event, ctx) => {
		try {
			await track(pi, ctx);
		} catch {
			/* 任何异常都不打扰用户 */
		}
	});
}
