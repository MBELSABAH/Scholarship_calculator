# UPEI Grades Extractor & Scholarship Analyzer

A Python/Selenium automation project that extracts academic records from the UPEI student portal, structures course and grade information, calculates GPA-related summaries, and estimates scholarship eligibility using academic-year rules.

This project demonstrates browser automation, object-oriented Python design, academic-record parsing, GPA conversion logic, repeated-course handling, and report generation.

> **Privacy note:** This tool works with sensitive academic information. It should only be run locally by the account owner. Do not commit real output files, screenshots, credentials, or private student records to GitHub.

---

## Academic Copilot web MVP (hackathon scholarship agent)

This branch exposes the existing calculator as a local web product: **“Ask your academic record.”** It includes the secure connection screen, structured `AcademicSnapshot` API, dashboard, course-year accordions, a sanitized demo record, and a DeepSeek-powered assistant grounded in allow-listed semantic tools.

The hackathon workflow adds live scholarship discovery from official UPEI pages, deterministic matching, a session-only student background profile, normalized application fields, draft review, and an explicit approval gate. On desktop the copilot remains in a sticky right sidebar while the dashboard scrolls. Supported browsers also expose a microphone that transcribes speech into the composer without sending it automatically.

“Latest scholarship” has one precise meaning: the most recent positive award from a completed, calculated academic year. Empty/future years use `scholarship_amount: null` with `calculation_status: "not_calculated"`; a valid completed $0 result remains `calculated` but is not selected as the latest acquired award.

The browser scraper now returns profile and course data directly to Python. FastAPI passes that record into the existing `Student`, `Courses`, and `Mark` classes, converts their deterministic results into JSON, and serves a no-build HTML/CSS/JavaScript frontend.

### Run the web app

Create the virtual environment and install dependencies as described below, then run:

```bash
uvicorn backend.app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Choose **Explore the demo record** to inspect the dashboard without university credentials.

The backend and frontend share one local server, so there is no separate frontend build command.

### Configure the academic assistant

Set the key in your shell:

```bash
export DEEPSEEK_API_KEY="your-key"
```

Or copy `.env.example` to `.env` and replace the placeholder. `.env` and `.env.*` are ignored; the example file is intentionally tracked. The assistant uses the official `https://api.deepseek.com/chat/completions` endpoint with `deepseek-v4-flash` and non-thinking mode. If no key is configured, `/api/chat` returns a clear configuration error and never substitutes a fake answer.

### API endpoints

- `POST /api/connect` — accepts a live UPEI connection request or `{ "demo": true }`, calculates a snapshot, and caches only that sanitized snapshot in memory
- `GET /api/snapshot` — returns the current sanitized snapshot
- `DELETE /api/snapshot` — clears the in-memory snapshot
- `POST /api/chat` — answers a question through DeepSeek tool calling against the current in-memory snapshot
- `POST /api/scholarships/search` — searches official UPEI pages and ranks structured matches against the connected snapshot
- `GET /api/scholarships` and `GET /api/scholarships/{id}` — return cached ranked matches and one official-source detail view
- `GET|PUT /api/student-background` — reads or confirms one session-only scholarship background fact
- `POST /api/scholarships/{id}/applications` — inspects semantic application requirements and prefills known facts
- `GET /api/applications/{id}` and `PUT /api/applications/{id}/answers` — manage reviewed application state
- `POST /api/applications/{id}/preview` — validates missing fields, answer approval, and warnings
- `POST /api/applications/{id}/approve-submit` — accepts only the deterministic `APPROVE_AND_SUBMIT` action
- `GET /api/health` — local health check

The chat endpoint also accepts `current_view`, `current_scholarship_id`, and `current_application_id`. The conversation ID is optional on the first turn and returned with every successful answer. Only recent user/assistant text is retained in memory; tool payloads, scholarship records, personal background, and applications remain in memory for the current local session.

Public scholarship retrieval is HTTPS-only and restricted to exact confirmed UPEI hosts. It follows only validated redirects, caps response size, strips scripts/styles, parses structured text, and never receives portal credentials, cookies, or the DeepSeek key. If retrieval fails, clearly labelled fake fixture awards are used; they are never represented as current UPEI awards.

The approval endpoint does not fake a live external submission. For a live award it records `approved_manual_official_submission_required`; demo fixtures can record a no-external-action demo submission. This keeps the final action explicit while avoiding an unsafe real application during development.

After configuring the key, run the required live demo prompts with:

```bash
python3 scripts/live_deepseek_smoke.py
python3 scripts/live_scholarship_agent_smoke.py
python3 scripts/live_essay_smoke.py
```

The runner prints only each prompt, the high-level DeepSeek → Python tool sequence, and the final answer. It does not use or request portal credentials.

### Credential flow

For the web path, the password arrives in a masked `SecretStr` request field and is passed directly to the selected Python scraper. It is not placed in subprocess arguments, written to either legacy output file, logged, returned to the browser, stored in the snapshot, or sent to an AI provider. DeepSeek receives only the question, concise conversation text, and selected sanitized tool results. Run this local endpoint behind HTTPS before exposing it beyond localhost.

The historical extractor scripts still support their command-line entry points and can generate the local text reports for CLI compatibility. Those generated files are ignored and are not application fixtures.

### Verify

```bash
python3 -B -m unittest discover -s tests -v
node --check frontend/app.js
git diff --check
```

---

## What the project does

- Logs into the UPEI student portal through Selenium-driven browser automation
- Extracts student profile information such as GPA, major, minor, and academic history
- Parses courses, grades, credits, and academic years
- Converts percentage grades into GPA and letter-grade representations
- Calculates cumulative GPA-related summaries
- Estimates yearly scholarship eligibility based on weighted averages and credit requirements
- Handles repeated courses by keeping the highest applicable grade for GPA fairness
- Generates local text reports for review

---

## Why this project matters

University grade portals often show information in a format that is useful for viewing but not ideal for analysis. This project turns portal data into structured Python objects and readable output files, making it easier to review academic progress, GPA status, and scholarship eligibility.

From a technical perspective, the project is useful because it combines:

- web automation
- data extraction
- rule-based academic calculations
- object-oriented modeling
- local report generation

---

## Main features

- **Cross-browser support:** Chrome and Safari workflows
- **Object-oriented design:** separate classes for students, courses, and marks
- **Academic-year grouping:** organizes completed courses by year
- **Repeated-course handling:** avoids unfair GPA calculation from repeated attempts
- **Scholarship logic:** checks weighted average and yearly credit conditions
- **Local report output:** generates text summaries for student information and grades
- **Special-grade handling:** supports values such as `DSC`, `P`, and `E`

---

## Tech stack

- Python
- Selenium
- ChromeDriver / Safari WebDriver
- Object-oriented Python classes
- Text-based report generation

---

## Repository structure

```text
Scholarship_calculator/
├── backend/                    # FastAPI, AcademicSnapshot models, service layer
│   ├── agent_service.py        # DeepSeek client, bounded tool loop, chat history
│   └── agent_tools.py          # Allow-listed deterministic academic tools
├── frontend/                   # No-build dashboard (HTML/CSS/JavaScript)
├── demo_data/                  # Sanitized fake academic record
├── tests/                      # Deterministic service tests
├── Main.py                     # CLI controller and main program flow
├── Student.py                  # Student object and summary representation
├── Courses.py                  # Course management and scholarship calculation
├── Mark.py                     # Grade translation: percent, GPA, and letter grade
├── scraper_utils.py            # Shared in-memory scraper transformations
├── grades_extractor_chrome.py  # Chrome-based portal automation
├── grades_extractor_safari.py  # Safari-based portal automation
├── requirements.txt            # Python dependencies
└── README.md
```

Generated local output files may include:

```text
student_information.txt
printer_friendly_grades.txt
```

These files can contain private academic data and should not be committed if they contain real student information.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/MBELSABAH/Scholarship_calculator.git
cd Scholarship_calculator
```

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Browser setup

### Chrome

Chrome requires a compatible ChromeDriver installation. Make sure ChromeDriver is installed and available on your system path.

### Safari

Safari requires WebDriver to be enabled locally.

On macOS, enable Safari WebDriver support with:

```bash
safaridriver --enable
```

You may also need to enable **Allow Remote Automation** from Safari's developer settings.

---

## Usage

Run the main program:

```bash
python Main.py
```

The program prompts you to choose a browser workflow and enter your UPEI login credentials locally.

> Credentials should never be hard-coded, committed, logged, or shared. Use this tool only on your own account and only where portal automation is permitted.

---

## Example output

The generated output is intended to summarize academic information in a readable local text format.

```text
Name: Example Student
Student ID: 0000000
Major(s): Computer Science, Mathematics
Minor(s): Business
Cumulative GPA: 4.2
Total Credit Hours: 69
====================================================================================================
Completed Courses by year:

Academic Year 2022-2023 (year 1):
1. Course: ENG-1010 (Academic Writing), MARK: 65, GPA: 1.7, LETTER: C-, Credit Hours: 3
2. Course: MATH-1910 (Single Variable Calculus I), MARK: 91, GPA: 4.3, LETTER: A+, Credit Hours: 4
...

Scholarship Eligibility:
Academic Year 2022-2023 (year 1) - Weighted Average: 78.57, No Scholarship: Weighted Average must be higher than 79%.
Academic Year 2023-2024 (year 2) - Weighted Average: 83.42, $500 Scholarship
Academic Year 2024-2025 (year 3) - Not enough courses taken in the academic year to calculate scholarship. Minimum year credits required: 18, current credits: 12
```

---

## Calculation notes

- Lab and tutorial sections with `0` credits are skipped
- Special grades such as `DSC`, `P`, and `E` are handled separately
- Repeated courses are treated by course code, with the highest applicable grade used where appropriate
- Scholarship eligibility depends on academic-year grouping, weighted average, and minimum credit rules
- Output should be reviewed manually before being used for any official academic decision

---

## Security and privacy considerations

This project interacts with a real student portal and can generate sensitive academic files.

Recommended precautions:

- Run locally only
- Do not commit real generated output files
- Do not store credentials in source code
- Do not upload screenshots containing real student information
- Use fake/sample output when demonstrating the project publicly
- Review UPEI portal terms and academic-data privacy expectations before using automation

---

## Portfolio value

This project demonstrates:

- practical browser automation
- structured data extraction from a real web system
- object-oriented Python design
- rule-based calculations
- report generation
- attention to privacy and data sensitivity

It is best presented as an academic-record automation and analysis tool rather than as a generic GPA calculator.

---

## Future improvements

- Add a mock/demo mode using fake academic records
- Add unit tests for GPA, repeated-course, and scholarship calculations
- Move generated outputs into an ignored `outputs/` directory
- Add clearer error handling for portal layout changes
- Add CSV/JSON export options
- Add screenshots using fake data only
- Add a formal `.gitignore` rule for generated academic reports

---

## License

MIT License — use freely, contribute openly.
