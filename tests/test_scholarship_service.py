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
)


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


def demo_scholarship(**overrides):
    values = {
        "id": "demo-test-award",
        "name": "Demo Computing Community Award",
        "amount": 2000,
        "deadline": "Demo only",
        "description": "A demo award for Computer Science students with financial need.",
        "faculty": ["School of Mathematical and Computational Sciences"],
        "major": ["Computer Science"],
        "year_of_study": ["Current 3rd Year"],
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
        self.assertEqual(match.match_level, "needs_more_information")
        self.assertIn("Financial need status must be confirmed by the student.", match.missing_information)
        self.assertNotIn("Student confirmed that financial need applies.", match.known_matches)

        self.session.save_background_answer("financial_need", True, confirmed=True)
        match = self.session.rank(self.search, self.snapshot)[0]
        self.assertEqual(match.match_level, "excellent")
        self.assertIn("Student confirmed that financial need applies.", match.known_matches)

    def test_background_confirmation_draft_review_and_submission_gate(self):
        state = self.session.open_application(self.scholarship.id, self.snapshot)
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


if __name__ == "__main__":
    unittest.main()
