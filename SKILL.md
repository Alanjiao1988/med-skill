---
name: pediatric-mcd-evidence-surveillance
description: 儿童微小病变肾病（MCD）与临床重叠的儿童肾病综合征表型（SSNS/FRNS/SDNS）月度证据监测。当用户要求肾病综合征文献更新、MCD 研究进展、激素敏感型/频复发/激素依赖型肾病综合征证据、利妥昔单抗（rituximab）/奥法妥木单抗/他克莫司/吗替麦考酚酯等治疗证据、足细胞与抗 nephrin 机制进展、儿童肾病生物标志物、KDIGO 或 IPNA 指南更新、相关临床试验状态追踪，或要求运行月度证据简报（monthly evidence brief / delta report）时触发。输出简体中文增量简报，只报告相对既有基线的变化，不产出泛化综述。
version: 0.2.0
language: zh-CN
disclaimer: 研究与证据监测用途，不构成医疗建议，不替代临床诊疗。
---

# 儿童 MCD / 肾病综合征月度证据监测

## 用途

按月运行一次证据监测工作流，聚焦儿童微小病变肾病（MCD）及临床重叠的儿童肾病综合征表型（SSNS、FRNS、SDNS），产出一份简体中文**增量**证据简报（delta brief）供宿主应用投递。

**核心区别于普通文献综述**：本技能比较的是「本月证据」与「持久化的证据基线」之间的差异。没有变化就明确写「本月无实质性变化」，而不是把已知内容重述一遍。

## 前置输入

| 输入 | 位置 | 缺失时的行为 |
|---|---|---|
| 去重与基线状态 | `state/seen.json` | 视为首次运行，进入 **Bootstrap 模式**（见下） |
| 患者画像（可选，私有） | `patient-profile.md` | `patient_relevance` 维度标记 `N/A`，只输出 strength / novelty 两维 |
| 检索窗口 | 由宿主传入或从 `state.window_end_edat` 推导 | 默认 `last_run - 15天` 到 `today`（约 45 天重叠窗口） |

`patient-profile.md` 属于健康隐私，已在 `.gitignore` 中排除，**不得提交到仓库**。格式见 `templates/patient-profile.example.md`。

## 核心工作流

1. **确定窗口**：`start = state.window_end_edat - 15d`，`end = today`。故意重叠 15 天，覆盖 PubMed 入库延迟。
2. **检索六条 track**：机制 / 治疗 / 生物标志物 / 自然史与安全性 / 指南共识 / 临床试验。检索式**必须**逐字使用 `references/search-queries.md` 中的固化查询，不得即兴改写；改写会破坏月度可比性。
3. **抓取与去重**：优先运行 `scripts/fetch_evidence.py`（确定性工作，不交给模型）。按 `PMID` → `DOI` → 注册号 → 规范化标题的顺序去重，规则见 `references/state-schema.md`。
4. **试验状态差分**：track F 追踪的是**状态变更**（招募中→完成、方案修订、结果公布、提前终止），不只是「新出现的试验」。用 `status_hash` 比对，规则见 `references/state-schema.md`。
5. **表型归一化**：在解读任何结论前，先标注研究人群的年龄段（儿童/成人/混合）与疾病表型（活检确诊 MCD / SSNS 临床表型 / FSGS / 未分层）。这一步先于打分。
6. **三维独立打分**：evidence strength、novelty、patient relevance 分别按 `references/scoring-rubric.md` 打分，互不折算。
7. **入选分诊**：按 rubric 的阈值决定进正文还是进附录清单。阴性/无效结果走独立豁免通道（见 rubric）。
8. **与基线比对**：每条 material study 必须写明相对 `state.baseline` 的差异；若与基线一致，归为「确证性证据」而非「新发现」。
9. **产出简报**：严格套用 `templates/brief-template.md`，同时输出 Markdown 与 email-ready 的 text/html 字段。
10. **回写状态**：更新 `state/seen.json`（`seen`、`baseline`、`last_run`、`window_end_edat`）。**只有简报成功生成后才回写**，避免失败运行吞掉一个窗口。

### Bootstrap 模式

`state/seen.json` 不存在时：把窗口拉长到 24 个月，产出一份**基线快照**而非 delta 简报，写入 `state.baseline`，并在简报抬头标注「首次运行 · 基线建立」。之后各月才进入正常 delta 模式。

## 硬约束

1. 不得把 SSNS 等同于活检确诊的 MCD。两者是临床表型与病理诊断，任何跨越都必须显式标注。
2. 不得在无显式适用性标签的情况下把成人证据外推到儿童。
3. 不得把动物、类器官、体外、组学等机制证据表述为已确立的临床疗效。
4. 不得把关联表述为因果。
5. 单项新研究不得自动推翻已被重复验证的证据、系统综述或指南共识；需要在简报中显式论证为何构成挑战。
6. 每条 material study 必须同时填写 `what_this_changes` 与 `what_this_does_not_prove`，两者都不得留空或写「无」。
7. evidence strength、novelty、patient relevance 是三个独立维度，必须分别打分，不得合成单一总分。
8. 不做个体化治疗决策。只识别与临床实践相关的证据和「值得与主诊医师讨论的问题」。
9. 每期简报抬头必须包含免责声明（见模板）。

## 检索实现要点

- **日期字段必须用 `[EDAT]`（Entrez 入库日），不得用 `[PDAT]`（出版日）。** PDAT 会被期刊回填和乱序，用于滚动窗口必然同时造成漏检与重复。
- PubMed 走 E-utilities（`esearch` → `esummary`/`efetch`）。无 API key 时限速 3 req/s；设置 `NCBI_API_KEY` 后可到 10 req/s。
- 临床试验走 ClinicalTrials.gov API v2，按 `AREA[LastUpdatePostDate]RANGE[...]` 过滤，翻页用 `nextPageToken`。
- 抗 nephrin 抗体同时命中 track A（机制）与 track C（生物标志物）。去重逻辑必须**保留跨 track 命中标记**，不得把它折叠成单一 track，否则会丢掉临床转化这条线。

## 参考文件

| 文件 | 内容 | 何时加载 |
|---|---|---|
| `references/search-queries.md` | 六条 track 的固化检索式 | 执行检索前 |
| `references/scoring-rubric.md` | 三维量表、锚点、入选阈值、阴性结果通道 | 打分与分诊时 |
| `references/state-schema.md` | `seen.json` schema、去重与状态差分规则 | 去重与回写时 |
| `templates/brief-template.md` | 简报章节与必填字段 | 撰写简报时 |
| `templates/patient-profile.example.md` | 患者画像格式 | 配置 relevance 维度时 |
| `scripts/fetch_evidence.py` | 检索 / 抓取 / 去重 / 状态差分 | 每次运行 |

## 输出语言

最终简报为简体中文，关键医学术语在括号内保留英文（如「抗 nephrin 抗体（anti-nephrin antibody）」）。研究标题保留原文并附中文意译。

## 投递契约

本技能只产出简报对象，**不假设任何邮件服务商**（Gmail / Outlook / SMTP 均不假设）。投递地址由宿主应用配置传入（如 `config.recipient`），不在本仓库硬编码。

输出对象字段：

```json
{
  "period": "2026-08",
  "mode": "delta | bootstrap",
  "subject": "……",
  "markdown": "……",
  "text": "……",
  "html": "……",
  "material_count": 0,
  "appendix_count": 0,
  "state_written": true
}
```
