#!/usr/bin/env python3
"""Deterministic evidence retrieval and state management for med-skill.

Fetch phase:
    python scripts/fetch_evidence.py
    python scripts/fetch_evidence.py --bootstrap
    python scripts/fetch_evidence.py --start 2026-07-01 --end 2026-08-23

Commit phase (NO network):
    python scripts/fetch_evidence.py --commit-state \
      --candidates out/candidates-2026-08.json \
      --decisions out/decisions-2026-08.json
"""

import argparse
import hashlib
import json
import os
import re
import sys
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

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
ISRCTN = "https://www.isrctn.com/api/query/format/default"
CTIS = "https://euclinicaltrials.eu/ctis-public-api/search"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ISRCTN_NS = "{http://www.67bricks.com/isrctn}"

API_KEY = os.environ.get("NCBI_API_KEY", "")
SLEEP = 0.11 if API_KEY else 0.34
WINDOW_OVERLAP_DAYS = 15
MAX_PUBMED_ESEARCH = 10000
UA = "med-skill-evidence-surveillance/0.3"
KEY_PREFIX = {"CTGOV": "NCT:", "ISRCTN": "ISRCTN:", "CTIS": "CTIS:"}
VALID_VERDICTS = {"material", "appendix", "preprint_watchlist", "discarded"}


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


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
    base = {"db": "pubmed", "term": term, "retmode": "json"}
    if API_KEY:
        base["api_key"] = API_KEY

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
    return ids


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


def efetch_pubmed(pmids, chunk_size=100):
    out = {}
    for i in range(0, len(pmids), chunk_size):
        chunk = pmids[i:i + chunk_size]
        p = {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}
        if API_KEY:
            p["api_key"] = API_KEY
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
        "(nephrotic syndrome OR minimal change disease OR steroid sensitive nephrotic syndrome "
        "OR steroid dependent nephrotic syndrome OR frequently relapsing nephrotic syndrome)"
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


def fetch_isrctn(start, end):
    query = '"nephrotic syndrome" OR "minimal change disease"'
    xml = http_text(ISRCTN + "?" + urllib.parse.urlencode({"q": query, "limit": 500}))
    root = ET.fromstring(xml)
    out = []
    for full in root.findall(ISRCTN_NS + "fullTrial"):
        tr = full.find(ISRCTN_NS + "trial")
        if tr is None:
            continue
        updated = parse_date_loose(tr.attrib.get("lastUpdated", ""))
        if not updated or not (start <= updated <= end):
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
    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        return start, end, "bootstrap" if args.bootstrap else "delta"
    if args.bootstrap or state is None:
        return today - timedelta(days=730), today, "bootstrap"
    prev = datetime.strptime(state["window_end_edat"], "%Y-%m-%d").date()
    return prev - timedelta(days=WINDOW_OVERLAP_DAYS), today, "delta"


def paper_candidate_id(rec):
    if rec.get("pmid"):
        return "PMID:" + rec["pmid"]
    if rec.get("epmc_id"):
        return "PPR:" + rec["epmc_id"]
    if rec.get("doi"):
        return "DOI:" + norm_doi(rec["doi"])
    return "TITLE:" + hashlib.sha256(norm_title(rec.get("title", "")).encode("utf-8")).hexdigest()[:16]


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
    state = load_state()
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
        "schema_version": 2,
        "run_id": run_id,
        "period": period,
        "mode": mode,
        "window": [str(start), str(end)],
        "queries_version": qver,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "core_sources_complete": True,
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
    out_path = os.path.join(OUT_DIR, "candidates-" + period + ".json")
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


def validate_no_preprint_baseline(baseline):
    for section, claims in (baseline or {}).items():
        if not isinstance(claims, list):
            continue
        for claim in claims:
            for src in claim.get("sources", []) if isinstance(claim, dict) else []:
                if str(src).startswith("PPR:"):
                    raise ValueError(f"baseline {section} contains preprint-only source {src}")


def validate_decisions(candidates, decisions):
    item_decisions = decisions.get("items")
    if not isinstance(item_decisions, dict):
        raise ValueError("decisions.items must be an object keyed by candidate_id")

    missing = []
    for rec in iter_candidate_papers(candidates):
        cid = rec.get("candidate_id") or paper_candidate_id(rec)
        decision = item_decisions.get(cid)
        if not isinstance(decision, dict):
            missing.append(cid)
            continue

        verdict = decision.get("verdict")
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"{cid}: invalid verdict {verdict!r}")

        scores = decision.get("scores")
        if not isinstance(scores, dict) or "S" not in scores or "N" not in scores or "R" not in scores:
            raise ValueError(f"{cid}: decisions must include explicit S/N/R (R may be 'N/A')")

        if rec.get("peer_review_status") == "preprint" and verdict == "material":
            raise ValueError(f"{cid}: a preprint cannot use verdict='material'; use preprint_watchlist/appendix/discarded")

        if verdict == "material":
            evidence_basis = decision.get("evidence_basis")
            if evidence_basis not in ("full_text", "abstract_only", "guideline_full_text"):
                raise ValueError(f"{cid}: material item requires explicit evidence_basis")

    if missing:
        preview = ", ".join(missing[:10])
        more = " ..." if len(missing) > 10 else ""
        raise ValueError(
            "decisions incomplete; refusing to mark unreviewed candidates as seen: " + preview + more
        )


def commit_phase(args):
    if not args.candidates or not args.decisions:
        sys.exit("--commit-state requires --candidates and --decisions")

    with open(args.candidates, encoding="utf-8") as f:
        candidates = json.load(f)
    with open(args.decisions, encoding="utf-8") as f:
        decisions = json.load(f)

    if candidates.get("run_id") != decisions.get("run_id"):
        sys.exit("run_id mismatch: refusing state commit")
    if decisions.get("brief_generated") is not True:
        sys.exit("decisions.brief_generated must be true")

    try:
        validate_decisions(candidates, decisions)
        baseline = decisions.get("baseline")
        if baseline is not None:
            validate_no_preprint_baseline(baseline)
    except ValueError as ex:
        sys.exit("decision validation failed: " + str(ex))

    state = load_state() or {
        "schema_version": 2,
        "queries_version": candidates.get("queries_version"),
        "seen": {},
        "baseline": {},
        "runs": [],
    }
    state["schema_version"] = 2
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
        entry["retrieval_depth"] = decision.get("evidence_basis", rec.get("retrieval_depth", "abstract"))
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

    material_count = sum(1 for decision in item_decisions.values() if decision.get("verdict") == "material")
    state["queries_version"] = candidates.get("queries_version")
    state["last_run"] = str(today)
    state["window_end_edat"] = candidates.get("window", ["", ""])[1]
    state.setdefault("runs", []).append({
        "run_id": candidates.get("run_id"),
        "date": str(today),
        "window": candidates.get("window"),
        "hits": candidates.get("counts", {}).get("pubmed_unique_hits", 0),
        "material": material_count,
        "brief_generated": True,
        "brief_path": decisions.get("brief_path", ""),
    })
    write_json_atomic(STATE_PATH, state)
    print("-> state/seen.json committed from exact candidate + decisions artifacts", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--commit-state", action="store_true")
    ap.add_argument("--candidates")
    ap.add_argument("--decisions")
    args = ap.parse_args()

    if args.commit_state:
        commit_phase(args)
    else:
        fetch_phase(args)


if __name__ == "__main__":
    main()
