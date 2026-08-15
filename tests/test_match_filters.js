"use strict";

const assert = require("node:assert/strict");
const { matchFilterCounts, matchFilterEmptyMessage } = require("../frontend/match_filters.js");

const matches = [
  ...Array.from({ length: 2 }, () => ({ match_level: "excellent" })),
  { match_level: "strong" },
  ...Array.from({ length: 3 }, () => ({ match_level: "potential" })),
  ...Array.from({ length: 2 }, () => ({ match_level: "unlikely" })),
];

assert.deepEqual(matchFilterCounts(matches), {
  all: 8,
  excellent: 2,
  strong: 1,
  potential: 3,
  unlikely: 2,
});

matches[3].match_level = "excellent";
assert.equal(matchFilterCounts(matches).excellent, 3);
assert.equal(matchFilterCounts(matches).potential, 2);
assert.equal(matchFilterEmptyMessage("potential"), "No Potential Fit scholarships right now.");

console.log("Scholarship match filter tests passed.");
