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

        # Filter courses for the given academic year
        for _, _, mark, credit_hours, course_year in self.__courses:
            if course_year == academic_year:
                # Include only valid marks in the calculation
                if isinstance(mark.percentage, (int, float)):
                    total_weighted_marks += mark.percentage * credit_hours
                    total_credit_hours += credit_hours
                elif mark.percentage == "E":  # Treat "E" as a mark of 0 for scholarships
                    total_weighted_marks += 0 * credit_hours
                    total_credit_hours += credit_hours

        if total_credit_hours == 0:  # No valid courses in the specified year
            return f"No courses taken in the academic year {academic_year} to calculate scholarship."
        elif total_credit_hours < 30:  # Less than the minimum amount of courses required
            return (f"Not enough courses taken in the academic year {academic_year} to calculate scholarship."
                    f" Minimum required 30, current credits: {total_credit_hours}")

        weighted_average = total_weighted_marks / total_credit_hours

        # Determine the scholarship amount based on the weighted average
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

        Returns:
            str: A message indicating the cumulative GPA or a message if no valid courses are found.
        """
        total_weighted_gpa: float = 0  # Total weighted GPA
        total_credit_hours: float = 0  # Total credit hours

        # Track highest marks for each course code
        highest_marks = {}
        for course_code, _, mark, credit_hours, _ in self.__courses:
            if mark.percentage not in ["DSC", "N/A", "E", "P"]:  # Exclude invalid marks
                if course_code not in highest_marks or mark.get_comparable_percentage() > highest_marks[course_code][0].get_comparable_percentage():
                    highest_marks[course_code] = (mark, credit_hours)

        # Calculate GPA using the highest marks
        for mark, credit_hours in highest_marks.values():
            total_weighted_gpa += mark.gpa * credit_hours
            total_credit_hours += credit_hours

        if total_credit_hours == 0:  # No valid courses
            return "No valid courses to calculate GPA."

        cumulative_gpa = total_weighted_gpa / total_credit_hours  # Calculate cumulative GPA
        return f"Cumulative GPA: {cumulative_gpa:.3f}, Total Credit Hours: {total_credit_hours}"

    def __str__(self) -> str:
        """
        Returns a string representation of the Courses object, listing all courses grouped by academic year,
        sorted first by subject name prefix (e.g., 'Math', 'CS') and then by subject mark.

        Returns:
            str: A string containing the student details and a list of all courses with their details.
        """
        separator: str = "=" * 100  # Separator for formatting
        return_value: str = ""

        # Group courses by academic year
        courses_by_year = {}
        for course_code, course_name, mark, credit_hours, academic_year in self.__courses:
            if academic_year not in courses_by_year:
                courses_by_year[academic_year] = []
            courses_by_year[academic_year].append((course_code, course_name, mark, credit_hours))

        # Sort years and process each year's courses
        for year in sorted(courses_by_year.keys()):
            return_value += f"\nYear {year}:\n"

            # Sort courses by subject prefix (e.g., 'Math', 'CS'), then by mark (percentage descending)
            sorted_courses = sorted(
                courses_by_year[year],
                key=lambda item: (
                    item[0].split('-')[0],  # Subject prefix (e.g., 'Math', 'CS')
                    -item[2].get_comparable_percentage()  # Mark (descending)
                ),
            )

            # Enumerate and format sorted courses
            for i, (course_code, course_name, mark, credit_hours) in enumerate(sorted_courses, start=1):
                return_value += (
                    f"{i}. Course: {course_code} ({course_name}), {mark}, Credit Hours: {credit_hours}\n"
                )

        return_value += separator  # Add the separator at the end
        return return_value
