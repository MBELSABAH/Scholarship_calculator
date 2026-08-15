"""Safe, cached retrieval of structured scholarship data from official UPEI pages."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from backend.scholarship_models import (
    ScholarshipRecord,
    ScholarshipSearchResult,
    ScholarshipSource,
    DeadlineConflict,
    DeadlineOccurrence,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_SCHOLARSHIPS_PATH = PROJECT_ROOT / "demo_data" / "scholarships.json"
DIRECTORY_URL = "https://www.upei.ca/scholarships-and-awards/displayscholarships"
ALLOWED_SCHOLARSHIP_HOSTS = {
    "upei.ca",
    "www.upei.ca",
    "secure.upei.ca",
    "calendar.upei.ca",
    "app.upei.ca",
}
MAX_RESPONSE_BYTES = 2_000_000
MAX_RESULTS = 8

MONTHS = {
    name.casefold(): index
    for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
        start=1,
    )
}
MONTHS.update({key[:3]: value for key, value in list(MONTHS.items())})
DEADLINE_PRIORITY = {
    "individual_award_page": 1,
    "application_page": 2,
    "application_form": 2,
    "upei_directory": 3,
    "award_cycle_page": 4,
    "fall_award_cycle_group": 5,
    "winter_award_cycle_group": 5,
}


class ScholarshipResearchError(RuntimeError):
    """A safe public-web retrieval or parsing failure."""


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _money(value: str | None) -> float | None:
    match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", value or "")
    return float(match.group(0).replace(",", "")) if match else None


def _award_id(url: str) -> str:
    return (parse_qs(urlparse(url).query).get("awardid") or [""])[0]


def _month_number(value: str) -> int | None:
    return MONTHS.get(value.strip().casefold()) or MONTHS.get(value.strip().casefold()[:3])


def parse_deadline_text(
    text: str | None,
    *,
    source: str,
    source_url: str | None,
    confidence: str = "high",
) -> list[DeadlineOccurrence]:
    """Parse explicit UPEI deadline wording without inventing a day."""
    raw = _clean_text(text)
    if not raw:
        return []
    found: list[DeadlineOccurrence] = []
    month_pattern = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    # Put two-digit alternatives first so ``30`` is not truncated to ``3``.
    day_pattern = r"(?:3[01]|[12][0-9]|0?[1-9])(?:st|nd|rd|th)?(?!\d)"
    patterns = (
        re.compile(rf"(?P<day>{day_pattern})\s*[- ]\s*(?P<month>{month_pattern})(?:[ ,/-]+(?P<year>20\d{{2}}))?", re.I),
        re.compile(rf"(?P<month>{month_pattern})\s*[- ]\s*(?P<day>{day_pattern})(?:,?\s*(?P<year>20\d{{2}}))?", re.I),
    )
    spans: set[tuple[int, int]] = set()
    for pattern in patterns:
        for match in pattern.finditer(raw):
            month = _month_number(match.group("month"))
            day = int(re.sub(r"\D", "", match.group("day")))
            year = int(match.group("year")) if match.group("year") else None
            if not month or (match.start(), match.end()) in spans:
                continue
            spans.add((match.start(), match.end()))
            display_month = datetime(2000, month, 1).strftime("%B")
            display = f"{display_month} {day}" + (f", {year}" if year else "")
            found.append(
                DeadlineOccurrence(
                    month=month,
                    day=day,
                    year=year,
                    display=display,
                    precision="exact" if year else "month_day",
                    source=source,
                    source_url=source_url,
                    confidence=confidence if confidence in {"high", "medium"} else "unknown",
                    recurring=year is None,
                )
            )
    if found:
        return found
    month_only = re.findall(rf"\b({month_pattern})\b", raw, re.I)
    for month_text in month_only:
        month = _month_number(month_text)
        if month:
            display = datetime(2000, month, 1).strftime("%B")
            found.append(
                DeadlineOccurrence(
                    month=month,
                    display=display,
                    precision="month",
                    source=source,
                    source_url=source_url,
                    confidence="medium" if confidence != "unknown" else "unknown",
                    recurring=True,
                )
            )
    return found


def resolve_deadlines(
    sources: list[tuple[str | None, str, str | None, str]], *, today: date | None = None
) -> dict[str, Any]:
    """Resolve source priority, conflicts, and the next recurring deadline."""
    parsed: list[DeadlineOccurrence] = []
    source_values: list[tuple[str, str, str | None]] = []
    for raw, source, source_url, confidence in sources:
        occurrences = parse_deadline_text(raw, source=source, source_url=source_url, confidence=confidence)
        parsed.extend(occurrences)
        if raw and occurrences:
            source_values.append((_clean_text(raw), source, source_url))
    if not parsed:
        return {
            "deadline": None,
            "deadline_display": "Not found",
            "deadline_precision": "unknown",
            "deadline_source": None,
            "deadline_source_url": None,
            "deadline_confidence": "unknown",
            "deadline_month": None,
            "deadline_day": None,
            "deadlines": [],
            "next_deadline": None,
            "next_deadline_display": None,
            "deadline_conflict": False,
            "other_deadlines": [],
        }
    highest = min(DEADLINE_PRIORITY.get(item.source or "", 99) for item in parsed)
    selected = [item for item in parsed if DEADLINE_PRIORITY.get(item.source or "", 99) == highest]
    primary = selected[0]
    unique_values = {(item.month, item.day, item.year, item.precision) for item in parsed}
    other = [
        DeadlineConflict(value=value, source=source, source_url=url)
        for value, source, url in source_values
        if source != primary.source and value != primary.display
    ]
    today = today or date.today()
    upcoming: list[tuple[date, DeadlineOccurrence, str]] = []
    for item in selected:
        if item.month is None:
            continue
        if item.year:
            try:
                candidate = date(item.year, item.month, item.day or 1)
            except ValueError:
                continue
            display = item.display
        else:
            candidate_year = today.year
            try:
                candidate = date(candidate_year, item.month, item.day or 1)
            except ValueError:
                continue
            if candidate < today:
                try:
                    candidate = date(candidate_year + 1, item.month, item.day or 1)
                except ValueError:
                    continue
            display = f"{datetime(candidate.year, item.month, 1).strftime('%B')} {item.day or ''}".strip() + f", {candidate.year}"
        if candidate >= today:
            upcoming.append((candidate, item, display))
    upcoming.sort(key=lambda item: item[0])
    next_item = upcoming[0] if upcoming else None
    recurring = primary.recurring
    return {
        "deadline": date(primary.year, primary.month, primary.day or 1).isoformat() if primary.year and primary.month else None,
        "deadline_display": primary.display,
        "deadline_precision": primary.precision,
        "deadline_source": primary.source,
        "deadline_source_url": primary.source_url,
        "deadline_confidence": primary.confidence,
        "deadline_month": primary.month,
        "deadline_day": primary.day,
        "deadlines": parsed if recurring or len(parsed) > 1 else selected,
        "next_deadline": next_item[0].isoformat() if next_item else None,
        "next_deadline_display": next_item[2] if next_item else None,
        "deadline_conflict": len(unique_values) > len({(item.month, item.day, item.year, item.precision) for item in selected}),
        "other_deadlines": other,
    }


class SafeUPEIWebClient:
    """HTTPS-only text fetcher with redirect, host, timeout, and size controls."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SCHOLARSHIP_HOSTS:
            raise ScholarshipResearchError("Scholarship research is restricted to official UPEI HTTPS pages.")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ScholarshipResearchError("The scholarship source URL is not allowed.") from exc
        if parsed.username or parsed.password or port:
            raise ScholarshipResearchError("The scholarship source URL is not allowed.")

    def fetch_html(self, url: str) -> str:
        current_url = url
        headers = {"User-Agent": "AcademicCopilot/1.0 scholarship-research"}
        timeout = httpx.Timeout(self.timeout_seconds)
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            for _ in range(5):
                self.validate_url(current_url)
                try:
                    with client.stream("GET", current_url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise ScholarshipResearchError("The UPEI source returned an invalid redirect.")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").lower()
                        if "html" not in content_type:
                            raise ScholarshipResearchError("The UPEI source was not an HTML page.")
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_RESPONSE_BYTES:
                                raise ScholarshipResearchError("The UPEI source exceeded the safe size limit.")
                            chunks.append(chunk)
                        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                except httpx.TimeoutException as exc:
                    raise ScholarshipResearchError("The UPEI scholarship source took too long to respond.") from exc
                except httpx.HTTPError as exc:
                    raise ScholarshipResearchError("The UPEI scholarship source is temporarily unavailable.") from exc
        raise ScholarshipResearchError("The UPEI source redirected too many times.")


class ScholarshipDiscoveryService:
    def __init__(self, web_client: SafeUPEIWebClient | None = None) -> None:
        self.web_client = web_client or SafeUPEIWebClient()
        self._directory_records: list[dict[str, Any]] | None = None
        self._details: dict[str, ScholarshipRecord] = {}
        self._last_search: ScholarshipSearchResult | None = None
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._directory_records = None
            self._details.clear()
            self._last_search = None

    def cached_search(self) -> ScholarshipSearchResult | None:
        with self._lock:
            if self._last_search is None:
                return None
            data = _model_dump(self._last_search)
        if data["source_mode"] == "live":
            data["source_mode"] = "cached"
        return ScholarshipSearchResult(**data)

    def search(
        self,
        *,
        faculty: str | None = None,
        major: str | None = None,
        year_of_study: int | None = None,
        keyword: str | None = None,
        refresh: bool = False,
    ) -> ScholarshipSearchResult:
        if refresh:
            self.clear()
        try:
            directory, was_cached = self._get_directory()
            ranked = sorted(
                directory,
                key=lambda item: self._directory_score(
                    item,
                    faculty=faculty,
                    major=major,
                    year_of_study=year_of_study,
                    keyword=keyword,
                ),
                reverse=True,
            )
            if keyword:
                keyword_folded = keyword.casefold()
                matching = [item for item in ranked if keyword_folded in item["search_text"]]
                ranked = matching or ranked
            selected = ranked[:MAX_RESULTS]
            scholarships = [self._get_detail(item) for item in selected]
            retrieved_at = datetime.now(UTC).isoformat()
            result = ScholarshipSearchResult(
                scholarships=scholarships,
                source_mode="cached" if was_cached else "live",
                sources=[
                    ScholarshipSource(
                        title="UPEI Scholarships and Awards Directory",
                        url=DIRECTORY_URL,
                        retrieved_at=retrieved_at,
                    )
                ],
            )
        except ScholarshipResearchError as exc:
            result = self._load_demo_fallback(str(exc))
        with self._lock:
            self._last_search = result
        return result

    def inspect(self, scholarship_id: str) -> ScholarshipRecord:
        with self._lock:
            cached = self._details.get(scholarship_id)
        if cached is not None:
            return cached
        cached_search = self.cached_search()
        if cached_search:
            for scholarship in cached_search.scholarships:
                if scholarship.id == scholarship_id:
                    return scholarship
        if not scholarship_id.isdigit():
            raise ScholarshipResearchError("That scholarship is not available in the current session.")
        source_url = f"https://www.upei.ca/scholarships-and-awards/display?awardid={scholarship_id}"
        html = self.web_client.fetch_html(source_url)
        record = self.parse_detail_html(html, source_url, fallback={"id": scholarship_id})
        with self._lock:
            self._details[record.id] = record
        return record

    def inspect_application_fields(self, scholarship: ScholarshipRecord) -> tuple[str, list[dict[str, Any]]]:
        if scholarship.application_url:
            try:
                html = self.web_client.fetch_html(scholarship.application_url)
                parsed = self.parse_form_html(html)
                if parsed:
                    return "official_form", parsed
            except ScholarshipResearchError:
                pass
            return "unavailable", []
        fields = self._criteria_fields(scholarship)
        return ("criteria_based_preview" if fields else "unavailable"), fields

    def _get_directory(self) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            cached = self._directory_records
        if cached is not None:
            return cached, True
        html = self.web_client.fetch_html(DIRECTORY_URL)
        records = self.parse_directory_html(html)
        if not records:
            raise ScholarshipResearchError("No scholarship records were found on the UPEI directory.")
        with self._lock:
            self._directory_records = records
        return records, False

    def _get_detail(self, fallback: dict[str, Any]) -> ScholarshipRecord:
        scholarship_id = fallback["id"]
        with self._lock:
            cached = self._details.get(scholarship_id)
        if cached is not None:
            return cached
        try:
            html = self.web_client.fetch_html(fallback["source_url"])
            record = self.parse_detail_html(html, fallback["source_url"], fallback=fallback)
        except ScholarshipResearchError:
            record = self._record_from_fields(
                {**fallback, "detail_status": "source_only"},
                fallback["source_url"],
            )
        if record.application_url:
            record = self._enrich_application_metadata(record)
        with self._lock:
            self._details[scholarship_id] = record
        return record

    @staticmethod
    def parse_directory_html(html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        records: list[dict[str, Any]] = []
        for row in soup.select(".scholarshipcompletelist .views-row"):
            link = row.select_one(".scholarshipname a[href]")
            if link is None:
                continue
            source_url = urljoin(DIRECTORY_URL, str(link.get("href")))
            scholarship_id = _award_id(source_url)
            if not scholarship_id:
                continue
            description = _clean_text(
                row.select_one(".scholarshipdescription").get_text(" ", strip=True)
                if row.select_one(".scholarshipdescription")
                else ""
            )
            amount_node = row.select_one(".valuemaxamount")
            deadline_node = row.select_one(".valuedeadline")
            name = _clean_text(link.get_text(" ", strip=True))
            row_text = _clean_text(row.get_text(" ", strip=True))
            records.append(
                {
                    "id": scholarship_id,
                    "name": name,
                    "description": description,
                    "amount": _money(amount_node.get_text(" ", strip=True) if amount_node else None),
                    "deadline": _clean_text(deadline_node.get_text(" ", strip=True)) or None
                    if deadline_node
                    else None,
                    "_deadline_source": "upei_directory",
                    "source_url": source_url,
                    "source_title": f"UPEI Scholarships & Awards — {name}",
                    "search_text": f"{name} {description} {row_text}".casefold(),
                }
            )
        return records

    @classmethod
    def parse_detail_html(
        cls, html: str, source_url: str, *, fallback: dict[str, Any]
    ) -> ScholarshipRecord:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        container = soup.select_one("#block-adminimal-upei-upeischolarshipdisplay .fullscholarship")
        if container is None:
            raise ScholarshipResearchError("The UPEI scholarship detail page could not be parsed.")
        heading = container.select_one("th")
        fields: dict[str, str] = {}
        links: dict[str, str] = {}
        for row in container.select("tr"):
            label = row.select_one(".label")
            value = row.select_one(".value")
            if label is None or value is None:
                continue
            key = _clean_text(label.get_text(" ", strip=True)).rstrip(":")
            fields[key] = _clean_text(value.get_text(" ", strip=True))
            link = value.select_one("a[href]")
            if link:
                links[key] = urljoin(source_url, str(link.get("href")))
        combined = {**fallback, **fields}
        combined["name"] = _clean_text(heading.get_text(" ", strip=True)) if heading else fallback.get("name")
        combined["application_url"] = (
            links.get("Application Form")
            or links.get("Application")
            or links.get("Apply")
            or fallback.get("application_url")
        )
        combined["detail_status"] = "extracted"
        return cls._record_from_fields(combined, source_url)

    @staticmethod
    def parse_form_html(html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        fields: list[dict[str, Any]] = []
        candidate_forms = []
        for form in soup.select("form"):
            signature = " ".join(
                str(value or "")
                for value in (
                    form.get("id"),
                    form.get("class"),
                    form.get("action"),
                    form.get("aria-label"),
                )
            ).casefold()
            controls = form.select("input, textarea, select")
            has_application_shape = bool(form.select("textarea, input[type='file']")) or len(controls) >= 3
            is_application_form = bool(re.search(r"award|scholarship|application", signature))
            if is_application_form or has_application_shape:
                candidate_forms.append(form)
        for index, control in enumerate(
            control for form in candidate_forms for control in form.select("input, textarea, select")
        ):
            control_type = str(control.get("type") or control.name or "text").lower()
            if control_type in {"hidden", "submit", "button", "reset", "image", "password"}:
                continue
            control_id = str(control.get("id") or control.get("name") or f"field_{index}")
            label_node = soup.find("label", attrs={"for": control.get("id")}) if control.get("id") else None
            label = _clean_text(label_node.get_text(" ", strip=True) if label_node else control.get("aria-label") or control_id)
            if re.search(r"\b(?:username|password|sign in|log in|login)\b", label, re.IGNORECASE):
                continue
            mapped_type = "textarea" if control.name == "textarea" else "select" if control.name == "select" else "file" if control_type == "file" else "boolean" if control_type in {"checkbox", "radio"} else "number" if control_type == "number" else "text"
            options = [_clean_text(option.get_text(" ", strip=True)) for option in control.select("option") if _clean_text(option.get_text(" ", strip=True))]
            fields.append(
                {
                    "field_id": re.sub(r"[^a-z0-9_]+", "_", control_id.casefold()).strip("_"),
                    "label": label,
                    "type": mapped_type,
                    "required": control.has_attr("required") or "required" in label.casefold(),
                    "max_length": int(control.get("maxlength")) if str(control.get("maxlength") or "").isdigit() else None,
                    "options": options,
                    "known_answer": None,
                    "sensitive": ScholarshipDiscoveryService._is_sensitive(label),
                    "essay": mapped_type == "textarea",
                    "source": "official_form",
                }
            )
        return fields[:50]

    @classmethod
    def _record_from_fields(cls, fields: dict[str, Any], source_url: str) -> ScholarshipRecord:
        name = _clean_text(str(fields.get("name") or fields.get("Name") or "UPEI Scholarship"))
        description = _clean_text(str(fields.get("Description") or fields.get("description") or ""))
        full_text = f"{name} {description}".casefold()
        application_url = fields.get("application_url")
        if application_url:
            SafeUPEIWebClient.validate_url(str(application_url))
        academic_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", description)
            if re.search(r"academic|average|grade|standing|course load", sentence, re.IGNORECASE)
        ]
        minimum_average_match = re.search(
            r"(?:at least|minimum(?: of)?|average of)\s*([0-9]{2,3})(?:\s*%)?",
            full_text,
        )
        citizenship_sentence = next(
            (
                sentence.strip()
                for sentence in re.split(r"(?<=[.!?])\s+", description)
                if re.search(r"citizen|resident|international|refugee|province|island", sentence, re.IGNORECASE)
            ),
            None,
        )
        deadline_sources: list[tuple[str | None, str, str | None, str]] = []
        detail_deadline = fields.get("Deadline") or fields.get("Application Deadline") or fields.get("Closing Date") or fields.get("Due Date")
        if detail_deadline:
            deadline_sources.append((str(detail_deadline), "individual_award_page", source_url, "high"))
        if fields.get("deadline"):
            deadline_sources.append((str(fields["deadline"]), str(fields.get("_deadline_source") or "upei_directory"), source_url, "high"))
        cycle_deadline = fields.get("cycle_deadline") or fields.get("award_cycle_deadline")
        if cycle_deadline:
            deadline_sources.append((str(cycle_deadline), str(fields.get("_cycle_source") or "award_cycle_page"), str(fields.get("cycle_url") or source_url), "medium"))
        deadline_info = resolve_deadlines(deadline_sources)
        email_matches = re.findall(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", f"{description} {full_text}", re.I)
        submission_email = str(fields.get("submission_email") or (email_matches[0] if email_matches else "")) or None
        required_documents = cls._infer_required_documents(full_text)
        submission_method = str(fields.get("submission_method") or "unknown")
        if submission_method not in {"portal", "email", "external_form", "unknown"}:
            submission_method = "unknown"
        if submission_email:
            submission_method = "email"
        elif application_url:
            submission_method = "external_form"
        application_status = cls._infer_application_status(
            fields.get("application_status") or fields.get("cycle_status") or description
        )
        return ScholarshipRecord(
            id=str(fields.get("id") or _award_id(source_url)),
            name=name,
            amount=_money(str(fields.get("Maximum Amount") or fields.get("amount") or "")),
            **deadline_info,
            description=description,
            faculty=cls._list_field(fields.get("Faculty") or fields.get("faculty")),
            major=cls._infer_majors(full_text),
            year_of_study=cls._infer_years(fields.get("Status"), f"{name}. {description}"),
            academic_requirements=" ".join(academic_sentences) or None,
            minimum_average=float(minimum_average_match.group(1)) if minimum_average_match else None,
            financial_need_required=True if "financial need" in full_text else None,
            citizenship_or_residency_requirements=citizenship_sentence,
            personal_statement_required=True if re.search(r"personal statement|essay", full_text) else None,
            reference_required=True if re.search(r"reference letter|letter of reference|references? required", full_text) else None,
            application_required=True if application_url else None,
            application_url=str(application_url) if application_url else None,
            submission_method=submission_method,
            submission_email=submission_email,
            required_documents=required_documents,
            application_status=application_status,
            source_url=source_url,
            source_title=str(fields.get("source_title") or f"UPEI Scholarships & Awards — {name}"),
            detail_status=str(fields.get("detail_status") or "extracted"),
        )

    def _enrich_application_metadata(self, scholarship: ScholarshipRecord) -> ScholarshipRecord:
        try:
            html = self.web_client.fetch_html(str(scholarship.application_url))
        except ScholarshipResearchError:
            return scholarship
        text = _clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        emails = re.findall(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)
        deadline_sources = []
        if scholarship.deadline_display:
            deadline_sources.append((scholarship.deadline_display, scholarship.deadline_source or "individual_award_page", scholarship.deadline_source_url or scholarship.source_url, scholarship.deadline_confidence))
        application_deadline_text = " ".join(
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if re.search(r"deadline|closing date|due date|applications? due|submit by", sentence, re.I)
        )
        if application_deadline_text:
            deadline_sources.append((application_deadline_text, "application_page", scholarship.application_url, "high"))
        deadline_info = resolve_deadlines(deadline_sources)
        updates = {**deadline_info}
        if emails:
            updates.update({"submission_email": emails[0], "submission_method": "email"})
        updates["required_documents"] = sorted(set(scholarship.required_documents + self._infer_required_documents(text)))
        inferred_status = self._infer_application_status(text)
        updates["application_status"] = inferred_status if inferred_status != "unknown" else scholarship.application_status
        if hasattr(scholarship, "model_copy"):
            return scholarship.model_copy(update=updates)
        return scholarship.copy(update=updates)

    @staticmethod
    def _infer_required_documents(text: str) -> list[str]:
        labels = (
            (r"personal statement|essay", "Personal statement"),
            (r"reference letter|letter of reference|references? required", "Reference letter"),
            (r"financial need form|financial need statement", "Financial need form"),
            (r"official transcript|transcript", "Official transcript"),
            (r"supporting document|supporting documentation", "Supporting documents"),
        )
        return [label for pattern, label in labels if re.search(pattern, text, re.I)]

    @staticmethod
    def _infer_application_status(value: Any) -> str:
        text = _clean_text(str(value or "")).casefold()
        if not text:
            return "unknown"
        if re.search(r"\bclosed\b|not currently accepting|no longer accepting", text):
            return "closed"
        if re.search(r"\bupcoming\b|opens? soon|opens? on|will open", text):
            return "upcoming"
        if re.search(r"open for applications|accepting applications|applications? are being accepted|applications? open", text):
            return "open"
        return "unknown"

    @staticmethod
    def _list_field(value: Any) -> list[str]:
        if isinstance(value, list):
            return [_clean_text(str(item)) for item in value if _clean_text(str(item))]
        return [item for item in (_clean_text(part) for part in re.split(r"[,;/]", str(value or ""))) if item]

    @staticmethod
    def _infer_majors(text: str) -> list[str]:
        aliases = {
            "Computer Science": ["computer science", "computing"],
            "Mathematics": ["mathematics", "math major"],
            "Statistics": ["statistics major"],
            "Actuarial Science": ["actuarial science"],
            "Data Analytics": ["data analytics"],
            "Business Analytics": ["business analytics"],
            "Engineering": ["engineering"],
            "Nursing": ["nursing"],
            "Music": ["music program"],
        }
        return [major for major, terms in aliases.items() if any(term in text for term in terms)]

    @staticmethod
    def _infer_years(status: Any, description: str) -> list[str]:
        status_text = str(status or "").casefold()
        description_text = description.casefold()
        text = f"{status_text} {description_text}"
        labels = {
            "1st": ["first", "1st", "1"],
            "2nd": ["second", "2nd", "2"],
            "3rd": ["third", "3rd", "3"],
            "4th": ["fourth", "4th", "4"],
        }
        inferred: list[str] = []
        description_sentences = re.split(r"(?<=[.!?])\s+", description_text)
        for label, terms in labels.items():
            status_matches = any(
                re.search(rf"\b{term}\b(?=[^.!?]{{0,35}}\byears?\b)", status_text)
                or re.search(rf"\byears?\b[^.!?]{{0,35}}\b{term}\b", status_text)
                for term in terms
            )
            if status_matches:
                timing = "Entering" if "entering" in status_text else "Current"
                inferred.append(f"{timing} {label} Year")
            matching_sentences = [
                sentence
                for sentence in description_sentences
                if any(
                    re.search(rf"\b{term}\b(?=[^.!?]{{0,35}}\byears?\b)", sentence)
                    or re.search(rf"\byears?\b[^.!?]{{0,35}}\b{term}\b", sentence)
                    for term in terms
                )
            ]
            if not matching_sentences:
                continue
            timing = "Entering" if any("entering" in sentence for sentence in matching_sentences) else "Current"
            item = f"{timing} {label} Year"
            if item not in inferred:
                inferred.append(item)
        if re.search(r"\bupper[- ]year\b", text) and not inferred:
            inferred.append("Upper Year")
        return inferred

    @staticmethod
    def _is_sensitive(label: str) -> bool:
        return bool(re.search(r"income|financial need|citizen|residen|disab|indigenous|country|family", label, re.IGNORECASE))

    @classmethod
    def _criteria_fields(cls, scholarship: ScholarshipRecord) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        description = scholarship.description.casefold()
        if scholarship.financial_need_required:
            fields.append({"field_id": "financial_need", "label": "Does financial need apply to your situation?", "type": "boolean", "required": True, "known_answer": None, "sensitive": True, "essay": False, "source": "official_criteria"})
        if scholarship.citizenship_or_residency_requirements:
            fields.append({"field_id": "citizenship_status", "label": "Citizenship or residency status", "type": "text", "required": True, "known_answer": None, "sensitive": True, "essay": False, "source": "official_criteria"})
        if scholarship.personal_statement_required:
            fields.append({"field_id": "personal_statement", "label": "Personal statement", "type": "textarea", "required": True, "max_length": 3000, "known_answer": None, "sensitive": False, "essay": True, "source": "official_criteria"})
        if scholarship.reference_required:
            fields.append({"field_id": "reference", "label": "Reference", "type": "text", "required": True, "known_answer": None, "sensitive": False, "essay": False, "source": "official_criteria"})
        personal_fields = [
            (r"\b(?:woman|women|female)\b", "gender_identity_criterion", "Does the published women/female identity criterion apply to you?", "boolean"),
            (r"\b(?:indigenous|mi['’]?kmaq|first nations|inuit|m[eé]tis)\b", "indigenous_identity", "Does the published Indigenous identity criterion apply to you?", "boolean"),
            (r"\bdisabilit(?:y|ies)\b", "disability_status", "Does the published disability criterion apply to you?", "boolean"),
            (r"\bpei high school|prince edward island high school\b", "pei_high_school_graduate", "Did you graduate from a PEI high school?", "boolean"),
            (r"\bco-?op\b", "co_op_terms_completed", "How many co-op work terms have you completed?", "number"),
        ]
        existing = {field["field_id"] for field in fields}
        for pattern, field_id, label, field_type in personal_fields:
            if field_id not in existing and re.search(pattern, description, re.IGNORECASE):
                criterion_sentence = next(
                    (
                        sentence
                        for sentence in re.split(r"(?<=[.!?])\s+", description)
                        if re.search(pattern, sentence, re.IGNORECASE)
                    ),
                    description,
                )
                is_preference = bool(re.search(r"\bprefer(?:ence|red|ably)?\b", criterion_sentence))
                fields.append({"field_id": field_id, "label": label, "type": field_type, "required": not is_preference, "known_answer": None, "sensitive": True, "essay": False, "source": "official_criteria"})
        return fields

    @staticmethod
    def _directory_score(item: dict[str, Any], *, faculty: str | None, major: str | None, year_of_study: int | None, keyword: str | None) -> float:
        text = item["search_text"]
        score = 0.0
        if major:
            major_terms = [major.casefold()]
            if "computer science" in major.casefold():
                major_terms.extend(["mathematical and computational sciences", "smcs", "computing"])
            score += 8 if any(term in text for term in major_terms) else 0
        if faculty:
            faculty_terms = [term for term in re.split(r"\W+", faculty.casefold()) if len(term) > 4]
            score += min(4, sum(term in text for term in faculty_terms))
        if year_of_study:
            word_years = {1: "first", 2: "second", 3: "third", 4: "fourth"}
            ordinal_terms = tuple(
                f"{year_of_study}{suffix} year" for suffix in ("st", "nd", "rd", "th")
            )
            word = word_years.get(year_of_study, "")
            if any(term in text for term in ordinal_terms) or re.search(
                rf"\b{word}[- ]year\b|\byears?\b[^.!?]{{0,30}}\b(?:{year_of_study}|{word})\b",
                text,
            ):
                score += 3
            elif year_of_study >= 2 and re.search(r"\bupper[- ]year\b", text):
                score += 2
        if keyword and keyword.casefold() in text:
            score += 10
        if item.get("deadline"):
            score += 0.5
        return score

    @staticmethod
    def _load_demo_fallback(reason: str) -> ScholarshipSearchResult:
        with DEMO_SCHOLARSHIPS_PATH.open("r", encoding="utf-8") as fixture_file:
            fixture = json.load(fixture_file)
        return ScholarshipSearchResult(
            scholarships=[ScholarshipRecord(**item) for item in fixture["scholarships"]],
            source_mode="demo_fallback",
            warning=f"{fixture['warning']} Retrieval detail: {reason}",
            sources=[
                ScholarshipSource(
                    title="UPEI Scholarships and Awards",
                    url="https://www.upei.ca/scholarships-and-awards",
                )
            ],
        )
