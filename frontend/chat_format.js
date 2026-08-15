(function installAcademicCopilotChatFormat(root) {
  "use strict";

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[character]));

  function renderInlineMarkdown(value) {
    return escapeHtml(value)
      .replace(/\*\*([^\n*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^\n*]+)\*/g, "<em>$1</em>");
  }

  function renderSafeBasicMarkdown(value) {
    const output = [];
    let listOpen = false;
    const closeList = () => {
      if (!listOpen) return;
      output.push("</ul>");
      listOpen = false;
    };

    String(value ?? "").replace(/\r\n?/g, "\n").split("\n").forEach((line) => {
      const bullet = line.match(/^\s*[-*•]\s+(.+)$/);
      if (bullet) {
        if (!listOpen) {
          output.push('<ul class="chat-markdown-list">');
          listOpen = true;
        }
        output.push(`<li>${renderInlineMarkdown(bullet[1])}</li>`);
        return;
      }

      closeList();
      const heading = line.match(/^\s*#{1,6}\s+(.+)$/);
      if (heading) {
        output.push(`<div class="chat-markdown-heading">${renderInlineMarkdown(heading[1])}</div>`);
      } else if (line.trim()) {
        output.push(`<div class="chat-markdown-line">${renderInlineMarkdown(line)}</div>`);
      } else {
        output.push('<div class="chat-markdown-spacer" aria-hidden="true"></div>');
      }
    });
    closeList();
    return output.join("");
  }

  const formatter = Object.freeze({ renderSafeBasicMarkdown });
  root.AcademicCopilotChatFormat = formatter;
  if (typeof module !== "undefined" && module.exports) module.exports = formatter;
}(typeof window === "undefined" ? globalThis : window));
