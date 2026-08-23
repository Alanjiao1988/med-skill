# 状态文件 schema 与去重规则

状态文件：`state/seen.json`（**已 gitignore**，可能含患者相关性痕迹）。
示例见 `state/seen.example.json`。

## Schema

```jsonc
{
  "schema_version": 1,
  "queries_version": 1,          // 与 references/search-queries.md 对齐；不一致时简报须告警
  "last_run": "2026-08-01",
  "window_end_edat": "2026-07-31", // 下次窗口从此日期回退 15 天开始
  "runs": [                        // 运行日志，用于排查漏检
    {"date": "2026-08-01", "window": ["2026-06-16","2026-07-31"], "hits": 214, "material": 7}
  ],
  "seen": {
    "PMID:40123456": {
      "track": ["B"],              // 数组：保留跨 track 命中（如 anti-nephrin 同时命中 A 和 C）
      "doi": "10.1016/j.kint.2026.05.012",
      "title_norm": "rituximab versus mmf in children with sdns a randomized trial",
      "first_seen": "2026-08-01",
      "verdict": "material",       // material | appendix | discarded
      "scores": {"S": 4, "N": 2, "R": 3}
    },
    "NCT:NCT06123456": {
      "track": ["F"],
      "title_norm": "obinutuzumab in pediatric steroid dependent nephrotic syndrome",
      "first_seen": "2026-05-01",
      "last_status": "RECRUITING",
      "has_results": false,
      "status_hash": "9f2c1e...",  // 见下
      "last_update_posted": "2026-07-12"
    }
  },
  "baseline": {
    "treatment": [
      {"claim": "利妥昔单抗在 SDNS 儿童中可延长无复发生存", "strength": 5, "sources": ["PMID:xxxxxx"], "updated": "2026-08-01"}
    ],
    "mechanism": [],
    "biomarkers": [],
    "natural_history": [],
    "guidelines": []
  }
}
```

## 去重顺序

按以下顺序，命中即停：

1. `PMID`
2. `DOI`（小写、去 `https://doi.org/` 前缀）
3. 试验注册号，按注册库加前缀：`NCT:`（ClinicalTrials.gov，沿用历史前缀以兼容既有 state）、
   `ISRCTN:`、`CTIS:`；预印本用 `PPR:` + Europe PMC id
4. `title_norm`：小写 → 去除所有非字母数字字符 → 压缩空白。用于捕捉「预印本 → 正式发表」「会议摘要 → 全文」的同一研究

**预印本转正式发表**：预印本以 `PPR:` 入 state；数月后同一研究在 PubMed 发表时，
第 4 级 `title_norm` 会命中该条目，因此不会被重复报告为新发现。若发表版结论与预印本不一致，
按 novelty 3 处理并在简报中写明「预印本 → 发表，结论变化」。

**跨 track 命中不去重成单一 track**：同一 PMID 在多个 track 命中时，把 track 追加进 `track` 数组，不覆盖。

## 试验状态差分（track F）

`status_hash = sha256(overallStatus + "|" + phases + "|" + hasResults + "|" + primaryCompletionDate)`

比对逻辑：

| 情况 | 处理 |
|---|---|
| 注册号不在 `seen` | 新试验 → 入简报「新登记」 |
| 在 `seen` 且 `status_hash` 相同 | 无变化 → 不入简报 |
| 在 `seen` 且 `status_hash` 变化 | **状态变更** → 入简报，写明「从 X → Y」 |
| `has_results` 由 false 变 true | 最高优先级 → 正文，标注 `[结果已公布]` |
| `overallStatus` 变为 `TERMINATED` / `WITHDRAWN` | 正文，标注 `[提前终止]`，并尽力检索终止原因 |

## 回写时机

**只在简报成功生成后回写。** 若运行中途失败，不更新 `last_run` / `window_end_edat`，
以免该窗口的文献被永久跳过。脚本以「先写临时文件再原子替换」的方式落盘。

## 基线更新规则

- `verdict = material` 且 `N = 3` 的条目 → 更新或新增对应 `baseline.claim`
- `verdict = material` 且 `N = 1`（确证性）→ 只把 PMID 追加进既有 claim 的 `sources`，不改写 claim
- 指南更新（track E）→ 直接覆盖对应 claim，并保留旧 claim 到 `superseded` 字段
