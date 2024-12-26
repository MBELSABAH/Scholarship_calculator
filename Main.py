import re
import subprocess
from Student import Student
from Courses import Courses
from Mark import Mark


# noinspection PyShadowingNames
def parse_grades_file(file_path: str):
    """
    Parses the grades file and organizes the courses by academic year.

    Args:
        file_path (str): Path to the grades file.

    Returns:
        dict: A dictionary where keys are academic years and values are lists of course details.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    parsed_courses_by_year = {}
    current_academic_year = None
    academic_year_pattern = r"--- Academic Year (\d{4}-\d{4}) ---"
    course_pattern = r"^(.*?) \| (.*?) \| (\d+) credits \| Final Grade: (.*)$"

    for line in lines:
        line = line.strip()
        # Check for academic year headers
        match_year = re.match(academic_year_pattern, line)
        if match_year:
            current_academic_year = match_year.group(1)
            parsed_courses_by_year[current_academic_year] = []
            continue

        # Check for course details
        match_course = re.match(course_pattern, line)
        if match_course and current_academic_year:
            parsed_course_code = match_course.group(1).split()[0]
            parsed_course_name = match_course.group(2)
            parsed_credit_hours = int(match_course.group(3))
            parsed_final_grade = match_course.group(4)
            # Default empty grades to "N/A"
            parsed_final_grade = "N/A" if parsed_final_grade == "" else parsed_final_grade
            parsed_courses_by_year[current_academic_year].append(
                (parsed_course_code, parsed_course_name, parsed_final_grade, parsed_credit_hours)
            )

    return parsed_courses_by_year


def map_years_to_academic_years(parsed_courses: dict):
    """
    Maps academic years to year1, year2, etc.

    Args:
        parsed_courses (dict): Dictionary of courses by academic year.

    Returns:
        dict: A dictionary mapping `year1`, `year2`, etc., to course details.
    """
    sorted_academic_years = sorted(parsed_courses.keys())  # Sort academic years
    # noinspection PyShadowingNames
    mapped_years = {
        f"year{i+1}": parsed_courses[academic_year]
        for i, academic_year in enumerate(sorted_academic_years)
    }
    return mapped_years


if __name__ == "__main__":
    # First, run the grades extractor to get the latest grades
    print("Fetching latest grades...")
    try:
        subprocess.run(["python3", "grades_extractor.py"], check=True)
        print("Successfully fetched latest grades.")
        print('='*100)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching grades: {e}")
        exit(1)

    # Parse the grades file
    grades_file_path = "printer_friendly_grades.txt"
    courses_by_academic_year = parse_grades_file(grades_file_path)

    # Map academic years to year1, year2, etc.
    mapped_courses_by_year = map_years_to_academic_years(courses_by_academic_year)

    # Create the Student object
    mohamed = Student("Mohamed Elsabah", 373007, None, ("Computer Science", "Mathematics"))

    # Create the Courses object and associate it with the Student
    courses_obj = Courses(mohamed)  # Renamed to avoid shadowing

    # Add courses to the Courses object
    for academic_year, academic_courses in mapped_courses_by_year.items():
        year_index = int(academic_year[-1])  # Extract year number from "year1", "year2", etc.
        for course_details in academic_courses:
            parsed_course_code, parsed_course_name, parsed_course_grade, parsed_course_credits = course_details
            if parsed_course_grade.isdigit():  # If the grade is numeric
                mark = Mark(int(parsed_course_grade))
            elif parsed_course_grade.upper() in ["P", "N/A", "DSC", "E"]:  # Handle special grades
                mark = Mark(parsed_course_grade.upper())
            else:
                raise ValueError(f"Unexpected grade format: {parsed_course_grade}")
            courses_obj.add_course(
                (parsed_course_code, parsed_course_name, mark, parsed_course_credits), academic_year=year_index
            )

    # Link the Courses object back to the Student
    mohamed.set_courses(courses_obj)

    # Print student information
    print(mohamed)
    print()  # Add a blank line before scholarships

    # Calculate scholarships for each year
    print("Scholarship Eligibility:")
    print("=" * 100)
    for year in range(1, len(mapped_courses_by_year) + 1):
        print(mohamed.get_courses().calculate_scholarship(year))
