# 简报模板

严格套用本模板。无内容时写“本期无”，不要删除小节。

---

# 儿童 MCD / 肾病综合征证据月报 · {{YYYY-MM}}

> 本简报为文献与试验注册监测产出，**不构成医疗建议，不替代临床诊疗**。  
> 检索窗口：{{start}} ~ {{end}}（PubMed EDAT） · 模式：{{delta | bootstrap}} · query v{{queries_version}}  
> 核心源完整性：{{complete / incomplete}} · {{若无 patient-profile：patient relevance = N/A}}

## 一句话结论

{{明确回答：本期是否出现足以改变既有判断的新证据？如果没有，直接写“本月无足以改变既有判断的高质量新证据”。}}

## 本期概览

| 指标 | 数量 |
|---|---:|
| PubMed unique hits | {{n}} |
| 新论文 | {{n}} |
| 预印本→正式发表 | {{n}} |
| 进入正文 material | {{n}} |
| 附录 | {{n}} |
| 新试验登记 | {{n}} |
| 试验记录重要变化 | {{n}} |
| 新预印本 | {{n}} |

---

## 一、可能改变既有判断的正式证据

> 主要放 N=3 且满足正式证据条件的条目。预印本不能进入本节。

### {{序号}}. {{中文意译标题}}

**原题**：{{original_title}}  
**来源**：{{PMID / DOI / guideline URL}} · {{journal / organization}} · {{date}}  
**领域**：{{A/B/C/D/E，可多选}}  
**人群**：{{儿童 / 成人 / 混合}} · {{biopsy-confirmed MCD / presumed MCD / SSNS / FRNS / SDNS / FSGS / mixed}}  
**claim type**：{{treatment / mechanism / diagnostic biomarker / prognostic biomarker / predictive biomarker / natural history / safety / guideline}}  
**证据基础**：{{full_text / abstract_only / guideline_full_text}}  
**同行评议**：{{peer_reviewed / guideline}}  
**适用性**：{{population_directness}}  
**打分**：S{{1-5}} · N{{1-3}} · R{{1-3 / N/A}}  
**范式状态**：{{CONFIRMS / EXTENDS / CHALLENGES / NEW_HYPOTHESIS / PARADIGM_SHIFT_CANDIDATE / CLINICALLY_VALIDATED_CHANGE}}

- **研究做了什么**：{{设计、人群、N、关键比较/机制}}
- **主要结果**：{{只写来源实际报告的数据；abstract_only 时不要补充摘要之外的细节}}
- **what_this_changes**：{{具体改变哪条 baseline claim}}
- **what_this_does_not_prove**：{{至少写一项边界}}
- **与既有 baseline 的差异**：{{X → Y，或说明只是限定}}
- **可与主诊医师讨论的问题**：{{可选，只写问题，不写治疗指令}}

---

## 二、扩展与确证性正式证据

> N=1–2 且达到 material 条件的正式发表研究。字段同上，可适当精简。

---

## 三、机制与 biomarker 重点

> 分开回答“人体机制证据强不强”和“是否已有临床可用性”。biomarker 必须标明 diagnostic / prognostic / predictive 功能。

---

## 四、安全性与自然史

> 优先长期复发轨迹、生长/骨健康、感染、免疫抑制剂毒性、严重不良事件及成年转归。

---

## 五、指南与共识

> 只有实质推荐、证据等级、适用人群、治疗顺序或安全性立场变化才写成 guideline change。官网更新时间变化、勘误或行政更新不得自动视为 N=3。

---

## 六、临床试验动态

| 注册来源 | 注册号 | 试验 | event | status | 年龄 | 结果 | 备注 |
|---|---|---|---|---|---|---|---|
| {{CTGOV/ISRCTN/CTIS}} | {{id}} | {{title}} | {{new_registration/status_changed/results_posted/early_stop/protocol_record_updated}} | {{status}} | {{age}} | {{yes/no/unknown}} | {{}} |

规则：
- `protocol_record_updated` 不得伪写成 status transition。
- 成人-only 试验必须明确标记。
- registry 无法可靠判断结果状态时写 `unknown`，不要猜。

---

## 七、预印本与早期信号（未同行评议）

> 预印本是来源状态，不是第七证据领域。每条仍标 A–E 内容领域。不得更新正式 baseline，也不得单独形成 practice-changing 结论。

- {{标题}} · {{PPR/DOI}} · 领域 {{A-E}} · 暂定 S{{1-3}}/N{{1-3}}/R{{1-3/N/A}} · {{一行结论}} · **未同行评议**

### 本期预印本→正式发表

- {{published title}} · {{PPR prior_key}} → {{PMID current_key}} · {{正式版是否改变样本/结果/结论/风险表述}}

---

## 八、附录：其他相关命中

<details><summary>展开 {{n}} 条</summary>

- {{identifier}} · {{title}} · {{track}} · {{S/N/R 或未评分}} · {{一句话}}

</details>

---

## 方法学与局限

- PubMed 为核心来源，使用 EDAT 滚动窗口并分页取全；候选至少读取 abstract。
- 拟进入正文的研究：{{n_full_text}} 项基于全文，{{n_abstract_only}} 项仅基于摘要。仅摘要条目不得外推摘要未报告细节。
- 补充来源：ClinicalTrials.gov、ISRCTN、EU CTIS public portal backend、Europe PMC preprints，以及宿主对 KDIGO/IPNA/ESPN/ERA 官方页面的核验。
- WHO ICTRP：官方存在 Search Portal、XML/CSV 下载和研究用途 Web Service；当前本仓库状态为 `available_but_not_integrated`。
- 区域注册库 CTRI、jRCT/JPRN、ChiCTR：当前为 `not_integrated_or_not_verified`；不要写成永久“无 API”。
- 非 PubMed 索引的区域数据库及非索引文献未系统覆盖；**PubMed 本身并未按英语过滤**。
- **本期 source_errors**：{{逐条列出；为空写“无”}}
- query version 若本期变化：{{说明是否存在 retrospective hits}}
- S/N/R 是本项目内部评级，不是 GRADE。
- {{其他局限}}

---

## 给宿主应用的投递对象

```json
{
  "recipient": "{{config.recipient}}",
  "subject": "儿童 MCD / 肾病综合征证据月报 · {{YYYY-MM}}",
  "markdown": "...",
  "text": "...",
  "html": "...",
  "delivery_pending": {{true|false}}
}
```
