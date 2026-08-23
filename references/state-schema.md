# 状态文件 schema、两阶段提交与去重规则

运行时状态：`state/seen.json`（已 gitignore）。状态可能包含患者相关性打分痕迹，不得提交。

本版本使用 **candidate → decision → state commit** 两阶段提交，避免“简报还没真正生成就把文献标记为已见”的数据丢失风险。

## Schema version

```text
schema_version: 2
queries_version: 2
```

## state/seen.json

```jsonc
{
  "schema_version": 2,
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
      "brief_generated": true
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

抓取阶段输出 `out/candidates-YYYY-MM.json`。必须包含：

```jsonc
{
  "run_id": "uuid-or-hash",
  "period": "2026-08",
  "mode": "delta",
  "window": ["2026-07-08", "2026-08-23"],
  "queries_version": 2,
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
  "run_id": "必须与 candidates 完全相同",
  "brief_generated": true,
  "brief_path": "out/brief-2026-08.md",
  "items": {
    "PMID:40123456": {
      "verdict": "material",
      "scores": {"S": 4, "N": 2, "R": 3},
      "peer_review_status": "peer_reviewed",
      "evidence_basis": "full_text"
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

1. `run_id` 一致；
2. `brief_generated == true`；
3. candidate 文件存在且结构有效；
4. decisions 中 material 条目具有 S/N/R 或明确 N/A；
5. baseline 不包含预印本作为正式证据来源。

提交阶段**不得重新运行网络检索**，否则分析过的候选集与最终写入 state 的候选集可能发生漂移。

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

PPR 永远不能作为 baseline 的唯一正式来源。可以存放在独立 `watchlist`（如宿主需要），但不得进入正式 baseline。

---

## 查询版本变化

`queries_version` 变化时：

- 不清空历史 state；
- 下一期必须声明“检索式发生变化，部分新增可能为追溯性命中”；
- 必要时运行 bounded backfill 验证，而不是把所有回溯命中误判为当月新科学进展。
