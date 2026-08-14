"""Chrome scraper for UPEI academic data.

The web backend imports :func:`scrape_academic_record` directly, so credentials
stay in process memory and are never placed in subprocess arguments or files.
The command-line entry point remains for the historical workflow.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
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
    """Retrieve profile and grade data without persisting credentials or records."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(service=Service(), options=chrome_options)
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
        try:
            submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
            driver.execute_script("arguments[0].click();", submit_button)
        except Exception:
            password_input.submit()
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
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "print-grade-label")))
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "print-grade-label"))
        ).click()

        term_list = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "student-terms-ul"))
        )
        for label in term_list.find_elements(By.TAG_NAME, "label"):
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", label)
                driver.execute_script("arguments[0].click();", label)
            except Exception:
                continue

        original_handles = driver.window_handles
        final_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[@id='print-grades']/div[1]/div[3]/div[2]/button")
            )
        )
        final_button.click()
        WebDriverWait(driver, 10).until(
            lambda current_driver: len(current_driver.window_handles) > len(original_handles)
        )
        new_handle = next(handle for handle in driver.window_handles if handle not in original_handles)
        driver.switch_to.window(new_handle)
        time.sleep(1)

        profile["name"] = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[@id='student-grades']//span[text()='Student Name:']/following-sibling::span",
                )
            )
        ).text.strip()
        profile["student_id"] = driver.find_element(
            By.XPATH,
            "//*[@id='student-grades']//span[text()='Student ID:']/following-sibling::span",
        ).text.strip()

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//table[contains(@class,'student-grade-table')]")
            )
        )
        courses: list[dict[str, Any]] = []
        rows = driver.find_elements(
            By.XPATH, "//table[contains(@class,'student-grade-table')]/tbody/tr"
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
        print("Usage: python grades_extractor_chrome.py <username> <password>")
        return 2
    scraped = scrape_academic_record(sys.argv[1], sys.argv[2])
    write_legacy_outputs(scraped)
    print("Student information and grades were retrieved successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
