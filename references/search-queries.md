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

其他注册库（本期未脚本化，作为已知缺口）：ISRCTN、CTRI（印度，儿童肾病病例量大）、jRCT、ChiCTR。
