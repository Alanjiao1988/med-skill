import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "fetch_evidence.py")

spec = importlib.util.spec_from_file_location("fetch_evidence", SCRIPT)
fe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fe)

RUN_ID = "11111111-1111-4111-8111-111111111111"


def empty_baseline():
    return {
        "treatment": [],
        "mechanism": [],
        "biomarkers": [],
        "natural_history": [],
        "guidelines": [],
    }


def candidate_artifact(run_id=RUN_ID, period="2026-08", window=None):
    window = window or ["2026-08-01", "2026-08-31"]
    return {
        "schema_version": 3,
        "run_id": run_id,
        "period": period,
        "mode": "delta",
        "window": window,
        "queries_version": 2,
        "generated_at": "2026-08-31T10:00:00+08:00",
        "report_repository": "Alanjiao1988/Med-report",
        "core_sources_complete": True,
        "supplemental_sources_complete": True,
        "source_errors": [],
        "counts": {
            "pubmed_unique_hits": 0,
            "new_papers": 0,
            "publication_transitions": 0,
            "cross_track_updates": 0,
            "trials_new": 0,
            "trials_changed": 0,
            "preprints": 0,
        },
        "new_papers": [],
        "publication_transitions": [],
        "cross_track_updates": [],
        "trials_new": [],
        "trials_changed": [],
        "preprints": [],
    }


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
        candidates = candidate_artifact()
        candidates["preprints"] = [
            {
                "candidate_id": "PPR:PPR123",
                "epmc_id": "PPR123",
                "doi": "10.1234/preprint",
                "title": "Preprint",
                "peer_review_status": "preprint",
            }
        ]
        candidates["counts"]["preprints"] = 1
        baseline = empty_baseline()
        baseline["mechanism"] = [{
            "claim": "example",
            "strength": 3,
            "sources": ["10.1234/preprint"],
            "updated": "2026-08-31",
        }]
        with self.assertRaises(ValueError):
            fe.validate_baseline(baseline, candidates, {"seen": {}})

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
        decisions = {"schema_version": 3, "items": {}}
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
            "schema_version": 3,
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
            "schema_version": 3,
            "items": {
                "PMID:123": {
                    "verdict": "material",
                    "scores": {"S": 4, "N": 2, "R": 3},
                    "evidence_basis": "abstract_only",
                    "material_basis": "strength_novelty",
                    "claim_type": "treatment",
                    "population_directness": "direct",
                    "what_this_changes": "Adds a new comparison.",
                    "what_this_does_not_prove": "Does not establish long-term safety.",
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
            "schema_version": 3,
            "items": {
                "PPR:PPR123": {
                    "verdict": "preprint_watchlist",
                    "scores": {"S": 2, "N": 2, "R": "N/A"},
                    "evidence_basis": "abstract_only",
                }
            }
        }
        fe.validate_decisions(candidates, decisions)

    def test_invalid_score_ranges_are_rejected(self):
        candidates = {
            "new_papers": [{
                "candidate_id": "PMID:123",
                "pmid": "123",
                "peer_review_status": "peer_reviewed",
            }],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {
            "schema_version": 3,
            "items": {
                "PMID:123": {
                    "verdict": "appendix",
                    "scores": {"S": 99, "N": 0, "R": "bad"},
                }
            },
        }
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_unknown_decision_ids_are_rejected(self):
        candidates = {
            "new_papers": [{
                "candidate_id": "PMID:123",
                "pmid": "123",
                "peer_review_status": "peer_reviewed",
            }],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {
            "schema_version": 3,
            "items": {
                "PMID:123": {
                    "verdict": "appendix",
                    "scores": {"S": 2, "N": 1, "R": "N/A"},
                },
                "PMID:999": {
                    "verdict": "appendix",
                    "scores": {"S": 2, "N": 1, "R": "N/A"},
                },
            },
        }
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_book_chapter_cannot_be_material(self):
        candidates = {
            "new_papers": [{
                "candidate_id": "PMID:123",
                "pmid": "123",
                "peer_review_status": "book_chapter",
            }],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {
            "schema_version": 3,
            "items": {
                "PMID:123": {
                    "verdict": "material",
                    "scores": {"S": 4, "N": 2, "R": 3},
                    "evidence_basis": "full_text",
                    "material_basis": "strength_novelty",
                    "claim_type": "treatment",
                    "population_directness": "direct",
                    "what_this_changes": "Example.",
                    "what_this_does_not_prove": "Example.",
                }
            },
        }
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_book_chapter_scores_cannot_be_inflated(self):
        candidates = {
            "new_papers": [{
                "candidate_id": "PMID:123",
                "pmid": "123",
                "peer_review_status": "book_chapter",
            }],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {
            "schema_version": 3,
            "items": {
                "PMID:123": {
                    "verdict": "appendix",
                    "scores": {"S": 3, "N": 2, "R": "N/A"},
                }
            },
        }
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_material_threshold_is_enforced(self):
        candidates = {
            "new_papers": [{
                "candidate_id": "PMID:123",
                "pmid": "123",
                "peer_review_status": "peer_reviewed",
            }],
            "publication_transitions": [],
            "cross_track_updates": [],
            "preprints": [],
        }
        decisions = {
            "schema_version": 3,
            "items": {
                "PMID:123": {
                    "verdict": "material",
                    "scores": {"S": 2, "N": 1, "R": 1},
                    "evidence_basis": "abstract_only",
                    "material_basis": "strength_novelty",
                    "claim_type": "treatment",
                    "population_directness": "direct",
                    "what_this_changes": "Example.",
                    "what_this_does_not_prove": "Example.",
                }
            },
        }
        with self.assertRaises(ValueError):
            fe.validate_decisions(candidates, decisions)

    def test_partial_date_arguments_are_rejected(self):
        args = SimpleNamespace(start="2026-08-01", end=None, bootstrap=False)
        with self.assertRaises(ValueError):
            fe.resolve_window(args, None, date(2026, 9, 3))

    def test_future_end_date_is_rejected(self):
        args = SimpleNamespace(start="2026-08-01", end="2026-10-01", bootstrap=False)
        with self.assertRaises(ValueError):
            fe.resolve_window(args, None, date(2026, 9, 3))


class ArtifactValidationTests(unittest.TestCase):
    def test_valid_empty_candidate_artifact_passes(self):
        fe.validate_candidate_artifact(candidate_artifact())

    def test_candidate_count_mismatch_is_rejected(self):
        candidates = candidate_artifact()
        candidates["counts"]["new_papers"] = 1
        with self.assertRaises(ValueError):
            fe.validate_candidate_artifact(candidates)

    def test_candidate_artifact_name_contains_run_id(self):
        path = fe.candidate_artifact_path("2026-08", RUN_ID)
        self.assertTrue(path.endswith(f"candidates-2026-08-{RUN_ID}.json"))

    def test_preprint_candidate_id_prefers_ppr_over_linked_pmid(self):
        rec = {
            "peer_review_status": "preprint",
            "epmc_id": "PPR123",
            "pmid": "99999999",
        }
        self.assertEqual(fe.paper_candidate_id(rec), "PPR:PPR123")

    def test_brief_must_be_inside_out_and_carry_run_markers(self):
        candidates = candidate_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "out")
            os.makedirs(out_dir)
            brief = os.path.join(out_dir, f"brief-2026-08-{RUN_ID}.md")
            with open(brief, "w", encoding="utf-8") as f:
                f.write(
                    f"<!-- med-skill-run-id: {RUN_ID} -->\n"
                    "<!-- med-skill-period: 2026-08 -->\n"
                    "不构成医疗建议，不替代临床诊疗。\n"
                )
            decisions = {"brief_path": brief}
            with mock.patch.object(fe, "ROOT", tmp), mock.patch.object(fe, "OUT_DIR", out_dir):
                path, content, digest = fe.validate_brief(decisions, candidates)
            self.assertEqual(path, brief)
            self.assertEqual(digest, fe.sha256_bytes(content))

    def test_stale_candidate_window_is_rejected(self):
        state = {
            "window_end_edat": "2026-09-01",
            "queries_version": 2,
        }
        with self.assertRaises(ValueError):
            fe.validate_commit_order(state, candidate_artifact())


class ReportArchiveTests(unittest.TestCase):
    def test_public_report_repository_is_rejected(self):
        candidates = candidate_artifact()
        with mock.patch.object(
            fe,
            "run_gh_json",
            return_value={
                "nameWithOwner": "Alanjiao1988/Med-report",
                "visibility": "PUBLIC",
                "defaultBranchRef": {"name": "main"},
                "url": "https://github.com/Alanjiao1988/Med-report",
            },
        ):
            with self.assertRaises(RuntimeError):
                fe.publish_report(b"report", candidates, "Alanjiao1988/Med-report")

    def test_private_report_is_created_at_run_specific_path(self):
        candidates = candidate_artifact()
        expected_path = fe.report_archive_path("2026-08", RUN_ID)
        calls = [
            {
                "nameWithOwner": "Alanjiao1988/Med-report",
                "visibility": "PRIVATE",
                "defaultBranchRef": {"name": "main"},
                "url": "https://github.com/Alanjiao1988/Med-report",
            },
            None,
            {
                "content": {
                    "path": expected_path,
                    "html_url": "https://github.com/example/report",
                    "sha": "file-sha",
                },
                "commit": {"sha": "commit-sha"},
            },
        ]
        with mock.patch.object(fe, "run_gh_json", side_effect=calls):
            archived = fe.publish_report(
                b"report",
                candidates,
                "Alanjiao1988/Med-report",
            )
        self.assertEqual(archived["path"], expected_path)
        self.assertEqual(archived["commit_sha"], "commit-sha")


class CommitTransactionTests(unittest.TestCase):
    def write_fixture(self, root):
        out_dir = os.path.join(root, "out")
        state_dir = os.path.join(root, "state")
        os.makedirs(out_dir)
        os.makedirs(state_dir)

        candidates = candidate_artifact()
        candidates_path = os.path.join(out_dir, f"candidates-2026-08-{RUN_ID}.json")
        decisions_path = os.path.join(out_dir, f"decisions-2026-08-{RUN_ID}.json")
        brief_path = os.path.join(out_dir, f"brief-2026-08-{RUN_ID}.md")
        decisions = {
            "schema_version": 3,
            "run_id": RUN_ID,
            "brief_generated": True,
            "brief_path": brief_path,
            "items": {},
            "baseline": empty_baseline(),
        }
        with open(candidates_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f)
        with open(decisions_path, "w", encoding="utf-8") as f:
            json.dump(decisions, f)
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(
                f"<!-- med-skill-run-id: {RUN_ID} -->\n"
                "<!-- med-skill-period: 2026-08 -->\n"
                "不构成医疗建议，不替代临床诊疗。\n"
            )
        return candidates_path, decisions_path, state_dir, out_dir

    def test_repeated_commit_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates_path, decisions_path, state_dir, out_dir = self.write_fixture(tmp)
            args = SimpleNamespace(
                candidates=candidates_path,
                decisions=decisions_path,
                report_repo="Alanjiao1988/Med-report",
            )
            archive = {
                "repository": "Alanjiao1988/Med-report",
                "path": fe.report_archive_path("2026-08", RUN_ID),
            }
            with (
                mock.patch.object(fe, "ROOT", tmp),
                mock.patch.object(fe, "OUT_DIR", out_dir),
                mock.patch.object(fe, "STATE_PATH", os.path.join(state_dir, "seen.json")),
                mock.patch.object(fe, "publish_report", return_value=archive),
            ):
                fe.commit_phase(args)
                fe.commit_phase(args)
                with open(fe.STATE_PATH, encoding="utf-8") as f:
                    state = json.load(f)
            self.assertEqual(len(state["runs"]), 1)
            self.assertEqual(state["runs"][0]["run_id"], RUN_ID)

    def test_publish_failure_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates_path, decisions_path, state_dir, out_dir = self.write_fixture(tmp)
            state_path = os.path.join(state_dir, "seen.json")
            args = SimpleNamespace(
                candidates=candidates_path,
                decisions=decisions_path,
                report_repo="Alanjiao1988/Med-report",
            )
            with (
                mock.patch.object(fe, "ROOT", tmp),
                mock.patch.object(fe, "OUT_DIR", out_dir),
                mock.patch.object(fe, "STATE_PATH", state_path),
                mock.patch.object(
                    fe,
                    "publish_report",
                    side_effect=RuntimeError("archive failed"),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    fe.commit_phase(args)
            self.assertFalse(os.path.exists(state_path))


class RegistryPrecisionTests(unittest.TestCase):
    """Registry APIs match whole records, so hits need a topical re-check."""

    def test_offtopic_registry_records_are_rejected(self):
        for text in (
            "Study of etoposide carboplatin pembrolizumab | High-grade neuroendocrine tumours Cancer",
            "ESTEEM testosterone quality of life | Hypogonadism",
            "Calcium dobesilate in diabetic nephropathy | Diabetic nephropathy",
            "MINIMA Stem With DELTA TT or DELTA ST-C Study | Hip osteoarthritis",
        ):
            self.assertFalse(fe.is_on_topic(text), text)

    def test_ontopic_records_are_kept(self):
        for text in (
            "Rituximab in nephrotic glomerulonephritis | Nephrotic syndrome, caused by minimal change disease",
            "Atacicept in Multiple Autoimmune Glomerular Diseases | Multiple Autoimmune Glomerular Diseases",
            "Zuberitamab in the First Episode of Paediatric Nephrotic Syndrome | nephrotic syndrome",
        ):
            self.assertTrue(fe.is_on_topic(text), text)

    def test_ctgov_condition_phrases_are_quoted(self):
        import inspect

        src = inspect.getsource(fe.fetch_trials)
        self.assertIn('"minimal change disease"', src)
        self.assertNotIn("(nephrotic syndrome OR minimal change disease", src)


class BookRecordTests(unittest.TestCase):
    """PubMed returns Bookshelf records that used to abort the whole run."""

    BOOK_XML = """<?xml version='1.0'?>
    <PubmedArticleSet><PubmedBookArticle><BookDocument>
      <PMID Version="1">32809474</PMID>
      <ArticleIdList><ArticleId IdType="bookaccession">NBK560639</ArticleId></ArticleIdList>
      <Book><Publisher><PublisherName>StatPearls Publishing</PublisherName></Publisher>
        <BookTitle book="statpearls">StatPearls</BookTitle>
        <PubDate><Year>2026</Year><Month>01</Month></PubDate></Book>
      <ArticleTitle book="statpearls">Minimal Change Disease</ArticleTitle>
      <Language>eng</Language>
      <AuthorList><Author><LastName>Zamora</LastName><Initials>G</Initials></Author></AuthorList>
      <PublicationType>Study Guide</PublicationType>
      <Abstract><AbstractText>Minimal change disease is a cause of nephrotic syndrome.</AbstractText></Abstract>
    </BookDocument></PubmedBookArticle></PubmedArticleSet>"""

    def test_book_record_parses(self):
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self.BOOK_XML)
        rec = fe.parse_pubmed_book(root.find("PubmedBookArticle"))
        self.assertIsNotNone(rec)
        self.assertEqual(rec["pmid"], "32809474")
        self.assertEqual(rec["title"], "Minimal Change Disease")
        self.assertIn("nephrotic syndrome", rec["abstract"])
        self.assertEqual(rec["full_text_url"], "https://www.ncbi.nlm.nih.gov/books/NBK560639/")

    def test_book_record_is_not_peer_reviewed_research(self):
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self.BOOK_XML)
        rec = fe.parse_pubmed_book(root.find("PubmedBookArticle"))
        # Tertiary educational content must stay distinguishable from原始研究.
        self.assertEqual(rec["peer_review_status"], "book_chapter")
        self.assertNotEqual(rec["peer_review_status"], "peer_reviewed")


class NCBIIdentityTests(unittest.TestCase):
    def test_eutils_params_carry_tool_identity(self):
        p = fe.eutils_params(db="pubmed", term="x")
        self.assertEqual(p["db"], "pubmed")
        self.assertTrue(p["tool"])
        self.assertIn("email", p)

    def test_fetch_requires_valid_contact_email(self):
        with mock.patch.object(fe, "NCBI_EMAIL", ""):
            with self.assertRaises(RuntimeError):
                fe.ensure_ncbi_identity()


if __name__ == "__main__":
    unittest.main()
