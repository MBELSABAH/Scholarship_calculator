"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");

const html = fs.readFileSync("frontend/index.html", "utf8");
const app = fs.readFileSync("frontend/app.js", "utf8");

assert.match(html, /<form id="connect-form" method="post" novalidate>/);
assert.match(html, /id="password"[^>]*type="password"/);
assert.match(app, /connectForm\.addEventListener\("submit", \(event\) => \{\s*event\.preventDefault\(\);/);
assert.match(app, /apiRequest\("\/api\/connect", \{\s*method: "POST"/);
assert.ok(!/URLSearchParams\([^)]*(?:username|password)/.test(app));
assert.match(app, /passwordInput\.value = ""/);
for (const handler of ["demoButton", "disconnectButton", "chatForm", "findScholarshipsButton", "setupSpeechRecognition"]) {
  assert.ok(app.includes(handler), `expected ${handler} wiring`);
}
assert.equal((app.match(/addChatMessage\("assistant", state\.status_message\)/g) || []).length, 0);
assert.match(app, /previous\?\.classList\.contains\(role\).*previousBubble\?\.textContent/);

console.log("Frontend login and bootstrap regression tests passed.");
