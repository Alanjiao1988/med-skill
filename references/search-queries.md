# 固化检索式

> **不得即兴改写。** 检索式是月度可比性的基础；任何修改都会让 delta 失去意义。
> 确需调整时：修改后 bump 本文件顶部的 `queries_version`，并在 `state/seen.json` 中记录变更，
> 下一期简报必须标注「检索式已变更，本期新增条目可能包含追溯性命中」。

```
queries_version: 1
date_field: EDAT   # 强制。不得改为 PDAT。
```

## 通用片段

以下片段在各 track 中复用，记为 `{PEDS}`、`{DISEASE}`、`{WINDOW}`。

```
{PEDS} =
("child"[MeSH] OR "infant"[MeSH] OR "adolescent"[MeSH]
 OR child*[tiab] OR pediatr*[tiab] OR paediatr*[tiab] OR infant*[tiab] OR adolescen*[tiab])

{DISEASE} =
("Nephrosis, Lipoid"[MeSH] OR "Nephrotic Syndrome"[MeSH]
 OR "minimal change disease"[tiab] OR "minimal change nephrotic syndrome"[tiab]
 OR "nephrotic syndrome"[tiab] OR "idiopathic nephrotic syndrome"[tiab]
 OR "steroid sensitive nephrotic syndrome"[tiab] OR "steroid-sensitive"[tiab]
 OR "steroid dependent nephrotic syndrome"[tiab] OR "steroid-dependent"[tiab]
 OR "frequently relapsing"[tiab] OR SSNS[tiab] OR SDNS[tiab] OR FRNS[tiab] OR MCD[tiab])

{WINDOW} =
("YYYY/MM/DD"[EDAT] : "YYYY/MM/DD"[EDAT])
```

> `{DISEASE}` 故意包含成人条目——成人证据要被**检出并标注为成人**，而不是在检索层被丢掉。
> 是否外推由硬约束 2 在解读层控制，不在检索层控制。
> `{PEDS}` 只用于 track B/D/F（临床类），A/C（机制与标志物）不加，避免漏掉未标注人群的基础研究。

---

## Track A — 机制

```
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

```
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

```
{DISEASE}
AND (biomarker*[tiab] OR "anti-nephrin antibod*"[tiab] OR autoantibod*[tiab]
     OR proteom*[tiab] OR metabolom*[tiab] OR transcriptom*[tiab]
     OR "single cell"[tiab] OR "urinary CD80"[tiab] OR suPAR[tiab]
     OR predict*[ti] OR prognos*[ti] OR stratif*[ti] OR "treatment response"[tiab])
AND {WINDOW}
```

> **打分时必须区分**：诊断（diagnostic）/ 预后（prognostic）/ 预测疗效（predictive）是三种不同功能，
> 不得混用。一个标志物只在其被验证的那一类功能上计分。

## Track D — 自然史与安全性

```
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

```
{DISEASE}
AND (guideline*[tiab] OR "practice guideline"[pt] OR consensus[tiab] OR recommendation*[tiab]
     OR KDIGO[tiab] OR IPNA[tiab] OR ESPN[tiab] OR ERA-EDTA[tiab] OR "position statement"[tiab])
AND {WINDOW}
```

补充非索引来源（脚本无法覆盖，需人工/宿主抓取，命中即视为 novelty 3）：
- KDIGO 官网 glomerular diseases 章节更新
- IPNA 临床实践建议（clinical practice recommendations）
- ESPN / ERA 工作组声明

## Track F — 临床试验

ClinicalTrials.gov API v2：

```
GET https://clinicaltrials.gov/api/v2/studies
  ?query.cond=nephrotic syndrome OR minimal change disease
  &filter.advanced=AREA[LastUpdatePostDate]RANGE[YYYY-MM-DD,YYYY-MM-DD]
  &pageSize=200
  &countTotal=true
  &format=json
```

**追踪的是状态变更，不是新出现。** 需要记录并比对的字段：

| 字段 | JSON 路径 |
|---|---|
| 注册号 | `protocolSection.identificationModule.nctId` |
| 标题 | `protocolSection.identificationModule.briefTitle` |
| 状态 | `protocolSection.statusModule.overallStatus` |
| 期相 | `protocolSection.designModule.phases` |
| 入组人群 | `protocolSection.eligibilityModule` (`minimumAge` / `stdAges`) |
| 结果是否公布 | `hasResults` |
| 最近更新日 | `protocolSection.statusModule.lastUpdatePostDateStruct.date` |

### ISRCTN

```
GET https://www.isrctn.com/api/query/format/default
  ?q=nephrotic syndrome OR minimal change disease
  &limit=500
```

返回 XML（命名空间 `http://www.67bricks.com/isrctn`）。**无服务端日期过滤**，全库命中量小
（nephrotic 约 60 条），因此全量取回后按 `trial/@lastUpdated` 在客户端过滤。

ISRCTN 不暴露统一的 `overallStatus` 字段（网页上的招募状态是由日期加 override 推导的）。
`trial/@version` 每次记录编辑递增，是最可靠的变更信号，因此 `status_hash` 由
`version | overallEndDate | recruitmentEnd | publicationStage` 组成。

### EU CTIS

```
POST https://euclinicaltrials.eu/ctis-public-api/search
Content-Type: application/json

{"pagination": {"page": 1, "size": 100},
 "searchCriteria": {"containAll": "nephrotic syndrome"}}
```

同样无服务端日期过滤，按 `lastUpdated`（`DD/MM/YYYY`）客户端过滤。
`ctStatus` 是不透明的整数码，**原样保留，不臆造状态标签**。
`ageGroup` 含 `0-17 years` 时才是儿童试验——CTIS 里相当一部分肾病综合征试验是纯成人的。

### 未覆盖的注册库（已知缺口，须写进简报的方法学小节）

| 注册库 | 状态 | 原因 |
|---|---|---|
| CTRI（印度） | **未覆盖** | 只有 PHP 表单，无检索 API；`POST advsearch.php` 实测只返回错误页 |
| jRCT（日本） | **未覆盖** | 仅 HTML 检索页，无 API |
| ChiCTR（中国） | **未覆盖** | 无公开 API |
| WHO ICTRP | **未覆盖** | 聚合了上述三家，但 `trialsearch.who.int` 无可用 API（实测 404），全量导出需申请协议 |

这几家都需要人工在门户上按季度抽查。CTRI 对儿童肾病综合征病例量不小，是当前最值得补的缺口——
若要脚本化，只能走 HTML 抓取，而抓取在医疗监测场景里会静默失效，风险高于收益，故本期不做。

---

## Track G — 预印本（Europe PMC）

```
GET https://www.ebi.ac.uk/europepmc/webservices/rest/search
  ?query=("nephrotic syndrome" OR "minimal change disease" OR "podocyte")
         AND SRC:PPR
         AND FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD]
  &format=json&resultType=core&pageSize=100&cursorMark=*
```

`SRC:PPR` 覆盖 medRxiv、bioRxiv、Research Square 等预印本服务器。

两条处理规则：

1. 预印本按 `references/scoring-rubric.md` 的降级规则**扣 1 分**（未同行评议），且默认归入 track A。
2. **预印本转正式发表**由 `title_norm` 去重自动捕捉——同一研究不会在预印本阶段和发表阶段各报一次。
   这正是四级去重里要有规范化标题这一级的原因。
