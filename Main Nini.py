from Student import Student
from Courses import Courses
from Mark import Mark

if __name__ == "__main__":
    # Create the Student object
    nini = Student("Ditthi Chaterjee", 19, 368797, None, ("Computer Science",), ("Business",))

    # Create the Courses object and associate it with the Student
    c = Courses(nini)
    c.add_course(
        ("MATH-1910", Mark(95), 4),
        ("MATH-1920", Mark(94), 4),
        ("ACCT-1010", Mark(85)),
        ("BUS-1410", Mark(84)),
        ("BUS-1710", Mark(88)),
        ("BUS-2720", Mark(95)),
        ("STAT-1910", Mark(85)),
        ("CS-1910", Mark(68)),
        ("CS-1920", Mark(80)),
        ("CS-2910", Mark(89)),
        ("CS-2520", Mark(86)),
        ("IKE-1040", Mark(100)),
        ("UPEI-1030", Mark(86)),
        ("UPEI-SVPR", Mark("P"), 0)
    )
    # Link the Courses object back to the Student
    nini.set_courses(c)

    # Print the Student object (with associated courses)
    print(nini)

    # Print the scholarship calculation result
    print(c.calculate_scholarship())
