import unittest

from backend.academic_service import build_academic_snapshot, load_demo_record
from backend.scholarship_agent import ScholarshipSession
from backend.scholarship_models import (
    ScholarshipRecord,
    ScholarshipSearchResult,
    ScholarshipSource,
)
from backend.scholarship_service import (
    DIRECTORY_URL,
    SafeUPEIWebClient,
    ScholarshipDiscoveryService,
    ScholarshipResearchError,
    parse_deadline_text,
    resolve_deadlines,
)
from datetime import date


class FakeWebClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch_html(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise ScholarshipResearchError("missing fixture page")
        return self.pages[url]


class StubDiscovery:
    def __init__(self, scholarship):
        self.scholarship = scholarship

    def inspect(self, scholarship_id):
        if scholarship_id != self.scholarship.id:
            raise ScholarshipResearchError("unknown test scholarship")
        return self.scholarship

    def inspect_application_fields(self, scholarship):
        return ScholarshipDiscoveryService._criteria_fields(scholarship) and (
            "criteria_based_preview",
            ScholarshipDiscoveryService._criteria_fields(scholarship),
        ) or ("unavailable", [])

    def clear(self):
        return None

    def search(self, **kwargs):
        self.last_search_kwargs = kwargs
        return ScholarshipSearchResult(
            scholarships=[self.scholarship],
            source_mode="demo_fallback",
            sources=[
                ScholarshipSource(
                    title="UPEI Scholarships and Awards",
                    url=self.scholarship.source_url,
                )
            ],
        )


def demo_scholarship(**overrides):
    values = {
        "id": "demo-test-award",
        "name": "Demo Computing Community Award",
        "amount": 2000,
        "deadline": "Demo only",
        "description": "A demo award for Computer Science students with financial need.",
        "faculty": ["School of Mathematical and Computational Sciences"],
        "major": ["Computer Science"],
        "year_of_study": ["Current 2nd Year"],
        "academic_requirements": "Good academic standing.",
        "minimum_average": 80,
        "financial_need_required": True,
        "citizenship_or_residency_requirements": None,
        "personal_statement_required": True,
        "reference_required": False,
        "application_required": True,
        "application_url": None,
        "source_url": "https://www.upei.ca/scholarships-and-awards",
        "source_title": "Demo fixture — not a current UPEI award",
        "is_demo": True,
    }
    values.update(overrides)
    return ScholarshipRecord(**values)


class ScholarshipDiscoveryTests(unittest.TestCase):
    def test_url_allow_list_rejects_nonofficial_and_credential_urls(self):
        SafeUPEIWebClient.validate_url("https://www.upei.ca/scholarships-and-awards")
        for url in (
            "http://www.upei.ca/scholarships-and-awards",
            "https://example.com/upei",
            "https://user:secret@www.upei.ca/award",
            "https://www.upei.ca:444/award",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ScholarshipResearchError):
                    SafeUPEIWebClient.validate_url(url)

    def test_directory_detail_parsing_and_session_cache(self):
        detail_url = "https://www.upei.ca/scholarships-and-awards/display?awardid=1144"
        directory_html = """
        <div class="scholarshipcompletelist"><div class="views-row">
          <div class="scholarshipname"><a href="/scholarships-and-awards/display?awardid=1144">Test Computing Award</a></div>
          <div class="scholarshipdescription">For Computer Science students with financial need.</div>
          <div class="valuemaxamount">$2,000</div><div class="valuedeadline">October 1</div>
        </div></div>
        """
        detail_html = """
        <div id="block-adminimal-upei-upeischolarshipdisplay"><div class="fullscholarship"><table>
          <tr><th>Test Computing Award</th></tr>
          <tr><td class="label">Maximum Amount:</td><td class="value">$2,000</td></tr>
          <tr><td class="label">Faculty:</td><td class="value">School of Mathematical and Computational Sciences</td></tr>
          <tr><td class="label">Deadline:</td><td class="value">October 1</td></tr>
          <tr><td class="label">Description:</td><td class="value">Awarded to Computer Science students with financial need and a minimum 80% average.</td></tr>
        </table></div></div>
        """
        web = FakeWebClient({DIRECTORY_URL: directory_html, detail_url: detail_html})
        service = ScholarshipDiscoveryService(web_client=web)
        first = service.search(major="Computer Science")
        second = service.search(major="Computer Science")

        self.assertEqual(first.source_mode, "live")
        self.assertEqual(second.source_mode, "cached")
        self.assertEqual(first.scholarships[0].id, "1144")
        self.assertEqual(first.scholarships[0].detail_status, "extracted")
        self.assertEqual(first.scholarships[0].source_url, detail_url)
        self.assertEqual(first.scholarships[0].minimum_average, 80)
        self.assertTrue(first.scholarships[0].financial_need_required)
        self.assertEqual(web.calls.count(DIRECTORY_URL), 1)
        self.assertEqual(web.calls.count(detail_url), 1)

    def test_unextractable_detail_preserves_specific_official_source(self):
        detail_url = "https://www.upei.ca/scholarships-and-awards/display?awardid=2048"
        directory_html = """
        <div class="scholarshipcompletelist"><div class="views-row">
          <div class="scholarshipname"><a href="/scholarships-and-awards/display?awardid=2048">Source Only Award</a></div>
          <div class="scholarshipdescription">Details are published on the official award page.</div>
          <div class="valuemaxamount">$1,500</div>
        </div></div>
        """
        unextractable_html = "<main><p>The page layout is not machine extractable.</p></main>"
        service = ScholarshipDiscoveryService(
            web_client=FakeWebClient(
                {DIRECTORY_URL: directory_html, detail_url: unextractable_html}
            )
        )

        scholarship = service.search().scholarships[0]

        self.assertEqual(scholarship.detail_status, "source_only")
        self.assertEqual(scholarship.source_url, detail_url)
        self.assertEqual(
            scholarship.source_title,
            "UPEI Scholarships & Awards — Source Only Award",
        )
        self.assertIsNone(scholarship.application_url)

    def test_form_parser_normalises_application_fields_and_ignores_login(self):
        html = """
        <form id="user-login"><label for="user">Username</label><input id="user">
          <label for="password">Password</label><input id="password" type="password"></form>
        <form id="scholarship-application">
          <label for="country">Country of origin (required)</label><input id="country" required>
          <label for="story">Community involvement</label><textarea id="story" maxlength="500" required></textarea>
          <label for="proof">Supporting document</label><input id="proof" type="file">
        </form>
        """
        fields = ScholarshipDiscoveryService.parse_form_html(html)
        self.assertEqual([field["field_id"] for field in fields], ["country", "story", "proof"])
        self.assertTrue(fields[0]["sensitive"])
        self.assertTrue(fields[1]["essay"])
        self.assertEqual(fields[1]["max_length"], 500)

    def test_year_parser_handles_compound_award_titles(self):
        years = ScholarshipDiscoveryService._infer_years(
            "Current students", "TD Bank Second, Third, or Fourth Year Scholarship"
        )
        self.assertEqual(
            years,
            ["Current 2nd Year", "Current 3rd Year", "Current 4th Year"],
        )

    def test_year_parser_preserves_entering_and_upper_year_language(self):
        self.assertEqual(
            ScholarshipDiscoveryService._infer_years(
                "Current students", "For students entering their fourth year."
            ),
            ["Entering 4th Year"],
        )
        self.assertEqual(
            ScholarshipDiscoveryService._infer_years(
                "Current students", "Awarded to an upper-year SMCS student."
            ),
            ["Upper Year"],
        )
        self.assertEqual(
            ScholarshipDiscoveryService._infer_years(
                "Current students", "Open to students in years 3 or 4."
            ),
            ["Current 3rd Year", "Current 4th Year"],
        )

    def test_deadline_parser_handles_recurring_multiple_formats(self):
        parsed = parse_deadline_text(
            "Oct-01 & Feb-01 each year",
            source="individual_award_page",
            source_url="https://www.upei.ca/award",
        )
        self.assertEqual([(item.month, item.day) for item in parsed], [(10, 1), (2, 1)])
        resolved = resolve_deadlines(
            [("Oct-01 & Feb-01 each year", "upei_directory", "https://www.upei.ca/award", "high")],
            today=date(2026, 8, 15),
        )
        self.assertIsNone(resolved["deadline"])
        self.assertEqual(resolved["deadline_display"], "October 1")
        self.assertEqual(resolved["next_deadline"], "2026-10-01")
        self.assertEqual(len(resolved["deadlines"]), 2)

    def test_unknown_deadline_is_not_claimed_as_no_deadline(self):
        resolved = resolve_deadlines([])
        self.assertIsNone(resolved["deadline"])
        self.assertEqual(resolved["deadline_display"], "Not found")
        self.assertEqual(resolved["deadline_precision"], "unknown")

    def test_cycle_month_and_status_are_kept_separate(self):
        record = ScholarshipDiscoveryService._record_from_fields(
            {
                "id": "cycle-award",
                "name": "Cycle award",
                "description": "Applications are closed until the beginning of Fall semester.",
                "cycle_deadline": "October",
                "_cycle_source": "fall_award_cycle_group",
                "cycle_status": "closed until Fall",
                "source_title": "UPEI cycle",
            },
            "https://www.upei.ca/scholarships-and-awards/display?awardid=cycle-award",
        )
        self.assertEqual(record.deadline_precision, "month")
        self.assertEqual(record.deadline_display, "October")
        self.assertEqual(record.application_status, "closed")

    def test_specific_deadline_has_high_confidence_and_wins_directory(self):
        resolved = resolve_deadlines(
            [
                ("October 1", "upei_directory", "https://www.upei.ca/directory", "high"),
                ("September 30, 2026", "application_form", "https://www.upei.ca/form", "high"),
            ],
            today=date(2026, 8, 15),
        )
        self.assertEqual(resolved["deadline"], "2026-09-30")
        self.assertEqual(resolved["deadline_source"], "application_form")
        self.assertTrue(resolved["deadline_conflict"])
        self.assertEqual(resolved["other_deadlines"][0].value, "October 1")


class ScholarshipSessionTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = build_academic_snapshot(load_demo_record(), source="demo")
        self.scholarship = demo_scholarship()
        self.session = ScholarshipSession(StubDiscovery(self.scholarship))
        self.search = ScholarshipSearchResult(
            scholarships=[self.scholarship],
            source_mode="demo_fallback",
            sources=[ScholarshipSource(title="UPEI Scholarships and Awards", url=self.scholarship.source_url)],
        )

    def test_unknown_sensitive_criterion_is_not_treated_as_eligibility(self):
        match = self.session.rank(self.search, self.snapshot)[0]
        self.assertEqual(match.match_level, "potential")
        self.assertIn("Financial need status must be confirmed by the student.", match.missing_information)
        self.assertNotIn("Student confirmed that financial need applies.", match.known_matches)

        self.session.save_background_answer("financial_need", True, confirmed=True)
        match = self.session.rank(self.search, self.snapshot)[0]
        self.assertEqual(match.match_level, "excellent")
        self.assertIn("Student confirmed that financial need applies.", match.known_matches)

    def test_gender_pending_question_keeps_official_context_and_resolves_male_answer(self):
        scholarship = demo_scholarship(
            financial_need_required=None,
            personal_statement_required=False,
            description="Awarded to a female student enrolled in Computer Science.",
        )
        search = ScholarshipSearchResult(scholarships=[scholarship], source_mode="demo_fallback", sources=[])
        self.session.rank(search, self.snapshot)
        pending = self.session.next_profile_question()
        self.assertEqual(pending["field"], "gender_identity_criterion")
        clarification = self.session.resolve_pending_question("which specific gender", self.snapshot)
        self.assertFalse(clarification["resolved"])
        self.assertEqual(clarification["message"], "The award specifies female students.")
        resolved = self.session.resolve_pending_question("I am male", self.snapshot)
        self.assertTrue(resolved["resolved"])
        self.assertFalse(self.session.get_background()["gender_identity_criterion"])
        self.assertIn("Unlikely Fit", resolved["message"])

    def test_background_confirmation_draft_review_and_submission_gate(self):
        state = self.session.open_application(self.scholarship.id, self.snapshot)
        self.assertEqual(state.next_action, "guided_application")
        self.assertEqual(
            state.next_question,
            "Does financial need apply to your situation?",
        )
        self.assertEqual(state.pending_background_field, "financial_need")
        with self.assertRaises(ValueError):
            self.session.save_background_answer("financial_need", True, confirmed=False)

        state = self.session.save_application_answer(
            state.application_id, "financial_need", True, user_approved=True
        )
        self.assertTrue(self.session.get_background()["financial_need"])
        draft = self.session.save_draft(
            state.application_id,
            "personal_statement",
            "I volunteer weekly at a community coding club.",
            "I volunteer weekly at a community coding club, helping learners build confidence.",
        )
        self.assertFalse(draft.user_approved)
        with self.assertRaises(ValueError):
            self.session.save_draft(
                state.application_id,
                "personal_statement",
                "I volunteer weekly at a community coding club.",
                "Seeing students gain confidence deepened my appreciation for teaching.",
            )
        preview = self.session.prepare_preview(state.application_id)
        self.assertFalse(preview.ready)
        self.assertTrue(any("not been explicitly reviewed" in warning for warning in preview.warnings))
        with self.assertRaises(ValueError):
            self.session.approve_and_submit(state.application_id, "looks good")

        self.session.save_application_answer(
            state.application_id,
            "personal_statement",
            draft.draft_text,
            user_approved=True,
        )
        preview = self.session.prepare_preview(state.application_id)
        self.assertTrue(preview.ready)
        self.assertTrue(preview.warnings)
        gated = self.session.submit_from_agent(state.application_id)
        self.assertEqual(gated["status"], "explicit_ui_approval_required")
        submitted = self.session.approve_and_submit(state.application_id, "APPROVE_AND_SUBMIT")
        self.assertTrue(submitted.approved_for_submission)
        self.assertTrue(submitted.submitted)
        self.assertEqual(submitted.submission_status, "demo_submission_recorded_no_external_action")

    def test_calculated_fourth_year_drives_search_and_year_matching(self):
        record = load_demo_record()
        record["student"] = {
            **record["student"],
            "faculty": "SMCS",
            "completed_credits": 102,
            "required_degree_credits": 120,
            "year_of_study": 1,
        }
        snapshot = build_academic_snapshot(record, source="demo")
        scholarships = [
            demo_scholarship(
                id="year-four",
                year_of_study=["Current 4th Year"],
                financial_need_required=None,
                personal_statement_required=False,
            ),
            demo_scholarship(
                id="year-one",
                year_of_study=["Current 1st Year"],
                financial_need_required=None,
                personal_statement_required=False,
            ),
            demo_scholarship(
                id="upper-year",
                major=[],
                faculty=["School of Mathematical and Computational Sciences"],
                year_of_study=["Upper Year"],
                minimum_average=None,
                academic_requirements=None,
                financial_need_required=None,
                personal_statement_required=False,
            ),
            demo_scholarship(
                id="entering-four",
                year_of_study=["Entering 4th Year"],
                financial_need_required=None,
                personal_statement_required=False,
            ),
        ]
        search = ScholarshipSearchResult(
            scholarships=scholarships,
            source_mode="demo_fallback",
            sources=[ScholarshipSource(title="UPEI", url=scholarships[0].source_url)],
        )

        ranked = {match.scholarship_id: match for match in self.session.rank(search, snapshot)}

        self.assertEqual(snapshot.student.year_of_study, 4)
        self.assertIn("fourth-year standing", " ".join(ranked["year-four"].known_matches).casefold())
        self.assertEqual(ranked["year-one"].match_level, "unlikely")
        self.assertIn("first year", " ".join(ranked["year-one"].known_conflicts).casefold())
        self.assertIn("upper-year", " ".join(ranked["upper-year"].known_matches).casefold())
        self.assertEqual(ranked["entering-four"].match_level, "potential")

    def test_search_and_rank_receives_calculated_year_and_academic_profile(self):
        record = load_demo_record()
        record["student"] = {
            **record["student"],
            "faculty": "SMCS",
            "completed_credits": 102,
            "required_degree_credits": 120,
        }
        snapshot = build_academic_snapshot(record, source="demo")
        scholarship = demo_scholarship(
            year_of_study=["Current 4th Year"],
            financial_need_required=None,
            personal_statement_required=False,
        )
        discovery = StubDiscovery(scholarship)
        session = ScholarshipSession(discovery)

        result = session.search_and_rank(snapshot)

        self.assertEqual(discovery.last_search_kwargs["year_of_study"], 4)
        self.assertEqual(result["student_profile_used"]["year_of_study"], 4)
        self.assertEqual(result["student_profile_used"]["completed_credits"], 102)
        self.assertEqual(result["student_profile_used"]["cumulative_gpa"], snapshot.student.cumulative_gpa)

    def test_source_only_application_returns_exact_official_destination(self):
        source_url = "https://www.upei.ca/scholarships-and-awards/display?awardid=596"
        scholarship = demo_scholarship(
            id="596",
            source_url=source_url,
            detail_status="source_only",
            application_url=None,
        )
        session = ScholarshipSession(StubDiscovery(scholarship))

        state = session.open_application("596", self.snapshot)

        self.assertTrue(state.application_id)
        self.assertEqual(state.next_action, "open_official_scholarship")
        self.assertEqual(state.destination_url, source_url)
        self.assertEqual(state.inspection_status, "unavailable")
        self.assertEqual(state.fields, [])
        self.assertFalse(session.prepare_preview(state.application_id).ready)

    def test_email_application_draft_is_reviewable_and_not_sent(self):
        scholarship = demo_scholarship(
            id="email-award",
            financial_need_required=None,
            personal_statement_required=False,
            submission_method="email",
            submission_email="scholarships@upei.ca",
            required_documents=["Official transcript", "Reference letter"],
        )
        session = ScholarshipSession(StubDiscovery(scholarship))

        state = session.open_application(scholarship.id, self.snapshot)
        draft = session.prepare_application_email(state.application_id)

        self.assertEqual(state.next_action, "guided_application")
        self.assertTrue(draft.ready)
        self.assertEqual(draft.to, "scholarships@upei.ca")
        self.assertIn("Application", draft.subject)
        self.assertIn("Official transcript", draft.attachments_required)
        self.assertTrue(draft.mailto_url.startswith("mailto:scholarships@upei.ca?"))
        self.assertIn("%E2%80%94", draft.mailto_url)

    def test_canonical_apply_route_is_available(self):
        from backend.app import app

        paths = {route.path for route in app.routes}
        self.assertIn("/api/scholarships/{scholarship_id}/apply", paths)


if __name__ == "__main__":
    unittest.main()
