# 固化检索式

> 检索式用于保证月度可比性，不得临时改写。确需调整时必须 bump `queries_version`，并在下一期简报中说明可能出现追溯性命中。

```text
queries_version: 2
date_field: EDAT
```

## 证据领域与来源

A–F 是**内容领域**：机制、治疗、生物标志物、自然史/安全性、指南/共识、临床试验。

`preprint` 是**来源/同行评议状态**，不是 Track G。预印本必须重新归入 A–E 的一个或多个领域。

## 通用 PubMed 片段

```text
{PEDS} =
("Child"[MeSH] OR "Infant"[MeSH] OR "Adolescent"[MeSH]
 OR child*[tiab] OR pediatr*[tiab] OR paediatr*[tiab] OR infant*[tiab] OR adolescen*[tiab])

{DISEASE} =
("Nephrosis, Lipoid"[MeSH] OR "Nephrotic Syndrome"[MeSH]
 OR "minimal change disease"[tiab] OR "minimal change nephropathy"[tiab]
 OR "minimal change nephrotic syndrome"[tiab]
 OR "idiopathic nephrotic syndrome"[tiab]
 OR "steroid sensitive nephrotic syndrome"[tiab]
 OR "steroid-sensitive nephrotic syndrome"[tiab]
 OR "steroid dependent nephrotic syndrome"[tiab]
 OR "steroid-dependent nephrotic syndrome"[tiab]
 OR "frequently relapsing nephrotic syndrome"[tiab]
 OR "frequent relapsing nephrotic syndrome"[tiab]
 OR (SSNS[tiab] AND nephrotic[tiab])
 OR (SDNS[tiab] AND nephrotic[tiab])
 OR (FRNS[tiab] AND nephrotic[tiab])
 OR (MCD[tiab] AND (nephrotic[tiab] OR kidney[tiab] OR renal[tiab] OR podocyt*[tiab])))

{WINDOW} =
("YYYY/MM/DD"[EDAT] : "YYYY/MM/DD"[EDAT])
```

说明：
- 不使用裸 `MCD`、`steroid-dependent`、`frequently relapsing` 作为独立疾病命中词，避免无关缩写/表型噪声。
- A/C 不强制儿童过滤，以便捕捉成人或混合人群的机制/biomarker 证据；适用性在解读层标记。
- B/D 使用 `{PEDS}`，优先儿童临床证据。

---

## Track A — 机制

```text
{DISEASE}
AND (podocyte*[tiab] OR "slit diaphragm"[tiab] OR nephrin[tiab] OR "anti-nephrin"[tiab]
     OR NEPH1[tiab] OR podocin[tiab] OR NPHS1[tiab] OR NPHS2[tiab]
     OR "foot process effacement"[tiab] OR permeability factor*[tiab]
     OR "circulating factor"[tiab] OR autoantib*[tiab] OR autoimmun*[tiab]
     OR "B cell"[tiab] OR "B-cell"[tiab] OR "T cell"[tiab] OR "T-cell"[tiab]
     OR complement[tiab] OR CD80[tiab] OR "regulatory T"[tiab])
AND {WINDOW}
```

## Track B — 治疗

```text
{DISEASE} AND {PEDS}
AND (glucocorticoid*[tiab] OR corticosteroid*[tiab] OR prednisolone[tiab] OR prednisone[tiab]
     OR rituximab[tiab] OR ofatumumab[tiab] OR obinutuzumab[tiab] OR "anti-CD20"[tiab]
     OR "mycophenolate mofetil"[tiab] OR mycophenolic[tiab] OR MMF[tiab]
     OR tacrolimus[tiab] OR cyclosporin*[tiab] OR "calcineurin inhibitor"[tiab]
     OR levamisole[tiab] OR cyclophosphamide[tiab]
     OR "steroid sparing"[tiab] OR "steroid-sparing"[tiab] OR abatacept[tiab])
AND {WINDOW}
```

## Track C — 生物标志物与精准表型

```text
{DISEASE}
AND (biomarker*[tiab] OR "anti-nephrin antibod*"[tiab] OR autoantibod*[tiab]
     OR proteom*[tiab] OR metabolom*[tiab] OR transcriptom*[tiab]
     OR "single cell"[tiab] OR "urinary CD80"[tiab] OR suPAR[tiab]
     OR predict*[ti] OR prognos*[ti] OR stratif*[ti] OR "treatment response"[tiab])
AND {WINDOW}
```

诊断（diagnostic）、预后（prognostic）、预测疗效（predictive）必须分别评价，不能互换。

## Track D — 自然史与安全性

```text
{DISEASE} AND {PEDS}
AND (relapse*[tiab] OR remission[tiab] OR "long term outcome*"[tiab] OR "natural history"[tiab]
     OR "transition to adult"[tiab] OR "chronic kidney disease"[tiab] OR "kidney failure"[tiab]
     OR growth[tiab] OR "bone mineral"[tiab] OR osteoporo*[tiab] OR fracture*[tiab]
     OR infection*[tiab] OR thrombo*[tiab] OR hypertens*[tiab] OR obesity[tiab]
     OR cataract*[tiab] OR "adverse event*"[tiab] OR toxicit*[tiab]
     OR "quality of life"[tiab])
AND {WINDOW}
```

## Track E — 指南与共识

```text
{DISEASE}
AND (guideline*[tiab] OR "practice guideline"[pt] OR consensus[tiab] OR recommendation*[tiab]
     OR KDIGO[tiab] OR IPNA[tiab] OR ESPN[tiab] OR ERA[tiab] OR "position statement"[tiab])
AND {WINDOW}
```

同时由宿主核验 KDIGO、IPNA、ESPN/ERA 官方页面。**官网发生更新本身不自动等于 novelty 3**；必须确认是否存在实质性推荐、证据等级、适用人群或安全性声明变化。

---

## Track F — 临床试验

### ClinicalTrials.gov API v2

```text
GET https://clinicaltrials.gov/api/v2/studies
  ?query.cond=("nephrotic syndrome" OR "minimal change disease" OR "minimal change nephropathy" OR "steroid sensitive nephrotic syndrome" OR "steroid dependent nephrotic syndrome" OR "frequently relapsing nephrotic syndrome")
  &filter.advanced=AREA[LastUpdatePostDate]RANGE[YYYY-MM-DD,YYYY-MM-DD]
  &pageSize=200
  &countTotal=true
  &format=json
```

**短语必须加引号。** 不加引号时 Essie 按词元松散匹配，实测会把 `MINIMA Stem With DELTA TT`（髋关节柄假体试验）当成 `minimal change disease` 命中。加引号后该噪声消失，且相关试验无损失。

最少记录：注册号、标题、overallStatus、phase、年龄、hasResults、lastUpdatePostDate、primary completion、enrollment。

**hash 变化不等于临床状态变化。** 如果 `overallStatus` 未变但 protocol hash 变化，应描述为 `protocol_record_updated`，而不是伪造 `X -> Y` 状态转换。

### ISRCTN

```text
GET https://www.isrctn.com/api/query/format/default
  ?q="nephrotic syndrome" OR "minimal change disease"
  &limit=500
```

ISRCTN 官方 API 支持 Boolean query。当前实现客户端按 `trial/@lastUpdated` 做窗口过滤。

### 注册库命中的主题复核（必需）

ISRCTN 的 `q` 与 CTIS 的 `containAll` 都是**全记录匹配**：只要"nephrotic syndrome"出现在通俗摘要、排除标准或不良事件描述里，该试验就会被返回。实测噪声包括睾酮试验、依托泊苷卡铂化疗试验、钙羟基苯磺酸糖尿病肾病试验。

因此对 ISRCTN / CTIS 命中必须再做一次**主题字段复核**，只保留疾病短语出现在标题或 condition 字段中的记录：

```text
title / scientificTitle / conditions/condition/description / diseaseClass*   (ISRCTN)
ctTitle / conditions                                                          (CTIS)
```

匹配短语集合同时覆盖肾小球病伞形术语（`glomerular disease`、`glomerulonephritis`、`glomerulopathy`、`podocytopathy`、`FSGS`），否则会误杀 basket trial——实测 CTIS 的 Atacicept PIONEER 试验 condition 写作 "Multiple Autoimmune Glomerular Diseases"，仅用 MCD/肾病综合征短语会漏掉。

### 防止静默截断

ISRCTN 请求 `limit=500` 后必须读取根节点 `totalCount`；若 `totalCount > limit`，视为检索失败并抛错，不得使用被截断的结果集。

若 registry 字段不能可靠给出“结果已发表”，不得从非空字符串简单推断 `has_results=true`；保留原始 publication stage，并在解读层判断。

### EU CTIS

当前脚本使用 CTIS 公开门户 backend 进行检索。EMA 官方保证公众可以通过 CTIS public portal 检索试验，但本仓库使用的 backend 不是稳定版本化 API 合同，因此标记：

```text
source_stability: experimental_public_portal_backend
```

接口失败时必须进入 `source_errors`，不能静默跳过。

### WHO ICTRP

WHO 官方提供：
- ICTRP Search Portal；
- 搜索结果 XML / CSV 下载；
- 研究用途 Web Service（可能需要按 WHO 条件申请/配置）。

因此当前状态是：

```text
WHO_ICTRP: available_but_not_integrated
```

不能写成 `no_api`。WHO ICTRP 可聚合 ChiCTR、JPRN/jRCT、CTRI 等多国注册来源，是未来提高全球试验覆盖率的优先接入点。

### 尚未稳定单独接入

| 注册来源 | 当前状态 |
|---|---|
| CTRI | `not_integrated_or_not_verified` |
| jRCT / JPRN | `not_integrated_or_not_verified` |
| ChiCTR | `not_integrated_or_not_verified` |

不要对这些服务作永久性的“没有 API”断言；每季度复核一次程序化访问能力。

---

## 预印本来源 — Europe PMC（不是 Track G）

```text
GET https://www.ebi.ac.uk/europepmc/webservices/rest/search
  ?query=("nephrotic syndrome" OR "minimal change disease" OR "minimal change nephropathy"
          OR "steroid-sensitive nephrotic syndrome" OR "steroid-dependent nephrotic syndrome"
          OR "frequently relapsing nephrotic syndrome")
         AND SRC:PPR
         AND FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD]
  &format=json&resultType=core&pageSize=100&cursorMark=*
```

规则：
1. 不用裸 `podocyte` 做预印本入口，避免把整个足细胞领域的大量无关论文纳入 MCD surveillance。
2. 根据题目/摘要把预印本归入 A–E 一个或多个领域；`preprint` 只记录同行评议状态。
3. 预印本转正式发表必须产生 `publication_transition` 事件，即使 title_norm/DOI 命中，也不能被静默去重。
4. Europe PMC 可能直接提供 published-version linkage；宿主应优先利用明确 linkage，title_norm 只作回退机制。

---

## PubMed 抓取完整性

- ESearch 必须分页取全，禁止固定 `retmax=400` 后截断。
- 单查询结果若超过 PubMed 可安全获取上限，应拆分日期窗口。
- 对候选 PMID 必须至少 EFetch abstract；ESummary 元数据不足以支持证据评级。
- EFetch 响应中除 `<PubmedArticle>` 外还可能包含 `<PubmedBookArticle>`（StatPearls、GeneReviews 等 NCBI Bookshelf 条目，使用 `BookDocument` 而非 `MedlineCitation/Article`）。必须一并解析，否则完整性校验会因"缺失 PMID"中断整次月度运行。这类记录标记为 `peer_review_status=book_chapter`，属三级教育性内容。
- 所有 E-utilities 请求必须携带 `tool` 与 `email` 参数（`NCBI_TOOL` / `NCBI_EMAIL` 环境变量），这是 NCBI 的使用要求。
- 拟进入正文的研究，如有合法全文，进一步阅读全文并记录 `evidence_basis=full_text`；否则写 `abstract_only`。