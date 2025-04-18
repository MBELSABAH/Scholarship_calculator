import subprocess
from Student import Student
from Courses import Courses
from Mark import Mark
import os
import re


def parse_grades_file(file_path: str):
    """
    Parses the grades file and organizes the courses by academic year.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    parsed_courses_by_year = {}
    current_academic_year = None
    academic_year_pattern = r"--- Academic Year (\d{4}-\d{4}) ---"
    course_pattern = r"^(.*?) \| (.*?) \| (\d+) credits \| Final Grade: (.*)$"

    for line in lines:
        line = line.strip()
        match_year = re.match(academic_year_pattern, line)
        if match_year:
            current_academic_year = match_year.group(1)
            parsed_courses_by_year[current_academic_year] = []
            continue

        match_course = re.match(course_pattern, line)
        if match_course and current_academic_year:
            code = match_course.group(1).split()[0]
            name = match_course.group(2)
            credits = int(match_course.group(3))
            grade = match_course.group(4)
            grade = "N/A" if grade == "" else grade
            parsed_courses_by_year[current_academic_year].append(
                (code, name, grade, credits)
            )

    return parsed_courses_by_year


def map_years_to_academic_years(parsed_courses: dict):
    """
    Maps academic years to year1, year2, etc.
    """
    sorted_years = sorted(parsed_courses.keys())
    return {f"year{i+1}": parsed_courses[y] for i, y in enumerate(sorted_years)}


if __name__ == "__main__":
    # Prompt for browser, username, and password
    browser = input("Which browser would you like to use? (chrome/safari): ").strip().lower()
    username = input("Enter your username: ").strip()
    password = input("Enter your password: ").strip()

    print(f"Using browser: {browser}")
    print("Fetching student information and latest grades...")

    try:
        venv_python = os.path.join('.', 'venv', 'bin', 'python')
        extractor = "grades_extractor_safari.py" if browser == "safari" else "grades_extractor_chrome.py"
        subprocess.run([venv_python, extractor, username, password], check=True)
        print("Successfully fetched student information and grades.")
        print("\n")  # spacing
        print('=' * 100)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching grades: {e}")
        exit(1)

    grades_file = "printer_friendly_grades.txt"
    info_file = "student_information.txt"

    try:
        courses_by_year = parse_grades_file(grades_file)
        mapped = map_years_to_academic_years(courses_by_year)

        # Read student info
        with open(info_file, "r", encoding="utf-8") as f:
            info_lines = f.readlines()

        name = "Unknown"
        student_id = 0
        majors = ()
        minors = ()
        for line in info_lines:
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Student ID:"):
                student_id = int(line.split(":", 1)[1].strip())
            elif line.startswith("Majors:"):
                majors = tuple(x.strip() for x in line.split(":", 1)[1].split(","))
            elif line.startswith("Minors:"):
                minors = tuple(x.strip() for x in line.split(":", 1)[1].split(","))

        student = Student(name, student_id, None, majors, minors)
        courses_obj = Courses(student)

        for year_key, course_list in mapped.items():
            year_idx = int(year_key[-1])
            for code, cname, cgrade, creds in course_list:
                if cgrade.isdigit():
                    mark = Mark(int(cgrade))
                else:
                    mark = Mark(cgrade.upper())
                courses_obj.add_course((code, cname, mark, creds), academic_year=year_idx)

        student.set_courses(courses_obj)

        print(student)
        print()
        print("Scholarship Eligibility:")
        print("=" * 100)
        for i in range(1, len(mapped) + 1):
            print(student.get_courses().calculate_scholarship(i))
    except FileNotFoundError as e:
        print(f"Error: {e}")
