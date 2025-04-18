from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
import time
import sys
import re


def extract_and_filter_information(output_file: str):
    """
    Extracts and formats relevant information dynamically from the 'My Progress' page and filters it.
    """
    try:
        parent_container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'programs-ataglance')]/div[2]/div[1]"))
        )
        at_a_glance_text = parent_container.text

        lines = at_a_glance_text.splitlines()
        filtered_lines = []
        current_title = None
        majors_list = []
        has_minors = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.endswith(":"):
                if current_title and not current_title.startswith("Majors:"):
                    filtered_lines.append(current_title)
                current_title = line
            else:
                if current_title and current_title.startswith("Majors:"):
                    majors_list.append(line.strip())
                elif current_title:
                    current_title += f" {line}"
                else:
                    filtered_lines.append(line)

            if line.startswith("Minors:"):
                has_minors = True

        if majors_list:
            majors_combined = ", ".join(majors_list)
            filtered_lines.append(f"Majors: {majors_combined}")

        if not has_minors:
            filtered_lines.append("Minors: None")

        final_filtered_lines = []
        for line in filtered_lines:
            if line.startswith("Cumulative GPA:"):
                gpa_match = re.search(r"Cumulative GPA: ([0-9.]+)", line)
                if gpa_match:
                    final_filtered_lines.append(f"Cumulative GPA: {gpa_match.group(1)}")
            elif line.startswith("Majors:") or line.startswith("Minors:"):
                final_filtered_lines.append(line.strip())

        with open(output_file, "w", encoding="utf-8") as file:
            file.write("\n".join(final_filtered_lines))

        print(f"Filtered information saved to {output_file}.")
    except Exception as e:
        print(f"Error during extraction: {e}")
        with open("debug_full_page.txt", "w", encoding="utf-8") as debug_file:
            debug_file.write(driver.page_source)
        print("Saved full page content to 'debug_full_page.txt' for inspection.")


def infer_academic_year(start_date):
    """
    Infers the academic year from the start date.
    """
    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    if month < 9:
        year -= 1
    return year


# Get credentials from command-line arguments
username = sys.argv[1]
password = sys.argv[2]

driver = webdriver.Safari()

try:
    # Step 1: Open the login page
    driver.get("https://collprodss.colleague.upei.ca/Student/Account/Login")

    # Step 2: Log in
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "UserName")))
    username_input = driver.find_element(By.ID, "UserName")
    password_input = driver.find_element(By.ID, "Password")

    username_input.clear()
    password_input.clear()
    time.sleep(0.5)
    username_input.send_keys(username)
    time.sleep(0.5)
    password_input.send_keys(password)
    time.sleep(0.5)

    # Explicitly click the submit button
    login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
    driver.execute_script("arguments[0].click();", login_button)

    # Give the site a moment to process login and redirect
    time.sleep(1.5)
    print("Login submitted.")

    # Step 3: Navigate directly to My Progress
    driver.get("https://collprodss.colleague.upei.ca/Student/Planning/Programs/MyProgress")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'programs-ataglance')]/div[2]/div[1]"))
    )
    print("Navigated directly to My Progress page.")

    # Step 4: Extract relevant information
    extract_and_filter_information("student_information.txt")

    # Step 5: Navigate directly to Grades page
    driver.get("https://collprodss.colleague.upei.ca/Student/Student/Grades")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']"))
    )
    time.sleep(2)  # let the header and content fully load
    print("Navigated directly to Grades page.")

    # —— NEW: explicitly locate Student Name and ID containers ——
    name_label = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Student Name:')]"))
    )
    id_label = driver.find_element(By.XPATH, "//*[contains(text(),'Student ID:')]")

    # The actual text (value) is in the same parent element; grab parent.text
    name_container = name_label.find_element(By.XPATH, "..")
    id_container = id_label.find_element(By.XPATH, "..")

    student_name = name_container.text.split(":", 1)[1].strip()
    student_id   = id_container.text.split(":", 1)[1].strip()

    # Prepend to the student_information.txt
    with open("student_information.txt", "r+", encoding="utf-8") as info_file:
        existing = info_file.read()
        info_file.seek(0)
        info_file.write(f"Name: {student_name}\nStudent ID: {student_id}\n{existing}")
    print(f"Fetched Name: {student_name}, ID: {student_id} → prepended to student_information.txt")

    # Step 6: Select all semesters
    checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
    for checkbox in checkboxes:
        try:
            if not checkbox.is_selected():
                driver.execute_script("arguments[0].click();", checkbox)
        except StaleElementReferenceException:
            continue
    print("All semesters selected.")

    # Step 7: Click the "Print" button
    print_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "print-grades-link"))
    )
    driver.execute_script("arguments[0].click();", print_button)
    print("Clicked the Print button.")

    # Step 8: Extract all grades
    time.sleep(1)
    course_rows = driver.find_elements(By.XPATH, "//table[contains(@class, 'student-grade-table')]/tbody/tr")
    results = []

    for row in course_rows:
        cols = row.find_elements(By.TAG_NAME, "td")
        if len(cols) >= 4:
            section     = " ".join(cols[0].text.split())
            title       = " ".join(cols[1].text.split())
            credit      = " ".join(cols[2].text.split())
            final_grade = " ".join(cols[3].text.split())
            start_date  = section.split(" ")[-1]
            year        = infer_academic_year(start_date)
            results.append((year, f"{section} | {title} | {credit} credits | Final Grade: {final_grade}"))

    # Step 9: Save grades
    results.sort(key=lambda x: x[0])
    with open("printer_friendly_grades.txt", "w", encoding="utf-8") as file:
        current_year = None
        for yr, details in results:
            if yr != current_year:
                if current_year is not None:
                    file.write("\n")
                file.write(f"--- Academic Year {yr}-{yr + 1} ---\n")
                current_year = yr
            file.write(f"{details}\n")

    print("Grades successfully extracted and saved to 'printer_friendly_grades.txt'.")
finally:
    driver.quit()
