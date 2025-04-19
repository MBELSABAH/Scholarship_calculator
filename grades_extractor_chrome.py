from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import sys
import re

def extract_and_filter_information(output_file: str):
    """
    Extracts GPA, Majors, and Minors from the My Progress page exactly as the Safari extractor does.
    """
    parent = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(@id, 'programs-ataglance')]/div[2]/div[1]")
        )
    )
    text = parent.text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    filtered, majors, current = [], [], None
    has_minors = False
    for line in lines:
        if line.endswith(":"):
            if current and not current.startswith("Majors:"):
                filtered.append(current)
            current = line
        else:
            if current and current.startswith("Majors:"):
                majors.append(line)
            elif current:
                current += f" {line}"
            else:
                filtered.append(line)
        if line.startswith("Minors:"):
            has_minors = True

    if majors:
        filtered.append(f"Majors: {', '.join(majors)}")
    if not has_minors:
        filtered.append("Minors: None")

    final = []
    for ln in filtered:
        if ln.startswith("Cumulative GPA:"):
            m = re.search(r"Cumulative GPA: ([0-9.]+)", ln)
            if m:
                final.append(f"Cumulative GPA: {m.group(1)}")
        elif ln.startswith("Majors:") or ln.startswith("Minors:"):
            final.append(ln)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(final))
    print(f"Filtered information saved to {output_file}.")

def infer_academic_year(start_date: str) -> int:
    """
    Infers the academic year from a 'YYYY-MM-DD' start date.
    """
    year, month = map(int, start_date.split("-")[:2])
    if month < 9:
        year -= 1
    return year

if __name__ == "__main__":
    username, password = sys.argv[1], sys.argv[2]

    chrome_opts = Options()
    # chrome_opts.add_argument("--headless")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(service=Service(), options=chrome_opts)
    try:
        # 1) Login
        driver.get("https://collprodss.colleague.upei.ca/Student/Account/Login")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "UserName")))
        driver.find_element(By.ID, "UserName").clear()
        driver.find_element(By.ID, "Password").clear()
        time.sleep(0.5)
        driver.find_element(By.ID, "UserName").send_keys(username)
        time.sleep(0.5)
        driver.find_element(By.ID, "Password").send_keys(password)
        time.sleep(0.5)
        try:
            btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            driver.execute_script("arguments[0].click();", btn)
        except:
            driver.find_element(By.ID, "Password").submit()
        time.sleep(1.5)
        print("Login submitted.")

        # 2) Extract student info
        driver.get("https://collprodss.colleague.upei.ca/Student/Planning/Programs/MyProgress")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'programs-ataglance')]/div[2]/div[1]"))
        )
        print("Navigated to My Progress page.")
        extract_and_filter_information("student_information.txt")

        # 3) Navigate to Grades page
        driver.get("https://collprodss.colleague.upei.ca/Student/Student/Grades")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "print-grade-label")))
        print("Navigated to Grades page.")

        # 4) Open term selection panel
        toggle = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "print-grade-label")))
        toggle.click()
        print("Opened term selection panel.")

        # 5) Select all term checkboxes via labels
        terms_ul = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "student-terms-ul")))
        labels = terms_ul.find_elements(By.TAG_NAME, "label")
        for lbl in labels:
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", lbl)
                driver.execute_script("arguments[0].click();", lbl)
            except:
                continue
        print("All term checkboxes toggled.")

        # 6) Click final Print (opens new tab)
        orig_handles = driver.window_handles
        final_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[@id='print-grades']/div[1]/div[3]/div[2]/button"))
        )
        final_btn.click()
        print("Clicked final Print, awaiting new window...")

        # 7) Switch to new printer-friendly tab
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > len(orig_handles))
        new = [h for h in driver.window_handles if h not in orig_handles][0]
        driver.switch_to.window(new)
        print("Switched to printer-friendly window.")
        time.sleep(1)

        # ——— extract student name & ID from the printed page ———
        name_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH,
                "//*[@id='student-grades']//span[text()='Student Name:']/following-sibling::span"
            ))
        )
        student_name = name_elem.text.strip()
        id_elem = driver.find_element(
            By.XPATH,
            "//*[@id='student-grades']//span[text()='Student ID:']/following-sibling::span"
        )
        student_id = id_elem.text.strip()

        # prepend to student_information.txt
        with open("student_information.txt", "r+", encoding="utf-8") as info_file:
            existing = info_file.read()
            info_file.seek(0)
            info_file.write(f"Name: {student_name}\nStudent ID: {student_id}\n{existing}")
        print(f"Prepended Name: {student_name}, ID: {student_id} to student_information.txt")

        # 8) Scrape table rows
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//table[contains(@class,'student-grade-table')]"))
        )
        rows = driver.find_elements(By.XPATH, "//table[contains(@class,'student-grade-table')]/tbody/tr")

        results = []
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 4:
                continue
            section = " ".join(cols[0].text.split())
            m = re.search(r"\d{4}-\d{2}-\d{2}", section)
            if not m:
                continue
            year = infer_academic_year(m.group(0))
            title = " ".join(cols[1].text.split())
            cred = " ".join(cols[2].text.split())
            grade = " ".join(cols[3].text.split())
            results.append((year, f"{section} | {title} | {cred} credits | Final Grade: {grade}"))

        # 9) Write to file
        results.sort(key=lambda x: x[0])
        with open("printer_friendly_grades.txt", "w", encoding="utf-8") as f:
            cur_year = None
            for yr, line in results:
                if yr != cur_year:
                    if cur_year is not None:
                        f.write("\n")
                    f.write(f"--- Academic Year {yr}-{yr+1} ---\n")
                    cur_year = yr
                f.write(line + "\n")
        print("Grades extracted to 'printer_friendly_grades.txt'.")

    finally:
        driver.quit()
