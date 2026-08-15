const loginView = document.querySelector("#login-view");
const dashboardView = document.querySelector("#dashboard-view");
const loginCard = document.querySelector("#login-card");
const loadingCard = document.querySelector("#loading-card");
const connectForm = document.querySelector("#connect-form");
const demoButton = document.querySelector("#demo-button");
const disconnectButton = document.querySelector("#disconnect-button");
const formError = document.querySelector("#form-error");
const progressItems = [...document.querySelectorAll(".progress-list li")];
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const chatSend = document.querySelector("#chat-send");
const chatMessages = document.querySelector("#chat-messages");
const chatStatus = document.querySelector("#chat-status");
const chatStatusText = document.querySelector("#chat-status-text");
const chatSuggestions = document.querySelector("#chat-suggestions");
const copilotContext = document.querySelector("#copilot-context");
const microphoneButton = document.querySelector("#microphone-button");
const findScholarshipsButton = document.querySelector("#find-scholarships-button");
const scholarshipFilters = document.querySelector("#scholarship-filters");
const scholarshipResults = document.querySelector("#scholarship-results");
const scholarshipDetail = document.querySelector("#scholarship-detail");
const applicationView = document.querySelector("#application-view");

const initialChatSuggestions = [
  "Find scholarships I should apply for.",
  "What was my latest scholarship?",
  "What are my lowest grades?",
];

let conversationId = null;
let chatRequestActive = false;
let currentView = "dashboard";
let currentScholarshipId = null;
let currentApplicationId = null;
let scholarshipMatches = [];
let activeMatchFilter = "all";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[character]));
const renderSafeBasicMarkdown = window.AcademicCopilotChatFormat.renderSafeBasicMarkdown;

const formatNumber = (value, digits = 0) => value === null || value === undefined ? "—" : Number(value).toLocaleString("en-CA", {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
});

const formatCurrency = (value) => value === null || value === undefined ? "—" : Number(value).toLocaleString("en-CA", {
  style: "currency", currency: "CAD", maximumFractionDigits: 0,
});

const formatYear = (year) => escapeHtml(String(year).replace("-", "–"));

const performanceMeta = {
  excellent: { label: "Excellent", range: "90–100" },
  strong: { label: "Strong", range: "80–89" },
  good: { label: "Good", range: "70–79" },
  needs_improvement: { label: "Needs improvement", range: "60–69" },
  low: { label: "Low / failing range", range: "Below 60" },
  neutral: { label: "Non-graded", range: "Special grade" },
};

const gradeBandChips = [
  ["90_100", "90+", "excellent"],
  ["80_89", "80–89", "strong"],
  ["70_79", "70–79", "good"],
  ["60_69", "60–69", "needs_improvement"],
  ["below_60", "<60", "low"],
];

function officialSourceUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    const allowed = new Set(["upei.ca", "www.upei.ca", "secure.upei.ca", "calendar.upei.ca", "app.upei.ca"]);
    return url.protocol === "https:" && allowed.has(url.hostname) ? url.href : null;
  } catch (_) {
    return null;
  }
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : "The request could not be completed.");
  }
  return body;
}

function setCopilotContext(view, scholarshipId = null, applicationId = null, label = null) {
  currentView = view;
  currentScholarshipId = scholarshipId;
  currentApplicationId = applicationId;
  const labels = {
    dashboard: "Dashboard overview",
    scholarships: "Scholarship matches",
    scholarship_detail: "Selected scholarship",
    application: "Scholarship application",
  };
  copilotContext.textContent = label || labels[view] || labels.dashboard;
}

function renderChatSuggestions(suggestions) {
  chatSuggestions.replaceChildren();
  suggestions.slice(0, 3).forEach((suggestion) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-chip";
    button.textContent = suggestion;
    button.disabled = chatRequestActive;
    button.addEventListener("click", () => sendChatMessage(suggestion));
    chatSuggestions.append(button);
  });
}

function showChatEmptyState() {
  const empty = document.createElement("div");
  empty.id = "chat-empty";
  empty.className = "chat-empty";
  empty.innerHTML = '<span class="chat-spark" aria-hidden="true">✦</span><p>Ask about your record or find official UPEI scholarships.</p>';
  chatMessages.replaceChildren(empty);
}

function resetChat() {
  conversationId = null;
  chatRequestActive = false;
  chatForm.reset();
  chatStatus.hidden = true;
  chatInput.disabled = false;
  chatSend.disabled = false;
  showChatEmptyState();
  renderChatSuggestions(initialChatSuggestions);
  setCopilotContext("dashboard");
}

function addChatMessage(role, message, isError = false, sources = []) {
  document.querySelector("#chat-empty")?.remove();
  const row = document.createElement("div");
  row.className = `chat-message ${role}${isError ? " error" : ""}`;
  const label = document.createElement("span");
  label.className = "chat-message-label";
  label.textContent = role === "user" ? "You" : "Academic Copilot";
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  if (role === "assistant" && !isError) {
    // The formatter escapes model text before adding a tiny allow-listed Markdown subset.
    bubble.innerHTML = renderSafeBasicMarkdown(message);
  } else {
    bubble.textContent = message;
  }
  row.append(label, bubble);
  const validSources = sources.map((source) => ({ ...source, safeUrl: officialSourceUrl(source.url) })).filter((source) => source.safeUrl);
  if (validSources.length) {
    const sourceList = document.createElement("div");
    sourceList.className = "chat-sources";
    validSources.slice(0, 3).forEach((source) => {
      const link = document.createElement("a");
      link.href = source.safeUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.title || "Official UPEI source";
      sourceList.append(link);
    });
    row.append(sourceList);
  }
  chatMessages.append(row);
  chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: "smooth" });
}

function statusForQuestion(question) {
  const lowered = question.toLowerCase();
  if (/draft|essay|statement/.test(lowered)) return "Preparing your draft…";
  if (/apply|application|submit/.test(lowered)) return "Reviewing application requirements…";
  if (lowered.includes("find") && lowered.includes("scholarship")) return "Searching UPEI scholarships…";
  if (/scholarship|average|best year/.test(lowered)) return "Comparing scholarship results…";
  if (/what if|project|future/.test(lowered)) return "Calculating your projected GPA…";
  return "Checking your academic profile…";
}

function setChatBusy(isBusy, question = "") {
  chatRequestActive = isBusy;
  chatInput.disabled = isBusy;
  chatSend.disabled = isBusy;
  microphoneButton.disabled = isBusy;
  chatSuggestions.querySelectorAll("button").forEach((button) => { button.disabled = isBusy; });
  chatStatusText.textContent = isBusy ? statusForQuestion(question) : "";
  chatStatus.hidden = !isBusy;
}

async function refreshScholarshipMatches() {
  const body = await apiRequest("/api/scholarships");
  scholarshipMatches = Array.isArray(body.matches) ? body.matches : [];
  renderScholarshipMatches();
}

async function refreshCurrentApplication() {
  if (!currentApplicationId) return;
  renderApplication(await apiRequest(`/api/applications/${encodeURIComponent(currentApplicationId)}`));
}

async function applyUiUpdates(updates) {
  for (const update of updates || []) {
    if (update === "refresh_scholarships") await refreshScholarshipMatches();
    if (update === "refresh_application") await refreshCurrentApplication();
  }
}

async function sendChatMessage(rawMessage) {
  const message = String(rawMessage || "").trim();
  if (!message || chatRequestActive) return;
  addChatMessage("user", message);
  chatInput.value = "";
  chatSuggestions.replaceChildren();
  setChatBusy(true, message);
  try {
    const payload = {
      message,
      current_view: currentView,
      current_scholarship_id: currentScholarshipId,
      current_application_id: currentApplicationId,
    };
    if (conversationId) payload.conversation_id = conversationId;
    const responseBody = await apiRequest("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    addChatMessage("assistant", responseBody.message, false, responseBody.sources || []);
    conversationId = responseBody.conversation_id;
    await applyUiUpdates(responseBody.ui_updates);
    renderChatSuggestions(Array.isArray(responseBody.suggested_replies) ? responseBody.suggested_replies : initialChatSuggestions.slice(0, 2));
  } catch (error) {
    addChatMessage("assistant", error.message, true);
    renderChatSuggestions(initialChatSuggestions.slice(0, 2));
  } finally {
    setChatBusy(false);
    chatInput.focus();
  }
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendChatMessage(chatInput.value);
});

function setupSpeechRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return;
  const recognition = new Recognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-CA";
  let originalText = "";
  microphoneButton.hidden = false;
  microphoneButton.addEventListener("click", () => {
    if (microphoneButton.classList.contains("listening")) return recognition.stop();
    originalText = chatInput.value.trim();
    recognition.start();
  });
  recognition.addEventListener("start", () => {
    microphoneButton.classList.add("listening");
    microphoneButton.setAttribute("aria-label", "Stop dictation");
  });
  recognition.addEventListener("result", (event) => {
    const transcript = [...event.results].map((result) => result[0].transcript).join(" ").trim();
    chatInput.value = [originalText, transcript].filter(Boolean).join(" ");
  });
  const finish = () => {
    microphoneButton.classList.remove("listening");
    microphoneButton.setAttribute("aria-label", "Dictate message");
    chatInput.focus();
  };
  recognition.addEventListener("end", finish);
  recognition.addEventListener("error", finish);
}

function showLoading(isDemo) {
  formError.textContent = "";
  loginCard.hidden = true;
  loadingCard.hidden = false;
  document.querySelector("#loading-title").textContent = isDemo ? "Preparing a sample record…" : "Connecting to UPEI…";
  progressItems.forEach((item, index) => {
    item.classList.toggle("active", index === 0);
    item.classList.remove("complete");
  });
}

function showLogin(errorMessage = "") {
  dashboardView.hidden = true;
  loginView.hidden = false;
  loadingCard.hidden = true;
  loginCard.hidden = false;
  formError.textContent = errorMessage;
}

function advanceProgress(index) {
  progressItems.forEach((item, itemIndex) => {
    item.classList.toggle("complete", itemIndex < index);
    item.classList.toggle("active", itemIndex === index);
  });
}

async function requestSnapshot(payload) {
  showLoading(payload.demo);
  const timings = payload.demo ? [150, 300, 450] : [1800, 5000, 9000];
  const timers = timings.map((time, index) => setTimeout(() => advanceProgress(index + 1), time));
  try {
    const body = await apiRequest("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    timers.forEach(clearTimeout);
    progressItems.forEach((item) => {
      item.classList.remove("active");
      item.classList.add("complete");
    });
    await new Promise((resolve) => setTimeout(resolve, payload.demo ? 300 : 550));
    renderDashboard(body);
  } catch (error) {
    timers.forEach(clearTimeout);
    showLogin(error.message);
  }
}

connectForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const usernameInput = document.querySelector("#username");
  const passwordInput = document.querySelector("#password");
  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  if (!username || !password) {
    formError.textContent = "Enter both your UPEI username and password.";
    return;
  }
  passwordInput.value = "";
  requestSnapshot({ username, password, demo: false });
});

demoButton.addEventListener("click", () => requestSnapshot({ username: "", password: "", demo: true }));

disconnectButton.addEventListener("click", async () => {
  try {
    await fetch("/api/snapshot", { method: "DELETE" });
  } finally {
    resetChat();
    scholarshipMatches = [];
    currentScholarshipId = null;
    currentApplicationId = null;
    showLogin();
    connectForm.reset();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});

function summaryCards(snapshot) {
  const { student, scholarship_summary: scholarship } = snapshot;
  const program = student.majors.length ? student.majors.join(" + ") : "Program unavailable";
  return [
    { label: "Cumulative GPA", icon: "↗", value: formatNumber(student.cumulative_gpa, 3), caption: "Calculated from your highest course attempts", className: "featured" },
    { label: "Completed credits", icon: "◎", value: formatNumber(student.total_credit_hours), caption: "Credit hours included by the calculator", className: "" },
    {
      label: "Latest scholarship",
      icon: "✦",
      value: scholarship.latest_acquired_amount === null ? "None yet" : formatCurrency(scholarship.latest_acquired_amount),
      caption: scholarship.latest_acquired_year ? `${String(scholarship.latest_acquired_year).replace("-", "–")} academic year` : "No acquired scholarship",
      className: "",
    },
    { label: "Program", icon: "◇", value: program, caption: student.minors.length ? `Minor: ${student.minors.join(", ")}` : "No minor listed", className: "program" },
  ];
}

function matchLabel(level) {
  return {
    excellent: "Excellent match",
    good: "Good match",
    possible: "Possible match",
    needs_more_information: "Needs information",
    not_eligible: "Known conflict",
  }[level] || "Possible match";
}

function renderScholarshipMatches() {
  const visible = activeMatchFilter === "all" ? scholarshipMatches : scholarshipMatches.filter((match) => match.match_level === activeMatchFilter);
  scholarshipFilters.hidden = scholarshipMatches.length === 0;
  if (!scholarshipMatches.length) {
    scholarshipResults.innerHTML = '<div class="discovery-empty"><span aria-hidden="true">✦</span><div><strong>No matches loaded yet</strong><p>Search official UPEI sources to compare awards with your connected record.</p></div></div>';
    return;
  }
  if (!visible.length) {
    scholarshipResults.innerHTML = '<div class="discovery-empty"><div><strong>No awards in this filter</strong><p>Try another match level.</p></div></div>';
    return;
  }
  scholarshipResults.innerHTML = visible.map((match) => {
    const scholarship = match.scholarship;
    const source = officialSourceUrl(scholarship.source_url);
    const viewAction = scholarship.detail_status === "source_only" && source
      ? `<a class="link-action" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer" aria-label="View ${escapeHtml(scholarship.name)} on the official UPEI page">View</a>`
      : `<button type="button" class="link-action" data-view-scholarship="${escapeHtml(match.scholarship_id)}">View</button>`;
    const facts = [
      ...match.known_matches.slice(0, 2).map((item) => `<li class="match-known">✓ ${escapeHtml(item)}</li>`),
      ...match.missing_information.slice(0, 2).map((item) => `<li class="match-missing">? ${escapeHtml(item)}</li>`),
      ...match.known_conflicts.slice(0, 1).map((item) => `<li class="match-conflict">! ${escapeHtml(item)}</li>`),
    ].join("");
    return `
      <article class="match-card" data-scholarship-id="${escapeHtml(match.scholarship_id)}">
        <div class="match-card-top">
          <div><span class="match-pill ${escapeHtml(match.match_level)}">${escapeHtml(matchLabel(match.match_level))}</span><h3>${escapeHtml(scholarship.name)}</h3></div>
          <strong class="match-amount">${escapeHtml(formatCurrency(scholarship.amount))}</strong>
        </div>
        <ul class="match-facts">${facts || "<li>Official criteria available in the detail view.</li>"}</ul>
        <div class="match-card-footer">
          <span>${scholarship.deadline ? `Deadline: ${escapeHtml(scholarship.deadline)}` : "Deadline not listed"}</span>
          ${viewAction}
        </div>
      </article>`;
  }).join("");
  scholarshipResults.querySelectorAll("[data-view-scholarship]").forEach((button) => {
    button.addEventListener("click", () => openScholarshipDetail(button.dataset.viewScholarship));
  });
}

async function runScholarshipSearch({ announceInChat = false } = {}) {
  findScholarshipsButton.disabled = true;
  findScholarshipsButton.textContent = "Searching…";
  scholarshipResults.innerHTML = '<div class="discovery-empty"><span class="status-pulse"></span><div><strong>Searching official UPEI awards…</strong><p>Comparing published criteria with your connected academic profile.</p></div></div>';
  setCopilotContext("scholarships");
  try {
    const body = await apiRequest("/api/scholarships/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    scholarshipMatches = Array.isArray(body.matches) ? body.matches : [];
    renderScholarshipMatches();
    if (body.warning) {
      const warning = document.createElement("p");
      warning.className = "discovery-warning";
      warning.textContent = body.warning;
      scholarshipResults.prepend(warning);
    }
    if (announceInChat) {
      addChatMessage("assistant", `I found and ranked ${scholarshipMatches.length} scholarship opportunities. Open one to review the official criteria and match explanation.`, false, body.sources || []);
      renderChatSuggestions(["Show my best match", "Which need more information?"]);
    }
  } catch (error) {
    scholarshipResults.innerHTML = `<div class="discovery-empty error"><div><strong>Scholarship search unavailable</strong><p>${escapeHtml(error.message)}</p></div></div>`;
  } finally {
    findScholarshipsButton.disabled = false;
    findScholarshipsButton.textContent = "Find scholarships";
  }
}

findScholarshipsButton.addEventListener("click", () => runScholarshipSearch({ announceInChat: true }));

scholarshipFilters.addEventListener("click", (event) => {
  const button = event.target.closest("[data-match-filter]");
  if (!button) return;
  activeMatchFilter = button.dataset.matchFilter;
  scholarshipFilters.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
  renderScholarshipMatches();
});

async function openScholarshipDetail(scholarshipId) {
  try {
    const match = await apiRequest(`/api/scholarships/${encodeURIComponent(scholarshipId)}`);
    const scholarship = match.scholarship;
    currentApplicationId = null;
    setCopilotContext("scholarship_detail", scholarshipId, null, scholarship.name);
    const source = officialSourceUrl(scholarship.source_url);
    if (scholarship.detail_status === "source_only") {
      if (source) window.open(source, "_blank", "noopener,noreferrer");
      return;
    }
    const sourceTitle = scholarship.source_title || "Official UPEI source";
    scholarshipDetail.innerHTML = `
      <div class="detail-heading">
        <div><span class="match-pill ${escapeHtml(match.match_level)}">${escapeHtml(matchLabel(match.match_level))}</span><h3>${escapeHtml(scholarship.name)}</h3></div>
        <strong>${escapeHtml(formatCurrency(scholarship.amount))}</strong>
      </div>
      <p class="detail-description">${escapeHtml(scholarship.description || "No description was published.")}</p>
      <div class="detail-columns">
        <div><h4>Why it may fit</h4><ul>${match.known_matches.map((item) => `<li>✓ ${escapeHtml(item)}</li>`).join("") || "<li>No academic match has been confirmed yet.</li>"}</ul></div>
        <div><h4>Still to verify</h4><ul>${[...match.missing_information, ...match.known_conflicts].map((item) => `<li>? ${escapeHtml(item)}</li>`).join("") || "<li>No missing criteria identified from the published page.</li>"}</ul></div>
      </div>
      <div class="detail-meta">
        <span>${scholarship.deadline ? `Deadline: ${escapeHtml(scholarship.deadline)}` : "Deadline not listed"}</span>
        ${source ? `<span class="official-source">Official source: <a href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">${escapeHtml(sourceTitle)}</a></span>` : ""}
      </div>
      <div class="detail-actions">
        <button type="button" class="primary-inline" id="help-apply-button">Help me apply</button>
        <button type="button" class="secondary-action" id="why-match-button">Why am I a match?</button>
        ${source ? `<a class="secondary-action official-page-action" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">Open official page ↗</a>` : ""}
      </div>`;
    scholarshipDetail.hidden = false;
    applicationView.hidden = true;
    scholarshipDetail.querySelector("#help-apply-button").addEventListener("click", () => openApplication(scholarshipId));
    scholarshipDetail.querySelector("#why-match-button").addEventListener("click", () => sendChatMessage("Why am I a match for this scholarship?"));
    renderChatSuggestions(["Why am I a match?", "Help me apply"]);
    scholarshipDetail.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    addChatMessage("assistant", error.message, true);
  }
}

async function openApplication(scholarshipId) {
  applicationView.hidden = false;
  applicationView.innerHTML = '<div class="application-loading"><span class="status-pulse"></span> Inspecting official application requirements…</div>';
  try {
    const state = await apiRequest(`/api/scholarships/${encodeURIComponent(scholarshipId)}/applications`, { method: "POST" });
    currentApplicationId = state.application_id;
    setCopilotContext("application", scholarshipId, state.application_id, `Application · ${state.scholarship_name}`);
    renderApplication(state);
    renderChatSuggestions(state.pending_background_field ? ["What should I answer next?", "Review the requirements"] : ["Help with my personal statement", "Review application"]);
    applicationView.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    applicationView.innerHTML = `<div class="application-error">${escapeHtml(error.message)}</div>`;
  }
}

function answerControl(field) {
  const value = field.known_answer ?? "";
  if (field.type === "boolean") {
    return `<select id="field-${escapeHtml(field.field_id)}"><option value="">Choose…</option><option value="true" ${value === true ? "selected" : ""}>Yes</option><option value="false" ${value === false ? "selected" : ""}>No</option></select>`;
  }
  if (field.type === "select") {
    return `<select id="field-${escapeHtml(field.field_id)}"><option value="">Choose…</option>${field.options.map((option) => `<option ${String(value) === option ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select>`;
  }
  if (field.type === "textarea") {
    return `<textarea id="field-${escapeHtml(field.field_id)}" ${field.max_length ? `maxlength="${field.max_length}"` : ""}>${escapeHtml(value)}</textarea>`;
  }
  return `<input id="field-${escapeHtml(field.field_id)}" type="${field.type === "number" ? "number" : "text"}" value="${escapeHtml(value)}" ${field.max_length ? `maxlength="${field.max_length}"` : ""} />`;
}

function renderApplication(state) {
  currentApplicationId = state.application_id;
  setCopilotContext("application", state.scholarship_id, state.application_id, `Application · ${state.scholarship_name}`);
  const fieldRows = state.fields.map((field) => `
    <div class="application-field" data-field-id="${escapeHtml(field.field_id)}" data-field-type="${escapeHtml(field.type)}">
      <div class="application-field-label"><label for="field-${escapeHtml(field.field_id)}">${escapeHtml(field.label)}${field.required ? " *" : ""}</label><span>${escapeHtml(field.source.replaceAll("_", " "))}</span></div>
      ${answerControl(field)}
      ${field.essay ? `<div class="essay-controls"><span>${field.max_length ? `Maximum ${field.max_length} characters` : "Review before use"}</span><label><input type="checkbox" class="essay-approval" ${state.user_approved_answers.includes(field.field_id) ? "checked" : ""}> I reviewed and approve this answer</label></div>` : ""}
      <button type="button" class="save-field-button">Save answer</button>
    </div>`).join("");
  applicationView.innerHTML = `
    <div class="application-heading">
      <div><span class="eyebrow">Guided application</span><h3 id="application-title">${escapeHtml(state.scholarship_name)}</h3></div>
      <span class="application-status">${escapeHtml(state.inspection_status.replaceAll("_", " "))}</span>
    </div>
    ${state.fields.length ? `<div class="application-fields">${fieldRows}</div>` : '<div class="application-empty">No machine-readable application fields were available. Review the official award page before proceeding.</div>'}
    <div id="application-preview" class="application-preview" hidden></div>
    <div class="application-actions">
      <button type="button" class="secondary-action" id="prepare-preview-button" ${state.fields.length ? "" : "disabled"}>Review application</button>
      <button type="button" class="approve-submit" id="approve-submit-button" disabled>Approve &amp; Submit</button>
    </div>
    <p class="application-boundary">Sensitive facts must come from you. A live application is never submitted automatically; approval records readiness for manual submission in the official system.</p>`;

  applicationView.querySelectorAll(".save-field-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest(".application-field");
      const fieldId = row.dataset.fieldId;
      const control = row.querySelector(`#field-${CSS.escape(fieldId)}`);
      let value = control.value;
      if (row.dataset.fieldType === "boolean" && value !== "") value = value === "true";
      const userApproved = row.querySelector(".essay-approval")?.checked ?? true;
      button.disabled = true;
      button.textContent = "Saving…";
      try {
        const updated = await apiRequest(`/api/applications/${encodeURIComponent(state.application_id)}/answers`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ field_id: fieldId, value, user_approved: userApproved }),
        });
        renderApplication(updated);
      } catch (error) {
        button.disabled = false;
        button.textContent = "Save answer";
        addChatMessage("assistant", error.message, true);
      }
    });
  });
  applicationView.querySelector("#prepare-preview-button")?.addEventListener("click", () => prepareApplicationPreview(state.application_id));
  applicationView.querySelector("#approve-submit-button")?.addEventListener("click", () => approveAndSubmit(state.application_id));
}

async function prepareApplicationPreview(applicationId) {
  try {
    const preview = await apiRequest(`/api/applications/${encodeURIComponent(applicationId)}/preview`, { method: "POST" });
    const panel = applicationView.querySelector("#application-preview");
    panel.hidden = false;
    panel.classList.toggle("ready", preview.ready);
    panel.innerHTML = `
      <span class="eyebrow">${preview.ready ? "Application ready" : "Review required"}</span>
      <h4>${preview.completed_fields} fields completed</h4>
      ${preview.missing_required_fields.length ? `<p><strong>Missing:</strong> ${escapeHtml(preview.missing_required_fields.join(", "))}</p>` : "<p>✓ Required fields complete</p>"}
      ${preview.warnings.map((warning) => `<p>! ${escapeHtml(warning)}</p>`).join("")}
      ${preview.ready ? "<p>✓ Academic information and reviewed answers passed validation.</p>" : ""}`;
    applicationView.querySelector("#approve-submit-button").disabled = !preview.ready;
    renderChatSuggestions(preview.ready ? ["Review application", "What happens on approval?"] : ["What is still missing?", "Help me finish"]);
  } catch (error) {
    addChatMessage("assistant", error.message, true);
  }
}

async function approveAndSubmit(applicationId) {
  const button = applicationView.querySelector("#approve-submit-button");
  button.disabled = true;
  button.textContent = "Approving…";
  try {
    const state = await apiRequest(`/api/applications/${encodeURIComponent(applicationId)}/approve-submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ explicit_action: "APPROVE_AND_SUBMIT" }),
    });
    renderApplication(state);
    const panel = applicationView.querySelector("#application-preview");
    panel.hidden = false;
    panel.classList.add("ready");
    panel.innerHTML = `<span class="eyebrow">Approval recorded</span><h4>${escapeHtml(state.submission_status.replaceAll("_", " "))}</h4><p>${state.submitted ? "Demo submission recorded; no external action occurred." : "Review and submit through the official UPEI application system. No live submission was performed."}</p>`;
  } catch (error) {
    button.disabled = false;
    button.textContent = "Approve & Submit";
    addChatMessage("assistant", error.message, true);
  }
}

function renderDashboard(snapshot) {
  const { student, scholarship_summary: scholarship, academic_years: years } = snapshot;
  const firstName = student.name.trim().split(/\s+/)[0] || "Student";
  const initials = student.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  document.querySelector("#first-name").textContent = firstName;
  document.querySelector("#masked-id").textContent = student.student_id_masked;
  document.querySelector("#avatar").textContent = initials || "AC";
  document.querySelector("#source-badge").textContent = snapshot.source === "demo" ? "Demo data" : "Live record";
  resetChat();
  scholarshipMatches = [];
  scholarshipDetail.hidden = true;
  applicationView.hidden = true;
  renderScholarshipMatches();

  document.querySelector("#summary-grid").innerHTML = summaryCards(snapshot).map((card) => `
    <article class="summary-card ${card.className === "featured" ? "featured" : ""}">
      <div class="summary-label"><span>${escapeHtml(card.label)}</span><span class="summary-icon" aria-hidden="true">${card.icon}</span></div>
      <div class="summary-value ${card.className === "program" ? "program-value" : ""}">${escapeHtml(card.value)}</div>
      <div class="summary-caption">${escapeHtml(card.caption)}</div>
    </article>`).join("");

  document.querySelector("#scholarship-total").textContent = `${scholarship.eligible_years} eligible ${scholarship.eligible_years === 1 ? "year" : "years"}`;
  document.querySelector("#scholarship-grid").innerHTML = years.map((year) => {
    const isLatest = year.year === scholarship.latest_acquired_year;
    const average = year.weighted_average === null ? "—" : formatNumber(year.weighted_average, 2);
    const statusText = {
      eligible: "Scholarship eligible",
      not_eligible: "Below scholarship threshold",
      insufficient_credits: "Minimum credits not met",
      no_courses: "No eligible courses",
    }[year.scholarship_status] || "Calculation complete";
    return `
      <article class="scholarship-card ${isLatest ? "latest" : ""}">
        <div class="year-line"><span>${formatYear(year.year)}</span>${isLatest ? '<span class="current-tag">Latest acquired</span>' : ""}</div>
        <div class="scholarship-numbers">
          <div><div class="average-value">${average}<span>%</span></div><div class="scholarship-status">${escapeHtml(statusText)}</div></div>
          <div class="award-value">${year.calculation_status === "not_calculated" ? "Not calculated" : escapeHtml(formatCurrency(year.scholarship_amount))}</div>
        </div>
      </article>`;
  }).join("");

  document.querySelector("#academic-years").innerHTML = years.slice().reverse().map((year, index) => {
    const statistics = year.statistics;
    const courseSummary = [
      `${statistics.total_courses} ${statistics.total_courses === 1 ? "course" : "courses"}`,
      `${statistics.graded_courses} graded`,
      statistics.non_graded_courses ? `${statistics.non_graded_courses} non-graded` : null,
    ].filter(Boolean).join(" · ");
    const chips = gradeBandChips.map(([key, label, band]) => `
      <span class="year-stat-chip ${band}"><span>${escapeHtml(label)}</span><strong>${statistics.grade_bands[key]}</strong></span>`).join("");
    return `
    <details class="academic-year performance-${escapeHtml(year.performance_band)}" ${index === 0 ? "open" : ""}>
      <summary>
        <span class="academic-year-title"><strong>${formatYear(year.year)}</strong><span>${escapeHtml(courseSummary)}</span></span>
        <span class="year-metric year-average"><span>Weighted average</span><strong>${year.weighted_average === null ? "—" : `${formatNumber(year.weighted_average, 2)}%`}</strong></span>
        <span class="year-metric"><span>Scholarship</span><strong>${year.calculation_status === "not_calculated" ? "Not calculated" : escapeHtml(formatCurrency(year.scholarship_amount))}</strong></span>
        <span class="chevron" aria-hidden="true">⌄</span>
        <span class="year-stat-chips" aria-label="Exclusive numeric grade bands">${chips}</span>
      </summary>
      <div class="course-table-wrap"><table class="course-table">
        <thead><tr><th>Course</th><th>Name</th><th>Grade</th><th>Letter</th><th>GPA</th><th>Credits</th></tr></thead>
        <tbody>${year.courses.map((course) => `
          <tr class="course-row performance-${escapeHtml(course.performance_band)}"><td>${escapeHtml(course.code)}</td><td>${escapeHtml(course.name)}</td><td><span class="grade-pill" title="${escapeHtml(performanceMeta[course.performance_band].label)} · ${escapeHtml(performanceMeta[course.performance_band].range)}">${escapeHtml(course.grade)}${typeof course.grade === "number" ? "%" : ""}</span></td><td>${escapeHtml(course.letter)}</td><td>${escapeHtml(course.gpa)}</td><td>${formatNumber(course.credits)}</td></tr>`).join("")}</tbody>
      </table></div>
    </details>`;
  }).join("");
  loginView.hidden = true;
  dashboardView.hidden = false;
  window.scrollTo({ top: 0 });
}

setupSpeechRecognition();
