"""Safari scraper for UPEI academic data with an import-safe service API."""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper_utils import (
    ProgressCallback,
    make_course_record,
    notify,
    parse_progress_text,
    write_legacy_outputs,
)


LOGIN_URL = "https://collprodss.colleague.upei.ca/Student/Account/Login"
PROGRESS_URL = "https://collprodss.colleague.upei.ca/Student/Planning/Programs/MyProgress"
GRADES_URL = "https://collprodss.colleague.upei.ca/Student/Student/Grades"


def scrape_academic_record(
    username: str,
    password: str,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Retrieve profile and grades directly with Safari, returning in-memory data."""
    driver = webdriver.Safari()
    try:
        notify(progress_callback, "connecting")
        driver.get(LOGIN_URL)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "UserName")))
        username_input = driver.find_element(By.ID, "UserName")
        password_input = driver.find_element(By.ID, "Password")
        username_input.clear()
        password_input.clear()
        username_input.send_keys(username)
        password_input.send_keys(password)
        login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
        driver.execute_script("arguments[0].click();", login_button)
        time.sleep(1.5)

        driver.get(PROGRESS_URL)
        progress_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(@id, 'programs-ataglance')]/div[2]/div[1]")
            )
        )
        notify(progress_callback, "signed_in")
        profile = parse_progress_text(progress_element.text)
        notify(progress_callback, "profile_loaded")

        driver.get(GRADES_URL)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']"))
        )
        time.sleep(2)

        name_label = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Student Name:')]"))
        )
        id_label = driver.find_element(By.XPATH, "//*[contains(text(),'Student ID:')]")
        profile["name"] = name_label.find_element(By.XPATH, "..").text.split(":", 1)[1].strip()
        profile["student_id"] = id_label.find_element(By.XPATH, "..").text.split(":", 1)[1].strip()

        for checkbox in driver.find_elements(By.XPATH, "//input[@type='checkbox']"):
            try:
                if not checkbox.is_selected():
                    driver.execute_script("arguments[0].click();", checkbox)
            except StaleElementReferenceException:
                continue

        print_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "print-grades-link"))
        )
        driver.execute_script("arguments[0].click();", print_button)
        time.sleep(1)

        courses: list[dict[str, Any]] = []
        rows = driver.find_elements(
            By.XPATH, "//table[contains(@class, 'student-grade-table')]/tbody/tr"
        )
        for row in rows:
            columns = row.find_elements(By.TAG_NAME, "td")
            if len(columns) < 4:
                continue
            section = " ".join(columns[0].text.split())
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", section)
            if not date_match:
                continue
            courses.append(
                make_course_record(
                    section=section,
                    name=" ".join(columns[1].text.split()),
                    credit_text=" ".join(columns[2].text.split()),
                    grade=" ".join(columns[3].text.split()),
                    start_date=date_match.group(0),
                )
            )
        notify(progress_callback, "grades_loaded")
        return {"student": profile, "courses": courses}
    finally:
        driver.quit()


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python grades_extractor_safari.py <username> <password>")
        return 2
    scraped = scrape_academic_record(sys.argv[1], sys.argv[2])
    write_legacy_outputs(scraped)
    print("Student information and grades were retrieved successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
