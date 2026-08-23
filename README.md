# med-skill

儿童肾病综合征证据监测技能（living evidence surveillance），聚焦微小病变肾病（MCD）及临床重叠表型：SSNS、FRNS、SDNS。

## 目标

每月产出一份简体中文**增量**证据简报（delta brief），覆盖机制、治疗、生物标志物、自然史与安全性、指南共识、临床试验六条 track。
调度与投递由宿主应用负责；本仓库只定义技能本身。

## 设计原则

- 不把 SSNS 等同于活检确诊的 MCD。
- 儿童证据与成人证据分开。
- 机制证据与临床证据分开。
- 科学重要性与患者相关性分开打分，不合成总分。
- 追踪月度证据**变化量**，而不是每月重写一份泛化综述。
- 滚动检索窗口 + 持久化 PMID/试验注册号去重。
- 明确写出每项研究**证明了什么**与**没有证明什么**。

## 仓库结构

```
SKILL.md                              技能主文件（frontmatter + 工作流 + 硬约束）
references/
  search-queries.md                   六条 track 的固化检索式（唯一真源，脚本从此解析）
  scoring-rubric.md                   三维量表、锚点、入选阈值、阴性结果豁免通道
  state-schema.md                     seen.json schema、去重顺序、试验状态差分规则
templates/
  brief-template.md                   简报章节与必填字段
  patient-profile.example.md          患者画像模板
scripts/
  fetch_evidence.py                   检索/抓取/去重/状态差分（仅标准库）
state/
  seen.example.json                   状态文件示例（真实 seen.json 已 gitignore）
tests/
  README.md                           回归夹具与检查清单
```

## 运行

```bash
# 首次：建立 24 个月基线
python scripts/fetch_evidence.py --bootstrap

# 每月：从 state 推导窗口（自动重叠 15 天）
python scripts/fetch_evidence.py

# 简报生成成功后才回写 state
python scripts/fetch_evidence.py --commit-state
```

产物为 `out/candidates-YYYY-MM.json`，交由模型按 `references/scoring-rubric.md` 打分、按
`templates/brief-template.md` 撰写简报。

可选环境变量 `NCBI_API_KEY`（有 key 时 E-utilities 限速从 3 req/s 提到 10 req/s）。

## 关键实现约定

- 日期字段**必须**用 `[EDAT]`（Entrez 入库日），不得用 `[PDAT]`（出版日）。PDAT 会被期刊回填和乱序，
  用于滚动窗口必然同时造成漏检与重复。脚本会在检出 `[PDAT]` 时直接报错退出。
- 检索式改动须 bump `queries_version`，下一期简报必须标注可能含追溯性命中。
- track F 追踪的是试验**状态变更**（招募→完成、方案修订、结果公布、提前终止），不只是新登记。
- 抗 nephrin 抗体等条目会同时命中机制与生物标志物 track，去重时保留跨 track 标记，不折叠。
- 只在简报成功生成后回写 state，避免失败运行永久跳过一个窗口。

## 隐私

`patient-profile.md` 与 `state/seen.json` 含健康相关信息，已在 `.gitignore` 中排除，不要提交。
投递地址由宿主应用配置传入，不在本仓库硬编码。

## 免责

本仓库用于研究与证据监测，**不构成医疗建议，不替代临床诊疗**。任何治疗调整须与主诊医师讨论。
