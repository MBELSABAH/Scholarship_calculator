import re
from Student import Student
from Courses import Courses
from Mark import Mark


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

    courses_by_year = {}
    current_year = None
    academic_year_pattern = r"--- Academic Year (\d{4}-\d{4}) ---"
    course_pattern = r"^(.*?) \| (.*?) \| (\d+) credits \| Final Grade: (.*)$"

    for line in lines:
        line = line.strip()
        # Check for academic year headers
        match_year = re.match(academic_year_pattern, line)
        if match_year:
            current_year = match_year.group(1)
            courses_by_year[current_year] = []
            continue

        # Check for course details
        match_course = re.match(course_pattern, line)
        if match_course and current_year:
            course_code = match_course.group(1).split()[0]
            course_name = match_course.group(2)
            credit_hours = int(match_course.group(3))
            final_grade = match_course.group(4)
            final_grade = "N/A" if final_grade == "" else final_grade  # Default empty grades to "N/A"
            courses_by_year[current_year].append((course_code, course_name, final_grade, credit_hours))

    return courses_by_year


def map_years_to_academic_years(courses_by_year: dict):
    """
    Maps academic years to year1, year2, etc.

    Args:
        courses_by_year (dict): Dictionary of courses by academic year.

    Returns:
        dict: A dictionary mapping `year1`, `year2`, etc., to course details.
    """
    sorted_years = sorted(courses_by_year.keys())  # Sort academic years
    mapped_years = {f"year{i+1}": courses_by_year[year] for i, year in enumerate(sorted_years)}
    return mapped_years


if __name__ == "__main__":
    # Parse the grades file
    grades_file = "printer_friendly_grades.txt"  # Replace with the path to your grades file
    courses_by_academic_year = parse_grades_file(grades_file)

    # Map academic years to year1, year2, etc.
    courses_by_year = map_years_to_academic_years(courses_by_academic_year)

    # Create the Student object
    mohamed = Student("Mohamed Elsabah", 373007, None, ("Computer Science", "Mathematics"))

    # Create the Courses object and associate it with the Student
    c = Courses(mohamed)

    # Add courses to the Courses object
    for year, courses in courses_by_year.items():
        academic_year = int(year[-1])  # Extract year number from "year1", "year2", etc.
        for course in courses:
            course_code, course_name, final_grade, credit_hours = course
            if final_grade.isdigit():  # If the grade is numeric
                mark = Mark(int(final_grade))
            elif final_grade.upper() in ["P", "N/A", "DSC", "E"]:  # Handle special grades
                mark = Mark(final_grade.upper())
            else:
                raise ValueError(f"Unexpected grade format: {final_grade}")
            c.add_course((course_code, course_name, mark, credit_hours), academic_year=academic_year)

    # Link the Courses object back to the Student
    mohamed.set_courses(c)

    # Print the Student object (with associated courses)
    print(mohamed)

    # Print the scholarship calculation results for each academic year
    for i in range(1, len(courses_by_year) + 1):
        print(c.calculate_scholarship(i))  # Scholarship for year1, year2, etc.
