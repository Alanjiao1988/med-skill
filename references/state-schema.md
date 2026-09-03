# 状态文件 schema、两阶段提交与去重规则

运行时状态：`state/seen.json`（已 gitignore）。状态可能包含患者相关性打分痕迹，不得提交。

本版本使用 **candidate → decision + brief → private report archive → state commit**
事务，避免“简报还没真正生成或尚未归档，就把文献标记为已见”的数据丢失风险。

## Schema version

```text
schema_version: 3
queries_version: 2
```

## state/seen.json

```jsonc
{
  "schema_version": 3,
  "queries_version": 2,
  "last_run": "2026-08-23",
  "window_end_edat": "2026-08-23",
  "runs": [
    {
      "run_id": "...",
      "date": "2026-08-23",
      "window": ["2026-07-08", "2026-08-23"],
      "hits": 123,
      "material": 5,
      "brief_generated": true,
      "brief_path": "out/brief-2026-08-RUN_ID.md",
      "candidates_sha256": "...",
      "decisions_sha256": "...",
      "brief_sha256": "...",
      "report_archive": {
        "repository": "Alanjiao1988/Med-report",
        "path": "reports/2026/2026-08/brief-2026-08-RUN_ID.md",
        "commit_sha": "..."
      }
    }
  ],
  "seen": {
    "PMID:40123456": {
      "track": ["B"],
      "doi": "10.xxxx/xxxx",
      "title_norm": "...",
      "first_seen": "2026-08-23",
      "peer_review_status": "peer_reviewed",
      "retrieval_depth": "abstract",
      "verdict": "material",
      "scores": {"S": 4, "N": 2, "R": 3}
    },
    "PPR:PPR123456": {
      "track": ["A", "C"],
      "doi": "10.xxxx/preprint",
      "title_norm": "...",
      "first_seen": "2026-07-23",
      "peer_review_status": "preprint",
      "is_preprint": true,
      "superseded_by": "PMID:40123456"
    },
    "NCT:NCT06123456": {
      "track": ["F"],
      "registry": "CTGOV",
      "last_status": "RECRUITING",
      "has_results": false,
      "protocol_hash": "...",
      "last_update_posted": "2026-08-12"
    }
  },
  "baseline": {
    "treatment": [],
    "mechanism": [],
    "biomarkers": [],
    "natural_history": [],
    "guidelines": []
  }
}
```

## Candidate artifact

抓取阶段输出 `out/candidates-YYYY-MM-RUN_ID.json`。同月重跑不得覆盖旧文件。
必须包含：

```jsonc
{
  "schema_version": 3,
  "run_id": "UUID",
  "period": "2026-08",
  "mode": "delta",
  "window": ["2026-07-08", "2026-08-23"],
  "queries_version": 2,
  "generated_at": "2026-08-23T10:00:00+08:00",
  "report_repository": "Alanjiao1988/Med-report",
  "core_sources_complete": true,
  "source_errors": [],
  "new_papers": [],
  "publication_transitions": [],
  "cross_track_updates": [],
  "trials_new": [],
  "trials_changed": [],
  "preprints": []
}
```

抓取阶段**不得修改 state**。

## Decisions artifact

模型完成证据解读和简报后，生成 decisions JSON。最少：

```jsonc
{
  "schema_version": 3,
  "run_id": "必须与 candidates 完全相同",
  "brief_generated": true,
  "brief_path": "out/brief-2026-08-RUN_ID.md",
  "items": {
    "PMID:40123456": {
      "verdict": "material",
      "scores": {"S": 4, "N": 2, "R": 3},
      "peer_review_status": "peer_reviewed",
      "evidence_basis": "full_text",
      "material_basis": "strength_novelty",
      "claim_type": "treatment",
      "population_directness": "direct",
      "what_this_changes": "...",
      "what_this_does_not_prove": "..."
    }
  },
  "baseline": {
    "treatment": [],
    "mechanism": [],
    "biomarkers": [],
    "natural_history": [],
    "guidelines": []
  }
}
```

`--commit-state` 必须同时读取 candidate + decisions，并验证：

1. candidate 与 decisions 都是 schema v3，且 `run_id` 一致；
2. candidate 完整、核心源完成、counts 与数组长度一致；
3. decisions 恰好覆盖全部 paper/preprint candidates，不多也不少；
4. S/N/R 在合法范围，preprint 的暂定 S≤3；
5. material 条目满足明确 `material_basis`，并具有 claim type、适用性、
   evidence basis、`what_this_changes` 与 `what_this_does_not_prove`；
6. preprint 和 book chapter 不能成为 material；
7. baseline 只引用 state/current candidates 中可核验的正式来源；PPR、已知
   preprint DOI 和 book chapter 均被拒绝；
8. brief 文件真实存在于 `out/`，是 UTF-8 Markdown，包含精确 run/period
   标记及医疗免责；
9. `run_id` 幂等，window end 与 query version 不得倒退；
10. 报告目标仓库必须为 private，且归档成功后才允许写 state。

提交阶段不得重新运行证据检索。它只访问 GitHub 以归档已经生成并验证过的
brief。state 使用跨平台文件锁、唯一临时文件和 `os.replace` 原子写入。

---

## 去重优先级

对于论文/预印本：

1. PMID
2. DOI（标准化为小写、去 doi.org 前缀）
3. Europe PMC PPR id
4. normalized title（最后回退）

对于试验：先 registry-specific ID，再比较 protocol/status hash。

### normalized title

使用 Unicode-aware 规范化：NFKC/NFKD 统一、转小写、去标点、压缩空白。不要只保留 `[a-z0-9]`，否则非英语标题会被错误清空。

---

## 预印本 → 正式发表

这是**版本转换事件，不是普通重复**。

若正式发表的 PMID/DOI/title 与既有 PPR 条目匹配：

```text
publication_transition = true
prior_key = PPR:...
current_key = PMID:...
```

必须重新进入候选集并重新评分，原因包括：

- 已完成同行评议；
- 结果、样本数、统计方法、措辞可能变化；
- 可能新增安全性或亚组信息。

state commit 后：

- 新建正式 `PMID:` 条目；
- 旧 PPR 条目保留历史并写 `superseded_by`；
- 不把正式发表静默并入 PPR key。

---

## 跨 track 命中

同一论文可同时属于多个内容领域，例如 anti-nephrin 可同时命中 A（机制）和 C（biomarker）。track 必须是数组并做并集更新。

---

## 临床试验变化

建议保存 `protocol_hash` 而不仅是 `overallStatus` hash。

### ClinicalTrials.gov

hash 至少覆盖：
- overallStatus
- phase
- hasResults
- enrollment
- eligibility age
- primary completion
- interventions/arms（如果 API 返回）
- primary outcomes（如果 API 返回）

### 变化分类

| 情况 | event |
|---|---|
| registry ID 首次出现 | `new_registration` |
| overallStatus 改变 | `status_changed` |
| hasResults false→true | `results_posted` |
| TERMINATED/WITHDRAWN/SUSPENDED | `early_stop` |
| hash 变化但 overallStatus 不变 | `protocol_record_updated` |

`protocol_record_updated` 不得写成虚假的 `X -> Y` 临床状态改变。

ISRCTN / CTIS 如果无法可靠解析 results status，应保留原始字段而不是从“非空”推断 `has_results=true`。

---

## baseline 更新规则

baseline 是“当前正式证据判断”，不能因为一项高相关或高 novelty 的弱证据自动修改。

### 允许正式更新 baseline 的最低条件

- `peer_review_status != preprint`
- 对实质 claim change：通常要求 `S >= 3`
- `N = 3` 仍需明确 `baseline_action` / 新 baseline 内容，而不是自动覆盖
- 指南更新必须是实质推荐变化，而不是网页更新时间变化

### 确证性研究

`N = 1` 的高质量同行评议研究可以追加到既有 claim 的 `sources`，但不自动改写 claim。

### 预印本

PPR 永远不能进入正式 baseline，即使同一 claim 还引用了其他正式来源。可以存放在
独立 `watchlist`（如宿主需要），但不得作为 baseline source。

---

## 查询版本变化

`queries_version` 变化时：

- 不清空历史 state；
- 下一期必须声明“检索式发生变化，部分新增可能为追溯性命中”；
- 必要时运行 bounded backfill 验证，而不是把所有回溯命中误判为当月新科学进展。
