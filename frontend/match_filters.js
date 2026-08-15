"use strict";

const MATCH_FILTER_LEVELS = ["all", "excellent", "strong", "potential", "unlikely"];
const MATCH_FILTER_LABELS = {
  all: "All",
  excellent: "Excellent",
  strong: "Strong",
  potential: "Potential",
  unlikely: "Unlikely",
};

function matchFilterCounts(matches) {
  const counts = Object.fromEntries(MATCH_FILTER_LEVELS.map((level) => [level, 0]));
  for (const match of matches || []) {
    counts.all += 1;
    if (Object.hasOwn(counts, match?.match_level)) counts[match.match_level] += 1;
  }
  return counts;
}

function matchFilterEmptyMessage(level) {
  return level === "all"
    ? "No scholarships match the current filters."
    : `No ${MATCH_FILTER_LABELS[level] || "matching"}${level === "potential" ? " Fit" : " Match"} scholarships right now.`;
}

const exported = { MATCH_FILTER_LEVELS, MATCH_FILTER_LABELS, matchFilterCounts, matchFilterEmptyMessage };
if (typeof module !== "undefined") module.exports = exported;
if (typeof window !== "undefined") window.AcademicCopilotMatchFilters = exported;
