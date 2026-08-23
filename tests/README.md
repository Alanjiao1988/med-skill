# 回归夹具

改动检索式、评分量表或模板后，用固定夹具重跑并对比输出，否则无法判断改动是变好还是变坏。

## 建立夹具

```bash
python scripts/fetch_evidence.py --start 2026-06-01 --end 2026-07-31
cp out/candidates-2026-07.json tests/fixture-2026-07/candidates.json
```

把当期人工确认过的简报存为 `tests/fixture-2026-07/expected-brief.md`，作为「金标准」。

## 回归检查清单

用夹具重新生成简报后逐条核对：

- [ ] 每条 material 条目的 `what_this_changes` / `what_this_does_not_prove` 都非空且非套话
- [ ] SSNS 条目未被表述为活检确诊 MCD
- [ ] 成人研究均带显式适用性标签
- [ ] 机制研究未出现疗效结论
- [ ] 阴性结果条目未被 novelty 规则误杀（对照 rubric 的豁免通道）
- [ ] 跨 track 命中（如 anti-nephrin）未被折叠成单一 track
- [ ] 试验区分了「新登记」与「状态变更」，而非只报新出现
- [ ] 三个注册库的条目都带 registry 标签，未混为一谈
- [ ] CTIS 条目的 `ageGroup` 是否含 `0-17 years`——纯成人试验不得当作儿童证据
- [ ] 预印本条目已扣 1 分且标注未同行评议
- [ ] 已发表版本出现时，对应预印本未被重复报告为新发现
- [ ] `source_errors` 非空时，简报的方法学小节是否如实声明了失败的源
- [ ] S/N/R 三个分数分别给出，未合成总分

## 已知未覆盖

脚本已覆盖：PubMed、ClinicalTrials.gov v2、ISRCTN、EU CTIS、Europe PMC 预印本。

未覆盖：CTRI（印度）、jRCT（日本）、ChiCTR（中国）、WHO ICTRP、会议摘要、非英文文献。
这几家无可用 API，需人工按季度在门户抽查，抽查结果手工并入当期简报。
