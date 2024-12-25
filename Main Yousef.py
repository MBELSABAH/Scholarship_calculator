from Student import Student
from Courses import Courses
from Mark import Mark

if __name__ == "__main__":
    # Create the Student object
    yousef = Student("Yousef Mahrous", 362435, None, "Sustainable Design Engineering")

    # Create the Courses object and associate it with the Student
    c = Courses(yousef)

    # Add 1st year courses
    c.add_course(
        ("MATH-1910", Mark(91), 4),
        ("CHEM-1110", Mark(87)),
        ("MATH-1920", Mark(80), 4),
        ("UPEI-1010", Mark(67)),
        ("MATH-3010", Mark(92)),
        ("MATH-2610", Mark(82)),
        ("ENGN-1200", Mark(80)),
        ("ENGN-1210", Mark(85)),
        ("ENGN-1300", Mark(85)),
        ("ENGN-1400", Mark(80)),
        ("ENGN-1800", Mark(80)),
        ("ENGN-1900", Mark(85)),
        ("ENGN-1990", Mark(68)),
        ("ENGN-1200", Mark(80)),

        academic_year=1
    )

    # Add 2nd year courses
    c.add_course(
        academic_year=2
    )

    # Add 3rd year courses
    c.add_course(
        academic_year=3
    )

    # Add 4th year courses
    c.add_course(
        academic_year=4
    )

    # Link the Courses object back to the Student
    yousef.set_courses(c)

    # Print the Student object (with associated courses)
    print(yousef)

    # Print the scholarship calculation results for each academic year
    print(c.calculate_scholarship(1))  # Scholarship for 1st year
    print(c.calculate_scholarship(2))  # Scholarship for 2nd year
    print(c.calculate_scholarship(3))  # Scholarship for 3rd year
    print(c.calculate_scholarship(4))  # Scholarship for 4th year
