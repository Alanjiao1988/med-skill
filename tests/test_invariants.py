import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "fetch_evidence.py")

spec = importlib.util.spec_from_file_location("fetch_evidence", SCRIPT)
fe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fe)


class MedSkillInvariantTests(unittest.TestCase):
    def test_unicode_title_normalization_preserves_non_latin_text(self):
        value = fe.norm_title("儿童 抗-Nephrin 抗体：研究！")
        self.assertIn("儿童", value)
        self.assertIn("抗", value)
        self.assertIn("nephrin", value)

    def test_trial_hash_change_without_status_change_is_protocol_update(self):
        prior = {
            "last_status": "RECRUITING",
            "has_results": False,
            "protocol_hash": "old",
        }
        current = {
            "status": "RECRUITING",
            "has_results": False,
            "protocol_hash": "new",
        }
        self.assertEqual(fe.classify_trial_change(prior, current), "protocol_record_updated")

    def test_results_posted_has_priority(self):
        prior = {"last_status": "COMPLETED", "has_results": False}
        current = {"status": "COMPLETED", "has_results": True}
        self.assertEqual(fe.classify_trial_change(prior, current), "results_posted")

    def test_preprint_baseline_is_rejected(self):
        baseline = {
            "mechanism": [
                {
                    "claim": "example",
                    "sources": ["PPR:PPR123"],
                }
            ]
        }
        with self.assertRaises(ValueError):
            fe.validate_no_preprint_baseline(baseline)

    def test_missing_decision_fails_closed(self):
        candidates = {
            "new_papers": [
                {
                    "candidate_id": "PMID:123",
                    "pmid": "123",
                    "peer_review_status": "peer_reviewed",
                }
            ],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {"items": {}}
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_preprint_cannot_be_material(self):
        candidates = {
            "new_papers": [],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [
                {
                    "candidate_id": "PPR:PPR123",
                    "epmc_id": "PPR123",
                    "peer_review_status": "preprint",
                }
            ],
        }
        decisions = {
            "items": {
                "PPR:PPR123": {
                    "verdict": "material",
                    "scores": {"S": 2, "N": 2, "R": "N/A"},
                    "evidence_basis": "abstract_only",
                }
            }
        }
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_complete_peer_reviewed_decision_passes(self):
        candidates = {
            "new_papers": [
                {
                    "candidate_id": "PMID:123",
                    "pmid": "123",
                    "peer_review_status": "peer_reviewed",
                }
            ],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {
            "items": {
                "PMID:123": {
                    "verdict": "material",
                    "scores": {"S": 4, "N": 2, "R": 3},
                    "evidence_basis": "abstract_only",
                }
            }
        }
        fe.validate_decisions(candidates, decisions)

    def test_preprint_watchlist_decision_passes(self):
        candidates = {
            "new_papers": [],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [
                {
                    "candidate_id": "PPR:PPR123",
                    "epmc_id": "PPR123",
                    "peer_review_status": "preprint",
                }
            ],
        }
        decisions = {
            "items": {
                "PPR:PPR123": {
                    "verdict": "preprint_watchlist",
                    "scores": {"S": 2, "N": 2, "R": "N/A"},
                    "evidence_basis": "abstract_only",
                }
            }
        }
        fe.validate_decisions(candidates, decisions)


if __name__ == "__main__":
    unittest.main()
