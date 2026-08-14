"""Safe, cached retrieval of structured scholarship data from official UPEI pages."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
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
            record = self._record_from_fields(fallback, fallback["source_url"])
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
        combined["application_url"] = links.get("Application Form")
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
        return ScholarshipRecord(
            id=str(fields.get("id") or _award_id(source_url)),
            name=name,
            amount=_money(str(fields.get("Maximum Amount") or fields.get("amount") or "")),
            deadline=_clean_text(str(fields.get("Deadline") or fields.get("deadline") or "")) or None,
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
            source_url=source_url,
            source_title=str(fields.get("source_title") or f"UPEI Scholarships & Awards — {name}"),
        )

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
        text = f"{status or ''} {description}".casefold()
        labels = {
            "1st": ["first", "1st"],
            "2nd": ["second", "2nd"],
            "3rd": ["third", "3rd"],
            "4th": ["fourth", "4th"],
        }
        return [
            f"Current {label} Year"
            for label, terms in labels.items()
            if any(
                re.search(rf"\b{term}\b(?=[^.!?]{{0,30}}\byear\b)", text)
                for term in terms
            )
        ]

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
        if year_of_study and any(term in text for term in (f"{year_of_study}rd year", f"{year_of_study}th year", f"{year_of_study}nd year", f"{year_of_study}st year")):
            score += 3
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
