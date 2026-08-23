# med-skill

一个可移植的 Agent Skill：按月监测儿童肾病综合征 / 微小病变肾病（MCD）相关证据，重点覆盖 SSNS、FRNS、SDNS，并生成简体中文 living evidence delta brief。

## 目标

每月回答三个问题：

1. 本期真正出现了什么新的学术/临床证据？
2. 这些证据相对既有 baseline 是确认、扩展、挑战还是可能改变实践？
3. 哪些证据与儿童 MCD/SSNS/FRNS/SDNS 的真实临床问题最相关？

宿主应用负责调度和最终投递；仓库本身不绑定 Gmail、Outlook 或 SMTP，也不硬编码个人邮箱。

## 六个证据领域

- A：机制（mechanism）
- B：治疗（treatment）
- C：生物标志物与精准表型（biomarker / precision phenotyping）
- D：自然史与安全性（natural history / safety）
- E：指南与共识（guideline / consensus）
- F：临床试验注册与状态变化（clinical trials）

**预印本不是第七个领域。** Europe PMC `SRC:PPR` 是补充来源；预印本仍映射回 A–E，并单独标记 `peer_review_status=preprint`。

## 核心设计原则

- 不把 SSNS 当成 biopsy-confirmed MCD。
- 成人证据可以被发现，但儿童适用性必须单独标注。
- 机制证据、biomarker 证据、治疗证据使用各自适合的 evidence-strength 锚点。
- S（strength）/ N（novelty）/ R（patient relevance）分别评价，不合成总分。
- PubMed 使用 EDAT 滚动窗口并分页取全；候选至少抓取 abstract。
- 拟进入正文的研究，有合法全文时优先阅读全文；仅摘要时必须标记 `abstract_only`。
- 预印本不能更新正式 baseline，也不能单独形成 practice-changing 结论。
- 预印本正式发表后重新进入流程，作为 `publication_transition` 重新评分。
- 只报告相对既有 baseline 的增量，不每月重写泛化综述。
- 每条 material study 都必须写 `what_this_changes` 和 `what_this_does_not_prove`。

## 仓库结构

```text
SKILL.md                              Agent Skill 主文件
references/
  search-queries.md                   A–F 固化检索策略、注册库/预印本来源规则
  scoring-rubric.md                   claim-specific S/N/R 评级与分诊
  state-schema.md                     candidate→decision→state 两阶段状态协议
templates/
  brief-template.md                   月度简报模板
  patient-profile.example.md          私有患者画像模板
  decisions.example.json              state commit 决策文件示例
scripts/
  fetch_evidence.py                   确定性抓取、去重、trial diff、state commit
state/
  seen.example.json                   schema v2 示例；真实 seen.json 被 gitignore
tests/
  README.md                           回归验证说明
```

## 运行流程

### 1. 首次建立 24 个月 baseline 候选集

```bash
python scripts/fetch_evidence.py --bootstrap
```

### 2. 正常月度抓取

```bash
python scripts/fetch_evidence.py
```

脚本输出：

```text
out/candidates-YYYY-MM.json
```

其中包含唯一 `run_id`。抓取阶段**不会修改 state**。

### 3. 宿主 AI 进行证据解读并生成简报

宿主读取：

- `SKILL.md`
- `references/scoring-rubric.md`
- `templates/brief-template.md`
- 当期 `out/candidates-YYYY-MM.json`
- 可选私有 `patient-profile.md`

然后生成：

```text
out/brief-YYYY-MM.md
out/decisions-YYYY-MM.json
```

`decisions` 必须复用 candidates 中相同的 `run_id`，并设置：

```json
"brief_generated": true
```

### 4. 只有简报成功后才提交 state

```bash
python scripts/fetch_evidence.py --commit-state \
  --candidates out/candidates-YYYY-MM.json \
  --decisions out/decisions-YYYY-MM.json
```

commit 阶段**不会重新联网检索**。这保证写入 state 的就是刚才实际分析并形成简报的那一批候选，而不是一个时间上已发生漂移的新抓取结果。

## 数据源

### 核心来源

| 来源 | 用途 | 当前策略 |
|---|---|---|
| PubMed E-utilities | A–E 正式文献 | `[EDAT]` + 分页取全 + EFetch abstract |

PubMed 是核心来源；若其抓取不完整，本期运行应失败，而不是生成一个伪“完整”简报。

### 补充来源

| 来源 | 用途 | 状态 |
|---|---|---|
| ClinicalTrials.gov API v2 | Track F | integrated |
| ISRCTN XML API | Track F | integrated |
| EU CTIS public portal backend | Track F | integrated, experimental endpoint stability |
| Europe PMC `SRC:PPR` | 预印本 | integrated |
| KDIGO / IPNA / ESPN / ERA 官网 | 指南核验 | host-assisted |
| WHO ICTRP | 全球试验聚合 | `available_but_not_integrated` |

WHO ICTRP 官方提供 Search Portal、XML/CSV 下载以及研究用途 Web Service；因此不能把它描述成“没有 API”。

### 当前未稳定单独接入

- CTRI
- jRCT / JPRN
- ChiCTR
- 部分区域数据库与非 PubMed 索引来源

这些状态写为 `not_integrated_or_not_verified`，而不是永久断言“无 API”。PubMed 检索本身没有设置英语过滤，因此局限不是“非英文文献全部未覆盖”，而是**非 PubMed 索引的区域/非索引文献未系统覆盖**。

## 状态安全

真实文件：

```text
patient-profile.md
state/seen.json
out/
```

均不应提交到 GitHub。`patient-profile.md` 包含健康隐私；`state/seen.json` 可能包含 patient relevance 评分痕迹。

## 检索式与 schema 版本

当前：

```text
Skill: 0.3.0
queries_version: 2
state schema_version: 2
```

从旧 v0.2 state 升级时，首次运行可能把旧 trial `status_hash` 视为需要重新建立 `protocol_hash` 的 `protocol_record_updated`；这属于一次性 migration，不应误写成真实临床状态改变。

## 宿主投递

宿主运行时提供：

```json
{
  "config": {
    "recipient": "<email-address>"
  }
}
```

Skill 输出 Markdown / text / HTML 邮件正文。若宿主具有邮件工具则发送；否则返回：

```json
"delivery_pending": true
```

## 免责

本项目用于研究与证据监测，**不构成医疗建议，不替代临床诊疗**。任何具体治疗调整应由患儿的临床团队结合完整病史决定。
