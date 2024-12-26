from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time


# Helper function to infer academic year
def infer_academic_year(start_date):
    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    if month < 9:  # Before September, it's part of the previous academic year
        year -= 1
    return year


# Set up Chrome options for headless mode
chrome_options = Options()
chrome_options.add_argument("--headless")  # Enable headless mode
chrome_options.add_argument("--disable-gpu")  # Disable GPU for compatibility
chrome_options.add_argument("--no-sandbox")  # Bypass OS security model, if needed
chrome_options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
chrome_options.add_argument("--window-size=1920,1080")  # Set window size for proper element detection

# Main Script
service = Service()  # You can optionally specify the path to ChromeDriver here if needed
driver = webdriver.Chrome(service=service, options=chrome_options)  # Use ChromeDriver with headless options

try:
    # Step 1: Open the login page
    driver.get("https://collprodss.colleague.upei.ca/Student/Account/Login")

    # Step 2: Log in
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "UserName"))
    )
    username_input = driver.find_element(By.ID, "UserName")
    password_input = driver.find_element(By.ID, "Password")

    # Clear the fields before entering text
    username_input.clear()
    password_input.clear()

    # Add delays to ensure smooth input
    time.sleep(0.5)
    username_input.send_keys("mbelsabah")  # Replace with your username

    time.sleep(0.5)
    password_input.send_keys("Brimxl12!")  # Replace with your password

    time.sleep(0.5)
    password_input.submit()  # Submit the login form

    # Wait for the page to load
    time.sleep(1)

    print("Login successful.")

    # Step 3: Navigate to Grades page
    grades_button = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/Student/Student/Grades']"))
    )
    driver.execute_script("arguments[0].click();", grades_button)
    print("Successfully clicked the Grades button.")

    # Wait for the grades page to load
    time.sleep(1)

    # Step 4: Click the first "Print" button
    print_button_1 = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "print-grades-link"))
    )
    driver.execute_script("arguments[0].click();", print_button_1)
    print("Clicked the first Print button.")

    # Wait for the print page to load
    time.sleep(1)

    # Step 5: Select all semesters by checking all checkboxes
    checkboxes = WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.XPATH, "//input[@type='checkbox']"))
    )

    for checkbox in checkboxes:
        if not checkbox.is_selected():
            try:
                # Use JavaScript to ensure the checkbox is clicked
                driver.execute_script("arguments[0].click();", checkbox)
            except Exception as e:
                print(f"Failed to click checkbox: {e}")
    print("All semesters selected.")

    # Step 6: Click the second "Print" button at the bottom
    print_button_2 = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[text()='Print']"))
    )
    try:
        driver.execute_script("arguments[0].click();", print_button_2)
        print("Clicked the second Print button.")
    except Exception as e:
        print(f"Failed to click the second Print button: {e}")

    # Wait for the printer-friendly page to load
    time.sleep(1)

    # Step 7: Switch to the new window (printer-friendly page)
    driver.switch_to.window(driver.window_handles[-1])

    # Step 8: Extract all grades from the printer-friendly page
    course_rows = driver.find_elements(By.XPATH, "//table[contains(@class, 'student-grade-table')]/tbody/tr")
    results = []

    for row in course_rows:
        columns = row.find_elements(By.TAG_NAME, "td")
        if len(columns) >= 4:  # Ensure the row has at least 4 columns
            course_section = " ".join(columns[0].text.split())  # Clean text
            title = " ".join(columns[1].text.split())  # Clean text
            credit = " ".join(columns[2].text.split())  # Clean text
            final_grade = " ".join(columns[3].text.split())  # Clean text
            start_date = course_section.split(" ")[-1]
            academic_year = infer_academic_year(start_date)
            results.append((academic_year, f"{course_section} | {title} |"
                                           f" {credit} credits | Final Grade: {final_grade}"))

    # Step 9: Save the results to a file without extra spaces between lines
    results.sort(key=lambda x: x[0])  # Sort by academic year
    with open("printer_friendly_grades.txt", "w", encoding="utf-8") as file:
        current_year = None
        for entry in results:
            academic_year, course_details = entry
            if academic_year != current_year:
                if current_year is not None:
                    file.write("\n")  # Add space between years
                file.write(f"--- Academic Year {academic_year}-{academic_year + 1} ---\n")
                current_year = academic_year
            file.write(f"{course_details}\n")

    print("Grades have been successfully extracted and grouped by academic year.")

finally:
    driver.quit()
