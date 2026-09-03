---
name: med-skill
user-invocable: true
description: 儿童肾病综合征与微小病变肾病（MCD）living evidence surveillance，面向患儿家长。用于按月检索、核验和总结 SSNS/FRNS/SDNS/MCD 的机制、治疗、生物标志物、自然史与安全性、指南共识和临床试验进展，生成简体中文增量证据简报，并把证据转成可带去门诊与主诊医师讨论的问题。涉及 rituximab、MMF、CNI、抗 nephrin、足细胞机制、复发风险、儿童肾病最新进展、儿童肾病指南、trial registry 更新、monthly evidence brief，或家长想了解孩子肾病的最新研究进展时使用。不提供诊断、用药或剂量建议。
---

# 儿童 MCD / 肾病综合征月度证据监测

版本：0.4.0

> 研究与证据监测用途，不构成医疗建议，不替代临床诊疗。

## 核心目标

每月运行一次 living evidence surveillance，聚焦儿童微小病变肾病（MCD）及临床重叠表型（SSNS、FRNS、SDNS）。输出的是相对既有证据基线的 **delta brief**，不是每月重写一份泛化综述。

**使用者是患儿家长，不是研究者。** 因此简报同时包含两层：

- **技术层**：S/N/R 评级、claim_type、population_directness、证据基础，保证判断可核验；
- **家长层**：把技术层翻译成"本月是否有需要注意的事"和"下次门诊可以问医生什么"，规则见 `references/caregiver-layer.md`。

家长层不降低证据标准，也不替代技术层。**绝大多数月份，家长层的正确结论是"本月没有需要改变任何事的证据"**——这是合格输出，不是失败。

## 六个证据领域

A. 机制（mechanism）  
B. 治疗（treatment）  
C. 生物标志物与精准表型（biomarker / precision phenotyping）  
D. 自然史与安全性（natural history / safety）  
E. 指南与共识（guideline / consensus）  
F. 临床试验注册与状态变化（clinical trials）

**预印本不是第七个证据领域。** `preprint` 是来源/同行评议状态；任何预印本仍必须归入 A–E 中一个或多个内容领域，并在输出中显式标记 `peer_review_status=preprint`。

## 前置输入

| 输入 | 位置/来源 | 缺失时行为 |
|---|---|---|
| 去重与证据基线状态 | `state/seen.json` | 首次运行进入 Bootstrap 模式 |
| 患者画像（可选、私有） | `patient-profile.md` | `patient_relevance = N/A` |
| 投递配置 | 宿主运行时 `config.recipient` | 不发送邮件，只返回 `delivery_pending` |
| 检索窗口 | 宿主传入或 state 推导 | `state.window_end_edat - 15d` 到 today |

`patient-profile.md` 属于健康隐私，已在 `.gitignore` 中排除，不得提交到仓库。

## 核心工作流

1. **确定窗口**：正常月度运行使用 15 天重叠窗口；首次运行使用 24 个月 Bootstrap。
2. **检索 A–F 六个领域**：PubMed A–E；临床试验注册库 F；Europe PMC 预印本作为 A–E 的补充来源。
3. **完整抓取 PubMed 候选**：必须分页取全 PMID；随后至少抓取 abstract，不能仅凭 title/ESummary 做证据评级。
4. **去重与版本识别**：PMID → DOI → registry ID → normalized title。预印本转正式发表必须作为 `publication_transition` 重新进入候选集，不能静默去重掉。
5. **表型与适用性归一化**：先标注年龄、人群、病理/临床表型，再解释结果。
6. **必要时升级到全文**：任何拟进入正文的 material study，如存在合法可访问全文（PMC / Europe PMC / publisher OA），应优先阅读全文。若只能读 abstract，必须标记 `evidence_basis=abstract_only`，不得声称摘要未提供的剂量、亚组、统计方法或安全性细节。
7. **三维独立评级**：evidence strength（S）、novelty（N）、patient relevance（R）按 `references/scoring-rubric.md` 执行，不合成总分。
8. **与 baseline 比较**：区分 confirmatory、extends、challenges、paradigm-shift candidate、guideline change。
9. **生成简报**：严格使用 `templates/brief-template.md`。先完成技术层，再按 `references/caregiver-layer.md` 生成家长层（三句话、门诊问题、当前用药安全信息）。家长层从技术层推导，不得引入技术层没有的结论。
10. **两阶段提交 state**：抓取阶段只生成 candidate artifact；宿主完成证据解读和简报后生成 decisions artifact；只有 `brief_generated=true` 且 `run_id` 匹配时才允许 `--commit-state`。提交阶段不得重新联网抓取。
11. **投递**：若宿主具有邮件/消息工具且提供 `config.recipient`，发送生成后的简报；否则返回简报并标记 `delivery_pending=true`。

## Bootstrap 模式

`state/seen.json` 不存在时，检索过去 24 个月并建立 baseline snapshot。Bootstrap 同样必须分页取全检索结果；任何 source truncation 都视为失败，不得以不完整结果建立基线。

## 硬约束

1. 不得把 SSNS 等同于活检确诊 MCD。
2. 成人证据可以被检出和评价，但不得无标记外推到儿童。
3. 动物、类器官、体外和组学证据不得表述为临床疗效。
4. 观察性关联不得写成因果。
5. 单项新研究不得自动推翻重复验证的证据或指南。
6. 每条 material study 必须同时填写 `what_this_changes` 和 `what_this_does_not_prove`。
7. S/N/R 独立；`patient relevance` 不得把低质量证据升级成高质量临床证据。
8. 预印本不得更新正式 evidence baseline，也不得单独触发 practice-changing 结论。
9. 指南网页有更新不等于 novelty=3；只有实质性推荐、证据等级或适用人群变化才能视为重要 guideline change。
10. 不做个体化治疗决策，只提出可与主诊医师讨论的问题。
11. 每期简报必须披露检索覆盖、失败源、全文/摘要证据基础和已知缺口。
12. **家长层禁止输出**：具体药物/剂量/疗程/减量停药方案、换药加药倾向、对当前治疗方案是否恰当的评价、化验值解读、预后判断、诊断意见、绕过主诊医师的行动建议。用户直接要求时也不例外——改为转成一条可带去门诊的问题。
13. **不得为了让简报"有内容"而抬高弱证据的呈现权重。** 无实质进展时必须直说本月无需改变任何事。
14. **不提供症状阈值或就医指征。** 这些必须来自患儿医疗团队；技能只提示家长向团队索取属于自己孩子的书面行动计划。
15. 检出国际指南变化时不得据此暗示国内当前做法有问题；写成可与主诊医师讨论的问题，并考虑药物可及性、适应证批准、医保覆盖与国内指南差异。
16. 书籍/教材类记录（StatPearls、GeneReviews 等 `peer_review_status=book_chapter`）属于三级教育性内容，可用于背景理解，**不得作为 material 证据**支撑 claim 变化。

## 数据源与可靠性层级

### 核心源（失败则本期 evidence brief 不应标记为完整）

- PubMed E-utilities：A–E，使用 `[EDAT]` 滚动窗口；必须分页，不允许 retmax 截断。

### 补充源（单源失败可继续，但必须披露）

- ClinicalTrials.gov API v2
- ISRCTN
- EU CTIS public portal backend（属于公开门户接口，需把接口变化风险视为已知不稳定性）
- Europe PMC `SRC:PPR`：预印本来源
- KDIGO / IPNA / ESPN / ERA 等官方页面：指南与共识补充核验

### WHO ICTRP

WHO ICTRP **不是“无 API”**。WHO 官方提供 Search Portal、XML/CSV 下载以及面向研究用途的 Web Service；本仓库当前尚未实现稳定自动接入，因此状态应写成 `available_but_not_integrated`，而不是 `no_api`。它可作为 ChiCTR、jRCT、CTRI 等区域注册库覆盖缺口的聚合补充来源。

### 当前未稳定自动化覆盖

CTRI、jRCT、ChiCTR 等单独注册库尚未在本仓库实现稳定程序化接入。不要断言这些服务“没有 API”；应记录为 `not_integrated_or_not_verified` 并定期复核。PubMed 本身不限制英文，因此局限应写为“非 PubMed 索引的区域数据库/非索引非英文文献未系统覆盖”，而不是“非英文文献未覆盖”。

## 检索与抓取实现规则

- PubMed 日期必须用 `[EDAT]`，不得用 `[PDAT]`。
- ESearch 必须使用分页或 history server 取全；如果单个查询超过 PubMed 可安全获取上限，必须拆分日期窗口，不能静默截断。
- PubMed 候选至少包含：PMID、DOI、title、journal、publication type、abstract、language、PMCID（若有）。
- ClinicalTrials.gov 状态比较不仅关注 `overallStatus`，还要能够识别重要 protocol record update；不能把“hash 变化”全部描述成临床状态改变。
- 来源抓取失败必须写入 `source_errors`。
- anti-nephrin 等条目可以同时属于 A 和 C，跨 track 标签必须保留。

## 参考文件

| 文件 | 内容 |
|---|---|
| `references/search-queries.md` | A–F 固化检索式、注册库与预印本来源规则 |
| `references/scoring-rubric.md` | claim-specific S/N/R 评级与分诊 |
| `references/state-schema.md` | candidate/decision/state 两阶段 schema 与去重规则 |
| `references/caregiver-layer.md` | 家长层写法、门诊问题规则与硬边界 |
| `templates/brief-template.md` | 月度简报格式 |
| `templates/patient-profile.example.md` | 私有患者画像模板 |
| `templates/decisions.example.json` | state commit 所需的 decisions artifact 示例 |
| `scripts/fetch_evidence.py` | 确定性抓取、去重、trial diff、state commit |

## 输出与投递契约

最终简报为简体中文，重要医学术语保留英文。宿主传入：

```json
{
  "config": {
    "recipient": "<email-address>"
  }
}
```

技能输出：

```json
{
  "period": "YYYY-MM",
  "mode": "delta | bootstrap",
  "subject": "儿童 MCD / 肾病综合征证据月报 · YYYY-MM",
  "markdown": "...",
  "text": "...",
  "html": "...",
  "material_count": 0,
  "appendix_count": 0,
  "delivery_pending": false,
  "state_written": true
}
```

不要在仓库中硬编码个人邮箱；由宿主应用的运行时配置负责实际投递。