#!/usr/bin/env python3
"""检索 / 抓取 / 去重 / 试验状态差分。

确定性工作全部在这里完成，模型只负责解读、打分和撰写中文简报。
只用标准库，无第三方依赖。

用法:
    python scripts/fetch_evidence.py                      # 用 state 推导窗口
    python scripts/fetch_evidence.py --start 2026-06-16 --end 2026-07-31
    python scripts/fetch_evidence.py --bootstrap          # 首次运行，24 个月窗口
    python scripts/fetch_evidence.py --commit-state       # 简报生成成功后回写 state

输出: out/candidates-YYYY-MM.json —— 待模型打分的新增/变更条目。
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

# Windows 控制台默认非 UTF-8，中文日志会乱码
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
SLEEP = 0.11 if API_KEY else 0.34          # 10 req/s with key, 3 req/s without
WINDOW_OVERLAP_DAYS = 15
UA = "med-skill-evidence-surveillance/0.2 (+https://github.com/Alanjiao1988/med-skill)"


# ---------- 基础工具 ----------

def http_json(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def http_text(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return ""


def http_post_json(url, body, retries=3):
    payload = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"User-Agent": UA, "Content-Type": "application/json",
                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def parse_date_loose(s):
    """接受 2026-08-20、2026-08-20T…、20/08/2026 三种格式；解析不了返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def norm_title(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", (t or "").lower())).strip()


def norm_doi(d):
    d = (d or "").strip().lower()
    return re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)


# ---------- 检索式解析: search-queries.md 是唯一真源 ----------

def load_queries():
    """从 references/search-queries.md 解析通用片段与各 track 检索式。"""
    with open(QUERIES_MD, encoding="utf-8") as f:
        md = f.read()

    frag = {}
    common = re.search(r"## 通用片段.*?```(.*?)```", md, re.S)
    if not common:
        sys.exit("search-queries.md: 找不到通用片段代码块")
    for name, body in re.findall(r"\{(\w+)\}\s*=\s*\n(.*?)(?=\n\{|\Z)", common.group(1), re.S):
        frag[name] = " ".join(body.split())

    version = 1
    m = re.search(r"queries_version:\s*(\d+)", md)
    if m:
        version = int(m.group(1))

    tracks = {}
    for letter, body in re.findall(r"## Track ([A-F]) —[^\n]*\n+```(.*?)```", md, re.S):
        tracks[letter] = " ".join(body.split())
    # track F 走 ClinicalTrials.gov 客户端，不经 PubMed 检索式
    missing = set("ABCDE") - set(tracks)
    if missing:
        sys.exit("search-queries.md: 缺少 track " + str(sorted(missing)))
    return version, frag, tracks


def build_term(raw, frag, start, end):
    window = '("{:%Y/%m/%d}"[EDAT] : "{:%Y/%m/%d}"[EDAT])'.format(start, end)
    term = raw.replace("{WINDOW}", window)
    for name, body in frag.items():
        if name == "WINDOW":
            continue
        term = term.replace("{" + name + "}", "(" + body + ")")
    if "[PDAT]" in term:
        sys.exit("检索式使用了 [PDAT]。必须用 [EDAT]，见 SKILL.md 检索实现要点。")
    return term


# ---------- PubMed ----------

def esearch(term, retmax=400):
    p = {"db": "pubmed", "term": term, "retmode": "json", "retmax": retmax}
    if API_KEY:
        p["api_key"] = API_KEY
    data = http_json(EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(p))
    time.sleep(SLEEP)
    res = data.get("esearchresult", {})
    ids = res.get("idlist", [])
    if int(res.get("count", 0)) > retmax:
        print("  ! 命中 " + str(res["count"]) + " 条，超过 retmax=" + str(retmax) + "，已截断",
              file=sys.stderr)
    return ids


def esummary(pmids):
    out = {}
    for i in range(0, len(pmids), 200):
        chunk = pmids[i:i + 200]
        p = {"db": "pubmed", "id": ",".join(chunk), "retmode": "json"}
        if API_KEY:
            p["api_key"] = API_KEY
        data = http_json(EUTILS + "/esummary.fcgi?" + urllib.parse.urlencode(p))
        time.sleep(SLEEP)
        result = data.get("result", {})
        for pmid in result.get("uids", []):
            r = result[pmid]
            doi = ""
            for aid in r.get("articleids", []):
                if aid.get("idtype") == "doi":
                    doi = norm_doi(aid.get("value"))
            out[pmid] = {
                "pmid": pmid,
                "title": r.get("title", ""),
                "journal": r.get("fulljournalname") or r.get("source", ""),
                "pubdate": r.get("pubdate", ""),
                "epubdate": r.get("epubdate", ""),
                "doi": doi,
                "pubtypes": r.get("pubtype", []),
                "authors": [a.get("name") for a in r.get("authors", [])][:6],
                "url": "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
            }
    return out


# ---------- ClinicalTrials.gov ----------

def flatten_trial(s):
    ps = s.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    elig = ps.get("eligibilityModule", {})
    phases = ",".join(design.get("phases", []) or [])
    has_results = bool(s.get("hasResults"))
    pcd = (status.get("primaryCompletionDateStruct") or {}).get("date", "")
    overall = status.get("overallStatus", "")
    nct = ident.get("nctId", "")
    raw = overall + "|" + phases + "|" + str(has_results) + "|" + pcd
    return {
        "registry": "CTGOV",
        "id": nct,
        "nct": nct,
        "title": ident.get("briefTitle", ""),
        "status": overall,
        "phases": phases,
        "has_results": has_results,
        "min_age": elig.get("minimumAge", ""),
        "std_ages": elig.get("stdAges", []),
        "primary_completion": pcd,
        "last_update_posted": (status.get("lastUpdatePostDateStruct") or {}).get("date", ""),
        "url": "https://clinicaltrials.gov/study/" + nct,
        "status_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
    }


def fetch_trials(start, end):
    studies, token = [], None
    date_range = "AREA[LastUpdatePostDate]RANGE[{:%Y-%m-%d},{:%Y-%m-%d}]".format(start, end)
    while True:
        p = {
            "query.cond": "nephrotic syndrome OR minimal change disease",
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
        time.sleep(0.2)
        if not token:
            break
    return [flatten_trial(s) for s in studies]


# ---------- ISRCTN ----------

def _isrctn_text(node, path):
    if node is None:
        return ""
    el = node.find(ISRCTN_NS + path)
    return (el.text or "").strip() if el is not None else ""


def fetch_isrctn(start, end):
    """ISRCTN 无可用的服务端日期过滤，命中量小（nephrotic 全库 ~60 条），
    因此全量取回后按 lastUpdated 在客户端过滤。"""
    xml = http_text(ISRCTN + "?" + urllib.parse.urlencode(
        {"q": "nephrotic syndrome OR minimal change disease", "limit": 500}))
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
        # ISRCTN 不暴露统一的 overallStatus；version 每次编辑递增，是最可靠的变更信号
        version = tr.attrib.get("version", "")
        pub_stage = _isrctn_text(res, "publicationStage")
        raw = "|".join([version, _isrctn_text(design, "overallEndDate"),
                        _isrctn_text(part, "recruitmentEnd"), pub_stage])
        out.append({
            "registry": "ISRCTN",
            "id": rid,
            "nct": rid,                       # 复用统一 key 前缀逻辑
            "title": _isrctn_text(desc, "title") or _isrctn_text(desc, "scientificTitle"),
            "status": "version " + version + (" · " + pub_stage if pub_stage else ""),
            "phases": _isrctn_text(design, "phase"),
            "has_results": bool(pub_stage),
            "min_age": _isrctn_text(part, "lowerAgeLimit"),
            "std_ages": [_isrctn_text(part, "ageRange")],
            "primary_completion": _isrctn_text(design, "overallEndDate")[:10],
            "last_update_posted": str(updated),
            "url": "https://www.isrctn.com/" + rid,
            "status_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
        })
    return out


# ---------- EU CTIS ----------

def fetch_ctis(start, end):
    """CTIS 无服务端日期过滤，按 lastUpdated 在客户端过滤。
    ctStatus 是不透明的整数码，原样保留，不臆造标签。"""
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
            has_results = str(r.get("resultsFirstReceived", "")).lower() == "yes"
            raw = "|".join([str(r.get("ctStatus", "")), str(r.get("trialPhase", "")),
                            str(has_results), str(r.get("decisionDateOverall", ""))])
            out.append({
                "registry": "CTIS",
                "id": ct,
                "nct": ct,
                "title": r.get("ctTitle", ""),
                "status": "ctStatus=" + str(r.get("ctStatus", "")),
                "phases": r.get("trialPhase", ""),
                "has_results": has_results,
                "min_age": "",
                "std_ages": [a.strip() for a in str(r.get("ageGroup", "")).split(",") if a.strip()],
                "primary_completion": "",
                "conditions": r.get("conditions", ""),
                "last_update_posted": str(updated),
                "url": "https://euclinicaltrials.eu/ctis-public/view/" + ct,
                "status_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
            })
        pg = (data or {}).get("pagination", {})
        if not pg.get("nextPage"):
            break
        page += 1
        time.sleep(0.3)
    return out


# ---------- 预印本 (Europe PMC) ----------

def fetch_preprints(start, end):
    """Europe PMC 的 SRC:PPR 覆盖 medRxiv / bioRxiv 等预印本服务器。
    预印本按 rubric 的降级规则扣 1 分；预印本转正式发表由 title_norm 去重捕捉。"""
    query = ('("nephrotic syndrome" OR "minimal change disease" OR "podocyte") '
             'AND SRC:PPR AND FIRST_PDATE:[{:%Y-%m-%d} TO {:%Y-%m-%d}]'.format(start, end))
    out, cursor = [], "*"
    while True:
        p = {"query": query, "format": "json", "pageSize": 100,
             "resultType": "core", "cursorMark": cursor}
        data = http_json(EPMC + "?" + urllib.parse.urlencode(p))
        rows = (data or {}).get("resultList", {}).get("result", [])
        for r in rows:
            out.append({
                "source": "preprint",
                "epmc_id": r.get("id", ""),
                "pmid": r.get("pmid", ""),
                "doi": norm_doi(r.get("doi")),
                "title": r.get("title", ""),
                "journal": r.get("publisher") or "preprint",
                "pubdate": r.get("firstPublicationDate", ""),
                "pubtypes": ["Preprint"],
                "track": ["A"],
                "url": "https://europepmc.org/article/PPR/" + r.get("id", ""),
            })
        nxt = (data or {}).get("nextCursorMark")
        if not rows or not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)
    return out


# ---------- state ----------

def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_state_atomic(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


KEY_PREFIX = {"CTGOV": "NCT:", "ISRCTN": "ISRCTN:", "CTIS": "CTIS:"}


def trial_key(t):
    """CTGOV 沿用历史的 NCT: 前缀，保持既有 state 兼容。"""
    return KEY_PREFIX.get(t.get("registry", "CTGOV"), "TRIAL:") + t["id"]


def seen_key_lookup(seen, rec):
    """按 PMID -> 注册号 -> DOI -> 规范化标题 的顺序查找已有条目。"""
    if rec.get("pmid") and "PMID:" + rec["pmid"] in seen:
        return "PMID:" + rec["pmid"]
    if rec.get("registry") and rec.get("id") and trial_key(rec) in seen:
        return trial_key(rec)
    if rec.get("epmc_id") and "PPR:" + rec["epmc_id"] in seen:
        return "PPR:" + rec["epmc_id"]
    doi, tn = norm_doi(rec.get("doi")), norm_title(rec.get("title"))
    for k, v in seen.items():
        if doi and v.get("doi") == doi:
            return k
        if tn and v.get("title_norm") == tn:
            return k
    return None


# ---------- 主流程 ----------

def resolve_window(args, state, today):
    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        return start, end, "bootstrap" if args.bootstrap else "delta"
    if args.bootstrap or state is None:
        if state is None and not args.bootstrap:
            print("! state/seen.json 不存在，自动进入 bootstrap 模式", file=sys.stderr)
        return today - timedelta(days=730), today, "bootstrap"
    prev = datetime.strptime(state["window_end_edat"], "%Y-%m-%d").date()
    return prev - timedelta(days=WINDOW_OVERLAP_DAYS), today, "delta"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--bootstrap", action="store_true", help="24 个月窗口，建立基线")
    ap.add_argument("--commit-state", action="store_true",
                    help="简报生成成功后调用，回写 state；否则只产出 candidates")
    args = ap.parse_args()

    state = load_state()
    today = date.today()
    start, end, mode = resolve_window(args, state, today)

    qver, frag, tracks = load_queries()
    if state and state.get("queries_version") not in (None, qver):
        print("! 检索式版本变更 " + str(state["queries_version"]) + " -> " + str(qver) +
              "，本期新增可能含追溯性命中，须在简报中标注", file=sys.stderr)

    seen = (state or {}).get("seen", {})
    source_errors = []
    print("窗口 " + str(start) + " ~ " + str(end) + " · 模式 " + mode +
          " · 检索式 v" + str(qver), file=sys.stderr)

    # --- PubMed track A-E ---
    hits, pmid_tracks = {}, {}
    for letter in "ABCDE":
        term = build_term(tracks[letter], frag, start, end)
        ids = esearch(term)
        print("Track " + letter + ": " + str(len(ids)) + " 条", file=sys.stderr)
        for pid in ids:
            pmid_tracks.setdefault(pid, []).append(letter)
    if pmid_tracks:
        hits = esummary(list(pmid_tracks))

    new_papers, confirm_papers = [], []
    for pmid, rec in hits.items():
        rec["track"] = pmid_tracks.get(pmid, [])          # 跨 track 命中保留为数组
        key = seen_key_lookup(seen, rec)
        if key:
            rec["dedup_key"] = key
            rec["prior_verdict"] = seen[key].get("verdict")
            newt = [t for t in rec["track"] if t not in seen[key].get("track", [])]
            if newt:
                rec["new_tracks"] = newt
                confirm_papers.append(rec)
        else:
            new_papers.append(rec)

    # --- track F: 追踪状态变更，不只是新出现；三个注册库 ---
    trials = []
    for label, fn in (("ClinicalTrials.gov", fetch_trials),
                      ("ISRCTN", fetch_isrctn),
                      ("EU CTIS", fetch_ctis)):
        try:
            got = fn(start, end)
            trials.extend(got)
            print("  " + label + ": " + str(len(got)) + " 条", file=sys.stderr)
        except Exception as ex:
            # 单个注册库不可用不应让整次运行失败，但必须在简报中声明覆盖缺口
            print("  ! " + label + " 抓取失败: " + type(ex).__name__ + " " + str(ex)[:120],
                  file=sys.stderr)
            source_errors.append(label + ": " + type(ex).__name__)

    trials_new, trials_changed = [], []
    for t in trials:
        key = trial_key(t)
        prior = seen.get(key)
        prev_status = str((prior or {}).get("last_status", "?"))
        if not prior:
            t["change"] = "新登记"
            trials_new.append(t)
        elif prior.get("status_hash") != t["status_hash"]:
            if t["has_results"] and not prior.get("has_results"):
                t["change"] = "[结果已公布]"
            elif t["status"] in ("TERMINATED", "WITHDRAWN", "SUSPENDED"):
                t["change"] = "[提前终止] " + prev_status + " -> " + t["status"]
            else:
                t["change"] = prev_status + " -> " + t["status"]
            trials_changed.append(t)
    print("Track F: 新登记 " + str(len(trials_new)) +
          " · 状态变更 " + str(len(trials_changed)), file=sys.stderr)

    # --- 预印本 (Europe PMC) ---
    preprints = []
    try:
        for pp in fetch_preprints(start, end):
            key = seen_key_lookup(seen, pp)
            if key:
                continue                      # 已见过，或已由正式发表版本捕捉
            preprints.append(pp)
        print("预印本: " + str(len(preprints)) + " 条新增", file=sys.stderr)
    except Exception as ex:
        print("! 预印本抓取失败: " + type(ex).__name__ + " " + str(ex)[:120], file=sys.stderr)
        source_errors.append("Europe PMC preprints: " + type(ex).__name__)

    os.makedirs(OUT_DIR, exist_ok=True)
    period = "{:%Y-%m}".format(end)
    payload = {
        "period": period,
        "mode": mode,
        "window": [str(start), str(end)],
        "queries_version": qver,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "counts": {
            "pubmed_hits": len(hits),
            "new_papers": len(new_papers),
            "cross_track_updates": len(confirm_papers),
            "trials_new": len(trials_new),
            "trials_changed": len(trials_changed),
            "preprints": len(preprints),
            "trials_by_registry": {
                reg: sum(1 for t in trials if t.get("registry") == reg)
                for reg in ("CTGOV", "ISRCTN", "CTIS")
            },
        },
        # 抓取失败的源必须原样带进简报的「方法学与局限」，不得静默吞掉
        "source_errors": source_errors,
        "known_gaps": ["CTRI (India)", "jRCT (Japan)", "ChiCTR (China)",
                       "会议摘要", "非英文文献"],
        "new_papers": new_papers,
        "cross_track_updates": confirm_papers,
        "trials_new": trials_new,
        "trials_changed": trials_changed,
        "preprints": preprints,
    }
    out_path = os.path.join(OUT_DIR, "candidates-" + period + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("-> " + out_path, file=sys.stderr)

    if not args.commit_state:
        print("state 未回写。简报生成成功后加 --commit-state 再跑一次。", file=sys.stderr)
        return

    # 仅在简报确认生成后回写；见 references/state-schema.md 回写时机
    state = state or {"schema_version": 1, "seen": {}, "baseline": {}, "runs": []}
    for rec in new_papers + confirm_papers:
        key = rec.get("dedup_key") or ("PMID:" + rec["pmid"])
        entry = state["seen"].setdefault(key, {"first_seen": str(today), "track": []})
        entry["track"] = sorted(set(entry.get("track", []) + rec["track"]))
        entry["doi"] = rec.get("doi", "")
        entry["title_norm"] = norm_title(rec.get("title"))
    for t in trials_new + trials_changed:
        e = state["seen"].setdefault(trial_key(t),
                                     {"first_seen": str(today), "track": ["F"]})
        e.update({"registry": t.get("registry", "CTGOV"),
                  "last_status": t["status"], "has_results": t["has_results"],
                  "status_hash": t["status_hash"], "title_norm": norm_title(t["title"]),
                  "last_update_posted": t["last_update_posted"]})
    for pp in preprints:
        e = state["seen"].setdefault("PPR:" + pp["epmc_id"],
                                     {"first_seen": str(today), "track": pp["track"]})
        e.update({"doi": pp.get("doi", ""), "title_norm": norm_title(pp.get("title")),
                  "is_preprint": True})
    state["queries_version"] = qver
    state["last_run"] = str(today)
    state["window_end_edat"] = str(end)
    state.setdefault("runs", []).append(
        {"date": str(today), "window": [str(start), str(end)], "hits": len(hits)})
    write_state_atomic(state)
    print("-> state/seen.json 已回写", file=sys.stderr)


if __name__ == "__main__":
    main()
