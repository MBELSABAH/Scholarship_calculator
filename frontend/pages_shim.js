(() => {
  "use strict";

  const originalFetch = window.fetch.bind(window);

  const demoSnapshot = {
    source: "demo",
    student: {
      name: "Maya Chen",
      full_name: "Maya Chen",
      display_name: "Maya",
      student_id: "0007007",
      student_id_masked: "••••007",
      cumulative_gpa: 4.094,
      portal_cumulative_gpa: 4.094,
      completed_credits: 54,
      required_degree_credits: 120,
      year_of_study: 3,
      faculty: "School of Mathematical and Computational Sciences",
      majors: ["Computer Science", "Mathematics"],
      minors: ["Business"]
    },
    academic_progress: {
      completed_credits: 54,
      required_degree_credits: 120,
      year_of_study: 3,
      credits_per_year: 30
    },
    scholarship_summary: {
      eligible_years: 2,
      latest_acquired_amount: 2000,
      latest_acquired_year: "2025-2026"
    },
    academic_years: [
      {
        year: "2023-2024",
        weighted_average: 81.84,
        scholarship_amount: 500,
        scholarship_status: "eligible",
        calculation_status: "calculated",
        performance_band: "strong",
        statistics: { total_courses: 6, graded_courses: 6, non_graded_courses: 0, grade_bands: { "90_100": 0, "80_89": 5, "70_79": 1, "60_69": 0, "below_60": 0 } },
        courses: [
          ["CS-1910-01","Computer Science I",78,"B+",3.3,3,"good"],
          ["MATH-1910-01","Single Variable Calculus I",82,"A-",3.7,3,"strong"],
          ["ENG-1010-01","Academic Writing",80,"A-",3.7,3,"strong"],
          ["STAT-1210-01","Introductory Statistics",81,"A-",3.7,3,"strong"],
          ["PHYS-1110-01","General Physics I",83,"A-",3.7,3,"strong"],
          ["BUS-1410-01","Marketing",87,"A",4.0,3,"strong"]
        ].map(([code,name,grade,letter,gpa,credits,performance_band]) => ({code,name,grade,letter,gpa,credits,performance_band}))
      },
      {
        year: "2024-2025",
        weighted_average: 94.32,
        scholarship_amount: 2000,
        scholarship_status: "eligible",
        calculation_status: "calculated",
        performance_band: "excellent",
        statistics: { total_courses: 6, graded_courses: 6, non_graded_courses: 0, grade_bands: { "90_100": 6, "80_89": 0, "70_79": 0, "60_69": 0, "below_60": 0 } },
        courses: [
          ["CS-1920-01","Computer Science II",96,"A+",4.3,3],
          ["CS-2610-01","Data Structures",94,"A+",4.3,3],
          ["MATH-1920-01","Single Variable Calculus II",95,"A+",4.3,3],
          ["MATH-2420-01","Linear Algebra",93,"A+",4.3,3],
          ["CS-2520-01","Programming Practices",92,"A+",4.3,3],
          ["BUS-2120-01","Business Analytics",96,"A+",4.3,3]
        ].map(([code,name,grade,letter,gpa,credits]) => ({code,name,grade,letter,gpa,credits,performance_band:"excellent"}))
      },
      {
        year: "2025-2026",
        weighted_average: 92.94,
        scholarship_amount: 2000,
        scholarship_status: "eligible",
        calculation_status: "calculated",
        performance_band: "excellent",
        statistics: { total_courses: 7, graded_courses: 6, non_graded_courses: 1, grade_bands: { "90_100": 6, "80_89": 0, "70_79": 0, "60_69": 0, "below_60": 0 } },
        courses: [
          ["CS-2820-01","Computer Architecture",94,"A+",4.3,3,"excellent"],
          ["CS-2910-01","Theory of Computation",93,"A+",4.3,3,"excellent"],
          ["CS-2920-01","Software Engineering",92,"A+",4.3,3,"excellent"],
          ["MATH-3010-01","Numerical Analysis",91,"A+",4.3,3,"excellent"],
          ["CS-3310-01","Database Systems",94,"A+",4.3,3,"excellent"],
          ["CS-3410-01","Operating Systems",93,"A+",4.3,3,"excellent"],
          ["COOP-0990-01","Co-op Preparation Requirement","P","P","P",0,"neutral"]
        ].map(([code,name,grade,letter,gpa,credits,performance_band]) => ({code,name,grade,letter,gpa,credits,performance_band}))
      }
    ]
  };

  const scholarshipMatches = [
    {
      scholarship_id: "pages-1",
      match_level: "excellent",
      known_matches: ["Strong academic standing", "Program alignment"],
      missing_information: ["Personal criteria still need confirmation"],
      known_conflicts: [],
      scholarship: {
        name: "UPEI Scholarship Opportunity",
        amount: 2000,
        deadline_display: "October 1",
        deadline_precision: "exact",
        description: "Example of an official UPEI scholarship match in the public demo.",
        source_url: "https://www.upei.ca/scholarships-and-awards",
        source_title: "UPEI Scholarships and Awards",
        application_url: "https://www.upei.ca/scholarships-and-awards",
        detail_status: "source_only"
      }
    },
    {
      scholarship_id: "pages-2",
      match_level: "strong",
      known_matches: ["Academic profile matches published criteria"],
      missing_information: ["Leadership or community involvement"],
      known_conflicts: [],
      scholarship: {
        name: "UPEI Student Award",
        amount: 1000,
        deadline_display: "October",
        deadline_precision: "month",
        description: "Example scholarship shown to demonstrate the matching workflow.",
        source_url: "https://www.upei.ca/scholarships-and-awards",
        source_title: "UPEI Scholarships and Awards",
        application_url: "https://www.upei.ca/scholarships-and-awards",
        detail_status: "source_only"
      }
    }
  ];

  let connected = false;
  const response = (data, status = 200) => Promise.resolve(new Response(
    status === 204 ? null : JSON.stringify(data),
    { status, headers: status === 204 ? {} : { "Content-Type": "application/json" } }
  ));

  window.fetch = async (input, init = {}) => {
    const raw = typeof input === "string" ? input : input.url;
    const url = new URL(raw, window.location.href);
    const path = url.pathname.replace(/^\/Scholarship_calculator/, "");
    const method = String(init.method || "GET").toUpperCase();

    if (path === "/api/connect" && method === "POST") {
      const body = JSON.parse(init.body || "{}");
      if (!body.demo) {
        return response({ detail: "Live UPEI login runs in the local FastAPI application. Use Explore the demo record on this public GitHub Pages build." }, 503);
      }
      connected = true;
      return response(demoSnapshot);
    }

    if (path === "/api/snapshot" && method === "DELETE") {
      connected = false;
      return response(null, 204);
    }

    if (path === "/api/snapshot" && method === "GET") {
      return connected ? response(demoSnapshot) : response({ detail: "No academic record is connected yet." }, 404);
    }

    if (path === "/api/scholarships/search" && method === "POST") {
      return response({ matches: scholarshipMatches, sources: [{ title: "UPEI Scholarships and Awards", url: "https://www.upei.ca/scholarships-and-awards" }] });
    }

    if (path === "/api/scholarships" && method === "GET") return response({ matches: scholarshipMatches });

    if (path === "/api/chat" && method === "POST") {
      const body = JSON.parse(init.body || "{}");
      const text = String(body.message || "").toLowerCase();
      let message = "This public GitHub Pages build mirrors the Academic Copilot interface. The live DeepSeek agent and UPEI connection run in the local FastAPI app.";
      let ui_updates = [];
      if (text.includes("scholarship")) {
        message = "I found two demonstration scholarship matches based on the sample academic record. The live version searches and ranks official UPEI sources using the connected student's real profile.";
        ui_updates = ["refresh_scholarships"];
      } else if (text.includes("gpa")) {
        message = "The demonstration record has a cumulative GPA of 4.094. In the live app, this value comes from the connected academic record and deterministic GPA logic.";
      }
      return response({ message, conversation_id: "github-pages-demo", suggested_replies: ["Find scholarships", "What is my GPA?"], tools_used: [], sources: [], ui_updates, pending_question: null });
    }

    if (path.startsWith("/api/")) return response({ detail: "This action requires the local FastAPI application." }, 503);
    return originalFetch(input, init);
  };
})();
