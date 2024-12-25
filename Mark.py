class Mark(object):
    """
    A class to represent a mark (grade) for a course.

    Attributes:
        percentage (str | int): The percentage grade for the course.
        gpa (float | str): The GPA equivalent of the percentage.
        letter (str): The letter grade equivalent of the percentage.
    """

    def __init__(self, percentage: str | int = "N/A"):
        """
        Initializes a Mark object.

        Args:
            percentage (str | int, optional): The percentage grade. Defaults to "N/A".
        """
        if percentage == "DSC":  # Handle discontinued courses
            self.percentage = "DSC"
            self.gpa = "N/A"
            self.letter = "N/A"
        else:
            self.percentage = percentage
            self.gpa = Mark.percentage_to_gpa(percentage)
            self.letter = Mark.percentage_to_letter(percentage)

    @staticmethod
    def percentage_to_gpa(percentage: str | int):
        """
        Converts a percentage to a GPA.

        Args:
            percentage (str | int): The percentage grade.

        Returns:
            float | str: The GPA equivalent of the percentage.
        """
        if isinstance(percentage, str):
            if percentage in ["N/A", "P", "DSC"]:
                return percentage
            if percentage == "E":  # E is treated as a mark of 0
                return 0
        elif isinstance(percentage, int):  # Numeric grades
            if 91 <= percentage <= 100:
                return 4.3
            elif 85 <= percentage < 91:
                return 4.0
            elif 80 <= percentage < 85:
                return 3.7
            elif 77 <= percentage < 80:
                return 3.3
            elif 74 <= percentage < 77:
                return 3.0
            elif 70 <= percentage < 74:
                return 2.7
            elif 67 <= percentage < 70:
                return 2.3
            elif 64 <= percentage < 67:
                return 2.0
            elif 60 <= percentage < 64:
                return 1.7
            elif 57 <= percentage < 60:
                return 1.3
            elif 54 <= percentage < 57:
                return 1.0
            elif 50 <= percentage < 54:
                return 0.7
            else:
                return 0
        return "N/A"  # Default for invalid percentage

    @staticmethod
    def percentage_to_letter(percentage: str | int):
        """
        Converts a percentage to a letter grade.

        Args:
            percentage (str | int): The percentage grade.

        Returns:
            str: The letter grade equivalent of the percentage.
        """
        if isinstance(percentage, str):
            if percentage in ["N/A", "P", "DSC"]:
                return percentage
            if percentage == "E":
                return "F"
        elif isinstance(percentage, int):  # Numeric grades
            if 91 <= percentage <= 100:
                return "A+"
            elif 85 <= percentage < 91:
                return "A"
            elif 80 <= percentage < 85:
                return "A-"
            elif 77 <= percentage < 80:
                return "B+"
            elif 74 <= percentage < 77:
                return "B"
            elif 70 <= percentage < 74:
                return "B-"
            elif 67 <= percentage < 70:
                return "C+"
            elif 64 <= percentage < 67:
                return "C"
            elif 60 <= percentage < 64:
                return "C-"
            elif 57 <= percentage < 60:
                return "D+"
            elif 54 <= percentage < 57:
                return "D"
            elif 50 <= percentage < 54:
                return "D-"
            else:
                return "F"
        return "N/A"

    def get_comparable_percentage(self):
        """
        Returns the percentage value for sorting purposes.

        Returns:
            int: The percentage value for sorting. Treats "E" as 0 and "N/A", "P", or "DSC" as -1.
        """
        if isinstance(self.percentage, int):
            return self.percentage
        if self.percentage == "E":
            return 0
        return -1  # Treat "N/A", "P", and "DSC" as the lowest possible value

    def __str__(self):
        """
        Returns a string representation of the mark.

        Returns:
            str: The percentage, GPA, and letter grade of the mark.
        """
        return f"MARK: {self.percentage}, GPA: {self.gpa}, LETTER: {self.letter}"
