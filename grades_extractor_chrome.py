from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import sys


def save_student_information(info_lines, file_path="student_information.txt"):
    """
    Saves extracted student information to a file.

    Args:
        info_lines (list): A list of strings representing student information lines.
        file_path (str): Path to the output file.
    """
    with open(file_path, "w", encoding="utf-8") as file:
        for line in info_lines:
            file.write(line + "\n")


def infer_academic_year(start_date):
    """
    Infers the academic year from the start date.

    Args:
        start_date (str): The start date in 'YYYY-MM-DD' format.

    Returns:
        int: The academic year as an integer.
    """
    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    if month < 9:
        year -= 1
    return year


# Get credentials from command-line arguments
username = sys.argv[1]
password = sys.argv[2]

# Setup Chrome options
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(service=Service(), options=chrome_options)

try:
    # Step 1: Open the login page
    driver.get("https://collprodss.colleague.upei.ca/Student/Account/Login")

    # Step 2: Log in
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "UserName"))
    )
    username_input = driver.find_element(By.ID, "UserName")
    password_input = driver.find_element(By.ID, "Password")

    username_input.clear()
    password_input.clear()

    time.sleep(0.5)
    username_input.send_keys(username)
    time.sleep(0.5)
    password_input.send_keys(password)
    time.sleep(0.5)
    password_input.submit()

    print("Login successful.")

    # Step 3: Navigate to "Student Planning"
    student_planning_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/Student/Planning']"))
    )
    driver.execute_script("arguments[0].click();", student_planning_button)
    print("Successfully clicked the 'Student Planning' button.")

    # Step 4: Go to "My Progress"
    my_progress_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/Student/MyProgress']"))
    )
    driver.execute_script("arguments[0].click();", my_progress_button)
    print("Successfully clicked the 'Go to My Progress' button.")

    # Step 5: Extract student information
    time.sleep(2)
    at_a_glance_section = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'At a Glance')]"))
    )

    # Extract 5 lines below "At a Glance"
    info_lines = []
    for i in range(1, 6):
        info_line = at_a_glance_section.find_element(By.XPATH, f"./following-sibling::*[{i}]").text
        info_lines.append(info_line)

    save_student_information(info_lines)
    print("Student information extracted and saved to 'student_information.txt'.")

    # Step 6: Return to Home Page
    home_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/Student/Home']"))
    )
    driver.execute_script("arguments[0].click();", home_button)
    print("Returned to the Home page.")

    # Step 7: Navigate to Grades page
    grades_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/Student/Student/Grades']"))
    )
    driver.execute_script("arguments[0].click();", grades_button)
    print("Successfully clicked the Grades button.")

    # Step 8: Select all semesters by checking all checkboxes
    checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
    for checkbox in checkboxes:
        if not checkbox.is_selected():
            driver.execute_script("arguments[0].click();", checkbox)
    print("All semesters selected.")

    # Step 9: Click the "Print" button
    print_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "print-grades-link"))
    )
    driver.execute_script("arguments[0].click();", print_button)
    print("Clicked the Print button.")

    # Step 10: Extract all grades
    time.sleep(1)
    course_rows = driver.find_elements(By.XPATH, "//table[contains(@class, 'student-grade-table')]/tbody/tr")
    results = []

    for row in course_rows:
        columns = row.find_elements(By.TAG_NAME, "td")
        if len(columns) >= 4:
            course_section = " ".join(columns[0].text.split())
            title = " ".join(columns[1].text.split())
            credit = " ".join(columns[2].text.split())
            final_grade = " ".join(columns[3].text.split())
            start_date = course_section.split(" ")[-1]
            academic_year = infer_academic_year(start_date)
            results.append((academic_year, f"{course_section} | {title} | {credit} credits | Final Grade: {final_grade}"))

    # Step 11: Save grades
    results.sort(key=lambda x: x[0])
    with open("printer_friendly_grades.txt", "w", encoding="utf-8") as file:
        current_year = None
        for entry in results:
            academic_year, course_details = entry
            if academic_year != current_year:
                if current_year is not None:
                    file.write("\n")
                file.write(f"--- Academic Year {academic_year}-{academic_year + 1} ---\n")
                current_year = academic_year
            file.write(f"{course_details}\n")

    print("Grades successfully extracted and saved to 'printer_friendly_grades.txt'.")

finally:
    driver.quit()
