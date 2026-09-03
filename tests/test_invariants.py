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


if __name__ == "__main__":
    unittest.main()
