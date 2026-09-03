#!/usr/bin/env python3
"""Deterministic evidence retrieval and state management for med-skill.

Fetch phase:
    python scripts/fetch_evidence.py
    python scripts/fetch_evidence.py --bootstrap
    python scripts/fetch_evidence.py --start 2026-07-01 --end 2026-08-23

Commit phase (no evidence retrieval; private GitHub archive only):
    python scripts/fetch_evidence.py --commit-state \
      --candidates out/candidates-2026-08-<run-id>.json \
      --decisions out/decisions-2026-08-<run-id>.json

Commit archives the validated brief to the configured private GitHub report
repository before advancing local state.
"""

import argparse
import base64
import binascii
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERIES_MD = os.path.join(ROOT, "references", "search-queries.md")
STATE_PATH = os.path.join(ROOT, "state", "seen.json")
OUT_DIR = os.path.join(ROOT, "out")

SKILL_VERSION = "0.5.0"
STATE_SCHEMA_VERSION = 3
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
ISRCTN = "https://www.isrctn.com/api/query/format/default"
CTIS = "https://euclinicaltrials.eu/ctis-public-api/search"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ISRCTN_NS = "{http://www.67bricks.com/isrctn}"

API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_TOOL = os.environ.get("NCBI_TOOL", "med-skill")
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")
REPORT_REPO_DEFAULT = os.environ.get("MED_REPORT_REPO", "Alanjiao1988/Med-report")
SLEEP = 0.11 if API_KEY else 0.34
WINDOW_OVERLAP_DAYS = 15
MAX_PUBMED_ESEARCH = 10000
MAX_REPORT_BYTES = 1_000_000
UA = "med-skill-evidence-surveillance/" + SKILL_VERSION
KEY_PREFIX = {"CTGOV": "NCT:", "ISRCTN": "ISRCTN:", "CTIS": "CTIS:"}
VALID_VERDICTS = {"material", "appendix", "preprint_watchlist", "discarded"}
CLAIM_TYPES = {
    "treatment",
    "mechanism",
    "diagnostic_biomarker",
    "prognostic_biomarker",
    "predictive_biomarker",
    "natural_history",
    "safety",
    "guideline",
}
POPULATION_DIRECTNESS = {"direct", "indirect", "mixed", "not_applicable"}
MATERIAL_BASES = {
    "strength_novelty",
    "patient_relevance",
    "negative_result",
    "new_safety_signal",
    "guideline_change",
}
PARADIGM_STATUSES = {
    "CONFIRMS_EXISTING_MODEL",
    "EXTENDS_EXISTING_MODEL",
    "CHALLENGES_EXISTING_MODEL",
    "NEW_HYPOTHESIS",
    "PARADIGM_SHIFT_CANDIDATE",
    "CLINICALLY_VALIDATED_CHANGE",
}
BASELINE_SECTIONS = {"treatment", "mechanism", "biomarkers", "natural_history", "guidelines"}
NEWLINE = chr(10)


def eutils_params(**kw):
    """Every E-utilities call must carry tool/email identity per NCBI policy."""
    p = dict(kw)
    p["tool"] = NCBI_TOOL
    p["email"] = NCBI_EMAIL
    if API_KEY:
        p["api_key"] = API_KEY
    return p


def ensure_ncbi_identity():
    if not NCBI_TOOL.strip():
        raise RuntimeError("NCBI_TOOL must be non-empty")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", NCBI_EMAIL):
        raise RuntimeError(
            "NCBI_EMAIL is required for PubMed retrieval; set it to a valid contact email"
        )


def request_bytes(req, retries=4, timeout=90):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    return json.loads(request_bytes(req).decode("utf-8"))


def http_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return request_bytes(req).decode("utf-8", "replace")


def http_post_json(url, body):
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
    )
    return json.loads(request_bytes(req, timeout=60).decode("utf-8"))


def parse_date_loose(s):
    s = (s or "").strip()
    if not s:
        return None
    for candidate, fmt in ((s[:10], "%Y-%m-%d"), (s[:10], "%d/%m/%Y")):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            pass
    return None


def norm_title(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def norm_doi(doi):
    doi = (doi or "").strip().lower()
    return re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)


def text_of(node):
    return "".join(node.itertext()).strip() if node is not None else ""


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path, obj):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="." + os.path.basename(path) + ".",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def state_lock():
    """Serialize state commits without leaving a stale ownership sentinel."""
    lock_path = STATE_PATH + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock_file = open(lock_path, "a+b")
    acquired = False
    try:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)

        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as ex:
            raise RuntimeError("another state commit is already in progress") from ex

        acquired = True
        yield
    finally:
        if acquired:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_json_artifact(path, label):
    absolute = os.path.abspath(path)
    try:
        with open(absolute, "rb") as f:
            raw = f.read()
    except OSError as ex:
        raise ValueError(f"{label} cannot be read: {absolute}: {ex}") from ex
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {absolute}: {ex}") from ex
    return obj, absolute, sha256_bytes(raw)


def require_path_within_out(path, label, extension):
    real_out = os.path.realpath(OUT_DIR)
    real_path = os.path.realpath(path)
    try:
        within_out = os.path.commonpath([real_out, real_path]) == real_out
    except ValueError:
        within_out = False
    if not within_out or os.path.splitext(real_path)[1].lower() != extension:
        raise ValueError(f"{label} must be a {extension} file inside out/")
    return real_path


def run_gh_json(args, input_obj=None, allow_not_found=False):
    if not shutil.which("gh"):
        raise RuntimeError("GitHub CLI 'gh' is required to archive reports")

    try:
        proc = subprocess.run(
            ["gh"] + list(args),
            input=json.dumps(input_obj, ensure_ascii=False) if input_obj is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError("gh command timed out after 120 seconds") from ex
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if allow_not_found and ("HTTP 404" in detail or "Not Found" in detail):
            return None
        raise RuntimeError("gh command failed: " + detail[:500])

    output = proc.stdout.strip()
    if not output:
        return {}
    try:
        return json.loads(output)
    except json.JSONDecodeError as ex:
        raise RuntimeError("gh returned invalid JSON: " + output[:300]) from ex


def load_queries():
    with open(QUERIES_MD, encoding="utf-8") as f:
        md = f.read()

    version_match = re.search(r"queries_version:\s*(\d+)", md)
    version = int(version_match.group(1)) if version_match else 1

    common = re.search(r"## 通用 PubMed 片段.*?```text(.*?)```", md, re.S)
    if not common:
        sys.exit("search-queries.md: cannot find common PubMed fragments")

    frag = {}
    for name, body in re.findall(r"\{(\w+)\}\s*=\s*\n(.*?)(?=\n\{|\Z)", common.group(1), re.S):
        frag[name] = " ".join(body.split())

    tracks = {}
    for letter, body in re.findall(r"## Track ([A-E]) —[^\n]*\n+```text(.*?)```", md, re.S):
        tracks[letter] = " ".join(body.split())

    missing = set("ABCDE") - set(tracks)
    if missing:
        sys.exit("search-queries.md: missing PubMed tracks " + repr(sorted(missing)))
    return version, frag, tracks


def build_term(raw, frag, start, end):
    window = '("{:%Y/%m/%d}"[EDAT] : "{:%Y/%m/%d}"[EDAT])'.format(start, end)
    term = raw.replace("{WINDOW}", window)
    for name, body in frag.items():
        if name != "WINDOW":
            term = term.replace("{" + name + "}", "(" + body + ")")
    if "[PDAT]" in term:
        sys.exit("PubMed query uses [PDAT]; med-skill requires [EDAT]")
    return term


# ---------------- PubMed ----------------

def esearch_all(term, page_size=500):
    base = eutils_params(db="pubmed", term=term, retmode="json")

    first = dict(base, retmax="0")
    data = http_json(EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(first))
    time.sleep(SLEEP)
    count = int(data.get("esearchresult", {}).get("count", 0))
    if count > MAX_PUBMED_ESEARCH:
        raise RuntimeError(
            "PubMed query matched more than 10,000 records; split the date window instead of truncating"
        )

    ids = []
    for retstart in range(0, count, page_size):
        p = dict(base, retstart=str(retstart), retmax=str(min(page_size, count - retstart)))
        page = http_json(EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(p))
        time.sleep(SLEEP)
        ids.extend(page.get("esearchresult", {}).get("idlist", []))

    if len(ids) != count:
        raise RuntimeError(f"PubMed pagination incomplete: expected {count}, got {len(ids)}")
    unique = list(dict.fromkeys(ids))
    if len(unique) != count:
        # Paging without the history server can repeat records while the index shifts.
        raise RuntimeError(
            f"PubMed pagination returned duplicates: {count} expected, {len(unique)} unique"
        )
    return unique


def parse_pubmed_article(pa):
    med = pa.find("MedlineCitation")
    art = med.find("Article") if med is not None else None
    if med is None or art is None:
        return None

    pmid = text_of(med.find("PMID"))
    title = text_of(art.find("ArticleTitle"))

    abstract_parts = []
    for x in art.findall("./Abstract/AbstractText"):
        txt = text_of(x)
        if not txt:
            continue
        label = (x.attrib.get("Label") or x.attrib.get("NlmCategory") or "").strip()
        abstract_parts.append((label + ": " if label else "") + txt)

    journal = text_of(art.find("./Journal/Title"))
    issue_date = art.find("./Journal/JournalIssue/PubDate")
    pubdate = ""
    if issue_date is not None:
        medline_date = text_of(issue_date.find("MedlineDate"))
        if medline_date:
            pubdate = medline_date
        else:
            parts = [text_of(issue_date.find(x)) for x in ("Year", "Month", "Day")]
            pubdate = " ".join(p for p in parts if p)

    ids = {"doi": "", "pmc": ""}
    for aid in pa.findall("./PubmedData/ArticleIdList/ArticleId"):
        kind = (aid.attrib.get("IdType") or "").lower()
        if kind == "doi":
            ids["doi"] = norm_doi(text_of(aid))
        elif kind == "pmc":
            ids["pmc"] = text_of(aid)

    authors = []
    for au in art.findall("./AuthorList/Author"):
        collective = text_of(au.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = text_of(au.find("LastName"))
        initials = text_of(au.find("Initials"))
        name = (last + " " + initials).strip()
        if name:
            authors.append(name)

    return {
        "pmid": pmid,
        "doi": ids["doi"],
        "pmcid": ids["pmc"],
        "title": title,
        "journal": journal,
        "pubdate": pubdate,
        "abstract": "\n".join(abstract_parts),
        "language": [text_of(x) for x in art.findall("./Language") if text_of(x)],
        "pubtypes": [text_of(x) for x in art.findall("./PublicationTypeList/PublicationType") if text_of(x)],
        "authors": authors[:8],
        "url": "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
        "full_text_url": ("https://pmc.ncbi.nlm.nih.gov/articles/" + ids["pmc"] + "/") if ids["pmc"] else "",
        "peer_review_status": "peer_reviewed",
        "retrieval_depth": "abstract",
    }


def parse_pubmed_book(pba):
    """Parse <PubmedBookArticle> (StatPearls, GeneReviews, NCBI Bookshelf).

    These are indexed in PubMed and are routinely returned by the A-E queries,
    but they use BookDocument rather than MedlineCitation/Article. Skipping them
    used to abort the whole run through the EFetch completeness check.
    """
    doc = pba.find("BookDocument")
    if doc is None:
        return None

    pmid = text_of(doc.find("PMID"))
    if not pmid:
        return None

    abstract_parts = []
    for x in doc.findall("./Abstract/AbstractText"):
        txt = text_of(x)
        if not txt:
            continue
        label = (x.attrib.get("Label") or x.attrib.get("NlmCategory") or "").strip()
        abstract_parts.append((label + ": " if label else "") + txt)

    book = doc.find("Book")
    book_title = text_of(book.find("BookTitle")) if book is not None else ""
    publisher = ""
    pubdate = ""
    if book is not None:
        publisher = text_of(book.find("./Publisher/PublisherName"))
        pd = book.find("PubDate")
        if pd is not None:
            pubdate = " ".join(
                t for t in (text_of(pd.find("Year")), text_of(pd.find("Month"))) if t
            )

    doi = ""
    accession = ""
    for aid in list(doc.findall("./ArticleIdList/ArticleId")) + list(
        pba.findall("./PubmedBookData/ArticleIdList/ArticleId")
    ):
        kind = (aid.attrib.get("IdType") or "").lower()
        if kind == "doi":
            doi = norm_doi(text_of(aid))
        elif kind == "bookaccession":
            accession = text_of(aid)

    authors = []
    for au in doc.findall("./AuthorList/Author"):
        collective = text_of(au.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        name = (text_of(au.find("LastName")) + " " + text_of(au.find("Initials"))).strip()
        if name:
            authors.append(name)

    pubtypes = [text_of(x) for x in doc.findall("./PublicationType") if text_of(x)]
    pubtypes += [text_of(x) for x in doc.findall("./PublicationTypeList/PublicationType") if text_of(x)]

    return {
        "pmid": pmid,
        "doi": doi,
        "pmcid": "",
        "title": text_of(doc.find("ArticleTitle")),
        "journal": " / ".join(x for x in (book_title, publisher) if x),
        "pubdate": pubdate,
        "abstract": NEWLINE.join(abstract_parts),
        "language": [text_of(x) for x in doc.findall("./Language") if text_of(x)],
        "pubtypes": sorted(set(pubtypes)) or ["Book Chapter"],
        "authors": authors[:8],
        "url": "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
        "full_text_url": ("https://www.ncbi.nlm.nih.gov/books/" + accession + "/") if accession else "",
        "peer_review_status": "book_chapter",
        "record_type": "book",
        "retrieval_depth": "abstract",
    }


def efetch_pubmed(pmids, chunk_size=100):
    out = {}
    for i in range(0, len(pmids), chunk_size):
        chunk = pmids[i:i + chunk_size]
        p = eutils_params(db="pubmed", id=",".join(chunk), retmode="xml")
        req = urllib.request.Request(
            EUTILS + "/efetch.fcgi?" + urllib.parse.urlencode(p),
            headers={"User-Agent": UA},
        )
        xml = request_bytes(req)
        time.sleep(SLEEP)
        root = ET.fromstring(xml)
        for pa in root.findall("PubmedArticle"):
            rec = parse_pubmed_article(pa)
            if rec and rec["pmid"]:
                out[rec["pmid"]] = rec
        for pba in root.findall("PubmedBookArticle"):
            rec = parse_pubmed_book(pba)
            if rec and rec["pmid"]:
                out.setdefault(rec["pmid"], rec)
    missing = sorted(set(pmids) - set(out))
    if missing:
        raise RuntimeError("PubMed EFetch missing PMID(s): " + ",".join(missing[:10]))
    return out


# ---------------- ClinicalTrials.gov ----------------

def flatten_trial(s):
    ps = s.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    elig = ps.get("eligibilityModule", {})
    arms = ps.get("armsInterventionsModule", {})
    outcomes = ps.get("outcomesModule", {})

    nct = ident.get("nctId", "")
    overall = status.get("overallStatus", "")
    has_results = bool(s.get("hasResults"))
    phases = design.get("phases", []) or []
    enrollment = (design.get("enrollmentInfo") or {}).get("count")
    pcd = (status.get("primaryCompletionDateStruct") or {}).get("date", "")

    protocol_subset = {
        "overall_status": overall,
        "phases": phases,
        "has_results": has_results,
        "enrollment": enrollment,
        "minimum_age": elig.get("minimumAge", ""),
        "maximum_age": elig.get("maximumAge", ""),
        "std_ages": elig.get("stdAges", []),
        "primary_completion": pcd,
        "interventions": arms.get("interventions", []),
        "primary_outcomes": outcomes.get("primaryOutcomes", []),
    }
    protocol_hash = hashlib.sha256(
        json.dumps(protocol_subset, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "registry": "CTGOV",
        "id": nct,
        "title": ident.get("briefTitle", ""),
        "status": overall,
        "phases": phases,
        "has_results": has_results,
        "enrollment": enrollment,
        "min_age": elig.get("minimumAge", ""),
        "max_age": elig.get("maximumAge", ""),
        "std_ages": elig.get("stdAges", []),
        "primary_completion": pcd,
        "last_update_posted": (status.get("lastUpdatePostDateStruct") or {}).get("date", ""),
        "url": "https://clinicaltrials.gov/study/" + nct,
        "protocol_hash": protocol_hash,
    }


def fetch_trials(start, end):
    studies, token = [], None
    date_range = "AREA[LastUpdatePostDate]RANGE[{:%Y-%m-%d},{:%Y-%m-%d}]".format(start, end)
    condition_query = (
        '("nephrotic syndrome" OR "minimal change disease" OR "minimal change nephropathy" '
        'OR "steroid sensitive nephrotic syndrome" OR "steroid dependent nephrotic syndrome" '
        'OR "frequently relapsing nephrotic syndrome")'
    )
    while True:
        p = {
            "query.cond": condition_query,
            "filter.advanced": date_range,
            "pageSize": "200",
            "countTotal": "true",
            "format": "json",
        }
        if token:
            p["pageToken"] = token
        data = http_json(CTGOV + "?" + urllib.parse.urlencode(p))
        studies.extend(data.get("studies", []))
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(0.2)
    return [flatten_trial(x) for x in studies]


# ---------------- ISRCTN ----------------

def _isrctn_text(node, path):
    if node is None:
        return ""
    el = node.find(ISRCTN_NS + path)
    return (el.text or "").strip() if el is not None else ""


# Core disease phrases plus the glomerular-disease umbrella terms registries use
# for basket trials. Wide enough to keep podocytopathy/glomerular trials, narrow
# enough to reject records that merely mention nephrotic syndrome in passing.
DISEASE_PHRASES = (
    "nephrotic syndrome",
    "minimal change disease",
    "minimal change nephropathy",
    "minimal change nephrotic",
    "lipoid nephrosis",
    "glomerular disease",
    "glomerular kidney disease",
    "glomerulonephritis",
    "glomerulopathy",
    "podocytopathy",
    "focal segmental glomerulosclerosis",
    "fsgs",
)


def is_on_topic(text):
    """True when a disease phrase appears in a registry record's topical fields.

    ISRCTN's `q` matches the whole record, so trials that merely mention
    nephrotic syndrome in a plain-English summary or exclusion criterion come
    back as hits. Precision is recovered by re-checking title/condition only.
    """
    low = (text or "").lower()
    return any(phrase in low for phrase in DISEASE_PHRASES)


def fetch_isrctn(start, end):
    query = '"nephrotic syndrome" OR "minimal change disease"'
    limit = 500
    xml = http_text(ISRCTN + "?" + urllib.parse.urlencode({"q": query, "limit": limit}))
    root = ET.fromstring(xml)

    total = int(root.attrib.get("totalCount") or 0)
    if total > limit:
        # The repo forbids silent truncation; surface it as a source error instead.
        raise RuntimeError(
            f"ISRCTN returned {total} trials but limit is {limit}; raise the limit or page the query"
        )

    out = []
    for full in root.findall(ISRCTN_NS + "fullTrial"):
        tr = full.find(ISRCTN_NS + "trial")
        if tr is None:
            continue
        updated = parse_date_loose(tr.attrib.get("lastUpdated", ""))
        if not updated or not (start <= updated <= end):
            continue

        cond = tr.find(ISRCTN_NS + "conditions")
        topical = " | ".join([
            _isrctn_text(tr.find(ISRCTN_NS + "trialDescription"), "title"),
            _isrctn_text(tr.find(ISRCTN_NS + "trialDescription"), "scientificTitle"),
            " ".join(text_of(x) for x in cond.iter()) if cond is not None else "",
        ])
        if not is_on_topic(topical):
            continue

        desc = tr.find(ISRCTN_NS + "trialDescription")
        design = tr.find(ISRCTN_NS + "trialDesign")
        part = tr.find(ISRCTN_NS + "participants")
        res = tr.find(ISRCTN_NS + "results")
        rid = tr.attrib.get("publicIdentifierCanonical", "")
        version = tr.attrib.get("version", "")
        pub_stage = _isrctn_text(res, "publicationStage")

        raw = "|".join([
            version,
            _isrctn_text(design, "overallEndDate"),
            _isrctn_text(part, "recruitmentEnd"),
            pub_stage,
            _isrctn_text(part, "lowerAgeLimit"),
            _isrctn_text(part, "upperAgeLimit"),
        ])
        out.append({
            "registry": "ISRCTN",
            "id": rid,
            "title": _isrctn_text(desc, "title") or _isrctn_text(desc, "scientificTitle"),
            "status": "version " + version,
            "publication_stage": pub_stage,
            "has_results": None,
            "phases": _isrctn_text(design, "phase"),
            "min_age": _isrctn_text(part, "lowerAgeLimit"),
            "max_age": _isrctn_text(part, "upperAgeLimit"),
            "std_ages": [_isrctn_text(part, "ageRange")],
            "primary_completion": _isrctn_text(design, "overallEndDate")[:10],
            "last_update_posted": str(updated),
            "url": "https://www.isrctn.com/" + rid,
            "protocol_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
        })
    return out


# ---------------- EU CTIS ----------------

def fetch_ctis(start, end):
    out, page = [], 1
    while True:
        data = http_post_json(CTIS, {
            "pagination": {"page": page, "size": 100},
            "searchCriteria": {"containAll": "nephrotic syndrome"},
        })
        rows = (data or {}).get("data", [])
        for r in rows:
            updated = parse_date_loose(r.get("lastUpdated"))
            if not updated or not (start <= updated <= end):
                continue
            ct = r.get("ctNumber", "")
            if not is_on_topic(str(r.get("ctTitle", "")) + " | " + str(r.get("conditions", ""))):
                continue
            results_received = str(r.get("resultsFirstReceived", "")).strip().lower()
            has_results = True if results_received == "yes" else (False if results_received == "no" else None)
            protocol_subset = {
                "ctStatus": r.get("ctStatus"),
                "trialPhase": r.get("trialPhase"),
                "ageGroup": r.get("ageGroup"),
                "conditions": r.get("conditions"),
                "resultsFirstReceived": r.get("resultsFirstReceived"),
                "decisionDateOverall": r.get("decisionDateOverall"),
                "lastUpdated": r.get("lastUpdated"),
            }
            out.append({
                "registry": "CTIS",
                "id": ct,
                "title": r.get("ctTitle", ""),
                "status": "ctStatus=" + str(r.get("ctStatus", "")),
                "phases": r.get("trialPhase", ""),
                "has_results": has_results,
                "min_age": "",
                "max_age": "",
                "std_ages": [x.strip() for x in str(r.get("ageGroup", "")).split(",") if x.strip()],
                "conditions": r.get("conditions", ""),
                "primary_completion": "",
                "last_update_posted": str(updated),
                "url": "https://euclinicaltrials.eu/ctis-public/view/" + ct,
                "source_stability": "experimental_public_portal_backend",
                "protocol_hash": hashlib.sha256(
                    json.dumps(protocol_subset, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()[:16],
            })
        pg = (data or {}).get("pagination", {})
        if not pg.get("nextPage"):
            break
        page += 1
        time.sleep(0.3)
    return out


# ---------------- Europe PMC preprints ----------------

TREATMENT_TERMS = (
    "rituximab", "ofatumumab", "obinutuzumab", "mycophenolate", "tacrolimus",
    "cyclospor", "prednisone", "prednisolone", "glucocorticoid", "levamisole",
    "cyclophosphamide", "treatment", "therapy", "randomized", "randomised",
)
BIOMARKER_TERMS = (
    "biomarker", "anti-nephrin", "antinephrin", "predict", "prognos", "proteom",
    "metabolom", "transcriptom", "single-cell", "single cell", "urinary cd80",
)
OUTCOME_TERMS = (
    "relapse", "remission", "long-term", "long term", "safety", "adverse",
    "toxicity", "growth", "infection", "quality of life", "natural history",
)
GUIDELINE_TERMS = ("guideline", "consensus", "recommendation", "position statement", "kdigo", "ipna")


def classify_preprint(text):
    low = (text or "").lower()
    tracks = []
    if any(x in low for x in TREATMENT_TERMS):
        tracks.append("B")
    if any(x in low for x in BIOMARKER_TERMS):
        tracks.append("C")
    if any(x in low for x in OUTCOME_TERMS):
        tracks.append("D")
    if any(x in low for x in GUIDELINE_TERMS):
        tracks.append("E")
    if not tracks or any(x in low for x in ("podocyte", "nephrin", "mechanism", "autoantib", "b cell", "t cell")):
        tracks.append("A")
    return sorted(set(tracks))


def fetch_preprints(start, end):
    disease_query = (
        '("nephrotic syndrome" OR "minimal change disease" OR "minimal change nephropathy" '
        'OR "steroid-sensitive nephrotic syndrome" OR "steroid-dependent nephrotic syndrome" '
        'OR "frequently relapsing nephrotic syndrome")'
    )
    query = disease_query + " AND SRC:PPR AND FIRST_PDATE:[{:%Y-%m-%d} TO {:%Y-%m-%d}]".format(start, end)
    out, cursor = [], "*"
    while True:
        p = {
            "query": query,
            "format": "json",
            "pageSize": 100,
            "resultType": "core",
            "cursorMark": cursor,
        }
        data = http_json(EPMC + "?" + urllib.parse.urlencode(p))
        rows = (data or {}).get("resultList", {}).get("result", [])
        for r in rows:
            abstract = r.get("abstractText", "") or ""
            title = r.get("title", "") or ""
            out.append({
                "source": "preprint",
                "epmc_id": r.get("id", ""),
                "pmid": r.get("pmid", "") or "",
                "doi": norm_doi(r.get("doi", "")),
                "title": title,
                "abstract": abstract,
                "journal": r.get("publisher") or r.get("journalTitle") or "preprint",
                "pubdate": r.get("firstPublicationDate", ""),
                "pubtypes": ["Preprint"],
                "track": classify_preprint(title + "\n" + abstract),
                "url": "https://europepmc.org/article/PPR/" + (r.get("id", "") or ""),
                "peer_review_status": "preprint",
                "retrieval_depth": "abstract",
            })
        nxt = (data or {}).get("nextCursorMark")
        if not rows or not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)
    return out


# ---------------- Dedup ----------------

def trial_key(rec):
    return KEY_PREFIX.get(rec.get("registry", ""), "TRIAL:") + rec.get("id", "")


def seen_key_lookup(seen, rec):
    pmid = rec.get("pmid")
    if pmid and "PMID:" + pmid in seen:
        return "PMID:" + pmid

    doi = norm_doi(rec.get("doi", ""))
    if doi:
        for key, value in seen.items():
            if norm_doi(value.get("doi", "")) == doi:
                return key

    if rec.get("registry") and rec.get("id"):
        key = trial_key(rec)
        if key in seen:
            return key

    ppr = rec.get("epmc_id")
    if ppr and "PPR:" + ppr in seen:
        return "PPR:" + ppr

    tn = norm_title(rec.get("title", ""))
    if tn:
        for key, value in seen.items():
            if value.get("title_norm") == tn:
                return key
    return None


def resolve_window(args, state, today):
    if bool(args.start) != bool(args.end):
        raise ValueError("--start and --end must be provided together")
    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        if start > end:
            raise ValueError("--start must be on or before --end")
        if end > today:
            raise ValueError("--end cannot be in the future")
        return start, end, "bootstrap" if args.bootstrap else "delta"
    if args.bootstrap or state is None:
        return today - timedelta(days=730), today, "bootstrap"
    prior_end = state.get("window_end_edat")
    if not prior_end:
        raise ValueError("state.window_end_edat is missing")
    prev = datetime.strptime(prior_end, "%Y-%m-%d").date()
    if prev > today:
        raise ValueError("state.window_end_edat is in the future")
    return prev - timedelta(days=WINDOW_OVERLAP_DAYS), today, "delta"


def paper_candidate_id(rec):
    if rec.get("peer_review_status") == "preprint" and rec.get("epmc_id"):
        return "PPR:" + rec["epmc_id"]
    if rec.get("pmid"):
        return "PMID:" + rec["pmid"]
    if rec.get("epmc_id"):
        return "PPR:" + rec["epmc_id"]
    if rec.get("doi"):
        return "DOI:" + norm_doi(rec["doi"])
    return "TITLE:" + hashlib.sha256(norm_title(rec.get("title", "")).encode("utf-8")).hexdigest()[:16]


def candidate_artifact_path(period, run_id):
    return os.path.join(OUT_DIR, f"candidates-{period}-{run_id}.json")


def report_archive_path(period, run_id):
    return f"reports/{period[:4]}/{period}/brief-{period}-{run_id}.md"


def classify_trial_change(prior, current):
    if prior is None:
        return "new_registration"
    old_status = prior.get("last_status")
    new_status = current.get("status")
    if current.get("has_results") is True and prior.get("has_results") is not True:
        return "results_posted"
    if new_status in ("TERMINATED", "WITHDRAWN", "SUSPENDED") and old_status != new_status:
        return "early_stop"
    if old_status != new_status:
        return "status_changed"
    return "protocol_record_updated"


# ---------------- Fetch phase ----------------

def fetch_phase(args):
    ensure_ncbi_identity()
    state = load_state()
    if state is not None and state.get("schema_version") not in (2, STATE_SCHEMA_VERSION):
        raise ValueError(
            f"unsupported state schema_version {state.get('schema_version')!r}"
        )
    today = date.today()
    start, end, mode = resolve_window(args, state, today)
    qver, frag, tracks = load_queries()

    if state and state.get("queries_version") not in (None, qver):
        print(
            f"! queries_version changed {state.get('queries_version')} -> {qver}; the brief must label retrospective hits",
            file=sys.stderr,
        )

    seen = (state or {}).get("seen", {})
    source_errors = []
    pmid_tracks = {}

    print(f"window {start} ~ {end} · mode {mode} · query v{qver}", file=sys.stderr)

    # PubMed is a core source. Failure aborts the run.
    for letter in "ABCDE":
        term = build_term(tracks[letter], frag, start, end)
        ids = esearch_all(term)
        print(f"Track {letter}: {len(ids)}", file=sys.stderr)
        for pid in ids:
            pmid_tracks.setdefault(pid, []).append(letter)

    papers = efetch_pubmed(list(pmid_tracks)) if pmid_tracks else {}
    new_papers, publication_transitions, cross_track_updates = [], [], []

    for pmid, rec in papers.items():
        rec["track"] = sorted(set(pmid_tracks.get(pmid, [])))
        rec["candidate_id"] = "PMID:" + pmid
        prior_key = seen_key_lookup(seen, rec)
        if not prior_key:
            new_papers.append(rec)
            continue

        prior = seen[prior_key]
        if prior.get("is_preprint") or prior.get("peer_review_status") == "preprint" or prior_key.startswith("PPR:"):
            rec["publication_transition"] = True
            rec["prior_key"] = prior_key
            publication_transitions.append(rec)
            continue

        new_tracks = [x for x in rec["track"] if x not in prior.get("track", [])]
        if new_tracks:
            rec["prior_key"] = prior_key
            rec["new_tracks"] = new_tracks
            cross_track_updates.append(rec)

    # Trial sources are supplemental.
    trials = []
    for label, fn in (("ClinicalTrials.gov", fetch_trials), ("ISRCTN", fetch_isrctn), ("EU CTIS", fetch_ctis)):
        try:
            got = fn(start, end)
            trials.extend(got)
            print(f"{label}: {len(got)}", file=sys.stderr)
        except Exception as ex:
            source_errors.append({"source": label, "error": type(ex).__name__, "detail": str(ex)[:240]})

    trials_new, trials_changed = [], []
    for trial in trials:
        key = trial_key(trial)
        prior = seen.get(key)
        if prior is None:
            trial["event"] = "new_registration"
            trials_new.append(trial)
        elif prior.get("protocol_hash") != trial.get("protocol_hash"):
            trial["event"] = classify_trial_change(prior, trial)
            trial["prior_status"] = prior.get("last_status")
            trials_changed.append(trial)

    # Preprints are supplemental source records mapped back into A-E.
    preprints = []
    try:
        for pp in fetch_preprints(start, end):
            pp["candidate_id"] = "PPR:" + pp["epmc_id"]
            prior_key = seen_key_lookup(seen, pp)
            if prior_key:
                continue
            preprints.append(pp)
    except Exception as ex:
        source_errors.append({"source": "Europe PMC preprints", "error": type(ex).__name__, "detail": str(ex)[:240]})

    run_id = str(uuid.uuid4())
    period = "{:%Y-%m}".format(end)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "period": period,
        "mode": mode,
        "window": [str(start), str(end)],
        "queries_version": qver,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "report_repository": args.report_repo,
        "core_sources_complete": True,
        "supplemental_sources_complete": not source_errors,
        "source_errors": source_errors,
        "known_gaps": [
            {"source": "WHO ICTRP", "status": "available_but_not_integrated"},
            {"source": "CTRI", "status": "not_integrated_or_not_verified"},
            {"source": "jRCT/JPRN", "status": "not_integrated_or_not_verified"},
            {"source": "ChiCTR", "status": "not_integrated_or_not_verified"},
            {"source": "regional/non-PubMed databases", "status": "not_systematically_covered"},
        ],
        "counts": {
            "pubmed_unique_hits": len(papers),
            "new_papers": len(new_papers),
            "publication_transitions": len(publication_transitions),
            "cross_track_updates": len(cross_track_updates),
            "trials_new": len(trials_new),
            "trials_changed": len(trials_changed),
            "preprints": len(preprints),
        },
        "new_papers": new_papers,
        "publication_transitions": publication_transitions,
        "cross_track_updates": cross_track_updates,
        "trials_new": trials_new,
        "trials_changed": trials_changed,
        "preprints": preprints,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = candidate_artifact_path(period, run_id)
    write_json_atomic(out_path, payload)
    print("-> " + out_path, file=sys.stderr)
    print("state NOT written; generate brief + decisions, then use --commit-state", file=sys.stderr)


# ---------------- Commit phase ----------------

def iter_candidate_papers(candidates):
    for bucket in ("new_papers", "publication_transitions", "cross_track_updates"):
        for rec in candidates.get(bucket, []):
            yield rec
    for rec in candidates.get("preprints", []):
        yield rec


def parse_iso_date(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as ex:
        raise ValueError(f"{label} must use YYYY-MM-DD") from ex


def validate_candidate_artifact(candidates):
    if not isinstance(candidates, dict):
        raise ValueError("candidates must be a JSON object")
    if candidates.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(
            f"candidates.schema_version must be {STATE_SCHEMA_VERSION}; refetch with this skill version"
        )

    run_id = candidates.get("run_id")
    try:
        uuid.UUID(str(run_id))
    except (ValueError, AttributeError, TypeError) as ex:
        raise ValueError("candidates.run_id must be a UUID") from ex

    period = candidates.get("period")
    if not isinstance(period, str) or not re.fullmatch(r"\d{4}-\d{2}", period):
        raise ValueError("candidates.period must use YYYY-MM")
    if candidates.get("mode") not in ("delta", "bootstrap"):
        raise ValueError("candidates.mode must be delta or bootstrap")

    window = candidates.get("window")
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError("candidates.window must contain [start, end]")
    start = parse_iso_date(window[0], "candidates.window[0]")
    end = parse_iso_date(window[1], "candidates.window[1]")
    if start > end:
        raise ValueError("candidates.window start must be on or before end")
    if period != end.strftime("%Y-%m"):
        raise ValueError("candidates.period must match the window end month")

    query_version = candidates.get("queries_version")
    if type(query_version) is not int or query_version < 1:
        raise ValueError("candidates.queries_version must be a positive integer")
    if candidates.get("core_sources_complete") is not True:
        raise ValueError("core PubMed retrieval is incomplete; refusing state commit")
    if not isinstance(candidates.get("source_errors"), list):
        raise ValueError("candidates.source_errors must be an array")
    supplemental_complete = candidates.get("supplemental_sources_complete")
    if type(supplemental_complete) is not bool:
        raise ValueError("candidates.supplemental_sources_complete must be boolean")
    if supplemental_complete != (not candidates["source_errors"]):
        raise ValueError(
            "candidates.supplemental_sources_complete conflicts with source_errors"
        )

    generated_at = candidates.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("candidates.generated_at is required")
    try:
        generated_datetime = datetime.fromisoformat(generated_at)
    except ValueError as ex:
        raise ValueError("candidates.generated_at must be ISO-8601") from ex
    if generated_datetime.utcoffset() is None:
        raise ValueError("candidates.generated_at must include a timezone offset")

    report_repository = candidates.get("report_repository")
    if not isinstance(report_repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", report_repository
    ):
        raise ValueError("candidates.report_repository must use owner/repo")

    bucket_names = (
        "new_papers",
        "publication_transitions",
        "cross_track_updates",
        "trials_new",
        "trials_changed",
        "preprints",
    )
    for bucket in bucket_names:
        if not isinstance(candidates.get(bucket), list):
            raise ValueError(f"candidates.{bucket} must be an array")

    counts = candidates.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("candidates.counts must be an object")
    for bucket in bucket_names:
        if type(counts.get(bucket)) is not int or counts[bucket] < 0:
            raise ValueError(f"candidates.counts.{bucket} must be a non-negative integer")
        if counts.get(bucket) != len(candidates[bucket]):
            raise ValueError(f"candidates.counts.{bucket} does not match its array length")
    if type(counts.get("pubmed_unique_hits")) is not int or counts["pubmed_unique_hits"] < 0:
        raise ValueError("candidates.counts.pubmed_unique_hits must be a non-negative integer")

    candidate_ids = set()
    for rec in iter_candidate_papers(candidates):
        if not isinstance(rec, dict):
            raise ValueError("paper candidates must be objects")
        cid = rec.get("candidate_id") or paper_candidate_id(rec)
        if not isinstance(cid, str) or not cid:
            raise ValueError("every paper candidate requires candidate_id")
        if cid != paper_candidate_id(rec):
            raise ValueError(f"{cid}: candidate_id does not match its source identifier")
        if cid in candidate_ids:
            raise ValueError(f"duplicate candidate_id: {cid}")
        candidate_ids.add(cid)
        if not str(rec.get("title", "")).strip():
            raise ValueError(f"{cid}: title is required")
        tracks = rec.get("track")
        if (
            not isinstance(tracks, list)
            or not tracks
            or any(track not in "ABCDE" for track in tracks)
        ):
            raise ValueError(f"{cid}: track must be a non-empty A-E array")

    for rec in candidates["preprints"]:
        if rec.get("peer_review_status") != "preprint" or not rec.get("epmc_id"):
            raise ValueError("preprint candidates require peer_review_status=preprint and epmc_id")
    for rec in candidates["publication_transitions"]:
        if rec.get("publication_transition") is not True or not rec.get("prior_key"):
            raise ValueError("publication transitions require publication_transition=true and prior_key")
    for rec in candidates["cross_track_updates"]:
        if not rec.get("prior_key") or not isinstance(rec.get("new_tracks"), list):
            raise ValueError("cross-track updates require prior_key and new_tracks")

    trial_ids = set()
    for bucket, expected_event in (
        ("trials_new", "new_registration"),
        ("trials_changed", None),
    ):
        for trial in candidates[bucket]:
            if not isinstance(trial, dict):
                raise ValueError(f"candidates.{bucket} entries must be objects")
            if trial.get("registry") not in KEY_PREFIX:
                raise ValueError(f"candidates.{bucket} has unsupported registry")
            key = trial_key(trial)
            if key.endswith(":") or key in trial_ids:
                raise ValueError(f"invalid or duplicate trial identifier: {key}")
            trial_ids.add(key)
            if expected_event and trial.get("event") != expected_event:
                raise ValueError(f"{key}: new trial must use event={expected_event}")
            if bucket == "trials_changed" and trial.get("event") not in {
                "status_changed",
                "results_posted",
                "early_stop",
                "protocol_record_updated",
            }:
                raise ValueError(f"{key}: invalid changed-trial event")
            if not str(trial.get("title", "")).strip():
                raise ValueError(f"{key}: title is required")
            if not trial.get("protocol_hash"):
                raise ValueError(f"{key}: protocol_hash is required")

    return start, end


def score_value(scores, key, maximum):
    value = scores.get(key)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"score {key} must be an integer from 1 to {maximum}")
    return value


def material_basis_is_valid(basis, claim_type, evidence_basis, s_score, n_score, r_score):
    if basis == "strength_novelty":
        return s_score >= 3 and n_score >= 2
    if basis == "patient_relevance":
        return r_score == 3 and s_score >= 2
    if basis == "negative_result":
        return s_score >= 3
    if basis == "new_safety_signal":
        return claim_type == "safety" and s_score >= 2
    if basis == "guideline_change":
        return (
            claim_type == "guideline"
            and n_score == 3
            and evidence_basis == "guideline_full_text"
        )
    return False


def validate_decisions(candidates, decisions):
    if not isinstance(decisions, dict):
        raise ValueError("decisions must be a JSON object")
    if decisions.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"decisions.schema_version must be {STATE_SCHEMA_VERSION}")

    item_decisions = decisions.get("items")
    if not isinstance(item_decisions, dict):
        raise ValueError("decisions.items must be an object keyed by candidate_id")

    candidate_by_id = {}
    for rec in iter_candidate_papers(candidates):
        cid = rec.get("candidate_id") or paper_candidate_id(rec)
        candidate_by_id[cid] = rec

    expected = set(candidate_by_id)
    actual = set(item_decisions)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        preview = ", ".join(missing[:10])
        more = " ..." if len(missing) > 10 else ""
        raise ValueError(
            "decisions incomplete; refusing to mark unreviewed candidates as seen: " + preview + more
        )
    if unknown:
        preview = ", ".join(unknown[:10])
        more = " ..." if len(unknown) > 10 else ""
        raise ValueError("decisions contains unknown candidate IDs: " + preview + more)

    for cid, rec in candidate_by_id.items():
        decision = item_decisions.get(cid)
        if not isinstance(decision, dict):
            raise ValueError(f"{cid}: decision must be an object")

        verdict = decision.get("verdict")
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"{cid}: invalid verdict {verdict!r}")

        scores = decision.get("scores")
        if not isinstance(scores, dict):
            raise ValueError(f"{cid}: decisions must include explicit S/N/R (R may be 'N/A')")
        try:
            s_score = score_value(scores, "S", 5)
            n_score = score_value(scores, "N", 3)
        except ValueError as ex:
            raise ValueError(f"{cid}: {ex}") from ex
        r_score = scores.get("R")
        if r_score != "N/A" and (type(r_score) is not int or not 1 <= r_score <= 3):
            raise ValueError(f"{cid}: score R must be 1-3 or 'N/A'")

        peer_status = rec.get("peer_review_status", "peer_reviewed")
        stated_status = decision.get("peer_review_status")
        if stated_status is not None and stated_status != peer_status:
            raise ValueError(f"{cid}: decision peer_review_status does not match candidate")
        if peer_status == "preprint":
            if s_score > 3:
                raise ValueError(f"{cid}: preprint provisional S cannot exceed 3")
            if verdict == "material":
                raise ValueError(
                    f"{cid}: a preprint cannot use verdict='material'; "
                    "use preprint_watchlist/appendix/discarded"
                )
        elif verdict == "preprint_watchlist":
            raise ValueError(f"{cid}: preprint_watchlist is only valid for preprints")
        if peer_status == "book_chapter":
            if verdict == "material":
                raise ValueError(f"{cid}: book chapters cannot be material evidence")
            if s_score != 1 or n_score != 1:
                raise ValueError(f"{cid}: book chapters must use S=1 and N=1")

        paradigm_status = decision.get("paradigm_status")
        if paradigm_status is not None and paradigm_status not in PARADIGM_STATUSES:
            raise ValueError(f"{cid}: invalid paradigm_status {paradigm_status!r}")

        if verdict == "material":
            evidence_basis = decision.get("evidence_basis")
            if evidence_basis not in ("full_text", "abstract_only", "guideline_full_text"):
                raise ValueError(f"{cid}: material item requires explicit evidence_basis")
            claim_type = decision.get("claim_type")
            if claim_type not in CLAIM_TYPES:
                raise ValueError(f"{cid}: material item requires a valid claim_type")
            if (claim_type == "guideline") != (evidence_basis == "guideline_full_text"):
                raise ValueError(
                    f"{cid}: guideline claims require guideline_full_text, "
                    "which is only valid for guideline claims"
                )
            directness = decision.get("population_directness")
            if directness not in POPULATION_DIRECTNESS:
                raise ValueError(f"{cid}: material item requires population_directness")
            for field in ("what_this_changes", "what_this_does_not_prove"):
                if not isinstance(decision.get(field), str) or not decision[field].strip():
                    raise ValueError(f"{cid}: material item requires non-empty {field}")
            basis = decision.get("material_basis")
            if basis not in MATERIAL_BASES:
                raise ValueError(f"{cid}: material item requires a valid material_basis")
            if not material_basis_is_valid(
                basis,
                claim_type,
                evidence_basis,
                s_score,
                n_score,
                r_score,
            ):
                raise ValueError(f"{cid}: scores/claim do not satisfy material_basis={basis}")


def source_status_index(candidates, state):
    index = {}
    for key, entry in (state or {}).get("seen", {}).items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("peer_review_status")
        index[key] = status
        doi = norm_doi(entry.get("doi", ""))
        if doi:
            index[doi] = status
            index["DOI:" + doi] = status

    for rec in iter_candidate_papers(candidates):
        status = rec.get("peer_review_status", "peer_reviewed")
        cid = rec.get("candidate_id") or paper_candidate_id(rec)
        index[cid] = status
        doi = norm_doi(rec.get("doi", ""))
        if doi:
            index[doi] = status
            index["DOI:" + doi] = status
    return index


def validate_baseline(baseline, candidates, state):
    if not isinstance(baseline, dict):
        raise ValueError("decisions.baseline must be an object")
    missing_sections = BASELINE_SECTIONS - set(baseline)
    unknown_sections = set(baseline) - BASELINE_SECTIONS
    if missing_sections or unknown_sections:
        raise ValueError(
            "baseline sections must be exactly "
            + ", ".join(sorted(BASELINE_SECTIONS))
        )

    source_index = source_status_index(candidates, state)
    for section, claims in baseline.items():
        if not isinstance(claims, list):
            raise ValueError(f"baseline.{section} must be an array")
        for position, claim in enumerate(claims):
            label = f"baseline.{section}[{position}]"
            if not isinstance(claim, dict):
                raise ValueError(f"{label} must be an object")
            if not isinstance(claim.get("claim"), str) or not claim["claim"].strip():
                raise ValueError(f"{label}.claim must be non-empty")
            strength = claim.get("strength")
            if type(strength) is not int or not 1 <= strength <= 5:
                raise ValueError(f"{label}.strength must be 1-5")
            parse_iso_date(claim.get("updated"), f"{label}.updated")
            sources = claim.get("sources")
            if not isinstance(sources, list) or not sources:
                raise ValueError(f"{label}.sources must be a non-empty array")
            for source in sources:
                if not isinstance(source, str) or not source.strip():
                    raise ValueError(f"{label}.sources entries must be non-empty strings")
                source = source.strip()
                if source.startswith("PPR:"):
                    raise ValueError(f"{label} contains preprint source {source}")
                status = source_index.get(source)
                if status is None:
                    doi = norm_doi(source)
                    status = source_index.get(doi) or source_index.get("DOI:" + doi)
                if status in ("preprint", "book_chapter"):
                    raise ValueError(f"{label} contains ineligible {status} source {source}")
                if status is None and not (
                    section == "guidelines" and source.startswith("https://")
                ):
                    raise ValueError(
                        f"{label} source {source} is unknown; use a canonical PMID or guideline URL"
                    )


def validate_brief(decisions, candidates):
    value = decisions.get("brief_path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("decisions.brief_path is required")
    path = value if os.path.isabs(value) else os.path.join(ROOT, value)
    path = require_path_within_out(os.path.abspath(path), "brief_path", ".md")
    expected_name = f"brief-{candidates['period']}-{candidates['run_id']}.md"
    if os.path.basename(path) != expected_name:
        raise ValueError(f"brief_path filename must be {expected_name}")
    try:
        with open(path, "rb") as f:
            content = f.read(MAX_REPORT_BYTES + 1)
    except OSError as ex:
        raise ValueError(f"brief_path cannot be read: {path}: {ex}") from ex
    if not content:
        raise ValueError("brief_path is empty")
    if len(content) > MAX_REPORT_BYTES:
        raise ValueError(f"brief exceeds the {MAX_REPORT_BYTES}-byte archive limit")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as ex:
        raise ValueError("brief must be UTF-8 Markdown") from ex

    run_marker = f"<!-- med-skill-run-id: {candidates['run_id']} -->"
    period_marker = f"<!-- med-skill-period: {candidates['period']} -->"
    for marker in (run_marker, period_marker):
        if marker not in text:
            raise ValueError(f"brief is missing required marker: {marker}")
    for phrase in ("不构成医疗建议", "不替代临床诊疗"):
        if phrase not in text:
            raise ValueError(f"brief is missing required safety statement: {phrase}")
    return path, content, sha256_bytes(content)


def publish_report(report_content, candidates, report_repo):
    expected_repo = candidates.get("report_repository", "")
    if report_repo.lower() != expected_repo.lower():
        raise ValueError(
            f"--report-repo {report_repo} does not match candidate artifact {expected_repo}"
        )

    metadata = run_gh_json(
        [
            "repo",
            "view",
            report_repo,
            "--json",
            "nameWithOwner,visibility,defaultBranchRef,url",
        ]
    )
    if metadata.get("visibility") != "PRIVATE":
        raise RuntimeError(
            f"report repository {report_repo} must be private before health-related reports are archived"
        )

    canonical_repo = metadata.get("nameWithOwner") or report_repo
    default_branch = (metadata.get("defaultBranchRef") or {}).get("name")
    if not default_branch:
        raise RuntimeError(f"report repository {canonical_repo} has no default branch")

    period = candidates["period"]
    run_id = candidates["run_id"]
    remote_path = report_archive_path(period, run_id)
    endpoint = f"repos/{canonical_repo}/contents/{remote_path}"
    existing = run_gh_json(["api", endpoint], allow_not_found=True)
    if existing is not None:
        encoded = existing.get("content")
        if existing.get("encoding") != "base64" or not isinstance(encoded, str):
            raise RuntimeError(f"cannot verify existing archived report {remote_path}")
        try:
            existing_content = base64.b64decode(encoded)
        except (ValueError, binascii.Error) as ex:
            raise RuntimeError(f"existing archived report has invalid base64: {remote_path}") from ex
        if existing_content != report_content:
            raise RuntimeError(f"archive collision: {remote_path} already exists with different content")
        commits_endpoint = (
            f"repos/{canonical_repo}/commits?"
            + urllib.parse.urlencode({"path": remote_path, "per_page": 1})
        )
        commits = run_gh_json(["api", commits_endpoint])
        if not isinstance(commits, list):
            raise RuntimeError(f"cannot resolve the commit for existing report {remote_path}")
        return {
            "repository": canonical_repo,
            "repository_url": metadata.get("url", ""),
            "path": remote_path,
            "url": existing.get("html_url", ""),
            "file_sha": existing.get("sha", ""),
            "commit_sha": commits[0].get("sha", "") if commits else "",
        }

    result = run_gh_json(
        ["api", "--method", "PUT", endpoint, "--input", "-"],
        input_obj={
            "message": f"Archive med-skill report {period} ({run_id})",
            "content": base64.b64encode(report_content).decode("ascii"),
            "branch": default_branch,
        },
    )
    archived = result.get("content") or {}
    commit = result.get("commit") or {}
    if archived.get("path") != remote_path:
        raise RuntimeError("GitHub did not confirm the expected report archive path")
    return {
        "repository": canonical_repo,
        "repository_url": metadata.get("url", ""),
        "path": remote_path,
        "url": archived.get("html_url", ""),
        "file_sha": archived.get("sha", ""),
        "commit_sha": commit.get("sha", ""),
    }


def prepare_state(state, candidates):
    if state is None:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "queries_version": candidates.get("queries_version"),
            "seen": {},
            "baseline": {section: [] for section in sorted(BASELINE_SECTIONS)},
            "runs": [],
        }
    if not isinstance(state, dict):
        raise ValueError("state must be a JSON object")
    if state.get("schema_version") not in (2, STATE_SCHEMA_VERSION):
        raise ValueError(
            f"unsupported state schema_version {state.get('schema_version')!r}"
        )
    if not isinstance(state.get("seen"), dict) or not isinstance(state.get("runs"), list):
        raise ValueError("state.seen must be an object and state.runs must be an array")
    state.setdefault(
        "baseline",
        {section: [] for section in sorted(BASELINE_SECTIONS)},
    )
    return state


def existing_run_entry(state, run_id):
    matches = [
        run for run in state.get("runs", [])
        if isinstance(run, dict) and run.get("run_id") == run_id
    ]
    if len(matches) > 1:
        raise ValueError(f"state contains duplicate run_id {run_id}")
    return matches[0] if matches else None


def validate_commit_order(state, candidates):
    current_end = state.get("window_end_edat")
    candidate_end = parse_iso_date(candidates["window"][1], "candidates.window[1]")
    if current_end:
        prior_end = parse_iso_date(current_end, "state.window_end_edat")
        if candidate_end < prior_end:
            raise ValueError(
                f"stale candidate window ends {candidate_end}, before committed cursor {prior_end}"
            )
    current_query_version = state.get("queries_version")
    if (
        type(current_query_version) is int
        and candidates["queries_version"] < current_query_version
    ):
        raise ValueError(
            "candidate queries_version is older than the committed state queries_version"
        )


def commit_phase(args):
    if not args.candidates or not args.decisions:
        raise ValueError("--commit-state requires --candidates and --decisions")

    candidates, candidates_path, candidates_sha = read_json_artifact(
        args.candidates, "candidates"
    )
    decisions, decisions_path, decisions_sha = read_json_artifact(
        args.decisions, "decisions"
    )
    candidates_path = require_path_within_out(candidates_path, "candidates", ".json")
    decisions_path = require_path_within_out(decisions_path, "decisions", ".json")

    validate_candidate_artifact(candidates)
    expected_candidate_name = (
        f"candidates-{candidates['period']}-{candidates['run_id']}.json"
    )
    expected_decisions_name = (
        f"decisions-{candidates['period']}-{candidates['run_id']}.json"
    )
    if os.path.basename(candidates_path) != expected_candidate_name:
        raise ValueError(f"candidates filename must be {expected_candidate_name}")
    if os.path.basename(decisions_path) != expected_decisions_name:
        raise ValueError(f"decisions filename must be {expected_decisions_name}")
    if candidates.get("run_id") != decisions.get("run_id"):
        raise ValueError("run_id mismatch: refusing state commit")
    if decisions.get("brief_generated") is not True:
        raise ValueError("decisions.brief_generated must be true")
    validate_decisions(candidates, decisions)
    brief_path, brief_content, brief_sha = validate_brief(decisions, candidates)

    with state_lock():
        state = prepare_state(load_state(), candidates)
        baseline = decisions.get("baseline")
        effective_baseline = baseline if baseline is not None else state.get("baseline")
        validate_baseline(effective_baseline, candidates, state)

        existing_run = existing_run_entry(state, candidates["run_id"])
        if existing_run is None:
            validate_commit_order(state, candidates)
        else:
            if existing_run.get("window") and existing_run["window"] != candidates["window"]:
                raise ValueError(
                    f"run_id {candidates['run_id']} was already committed with a different window"
                )
            for field, expected in (
                ("candidates_sha256", candidates_sha),
                ("decisions_sha256", decisions_sha),
                ("brief_sha256", brief_sha),
            ):
                prior = existing_run.get(field)
                if prior and prior != expected:
                    raise ValueError(
                        f"run_id {candidates['run_id']} was already committed with a different {field}"
                    )

        report_archive = publish_report(brief_content, candidates, args.report_repo)
        relative_brief = os.path.relpath(brief_path, ROOT).replace(os.sep, "/")

        if existing_run is not None:
            existing_run.update({
                "brief_path": relative_brief,
                "candidates_path": os.path.relpath(candidates_path, ROOT).replace(os.sep, "/"),
                "decisions_path": os.path.relpath(decisions_path, ROOT).replace(os.sep, "/"),
                "candidates_sha256": candidates_sha,
                "decisions_sha256": decisions_sha,
                "brief_sha256": brief_sha,
                "report_archive": report_archive,
            })
            state["schema_version"] = STATE_SCHEMA_VERSION
            write_json_atomic(STATE_PATH, state)
            print(
                f"-> run {candidates['run_id']} already committed; report archive verified",
                file=sys.stderr,
            )
            return

        seen = state.setdefault("seen", {})
        item_decisions = decisions["items"]
        today = date.today()

        for rec in iter_candidate_papers(candidates):
            cid = rec.get("candidate_id") or paper_candidate_id(rec)
            decision = item_decisions[cid]

            if rec.get("peer_review_status") == "preprint":
                key = "PPR:" + rec.get("epmc_id", "")
            else:
                key = "PMID:" + rec.get("pmid", "") if rec.get("pmid") else cid

            entry = seen.setdefault(key, {"first_seen": str(today), "track": []})
            entry["track"] = sorted(set(entry.get("track", []) + rec.get("track", [])))
            entry["doi"] = norm_doi(rec.get("doi", ""))
            entry["title_norm"] = norm_title(rec.get("title", ""))
            entry["peer_review_status"] = rec.get("peer_review_status", "peer_reviewed")
            entry["retrieval_depth"] = decision.get(
                "evidence_basis", rec.get("retrieval_depth", "abstract")
            )
            entry["verdict"] = decision.get("verdict")
            entry["scores"] = decision.get("scores")
            entry["paradigm_status"] = decision.get("paradigm_status")

            if rec.get("peer_review_status") == "preprint":
                entry["is_preprint"] = True

            prior_key = rec.get("prior_key")
            if rec.get("publication_transition") and prior_key in seen:
                seen[prior_key]["superseded_by"] = key
                entry["supersedes"] = prior_key

        for trial in candidates.get("trials_new", []) + candidates.get("trials_changed", []):
            key = trial_key(trial)
            entry = seen.setdefault(key, {"first_seen": str(today), "track": ["F"]})
            entry.update({
                "registry": trial.get("registry"),
                "last_status": trial.get("status"),
                "has_results": trial.get("has_results"),
                "protocol_hash": trial.get("protocol_hash"),
                "title_norm": norm_title(trial.get("title", "")),
                "last_update_posted": trial.get("last_update_posted", ""),
            })

        if baseline is not None:
            state["baseline"] = baseline

        material_count = sum(
            1 for decision in item_decisions.values()
            if decision.get("verdict") == "material"
        )
        state["schema_version"] = STATE_SCHEMA_VERSION
        state["queries_version"] = candidates.get("queries_version")
        state["last_run"] = str(today)
        state["window_end_edat"] = candidates["window"][1]
        state.setdefault("runs", []).append({
            "run_id": candidates.get("run_id"),
            "date": str(today),
            "window": candidates.get("window"),
            "hits": candidates.get("counts", {}).get("pubmed_unique_hits", 0),
            "material": material_count,
            "brief_generated": True,
            "brief_path": relative_brief,
            "candidates_path": os.path.relpath(candidates_path, ROOT).replace(os.sep, "/"),
            "decisions_path": os.path.relpath(decisions_path, ROOT).replace(os.sep, "/"),
            "candidates_sha256": candidates_sha,
            "decisions_sha256": decisions_sha,
            "brief_sha256": brief_sha,
            "report_archive": report_archive,
        })
        write_json_atomic(STATE_PATH, state)
        print(
            "-> state/seen.json committed after private report archive: "
            + report_archive["path"],
            file=sys.stderr,
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--commit-state", action="store_true")
    ap.add_argument("--candidates")
    ap.add_argument("--decisions")
    ap.add_argument(
        "--report-repo",
        default=REPORT_REPO_DEFAULT,
        help="private GitHub owner/repo used to archive generated reports",
    )
    args = ap.parse_args()

    if bool(args.start) != bool(args.end):
        ap.error("--start and --end must be provided together")
    if args.commit_state:
        if args.start or args.end or args.bootstrap:
            ap.error("--commit-state cannot be combined with fetch window options")
        if not args.candidates or not args.decisions:
            ap.error("--commit-state requires --candidates and --decisions")
    elif args.candidates or args.decisions:
        ap.error("--candidates and --decisions are only valid with --commit-state")

    try:
        if args.commit_state:
            commit_phase(args)
        else:
            fetch_phase(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as ex:
        sys.exit(str(ex))


if __name__ == "__main__":
    main()
