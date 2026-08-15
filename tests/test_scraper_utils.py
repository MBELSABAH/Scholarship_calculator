import unittest

from scraper_utils import parse_progress_text


class ProgressTextTests(unittest.TestCase):
    def test_progress_parser_reads_combined_credit_progress(self):
        result = parse_progress_text(
            """
            Faculty: School of Mathematical and Computational Sciences
            Credits Completed: 102 of 120
            """
        )

        self.assertEqual(result["completed_credits"], 102)
        self.assertEqual(result["required_degree_credits"], 120)


if __name__ == "__main__":
    unittest.main()
