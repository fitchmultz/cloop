/**
 * markdown.js - Safe markdown rendering utilities.
 *
 * Purpose:
 *   Convert lightweight markdown into sanitized HTML for chat and other rich text.
 *
 * Responsibilities:
 *   - Block-level markdown rendering
 *   - Inline markdown rendering
 *   - Safe link sanitization
 *
 * Non-scope:
 *   - Full CommonMark parity
 *   - Syntax highlighting
 */

import { escapeHtml } from './utils.js';

const CODE_SPAN_TOKEN = "__CLOOP_CODE_SPAN__";

function sanitizeUrl(url) {
  const trimmed = String(url ?? "").trim();
  if (/^(https?:|mailto:)/i.test(trimmed)) {
    return escapeHtml(trimmed);
  }
  return "#";
}

function renderInlineMarkdown(text) {
  const escaped = escapeHtml(text);
  const codeSpans = [];

  let html = escaped.replace(/`([^`]+)`/g, (_, code) => {
    const token = `${CODE_SPAN_TOKEN}${codeSpans.length}__`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });

  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => (
    `<a href="${sanitizeUrl(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
  ));
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*]+)\*(?=[\s.,!?;:)]|$)/g, "$1<em>$2</em>");

  return codeSpans.reduce(
    (result, snippet, index) => result.replace(`${CODE_SPAN_TOKEN}${index}__`, snippet),
    html,
  );
}

function wrapList(items, type) {
  if (items.length === 0) {
    return "";
  }
  const tag = type === "ordered" ? "ol" : "ul";
  return `<${tag}>${items.map((item) => `<li>${item}</li>`).join("")}</${tag}>`;
}

export function renderMarkdown(markdown) {
  if (!markdown) {
    return "";
  }

  const lines = String(markdown).replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listType = null;
  let listItems = [];
  let codeFence = null;
  let codeLines = [];
  let quoteLines = [];

  const flushParagraph = () => {
    if (paragraphLines.length === 0) {
      return;
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraphLines.join(" "))}</p>`);
    paragraphLines = [];
  };

  const flushList = () => {
    if (!listType || listItems.length === 0) {
      return;
    }
    blocks.push(wrapList(listItems, listType));
    listType = null;
    listItems = [];
  };

  const flushQuote = () => {
    if (quoteLines.length === 0) {
      return;
    }
    blocks.push(`<blockquote><p>${renderInlineMarkdown(quoteLines.join(" "))}</p></blockquote>`);
    quoteLines = [];
  };

  const flushCode = () => {
    if (codeFence === null) {
      return;
    }
    const languageClass = codeFence ? ` class="language-${escapeHtml(codeFence)}"` : "";
    blocks.push(`<pre><code${languageClass}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeFence = null;
    codeLines = [];
  };

  for (const line of lines) {
    const fenceMatch = line.match(/^```([\w-]+)?\s*$/);
    if (fenceMatch) {
      flushParagraph();
      flushList();
      flushQuote();

      if (codeFence !== null) {
        flushCode();
      } else {
        codeFence = fenceMatch[1] ?? "";
      }
      continue;
    }

    if (codeFence !== null) {
      codeLines.push(line);
      continue;
    }

    if (/^\s*$/.test(line)) {
      flushParagraph();
      flushList();
      flushQuote();
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      flushQuote();
      const level = headingMatch[1].length;
      blocks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2].trim())}</h${level}>`);
      continue;
    }

    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      flushParagraph();
      flushList();
      flushQuote();
      blocks.push("<hr>");
      continue;
    }

    const quoteMatch = line.match(/^\s*>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quoteLines.push(quoteMatch[1]);
      continue;
    }

    const unorderedMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      flushQuote();
      if (listType && listType !== "unordered") {
        flushList();
      }
      listType = "unordered";
      listItems.push(renderInlineMarkdown(unorderedMatch[1].trim()));
      continue;
    }

    const orderedMatch = line.match(/^\s*\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      flushQuote();
      if (listType && listType !== "ordered") {
        flushList();
      }
      listType = "ordered";
      listItems.push(renderInlineMarkdown(orderedMatch[1].trim()));
      continue;
    }

    flushList();
    flushQuote();
    paragraphLines.push(line.trim());
  }

  flushParagraph();
  flushList();
  flushQuote();
  flushCode();

  return blocks.join("");
}
