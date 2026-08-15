(function exposeGreeting(root) {
  function salutationForHour(hour) {
    if (hour < 12) return "Good morning";
    if (hour < 18) return "Good afternoon";
    return "Good evening";
  }

  function formatGreeting(displayName, hour) {
    const name = String(displayName || "").trim().replace(/[,.]+$/, "") || "Student";
    return `${salutationForHour(hour)}, ${name}.`;
  }

  const api = { salutationForHour, formatGreeting };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AcademicCopilotGreeting = api;
})(typeof window !== "undefined" ? window : globalThis);
