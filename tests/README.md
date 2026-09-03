# 回归与审计清单

本目录用于验证 med-skill 的关键不变量。修改检索式、评分量表、state schema 或 brief template 后，应先运行本地 invariant tests，再使用固定候选夹具重新跑证据解释，并比较结构和结论变化。

## 快速本地测试

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

`tests/test_invariants.py` 当前锁定以下关键行为：

- Unicode 标题规范化不破坏中文/非拉丁字符
- trial protocol 更新不会被伪装成 status change
- results posted 的事件优先级
- formal baseline 拒绝 `PPR:` 预印本来源
- candidate 缺 decision 时 state commit fail closed
- preprint 不能用 `verdict=material`
- 合法 peer-reviewed / preprint-watchlist decision 可通过验证
- 注册库离题记录（肿瘤/骨科/内分泌试验）被主题复核拒绝
- 肾小球病 basket trial 不被主题复核误杀
- ClinicalTrials.gov 检索短语保持加引号
- PubMed book 记录可解析，且标记为 `book_chapter` 而非 `peer_reviewed`
- E-utilities 请求携带 NCBI 要求的 tool 身份

这些测试不联网。

## 建立候选夹具

```bash
python scripts/fetch_evidence.py --start 2026-06-01 --end 2026-07-31
mkdir -p tests/fixture-2026-07
cp out/candidates-2026-07.json tests/fixture-2026-07/candidates.json
```

把人工复核后的：

```text
tests/fixture-2026-07/expected-brief.md
tests/fixture-2026-07/expected-decisions.json
```

作为回归参照。真实患者画像不得进入 fixture。

## 抓取层必须满足

- [ ] PubMed 查询使用 `[EDAT]`，没有 `[PDAT]`
- [ ] `<PubmedBookArticle>` 被解析；Bookshelf 条目不会让整次运行中断
- [ ] 所有 E-utilities 请求带 `tool`/`email`
- [ ] ClinicalTrials.gov `query.cond` 短语加引号
- [ ] ISRCTN/CTIS 命中经过标题/condition 主题复核
- [ ] ISRCTN `totalCount > limit` 时失败而不是静默截断
- [ ] PubMed 不使用固定 retmax 截断；返回 PMID 数与 ESearch count 一致
- [ ] PubMed 候选包含 abstract；不能只凭 ESummary metadata 评分
- [ ] PubMed 核心源失败时本次抓取 fail closed，不生成伪完整 brief
- [ ] 多 track 命中保留数组，例如 anti-nephrin 可同时 A+C
- [ ] 裸 `MCD`、裸 `steroid-dependent` 等高噪声检索词没有重新引入
- [ ] 预印本 disease query 没有使用裸 `podocyte` 扩展到整个足细胞领域
- [ ] 预印本映射回 A–E；没有恢复成所谓 Track G
- [ ] preprint → peer-reviewed publication 产生 `publication_transition`，而不是被 title_norm 静默吞掉
- [ ] Unicode 标题规范化不会把中文/日文等非拉丁字符清空

## Clinical trial 层必须满足

- [ ] ClinicalTrials.gov 区分 `new_registration`、`status_changed`、`results_posted`、`early_stop`、`protocol_record_updated`
- [ ] hash 变化但 overall status 未变时，不伪写成 `X -> Y` status transition
- [ ] 成人-only trial 显式标明年龄，不因 nephrotic syndrome 关键词就当成儿童证据
- [ ] ISRCTN 无法可靠确定 results status 时允许 `has_results=null`，不从非空 publicationStage 猜 true
- [ ] EU CTIS backend 失败被记录到 `source_errors`
- [ ] EU CTIS backend 被标记为 experimental public-portal endpoint，而非承诺稳定 API
- [ ] WHO ICTRP 状态是 `available_but_not_integrated`，不是 `no_api`
- [ ] CTRI/jRCT/ChiCTR 状态使用 `not_integrated_or_not_verified`，没有永久断言“无 API”

## 证据解释层必须满足

- [ ] SSNS 未被表述为 biopsy-confirmed MCD
- [ ] 成人证据带 `population_directness`，但不会仅因“成人”机械降低其内部研究质量 S
- [ ] treatment / mechanism / biomarker / natural-history 使用 claim-specific S 锚点
- [ ] biomarker 的 diagnostic / prognostic / predictive 功能没有混用
- [ ] 机制研究不会被写成已证明临床疗效
- [ ] 观察性关联不会被写成因果
- [ ] 蛋白尿/缓解终点按具体研究问题解释，没有被一律贴上低价值 surrogate 标签
- [ ] R=3 不会把 S=1 的极弱证据顶成临床正文 material
- [ ] 预印本不会写入 formal baseline，也不会单独形成 practice-changing 结论
- [ ] 指南网页更新不会自动 N=3；必须确认实质 recommendation change
- [ ] 每条 material item 的 `what_this_changes` / `what_this_does_not_prove` 都具体且非空
- [ ] 有合法全文的 material study 优先全文；abstract-only 条目不会补写摘要不存在的细节

## State transaction 必须满足

- [ ] fetch 阶段只写 `candidates`，不修改 `state/seen.json`
- [ ] candidate artifact 有唯一 `run_id`
- [ ] commit 要求 candidate 与 decisions 的 `run_id` 完全一致
- [ ] `brief_generated` 不是 true 时 commit 必须拒绝
- [ ] commit 阶段不联网重新抓取
- [ ] 每个新 paper / publication transition / preprint candidate 都必须有明确 decision；缺任何一项时 fail closed
- [ ] material decision 必须有明确 `evidence_basis`
- [ ] preprint 不能使用 `verdict=material`
- [ ] baseline 的 `sources` 不含 `PPR:`
- [ ] publication transition 后正式 PMID 建立新 entry，PPR 历史 entry 写 `superseded_by`

## 家长层必须满足

- [ ] 「给家长的三句话」存在且恰好三句
- [ ] 无实质进展时第 1 句直说“本月没有需要改变任何事的证据”，没有为凑内容抬高弱证据
- [ ] 门诊问题 ≤3 条，具体、附出处、以“这对我们适用吗”形式提出
- [ ] 门诊问题中没有换药/加药/停药/减量/剂量/化验解读内容
- [ ] 没有输出症状阈值或就医指征（这些应来自患儿医疗团队）
- [ ] 没有对当前治疗方案是否恰当作出评价
- [ ] 没有据国际指南变化暗示国内做法有问题
- [ ] 无 patient-profile 时明确写“未配置患儿画像，无法判断个体相关性”
- [ ] book_chapter 条目没有被当成原始研究证据

## 简报必须披露

- [ ] 核心源完整性
- [ ] source_errors
- [ ] full-text 与 abstract-only 数量
- [ ] queries_version 变化造成的 retrospective-hit 风险
- [ ] WHO ICTRP 尚未自动集成
- [ ] 区域/非 PubMed 索引数据库未系统覆盖
- [ ] 不使用“非英文文献全部未覆盖”这种错误表述，因为 PubMed 本身没有英语过滤
- [ ] S/N/R 明确声明为内部评级而非 GRADE

## 当前覆盖状态

自动化核心/补充源：PubMed、ClinicalTrials.gov、ISRCTN、EU CTIS public portal backend、Europe PMC preprints。

宿主辅助：KDIGO、IPNA、ESPN/ERA 官方页面。

待增强：WHO ICTRP 自动接入，以及 CTRI、jRCT/JPRN、ChiCTR 等区域注册源的稳定集成与验证。
