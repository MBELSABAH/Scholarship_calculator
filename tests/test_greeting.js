const assert = require("node:assert/strict");
const { formatGreeting, salutationForHour } = require("../frontend/greeting.js");

assert.equal(salutationForHour(8), "Good morning");
assert.equal(salutationForHour(13), "Good afternoon");
assert.equal(salutationForHour(20), "Good evening");
assert.equal(formatGreeting("Mohamed", 8), "Good morning, Mohamed.");
assert.equal(formatGreeting("Mohamed", 13), "Good afternoon, Mohamed.");
assert.equal(formatGreeting("Mohamed", 20), "Good evening, Mohamed.");
assert.equal(formatGreeting("Mohamed,", 13), "Good afternoon, Mohamed.");

console.log("Greeting formatting tests passed.");
