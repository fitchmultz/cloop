/**
 * stream.ts - Browser-side SSE helpers.
 *
 * Purpose:
 *   Parse JSON server-sent event streams consistently for chat and RAG flows.
 *
 * Responsibilities:
 *   - Consume ReadableStream responses from fetch().
 *   - Parse SSE event/data blocks.
 *   - Emit typed JSON payloads to feature modules.
 *
 * Scope:
 *   - Streaming helpers only.
 *
 * Usage:
 *   - Imported by chat.ts and rag.ts.
 *
 * Invariants/Assumptions:
 *   - Backend streaming responses use SSE-style event/data framing.
 *   - Each data block is valid JSON.
 */

export async function consumeJsonEventStream<TPayload>(
  response: Response,
  onEvent: (eventName: string, payload: TPayload) => void,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Streaming response body is unavailable.");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  const flushBlock = (block: string): void => {
    if (!block.trim()) {
      return;
    }

    let eventName = "message";
    const dataLines: string[] = [];

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

    if (dataLines.length === 0) {
      return;
    }

    onEvent(eventName, JSON.parse(dataLines.join("\n")) as TPayload);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

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
