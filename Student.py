from Courses import Courses  # Import Courses to avoid circular dependencies


class Student:
    """
    A class to represent a student.
    """

    def __init__(self, name: str, student_id: int, courses: Courses,
                 major: str | tuple[str, ...], minor: str | tuple[str, ...] = None):
        """
        Initializes a Student object.
        """
        self.__name = name
        self.__student_id = student_id
        self.__courses = courses
        self.__majors = tuple(m.lower() for m in major) if isinstance(major, tuple) else (major.lower(),)
        self.__minors = tuple(m.lower() for m in minor) if isinstance(minor, tuple) else (
            minor.lower(),) if minor else ()

    def set_courses(self, courses: Courses) -> None:
        """
        Sets the student's courses.
        """
        self.__courses = courses

    def get_courses(self) -> Courses:
        """
        Gets the student's courses.

        Returns:
            Courses: The student's courses object
        """
        return self.__courses

    def __str__(self) -> str:
        """
        Returns a string representation of the student.
        """
        separator = "=" * 100
        majors = ", ".join(m.title() for m in self.__majors)
        minors = ", ".join(m.title() for m in self.__minors) if self.__minors else "None"
        gpa = self.__courses.calculate_cumulative_gpa()

        return (
            f"Name: {self.__name}\n"
            f"Student ID: {self.__student_id}\n"
            f"Major(s): {majors}\n"
            f"Minor(s): {minors}\n"
            f"{gpa}\n"
            f"{separator}\n"
            f"{self.__courses}"
        )