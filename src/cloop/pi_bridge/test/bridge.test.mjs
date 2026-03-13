import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import readline from "node:readline";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const bridgePath = path.resolve(testDir, "..", "bridge.mjs");

function startBridge() {
	const child = spawn(process.execPath, [bridgePath], {
		stdio: ["pipe", "pipe", "pipe"],
	});
	const rl = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
	const stderr = [];
	const lines = [];
	const waiters = [];
	let exitError = null;
	child.stderr.on("data", (chunk) => {
		stderr.push(chunk.toString("utf8"));
	});
	rl.on("line", (line) => {
		const waiter = waiters.shift();
		if (waiter) {
			waiter.resolve(line);
			return;
		}
		lines.push(line);
	});
	child.once("error", (error) => {
		exitError = error;
		const waiter = waiters.shift();
		if (waiter) {
			waiter.reject(error);
		}
	});
	child.once("exit", (code, signal) => {
		exitError = new Error(`bridge exited before emitting a line (code=${code}, signal=${signal})`);
		const waiter = waiters.shift();
		if (waiter) {
			waiter.reject(exitError);
		}
	});

	const readEvent = async () => {
		if (lines.length > 0) {
			return JSON.parse(lines.shift());
		}
		if (exitError) {
			throw exitError;
		}
		const line = await new Promise((resolve, reject) => {
			waiters.push({ resolve, reject });
		});
		return JSON.parse(line);
	};

	const send = (payload) => {
		child.stdin.write(`${JSON.stringify(payload)}\n`);
	};

	const stop = async () => {
		rl.close();
		if (child.stdin && !child.stdin.destroyed) {
			child.stdin.end();
		}
		if (child.exitCode !== null || child.signalCode !== null) {
			return;
		}
		await new Promise((resolve) => {
			const timer = setTimeout(() => {
				child.kill("SIGKILL");
			}, 500);
			child.once("exit", () => {
				clearTimeout(timer);
				resolve();
			});
			child.kill("SIGTERM");
		});
	};

	return { child, readEvent, send, stop, stderr };
}

test("bridge emits hello and responds to ping", async () => {
	const bridge = startBridge();
	try {
		const hello = await bridge.readEvent();
		assert.equal(hello.type, "hello");
		assert.equal(hello.bridge, "cloop-pi-bridge");

		bridge.send({ type: "ping", protocol: 1, request_id: "ping-1" });
		const pong = await bridge.readEvent();
		assert.equal(pong.type, "pong");
		assert.equal(pong.request_id, "ping-1");
		assert.equal(pong.protocol, 1);
	} finally {
		await bridge.stop();
	}
});

test("bridge reports invalid start requests as protocol errors", async () => {
	const bridge = startBridge();
	try {
		await bridge.readEvent();

		bridge.send({
			type: "start",
			protocol: 1,
			request_id: "bad-start",
			model: "",
			messages: [{ role: "user", content: "hi" }],
			thinking_level: "none",
			timeout_ms: 1000,
			max_tool_rounds: 1,
			tools: [],
		});
		const error = await bridge.readEvent();
		assert.equal(error.type, "error");
		assert.equal(error.request_id, "bad-start");
		assert.match(error.message, /model selector/i);
	} finally {
		await bridge.stop();
	}
});
