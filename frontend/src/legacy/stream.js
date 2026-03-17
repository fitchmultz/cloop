/**
 * stream.js - Browser-side SSE helpers
 *
 * Purpose:
 *   Parse JSON server-sent event streams consistently for chat and RAG flows.
 *
 * Responsibilities:
 *   - Consume ReadableStream responses from fetch()
 *   - Parse SSE event/data blocks
 *   - Emit JSON payloads to feature modules
 *
 * Non-scope:
 *   - Feature-specific rendering decisions
 *   - HTTP request creation
 */

export async function consumeJsonEventStream(response, onEvent) {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Streaming response body is unavailable.");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  const flushBlock = (block) => {
    if (!block.trim()) {
      return;
    }

    let eventName = "message";
    const dataLines = [];

    for (const rawLine of block.split("\n")) {
      const line = rawLine.trimEnd();
      if (!line) {
        continue;
      }
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim() || "message";
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    if (!dataLines.length) {
      return;
    }

    const payload = JSON.parse(dataLines.join("\n"));
    onEvent(eventName, payload);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundaryIndex = buffer.indexOf("\n\n");
    while (boundaryIndex !== -1) {
      const block = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);
      flushBlock(block);
      boundaryIndex = buffer.indexOf("\n\n");
    }

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    flushBlock(buffer);
  }
}
