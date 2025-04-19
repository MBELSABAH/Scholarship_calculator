from Mark import Mark  # Import Mark for handling course grades


class Courses(object):
    """
    A class to represent a collection of courses taken by a student.

    Attributes:
        __student (Student): The student associated with these courses.
        __courses (list): A list of tuples, where each tuple represents a course.
                          Each tuple contains (course_code, course_name, mark, credit_hours, academic_year).
    """

    def __init__(self, student):
        """
        Initializes the Courses object with a student and an empty list of courses.

        Args:
            student (Student): The student associated with these courses.

        Raises:
            TypeError: If the provided student is not an instance of the Student class.
        """
        from Student import Student  # Lazy import to avoid circular dependencies
        if not isinstance(student, Student):
            raise TypeError(f"Expected a Student object, got {type(student).__name__}")
        self.__student = student  # Store the student object
        self.__courses = []  # Initialize an empty list to store course details

    def add_course(self, *courses, academic_year: int):
        """
        Adds multiple courses to the list of courses for a specific academic year.

        Args:
            *courses: A variable number of tuples representing courses.
                      Each tuple can contain (course_code, course_name, mark, credit_hours).
            academic_year (int): The academic year the courses were taken.
        """
        for course in courses:
            if len(course) == 1:
                course_code = course[0]
                course_name = "N/A"  # Default course name
                mark = Mark()
                credit_hours = 3
            elif len(course) == 2:
                course_code, course_name = course
                mark = Mark()
                credit_hours = 3
            elif len(course) == 3:
                course_code, course_name, mark = course
                credit_hours = 3
            elif len(course) == 4:
                course_code, course_name, mark, credit_hours = course
            else:
                raise ValueError("Each course must be a tuple of length 1, 2, 3, or 4.")

            if mark is None:
                mark = Mark()
            if not isinstance(mark, Mark):
                raise ValueError(f"Expected a Mark object, got {type(mark).__name__}.")
            if credit_hours < 0:
                raise ValueError("Credit hours must be a positive integer.")

            # Append the course details along with the academic year
            self.__courses.append((course_code, course_name, mark, credit_hours, academic_year))

    def get_courses_and_marks(self) -> dict:
        """
        Returns a dictionary of courses and their marks.

        Returns:
            dict: A dictionary where keys are course codes and values are tuples of (course_name, Mark object).
        """
        return {course_code: (course_name, mark) for course_code, course_name, mark, _, _ in self.__courses}

    def calculate_scholarship(self, academic_year: int) -> str:
        """
        Calculates the scholarship based on the weighted average of marks for a specific academic year.

        Args:
            academic_year (int): The academic year for which to calculate the scholarship.

        Returns:
            str: A message indicating the weighted average and the scholarship amount.
        """
        total_weighted_marks = 0
        total_credit_hours = 0

        for _, _, mark, credit_hours, course_year in self.__courses:
            if course_year == academic_year:
                if isinstance(mark.percentage, (int, float)):
                    total_weighted_marks += mark.percentage * credit_hours
                    total_credit_hours += credit_hours
                elif mark.percentage == "E":
                    total_weighted_marks += 0
                    total_credit_hours += credit_hours

        if total_credit_hours == 0:
            return f"Year {academic_year} - No courses taken in the academic year to calculate scholarship."
        elif total_credit_hours < 18:
            return (f"Year {academic_year} - Not enough courses taken in the academic year to calculate scholarship."
                    f" Minimum year credits required: 18, current credits: {total_credit_hours}"
                    )

        weighted_average = total_weighted_marks / total_credit_hours

        if 95 <= weighted_average <= 100:
            return f"Year {academic_year} - Weighted Average: {weighted_average:.2f}, $3000 Scholarship"
        elif 90 <= weighted_average < 95:
            return f"Year {academic_year} - Weighted Average: {weighted_average:.2f}, $2000 Scholarship"
        elif 85 <= weighted_average < 90:
            return f"Year {academic_year} - Weighted Average: {weighted_average:.2f}, $1000 Scholarship"
        elif 80 <= weighted_average < 85:
            return f"Year {academic_year} - Weighted Average: {weighted_average:.2f}, $500 Scholarship"
        else:
            return (f"Year {academic_year} - No Scholarship: Weighted Average must be higher than 79%. Current:"
                    f" {weighted_average:.2f}")

    def calculate_cumulative_gpa(self) -> str:
        """
        Calculates the cumulative GPA (CGPA) using only courses with valid numeric GPAs.
        Includes only the highest mark for each course code in the calculation.
        Ignores section numbers in course codes (e.g., CS-1910-01 and CS-1910-02 are treated as same course).

        Returns:
            str: A message indicating the cumulative GPA or a message if no valid courses are found.
        """
        total_weighted_gpa: float = 0
        total_credit_hours: float = 0

        highest_marks = {}
        for course_code, _, mark, credit_hours, _ in self.__courses:
            base_course_code = '-'.join(course_code.split('-')[:2])
            if mark.percentage not in ["DSC", "N/A", "P"]:
                if (base_course_code not in highest_marks or mark.get_comparable_percentage() >
                        highest_marks[base_course_code][0].get_comparable_percentage()):
                    highest_marks[base_course_code] = (mark, credit_hours)

        for mark, credit_hours in highest_marks.values():
            total_weighted_gpa += mark.gpa * credit_hours
            total_credit_hours += credit_hours

        if total_credit_hours == 0:
            return "No valid courses to calculate GPA."

        cumulative_gpa = total_weighted_gpa / total_credit_hours
        return f"Cumulative GPA: {cumulative_gpa:.3f}\nTotal Credit Hours: {total_credit_hours}"

    def __str__(self) -> str:
        """
        Returns a string representation of the Courses object, listing all courses grouped by academic year,
        sorted first by subject name prefix (e.g., 'Math', 'CS') and then by subject mark.
        """
        separator: str = "=" * 100
        output: str = "Completed Courses by year:\n"

        # Group by year
        courses_by_year = {}
        for course_code, course_name, mark, credit_hours, year in self.__courses:
            courses_by_year.setdefault(year, []).append((course_code, course_name, mark, credit_hours))

        for year in sorted(courses_by_year):
            output += f"\nYear {year}:\n{separator}\n"
            sorted_courses = sorted(
                courses_by_year[year],
                key=lambda item: (item[0].split('-')[0], -item[2].get_comparable_percentage())
            )
            width = len(str(len(sorted_courses)))
            for i, (code, name, mark, credits) in enumerate(sorted_courses, start=1):
                output += (
                    f"{i:>{width}}. Course: {code} ({name}), {mark}, Credit Hours: {credits}\n"
                )
            output += separator + "\n"

        return output