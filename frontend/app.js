const loginView = document.querySelector("#login-view");
const dashboardView = document.querySelector("#dashboard-view");
const loginCard = document.querySelector("#login-card");
const loadingCard = document.querySelector("#loading-card");
const connectForm = document.querySelector("#connect-form");
const demoButton = document.querySelector("#demo-button");
const disconnectButton = document.querySelector("#disconnect-button");
const formError = document.querySelector("#form-error");
const progressItems = [...document.querySelectorAll(".progress-list li")];

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "'": "&#39;",
  '"': "&quot;",
}[character]));

const formatNumber = (value, digits = 0) => {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("en-CA", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const formatCurrency = (value) => Number(value || 0).toLocaleString("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});

const formatYear = (year) => escapeHtml(String(year).replace("-", "–"));

function showLoading(isDemo) {
  formError.textContent = "";
  loginCard.hidden = true;
  loadingCard.hidden = false;
  document.querySelector("#loading-title").textContent = isDemo
    ? "Preparing a sample record…"
    : "Connecting to UPEI…";
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
    const response = await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const responseBody = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseBody.detail || "We couldn't connect to the academic record.");
    }
    timers.forEach(clearTimeout);
    progressItems.forEach((item) => {
      item.classList.remove("active");
      item.classList.add("complete");
    });
    await new Promise((resolve) => setTimeout(resolve, payload.demo ? 300 : 550));
    renderDashboard(responseBody);
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
  const payload = {
    username,
    password,
    browser: document.querySelector("#browser").value,
    demo: false,
  };
  passwordInput.value = "";
  requestSnapshot(payload);
});

demoButton.addEventListener("click", () => {
  requestSnapshot({ username: "", password: "", browser: "chrome", demo: true });
});

disconnectButton.addEventListener("click", async () => {
  try {
    await fetch("/api/snapshot", { method: "DELETE" });
  } finally {
    showLogin();
    connectForm.reset();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});

function summaryCards(snapshot) {
  const { student, scholarship_summary: scholarship } = snapshot;
  const program = student.majors.length ? student.majors.join(" + ") : "Program unavailable";
  return [
    {
      label: "Cumulative GPA",
      icon: "↗",
      value: formatNumber(student.cumulative_gpa, 3),
      caption: "Calculated from your highest course attempts",
      className: "featured",
    },
    {
      label: "Completed credits",
      icon: "◎",
      value: formatNumber(student.total_credit_hours),
      caption: "Credit hours included by the calculator",
      className: "",
    },
    {
      label: "Latest scholarship",
      icon: "✦",
      value: formatCurrency(scholarship.latest_scholarship_amount),
      caption: scholarship.latest_academic_year
        ? `${String(scholarship.latest_academic_year).replace("-", "–")} academic year`
        : "No completed academic year",
      className: "",
    },
    {
      label: "Program",
      icon: "◇",
      value: program,
      caption: student.minors.length ? `Minor: ${student.minors.join(", ")}` : "No minor listed",
      className: "program",
    },
  ];
}

function renderDashboard(snapshot) {
  const { student, scholarship_summary: scholarship, academic_years: years } = snapshot;
  const firstName = student.name.trim().split(/\s+/)[0] || "Student";
  const initials = student.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();

  document.querySelector("#first-name").textContent = firstName;
  document.querySelector("#masked-id").textContent = student.student_id_masked;
  document.querySelector("#avatar").textContent = initials || "AC";
  document.querySelector("#source-badge").textContent = snapshot.source === "demo" ? "Demo data" : "Live record";

  document.querySelector("#summary-grid").innerHTML = summaryCards(snapshot).map((card) => `
    <article class="summary-card ${card.className === "featured" ? "featured" : ""}">
      <div class="summary-label">
        <span>${escapeHtml(card.label)}</span>
        <span class="summary-icon" aria-hidden="true">${card.icon}</span>
      </div>
      <div class="summary-value ${card.className === "program" ? "program-value" : ""}">${escapeHtml(card.value)}</div>
      <div class="summary-caption">${escapeHtml(card.caption)}</div>
    </article>
  `).join("");

  document.querySelector("#scholarship-total").textContent = `${scholarship.eligible_years} eligible ${scholarship.eligible_years === 1 ? "year" : "years"}`;
  document.querySelector("#scholarship-grid").innerHTML = years.map((year, index) => {
    const isLatest = index === years.length - 1;
    const average = year.weighted_average === null ? "—" : formatNumber(year.weighted_average, 2);
    const statusText = {
      eligible: "Scholarship eligible",
      not_eligible: "Below scholarship threshold",
      insufficient_credits: "Minimum credits not met",
      no_courses: "No eligible courses",
    }[year.scholarship_status] || "Calculation complete";
    return `
      <article class="scholarship-card ${isLatest ? "latest" : ""}">
        <div class="year-line">
          <span>${formatYear(year.year)}</span>
          ${isLatest ? '<span class="current-tag">Latest</span>' : ""}
        </div>
        <div class="scholarship-numbers">
          <div>
            <div class="average-value">${average}<span>%</span></div>
            <div class="scholarship-status">${escapeHtml(statusText)}</div>
          </div>
          <div class="award-value">${escapeHtml(formatCurrency(year.scholarship_amount))}</div>
        </div>
      </article>
    `;
  }).join("");

  document.querySelector("#academic-years").innerHTML = years.slice().reverse().map((year, index) => `
    <details class="academic-year" ${index === 0 ? "open" : ""}>
      <summary>
        <span class="academic-year-title">
          <strong>${formatYear(year.year)}</strong>
          <span>${year.courses.length} ${year.courses.length === 1 ? "course" : "courses"}</span>
        </span>
        <span class="year-metric"><span>Weighted average</span><strong>${year.weighted_average === null ? "—" : `${formatNumber(year.weighted_average, 2)}%`}</strong></span>
        <span class="year-metric"><span>Scholarship</span><strong>${escapeHtml(formatCurrency(year.scholarship_amount))}</strong></span>
        <span class="chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="course-table-wrap">
        <table class="course-table">
          <thead><tr><th>Course</th><th>Name</th><th>Grade</th><th>Letter</th><th>GPA</th><th>Credits</th></tr></thead>
          <tbody>
            ${year.courses.map((course) => `
              <tr>
                <td>${escapeHtml(course.code)}</td>
                <td>${escapeHtml(course.name)}</td>
                <td><span class="grade-pill">${escapeHtml(course.grade)}</span></td>
                <td>${escapeHtml(course.letter)}</td>
                <td>${escapeHtml(course.gpa)}</td>
                <td>${formatNumber(course.credits)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </details>
  `).join("");

  loginView.hidden = true;
  dashboardView.hidden = false;
  window.scrollTo({ top: 0 });
}
