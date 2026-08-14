# UPEI Grades Extractor & Scholarship Analyzer

A Python/Selenium automation project that extracts academic records from the UPEI student portal, structures course and grade information, calculates GPA-related summaries, and estimates scholarship eligibility using academic-year rules.

This project demonstrates browser automation, object-oriented Python design, academic-record parsing, GPA conversion logic, repeated-course handling, and report generation.

> **Privacy note:** This tool works with sensitive academic information. It should only be run locally by the account owner. Do not commit real output files, screenshots, credentials, or private student records to GitHub.

---

## Academic Copilot web MVP (Phase 1–2)

This branch also exposes the existing calculator as a local web product: **“Ask your academic record.”** The current checkpoint includes the secure connection screen, structured `AcademicSnapshot` API, dashboard, course-year accordions, and a sanitized demo record. The DeepSeek agent is intentionally not included yet; it begins only after dashboard approval.

The browser scraper now returns profile and course data directly to Python. FastAPI passes that record into the existing `Student`, `Courses`, and `Mark` classes, converts their deterministic results into JSON, and serves a no-build HTML/CSS/JavaScript frontend.

### Run the web app

Create the virtual environment and install dependencies as described below, then run:

```bash
uvicorn backend.app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Choose **Explore the demo record** to inspect the dashboard without university credentials.

The backend and frontend share one local server, so there is no separate frontend build command.

### API endpoints

- `POST /api/connect` — accepts a live UPEI connection request or `{ "demo": true }`, calculates a snapshot, and caches only that sanitized snapshot in memory
- `GET /api/snapshot` — returns the current sanitized snapshot
- `DELETE /api/snapshot` — clears the in-memory snapshot
- `GET /api/health` — local health check

### Credential flow

For the web path, the password arrives in a masked `SecretStr` request field and is passed directly to the selected Python scraper. It is not placed in subprocess arguments, written to either legacy output file, logged, returned to the browser, stored in the snapshot, or sent to an AI provider. Run this local endpoint behind HTTPS before exposing it beyond localhost.

The historical extractor scripts still support their command-line entry points and can generate the local text reports for CLI compatibility. Those generated files are ignored and are not application fixtures.

### Verify

```bash
python -B -m unittest discover -v
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
