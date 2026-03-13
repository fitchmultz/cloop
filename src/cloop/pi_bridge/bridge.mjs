import process from "node:process";
import readline from "node:readline";

import { Agent } from "@mariozechner/pi-agent-core";
import { StringEnum, Type } from "@mariozechner/pi-ai";
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";

const PROTOCOL_VERSION = 1;
const BRIDGE_NAME = "cloop-pi-bridge";
const BRIDGE_VERSION = "0.1.0";

const authStorage = AuthStorage.create();
const modelRegistry = new ModelRegistry(authStorage);
const sessions = new Map();

function emit(payload) {
	process.stdout.write(`${JSON.stringify({ protocol: PROTOCOL_VERSION, ...payload })}\n`);
}

function logError(message, error) {
	const detail = error instanceof Error ? error.stack ?? error.message : String(error);
	process.stderr.write(`${message}: ${detail}\n`);
}

function parseModelSelector(selector) {
	if (typeof selector !== "string" || selector.trim().length === 0) {
		throw new Error("Bridge request missing model selector");
	}
	if (selector.includes("/")) {
		const [provider, ...rest] = selector.split("/");
		const modelId = rest.join("/");
		if (!provider || !modelId) {
			throw new Error(`Invalid model selector: ${selector}`);
		}
		const model = modelRegistry.find(provider, modelId);
		if (!model) {
			throw new Error(`Unsupported or unavailable pi model: ${selector}`);
		}
		return model;
	}
	const matches = modelRegistry.getAll().filter((model) => model.id === selector);
	if (matches.length === 1) {
		return matches[0];
	}
	if (matches.length > 1) {
		throw new Error(`Model selector is ambiguous; use provider/model form: ${selector}`);
	}
	throw new Error(`Unsupported or unavailable pi model: ${selector}`);
}

function defaultUsage() {
	return {
		input: 0,
		output: 0,
		cacheRead: 0,
		cacheWrite: 0,
		totalTokens: 0,
		cost: {
			input: 0,
			output: 0,
			cacheRead: 0,
			cacheWrite: 0,
			total: 0,
		},
	};
}

function normalizeTextContent(content) {
	if (typeof content === "string") {
		return [{ type: "text", text: content }];
	}
	if (Array.isArray(content)) {
		return content;
	}
	return [{ type: "text", text: "" }];
}

function parseSystemPrompt(messages) {
	const systemParts = [];
	const conversation = [];
	const baseTimestamp = Date.now();
	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index] ?? {};
		const role = message.role;
		if (role === "system") {
			const content = typeof message.content === "string" ? message.content : "";
			if (content) {
				systemParts.push(content);
			}
			continue;
		}
		const timestamp = baseTimestamp + index;
		if (role === "user") {
			conversation.push({
				role: "user",
				content: normalizeTextContent(message.content),
				timestamp,
			});
			continue;
		}
		if (role === "assistant") {
			const blocks = [];
			const content = message.content;
			if (typeof content === "string" && content.length > 0) {
				blocks.push({ type: "text", text: content });
			}
			const toolCalls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
			for (const toolCall of toolCalls) {
				const fn = toolCall?.function ?? {};
				if (!fn.name) {
					continue;
				}
				let args = fn.arguments ?? {};
				if (typeof args === "string") {
					try {
						args = JSON.parse(args || "{}");
					} catch {
						args = {};
					}
				}
				blocks.push({
					type: "toolCall",
					id: String(toolCall.id ?? `${fn.name}-${timestamp}`),
					name: String(fn.name),
					arguments: args && typeof args === "object" ? args : {},
				});
			}
			conversation.push({
				role: "assistant",
				content: blocks,
				api: "openai-completions",
				provider: "openai",
				model: "historical-context",
				usage: defaultUsage(),
				stopReason: "stop",
				timestamp,
			});
			continue;
		}
		if (role === "tool") {
			conversation.push({
				role: "toolResult",
				toolCallId: String(message.tool_call_id ?? `tool-${timestamp}`),
				toolName: String(message.name ?? "tool"),
				content: normalizeTextContent(message.content),
				isError: false,
				timestamp,
			});
			continue;
		}
		throw new Error(`Unsupported bridge message role: ${String(role)}`);
	}
	return {
		systemPrompt: systemParts.join("\n\n"),
		messages: conversation,
	};
}

function translateSchema(schema) {
	if (!schema || typeof schema !== "object") {
		throw new Error("Tool schema must be a JSON object");
	}
	const description = typeof schema.description === "string" ? schema.description : undefined;
	const defaultValue = schema.default;
	if (schema.type === "string") {
		if (Array.isArray(schema.enum)) {
			return StringEnum(schema.enum, { description, default: defaultValue });
		}
		return Type.String({ description, default: defaultValue });
	}
	if (schema.type === "integer") {
		return Type.Integer({
			description,
			default: defaultValue,
			minimum: schema.minimum,
			maximum: schema.maximum,
		});
	}
	if (schema.type === "number") {
		return Type.Number({
			description,
			default: defaultValue,
			minimum: schema.minimum,
			maximum: schema.maximum,
		});
	}
	if (schema.type === "boolean") {
		return Type.Boolean({ description, default: defaultValue });
	}
	if (schema.type === "array") {
		return Type.Array(translateSchema(schema.items ?? { type: "string" }), {
			description,
			default: defaultValue,
			minItems: schema.minItems,
			maxItems: schema.maxItems,
		});
	}
	if (schema.type === "object") {
		const properties = schema.properties ?? {};
		const required = new Set(Array.isArray(schema.required) ? schema.required : []);
		const translated = {};
		for (const [key, value] of Object.entries(properties)) {
			const propSchema = translateSchema(value);
			translated[key] = required.has(key) ? propSchema : Type.Optional(propSchema);
		}
		return Type.Object(translated, {
			description,
			additionalProperties: schema.additionalProperties ?? false,
		});
	}
	throw new Error(`Unsupported tool schema type: ${String(schema.type)}`);
}

function createTool(session, spec) {
	return {
		name: spec.name,
		label: spec.name,
		description: spec.description,
		parameters: translateSchema(spec.input_schema),
		async execute(toolCallId, params) {
			return await new Promise((resolve, reject) => {
				session.pendingToolResults.set(toolCallId, { resolve, reject, toolName: spec.name });
				emit({
					type: "tool_call",
					request_id: session.requestId,
					tool_call_id: toolCallId,
					name: spec.name,
					arguments: params,
				});
			});
		},
	};
}

function normalizeAssistantMessage(message) {
	const text = [];
	for (const block of message.content ?? []) {
		if (block.type === "text") {
			text.push(block.text);
		}
	}
	return {
		text: text.join(""),
		model: `${message.provider}/${message.model}`,
		provider: message.provider,
		api: message.api,
		usage: message.usage,
		stop_reason: message.stopReason,
	};
}

async function runSession(session) {
	let timedOut = false;
	let roundLimitExceeded = false;
	let toolRounds = 0;
	let timeoutHandle = null;
	let unsubscribe = () => {};
	try {
		const model = parseModelSelector(session.request.model);
		const normalized = parseSystemPrompt(session.request.messages);
		if (normalized.messages.length === 0) {
			throw new Error("Pi bridge request must include at least one non-system message");
		}
		const lastMessage = normalized.messages[normalized.messages.length - 1];
		if (lastMessage.role === "assistant") {
			throw new Error("Pi bridge request must end with a user or tool message");
		}
		const tools = (session.request.tools ?? []).map((spec) => createTool(session, spec));

		const agent = new Agent();
		agent.setModel(model);
		agent.setSystemPrompt(normalized.systemPrompt);
		agent.setThinkingLevel(session.request.thinking_level === "none" ? "off" : session.request.thinking_level);
		agent.setTools(tools);
		agent.replaceMessages(normalized.messages);
		session.agent = agent;

		timeoutHandle =
			typeof session.request.timeout_ms === "number" && session.request.timeout_ms > 0
				? setTimeout(() => {
						timedOut = true;
						agent.abort();
				  }, session.request.timeout_ms)
				: null;

		unsubscribe = agent.subscribe((event) => {
			if (event.type === "message_update") {
				const assistantEvent = event.assistantMessageEvent;
				if (assistantEvent.type === "text_delta") {
					emit({
						type: "text_delta",
						request_id: session.requestId,
						delta: assistantEvent.delta,
					});
				}
				if (assistantEvent.type === "thinking_delta") {
					emit({
						type: "thinking_delta",
						request_id: session.requestId,
						delta: assistantEvent.delta,
					});
				}
			}
			if (event.type === "turn_end" && event.toolResults.length > 0) {
				toolRounds += 1;
				if (toolRounds > (session.request.max_tool_rounds ?? 1)) {
					roundLimitExceeded = true;
					agent.abort();
				}
			}
			if (event.type === "tool_execution_end") {
				const details = event.result?.details ?? null;
				emit({
					type: "tool_result",
					request_id: session.requestId,
					tool_call_id: event.toolCallId,
					tool_name: event.toolName,
					is_error: Boolean(details?._cloop_is_error ?? event.isError),
					details,
				});
			}
		});

		await agent.continue();
		unsubscribe();
		if (timeoutHandle) {
			clearTimeout(timeoutHandle);
		}

		const finalMessage = [...agent.state.messages]
			.reverse()
			.find((message) => message.role === "assistant");
		if (!finalMessage) {
			throw new Error("Pi bridge finished without an assistant message");
		}
		if (timedOut || finalMessage.stopReason === "error" || finalMessage.stopReason === "aborted") {
			emit({
				type: "error",
				request_id: session.requestId,
				code: timedOut ? "timeout" : roundLimitExceeded ? "tool_round_limit" : "bridge_error",
				message:
					finalMessage.errorMessage ||
					(timedOut
						? "Pi bridge request timed out"
						: roundLimitExceeded
							? "Pi bridge tool round limit exceeded"
							: "Pi bridge request failed"),
				retryable: false,
			});
			return;
		}
		emit({
			type: "done",
			request_id: session.requestId,
			...normalizeAssistantMessage(finalMessage),
		});
	} catch (error) {
		logError(`Bridge session ${session.requestId} failed`, error);
		emit({
			type: "error",
			request_id: session.requestId,
			code: "bridge_error",
			message: error instanceof Error ? error.message : String(error),
			retryable: false,
		});
	} finally {
		unsubscribe();
		if (timeoutHandle) {
			clearTimeout(timeoutHandle);
		}
		for (const pending of session.pendingToolResults.values()) {
			pending.reject(new Error("Pi bridge session ended before tool result arrived"));
		}
		sessions.delete(session.requestId);
	}
}

function handleStart(message) {
	if (!message.request_id || typeof message.request_id !== "string") {
		throw new Error("Bridge start message requires request_id");
	}
	if (sessions.has(message.request_id)) {
		throw new Error(`Duplicate bridge request_id: ${message.request_id}`);
	}
	const session = {
		requestId: message.request_id,
		request: message,
		agent: null,
		pendingToolResults: new Map(),
	};
	sessions.set(message.request_id, session);
	void runSession(session);
}

function handleToolResult(message) {
	const session = sessions.get(message.request_id);
	if (!session) {
		throw new Error(`Unknown bridge request_id for tool_result: ${message.request_id}`);
	}
	const pending = session.pendingToolResults.get(message.tool_call_id);
	if (!pending) {
		throw new Error(`Unknown tool_call_id for tool_result: ${message.tool_call_id}`);
	}
	session.pendingToolResults.delete(message.tool_call_id);
	const payload = message.payload ?? {};
	const text = JSON.stringify(payload);
	pending.resolve({
		content: [{ type: "text", text }],
		details: { ...payload, _cloop_is_error: Boolean(message.is_error) },
	});
}

function handleAbort(message) {
	const session = sessions.get(message.request_id);
	if (!session || !session.agent) {
		return;
	}
	session.agent.abort();
}

function handlePing(message) {
	emit({
		type: "pong",
		request_id: message.request_id,
		latency_ms: 0,
	});
}

function dispatch(message) {
	switch (message.type) {
		case "start":
			handleStart(message);
			return;
		case "tool_result":
			handleToolResult(message);
			return;
		case "abort":
			handleAbort(message);
			return;
		case "ping":
			handlePing(message);
			return;
		default:
			throw new Error(`Unsupported bridge message type: ${message.type}`);
	}
}

emit({
	type: "hello",
	bridge: BRIDGE_NAME,
	version: BRIDGE_VERSION,
});

const rl = readline.createInterface({
	input: process.stdin,
	crlfDelay: Infinity,
});

rl.on("line", (line) => {
	if (!line.trim()) {
		return;
	}
	let message;
	try {
		message = JSON.parse(line);
	} catch (error) {
		logError("Failed to parse bridge input", error);
		return;
	}
	if (message.protocol !== PROTOCOL_VERSION) {
		logError("Protocol mismatch", new Error(`Expected ${PROTOCOL_VERSION}, received ${message.protocol}`));
		return;
	}
	try {
		dispatch(message);
	} catch (error) {
		logError("Failed to process bridge message", error);
		if (message?.request_id) {
			emit({
				type: "error",
				request_id: message.request_id,
				code: "protocol_error",
				message: error instanceof Error ? error.message : String(error),
				retryable: false,
			});
		}
	}
});

rl.on("close", () => {
	for (const session of sessions.values()) {
		if (session.agent) {
			session.agent.abort();
		}
	}
});
