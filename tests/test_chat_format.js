"use strict";

const assert = require("node:assert/strict");
const { renderSafeBasicMarkdown } = require("../frontend/chat_format.js");

const bold = renderSafeBasicMarkdown("Your latest scholarship is **$2,000**.");
assert.match(bold, /<strong>\$2,000<\/strong>/);
assert.ok(!bold.includes("**"));

const heading = renderSafeBasicMarkdown("### Scholarship");
assert.match(heading, /class="chat-markdown-heading">Scholarship<\/div>/);
assert.ok(!heading.includes("###"));

const bullets = renderSafeBasicMarkdown("- First match\n• Second match");
assert.match(bullets, /<ul class="chat-markdown-list">/);
assert.match(bullets, /<li>First match<\/li><li>Second match<\/li>/);

const hostile = renderSafeBasicMarkdown("**<script>alert(1)</script>** <img src=x onerror=alert(2)>");
assert.ok(!hostile.includes("<script>"));
assert.ok(!hostile.includes("<img"));
assert.match(hostile, /&lt;script&gt;/);

console.log("Safe chat Markdown formatter tests passed.");
