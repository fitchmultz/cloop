import process from "node:process";
import readline from "node:readline";
import { pathToFileURL } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";
import { StringEnum, Type } from "@mariozechner/pi-ai";
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";

export const PROTOCOL_VERSION = 1;
export const BRIDGE_NAME = "cloop-pi-bridge";
export const BRIDGE_VERSION = "0.1.0";

const authStorage = AuthStorage.create();
const modelRegistry = new ModelRegistry(authStorage);
const sessions = new Map();

export function emit(output, payload) {
	output.write(`${JSON.stringify({ protocol: PROTOCOL_VERSION, ...payload })}\n`);
}

export function logError(errorStream, message, error) {
	const detail = error instanceof Error ? error.stack ?? error.message : String(error);
	errorStream.write(`${message}: ${detail}\n`);
}

export function defaultUsage() {
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

export function normalizeTextContent(content) {
	if (typeof content === "string") {
		return [{ type: "text", text: content }];
	}
	if (Array.isArray(content)) {
		return content;
	}
	return [{ type: "text", text: "" }];
}

function parseJsonObject(raw) {
	if (!raw || typeof raw !== "string") {
		return {};
	}
	try {
		const parsed = JSON.parse(raw);
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}

function resolveMessageTimestamp(message, fallbackTimestamp) {
	return typeof message?.timestamp === "number" ? message.timestamp : fallbackTimestamp;
}

function splitSelector(selector) {
	if (typeof selector !== "string" || !selector.includes("/")) {
		return null;
	}
	const [provider, ...rest] = selector.split("/");
	const model = rest.join("/");
	if (!provider || !model) {
		return null;
	}
	return { provider, model };
}

function replayAssistantMetadata(message, defaults) {
	const selector = splitSelector(message?.model);
	return {
		provider:
			typeof message?.provider === "string"
				? message.provider
				: selector?.provider || defaults.provider,
		api: typeof message?.api === "string" ? message.api : defaults.api,
		model:
			typeof message?.model === "string" && !message.model.includes("/")
				? message.model
				: selector?.model || defaults.model,
		usage:
			message?.usage && typeof message.usage === "object" ? message.usage : defaultUsage(),
		stopReason: typeof message?.stop_reason === "string" ? message.stop_reason : "stop",
		errorMessage: typeof message?.error_message === "string" ? message.error_message : undefined,
	};
}

function assistantBlocksFromMessage(message) {
	const blocks = [];
	const content = message?.content;
	if (typeof content === "string" && content.length > 0) {
		blocks.push({ type: "text", text: content });
	} else if (Array.isArray(content)) {
		for (const block of content) {
			if (!block || typeof block !== "object") {
				continue;
			}
			if (block.type === "text" && typeof block.text === "string") {
				blocks.push({ type: "text", text: block.text });
				continue;
			}
			if (block.type === "toolCall" && typeof block.name === "string") {
				blocks.push({
					type: "toolCall",
					id: String(block.id ?? `${block.name}-replay`),
					name: block.name,
					arguments:
						block.arguments && typeof block.arguments === "object" ? block.arguments : {},
				});
			}
		}
	}
	const toolCalls = Array.isArray(message?.tool_calls) ? message.tool_calls : [];
	for (const toolCall of toolCalls) {
		const fn = toolCall?.function ?? {};
		if (!fn.name) {
			continue;
		}
		const args =
			typeof fn.arguments === "string"
				? parseJsonObject(fn.arguments)
				: fn.arguments && typeof fn.arguments === "object"
					? fn.arguments
					: {};
		blocks.push({
			type: "toolCall",
			id: String(toolCall.id ?? `${fn.name}-replay`),
			name: String(fn.name),
			arguments: args,
		});
	}
	return blocks;
}

export function parseConversationMessages(messages, defaults) {
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
		const timestamp = resolveMessageTimestamp(message, baseTimestamp + index);
		if (role === "user") {
			conversation.push({
				role: "user",
				content: normalizeTextContent(message.content),
				timestamp,
			});
			continue;
		}
		if (role === "assistant") {
			const metadata = replayAssistantMetadata(message, defaults);
			conversation.push({
				role: "assistant",
				content: assistantBlocksFromMessage(message),
				api: metadata.api,
				provider: metadata.provider,
				model: metadata.model,
				usage: metadata.usage,
				stopReason: metadata.stopReason,
				errorMessage: metadata.errorMessage,
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
				isError: Boolean(message.is_error),
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

export async function parseModelSelector(selector, registry = modelRegistry) {
	if (typeof selector !== "string" || selector.trim().length === 0) {
		throw new Error("Bridge request missing model selector");
	}

	let model;
	if (selector.includes("/")) {
		const split = splitSelector(selector);
		if (!split) {
			throw new Error(`Invalid model selector: ${selector}`);
		}
		model = registry.find(split.provider, split.model);
		if (!model) {
			throw new Error(`Unsupported pi model selector: ${selector}`);
		}
	} else {
		const matches = registry.getAll().filter((candidate) => candidate.id === selector);
		if (matches.length === 1) {
			model = matches[0];
		} else if (matches.length > 1) {
			throw new Error(`Model selector is ambiguous; use provider/model form: ${selector}`);
		} else {
			throw new Error(`Unsupported pi model selector: ${selector}`);
		}
	}

	const available = await registry.getAvailable();
	const isAvailable = available.some(
		(candidate) => candidate.provider === model.provider && candidate.id === model.id,
	);
	if (!isAvailable) {
		throw new Error(
			`Pi model is not currently available with current auth/config: ${selector}. ` +
				"Run `pi --list-models` to confirm availability and authenticate pi for the selected provider.",
		);
	}
	return model;
}

export function translateSchema(schema) {
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

export function createTool(session, spec, emitEvent = (payload) => emit(process.stdout, payload)) {
	return {
		name: spec.name,
		label: spec.name,
		description: spec.description,
		parameters: translateSchema(spec.input_schema),
		async execute(toolCallId, params) {
			return await new Promise((resolve, reject) => {
				session.pendingToolResults.set(toolCallId, { resolve, reject, toolName: spec.name });
				emitEvent({
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

export function normalizeAssistantMessage(message) {
	const text = [];
	for (const block of message.content ?? []) {
		if (block.type === "text") {
			text.push(block.text);
		}
	}
	return {
		text: text.join(""),
		model: `${message.provider}/${message.model}`,
		model_id: message.model,
		provider: message.provider,
		api: message.api,
		usage: message.usage,
		stop_reason: message.stopReason,
	};
}

export function buildBridgeErrorPayload({
	requestId,
	timedOut = false,
	roundLimitExceeded = false,
	finalMessage = null,
	error = null,
}) {
	if (timedOut) {
		return {
			type: "error",
			request_id: requestId,
			code: "timeout",
			message: finalMessage?.errorMessage || "Pi bridge request timed out",
			retryable: false,
		};
	}
	if (roundLimitExceeded) {
		return {
			type: "error",
			request_id: requestId,
			code: "tool_round_limit",
			message:
				finalMessage?.errorMessage ||
				"Pi bridge tool round limit exceeded before the model produced a terminal response.",
			retryable: false,
		};
	}
	if (finalMessage?.stopReason === "aborted") {
		return {
			type: "error",
			request_id: requestId,
			code: "aborted",
			message: finalMessage.errorMessage || "Pi bridge request was aborted",
			retryable: false,
		};
	}
	return {
		type: "error",
		request_id: requestId,
		code: "bridge_error",
		message:
			finalMessage?.errorMessage || (error instanceof Error ? error.message : String(error ?? "Pi bridge request failed")),
		retryable: false,
	};
}

export async function runSession(
	session,
	{
		AgentClass = Agent,
		emitEvent = (payload) => emit(process.stdout, payload),
		log = (message, error) => logError(process.stderr, message, error),
		registry = modelRegistry,
	} = {},
) {
	let timedOut = false;
	let roundLimitExceeded = false;
	let toolRounds = 0;
	let timeoutHandle = null;
	let unsubscribe = () => {};
	try {
		const model = await parseModelSelector(session.request.model, registry);
		const normalized = parseConversationMessages(session.request.messages, {
			provider: model.provider,
			api: model.api,
			model: model.id,
		});
		if (normalized.messages.length === 0) {
			throw new Error("Pi bridge request must include at least one non-system message");
		}
		const lastMessage = normalized.messages[normalized.messages.length - 1];
		if (lastMessage.role === "assistant") {
			throw new Error("Pi bridge request must end with a user or tool message");
		}
		const tools = (session.request.tools ?? []).map((spec) =>
			createTool(session, spec, emitEvent),
		);

		const agent = new AgentClass();
		agent.setModel(model);
		agent.setSystemPrompt(normalized.systemPrompt);
		agent.setThinkingLevel(
			session.request.thinking_level === "none" ? "off" : session.request.thinking_level,
		);
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
					emitEvent({
						type: "text_delta",
						request_id: session.requestId,
						delta: assistantEvent.delta,
					});
				}
				if (assistantEvent.type === "thinking_delta") {
					emitEvent({
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
				emitEvent({
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
		if (timedOut || roundLimitExceeded || finalMessage.stopReason === "error" || finalMessage.stopReason === "aborted") {
			emitEvent(
				buildBridgeErrorPayload({
					requestId: session.requestId,
					timedOut,
					roundLimitExceeded,
					finalMessage,
				}),
			);
			return;
		}
		emitEvent({
			type: "done",
			request_id: session.requestId,
			...normalizeAssistantMessage(finalMessage),
		});
	} catch (error) {
		log(`Bridge session ${session.requestId} failed`, error);
		emitEvent(
			buildBridgeErrorPayload({ requestId: session.requestId, error }),
		);
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

function handleStart(message, emitEvent) {
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
	void runSession(session, { emitEvent });
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

function handlePing(message, emitEvent) {
	emitEvent({
		type: "pong",
		request_id: message.request_id,
		latency_ms: 0,
	});
}

function dispatch(message, emitEvent) {
	switch (message.type) {
		case "start":
			handleStart(message, emitEvent);
			return;
		case "tool_result":
			handleToolResult(message);
			return;
		case "abort":
			handleAbort(message);
			return;
		case "ping":
			handlePing(message, emitEvent);
			return;
		default:
			throw new Error(`Unsupported bridge message type: ${message.type}`);
	}
}

export function startBridgeProcess({
	input = process.stdin,
	output = process.stdout,
	errorStream = process.stderr,
} = {}) {
	const emitEvent = (payload) => emit(output, payload);
	const log = (message, error) => logError(errorStream, message, error);

	emitEvent({
		type: "hello",
		bridge: BRIDGE_NAME,
		version: BRIDGE_VERSION,
	});

	const rl = readline.createInterface({
		input,
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
			log("Failed to parse bridge input", error);
			return;
		}
		if (message.protocol !== PROTOCOL_VERSION) {
			log("Protocol mismatch", new Error(`Expected ${PROTOCOL_VERSION}, received ${message.protocol}`));
			return;
		}
		try {
			dispatch(message, emitEvent);
		} catch (error) {
			log("Failed to process bridge message", error);
			if (message?.request_id) {
				emitEvent({
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

	return { rl };
}

export function isMainModule(entryArg = process.argv[1]) {
	if (!entryArg) {
		return false;
	}
	return import.meta.url === pathToFileURL(entryArg).href;
}

if (isMainModule()) {
	startBridgeProcess();
}
