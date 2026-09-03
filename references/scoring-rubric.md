# 三维评分量表与入选分诊

三个维度独立评价，不得合成总分：

- `S` = Evidence strength：**对该研究实际主张（claim）而言**证据有多强
- `N` = Novelty：相对于当前 `state.baseline` 改变了多少
- `R` = Patient relevance：与私有 patient profile 的相关程度

另外每条 material item 必须显示三个非数值标签：

```text
population_directness: direct | indirect | mixed | not_applicable
peer_review_status: peer_reviewed | preprint | guideline | registry | book_chapter
evidence_basis: full_text | abstract_only | registry_record | guideline_full_text
```

`book_chapter` 用于 PubMed 中的 NCBI Bookshelf 条目（StatPearls、GeneReviews 等）。这些是**三级教育性内容**，不是原始研究：可用于背景理解和术语核对，但**不得作为 material 证据**支撑任何 claim 变化，也不得进入 baseline。decision 固定使用 S1/N1（内容更新≠新证据）。

`S/N/R` 不替代 GRADE，也不应伪装成标准化临床指南证据等级。

---

## 维度 1：Evidence strength（S，1–5）

### 原则：按 claim type 评分

不能用同一把“RCT 尺子”评价机制研究、biomarker 和自然史。先标注 `claim_type`，再使用对应锚点。

### A. 治疗 / 临床干预 claim

| S | 锚点 |
|---|---|
| 5 | 高质量系统综述/Meta（底层研究质量与一致性良好）、多项一致 RCT，或基于充分证据的正式指南推荐 |
| 4 | 设计和执行良好的 RCT；或具有强比较设计的多中心前瞻研究 |
| 3 | 前瞻性队列、良好对照的回顾队列、较小或存在重要限制的 RCT |
| 2 | 无对照病例系列、横断面、小样本探索研究 |
| 1 | 个案、会议摘要、纯专家观点；前临床研究不能作为治疗有效性的临床证据 |

### B. 机制 claim

| S | 锚点 |
|---|---|
| 5 | 在独立人群中重复的人体机制证据，并有正交/功能验证，能够稳健支持同一机制链条 |
| 4 | 高质量人体机制研究：多中心或独立验证队列、组织/血液/尿液证据与机制读出一致 |
| 3 | 单个人体队列或病例对照研究提供较一致的机制证据，但尚缺独立复制/功能闭环 |
| 2 | 小样本人群探索、纯组学相关性、未经充分验证的抗体/通路信号 |
| 1 | 动物、类器官、体外模型或假说性研究（可有科研价值，但不能当成人体机制已证实） |

### C. Biomarker claim

必须先指定功能：`diagnostic` / `prognostic` / `predictive`。

| S | 锚点 |
|---|---|
| 5 | 多个独立队列外部验证，性能稳定，且针对同一 biomarker 功能有明确临床阈值/可重复性 |
| 4 | 大型或多中心前瞻验证，包含外部/独立验证集或严格预设分析 |
| 3 | 单队列较充分验证，有合理对照和性能指标，但缺外部验证 |
| 2 | 探索性关联、小样本、仅 discovery cohort |
| 1 | 纯组学候选信号、个案或前临床 biomarker 假说 |

### D. 自然史 / 安全性 claim

| S | 锚点 |
|---|---|
| 5 | 高质量系统综述或多个大型长期队列结果一致；严重安全信号被重复确认 |
| 4 | 多中心前瞻长期队列、可靠药物警戒/注册数据或大型比较性安全研究 |
| 3 | 设计良好的单中心长期队列或有对照回顾队列 |
| 2 | 无对照系列、小样本回顾研究 |
| 1 | 个案、会议摘要、假说性安全信号 |

### E. 指南 / 共识

指南不能仅因“来自权威组织”自动记 S5。记录该推荐本身的证据等级和方法学：

- 正式 evidence-based guideline + 清晰 evidence grading：通常 S4–5
- consensus / position statement：通常 S2–4，取决于证据基础
- 网页文字更新、勘误或行政更新：不构成独立高强度证据

### 通用降级因素

以下因素影响的是**可解释性/偏倚风险**，而不是“成人就自动低分”：

- 混合疾病表型且关键结果未分层
- 混合年龄层且关键结果未分层
- 严重失访、选择偏倚、未预设分析、明显 outcome switching
- 只报告无法直接支持目标 claim 的替代读出

注意：在肾病综合征研究中，蛋白尿缓解/复发本身常是核心疾病结局；不能笼统把“proteinuria”视为低价值 surrogate。应结合研究问题判断。

### 成人证据的处理

成人研究的 S 评价“在其研究人群中证据多强”，**不因成人身份机械降分**。是否能用于儿童由 `population_directness`、R 和文字适用性说明控制。

---

## 预印本规则

预印本不是内容 track。先按研究设计给一个**暂定 S**，再标记：

```text
peer_review_status = preprint
```

约束：

1. 预印本的暂定 `S` 最高为 3；避免把未同行评议研究与已复核高强度证据等量齐观。
2. 预印本不得更新正式 baseline。
3. 预印本不得单独触发 `practice-changing` 或 `clinically_validated_change`。
4. 重大预印本可以进入“早期信号 / watchlist”，但必须醒目标记未同行评议。
5. 正式发表后必须重新进入流程作为 `publication_transition`，重新评分，而不是因为 title_norm 相同而被静默跳过。

---

## 维度 2：Novelty（N，1–3）

相对 `state.baseline` 判断。

| N | 锚点 |
|---|---|
| 3 | 实质挑战/改写既有基线；首次出现并有足够证据支持的重要机制/靶点；正式指南发生实质推荐变化 |
| 2 | 扩展既有方向：新的量化、亚组、比较臂、长期结果、独立复制或新的安全性信号 |
| 1 | 基本确认既有判断，没有重要新限定 |

**重要：**
- “来自 KDIGO/IPNA/ESPN”不自动等于 N3。
- 正式指南只有在推荐方向、强度、证据等级、适用人群、治疗顺序或重要安全性立场发生变化时才可能 N3。
- `publication_transition` 本身通常 N1–2；只有正式版结论与预印本明显改变时才可能 N3。

建议同时给出文本分类：

```text
CONFIRMS_EXISTING_MODEL
EXTENDS_EXISTING_MODEL
CHALLENGES_EXISTING_MODEL
NEW_HYPOTHESIS
PARADIGM_SHIFT_CANDIDATE
CLINICALLY_VALIDATED_CHANGE
```

---

## 维度 3：Patient relevance（R，1–3 或 N/A）

需要私有 `patient-profile.md`。

| R | 锚点 |
|---|---|
| 3 | 年龄/表型高度匹配，并直接涉及当前或近期真实决策点、用药或关键长期风险 |
| 2 | 表型较匹配，但治疗线/时点不同；或与当前治疗长期安全性相关 |
| 1 | 同疾病谱但年龄、表型、治疗阶段或研究对象差异明显 |
| N/A | 未配置 patient profile |

R 只表示“值得关注”，**不能提升 S**。

---

## 入选分诊

### 正文 material

满足任一：

1. `S >= 3 AND N >= 2`
2. `R = 3 AND S >= 2`
3. 阴性/无效结果：`S >= 3`
4. 新安全性信号：`S >= 2`
5. 正式指南的实质推荐变化

### 特殊限制

- `S = 1` 的前临床/纯探索证据即使 R=3，也只能进入机制 watchlist，不进入临床相关正文。
- 预印本只能进入“早期信号/预印本”区；不能成为正式 baseline 或 practice-changing 证据。
- 正文建议上限 12 条，超出时按临床/科学重要性而非单纯 R 排序。

### 附录

其余相关条目进入附录；明显跑题才丢弃。

---

## Full-text requirement

拟进入正文的研究：

- 有合法全文 → 优先基于全文评价，并记录 `evidence_basis=full_text`
- 无法取得全文 → 可基于摘要评价，但必须记录 `abstract_only`
- `abstract_only` 时不得补写摘要未报告的剂量、亚组、终点定义、统计方法或安全性细节

---

## 打分自检

- [ ] claim_type 是否明确？
- [ ] 是否先标注年龄/表型，再解释适用性？
- [ ] SSNS 是否被错误写成活检 MCD？
- [ ] 成人研究是否显式标 `population_directness`？
- [ ] 机制证据是否被写成临床疗效？
- [ ] biomarker 的 diagnostic/prognostic/predictive 功能是否混用？
- [ ] S 是否按 claim-specific 锚点评，而不是只看“是不是 RCT”？
- [ ] 预印本是否被错误写入 baseline？
- [ ] 书籍/教材条目（book_chapter）是否被误当成原始研究证据？
- [ ] material study 有全文时是否阅读全文？
- [ ] `what_this_changes` 与 `what_this_does_not_prove` 是否具体？
