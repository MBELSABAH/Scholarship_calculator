# 📚 UPEI Grades Extractor & Analyzer

A cross-platform Python project that automatically logs into the UPEI student portal, extracts grade and academic data, and calculates GPA and scholarship eligibility. Supports both Chrome and Safari browsers using Selenium.

## 🚀 Features

- ✅ Extracts GPA, major, minor, and full grade history
- 📄 Outputs a printer-friendly transcript-style `.txt` file
- 🎓 Calculates cumulative GPA and determines yearly scholarship eligibility
- 🔎 Distinguishes between academic years, filters repeated courses for GPA fairness
- 🧪 Designed with object-oriented principles for `Student`, `Courses`, and `Mark`

## 🛠️ Usage

1. **Clone the repo** and install requirements:
   ```bash
   git clone https://github.com/yourusername/grades-extractor.git
   cd grades-extractor
   pip install -r requirements.txt
   ```

2. **Activate your virtual environment (optional but recommended)**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # macOS/Linux
   .\venv\Scripts\activate    # Windows
   ```

3. **Run the program**:
   ```bash
   python Main.py
   ```

   You'll be prompted to choose your browser (`chrome` or `safari`) and enter your UPEI credentials.

4. **Output files generated**:
   - `student_information.txt` — name, ID, major(s), minor(s), GPA
   - `printer_friendly_grades.txt` — full list of courses and grades by year
   - Terminal output — cumulative GPA + scholarship eligibility by year

## 🧱 Project Structure

```
grades-extractor/
├── Courses.py                  # Course management & scholarship calculation
├── Mark.py                     # Grade translation (percent → GPA, letter)
├── Student.py                  # Student object and summary representation
├── Main.py                     # CLI controller and object builder
├── grades_extractor_chrome.py # Chrome-based web automation
├── grades_extractor_safari.py # Safari-based web automation
├── printer_friendly_grades.txt# Output: Grades sorted by academic year
├── student_information.txt     # Output: Name, ID, majors, minors, GPA
├── requirements.txt            # Dependencies (only selenium)
```

## 📋 Example Output

```
Name: I Solo Your Boyfriend
Student ID: 0362435
Major(s): Professional Yapper
Minor(s): Narcissism
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

## 🧠 Notes

- Lab and tutorial sections with `0 credits` are skipped
- Handles special grades: `DSC` (Discontinued), `P` (Pass), `E` (Error/0%)
- GPA only considers highest grade for repeated course codes (ignores section differences)
- Browser automation is headless by default (no GUI pops up)

## 💻 Requirements

- Python 3.10+
- ChromeDriver or Safari with WebDriver enabled
- Internet connection and valid UPEI credentials

Install required packages via:

```bash
pip install -r requirements.txt
```

## ⚖️ License

MIT License — use freely, contribute openly.

---
