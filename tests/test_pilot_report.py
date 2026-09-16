import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_pilot_report as report  # noqa: E402


class PilotReportTests(unittest.TestCase):
    @staticmethod
    def edges() -> list[dict]:
        rows = []
        for number in range(30):
            rows.append({
                "assertion_id": f"conn_{number:024x}",
                "predicate": ("about_topic", "cites_instrument", "document_of")[
                    number % 3
                ],
            })
        return rows

    def test_precision_sample_is_deterministic_and_stratified(self) -> None:
        first = report.precision_sample(self.edges(), 12)
        second = report.precision_sample(list(reversed(self.edges())), 12)
        self.assertEqual(
            [row["assertion_id"] for row in first],
            [row["assertion_id"] for row in second],
        )
        self.assertEqual(len(first), 12)
        predicates = {row["predicate"] for row in first}
        self.assertEqual(
            predicates, {"about_topic", "cites_instrument", "document_of"}
        )

    def test_invalid_sample_size_fails(self) -> None:
        with self.assertRaises(ValueError):
            report.precision_sample(self.edges(), 31)


if __name__ == "__main__":
    unittest.main()
