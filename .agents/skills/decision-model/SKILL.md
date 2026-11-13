<!-- @version 2.9.0 -->
---
name: decision-model
description: 百炼 Token Plan 决策模型 decision-model-preview 的调用能力。结构化判定（choice/score/noul）直接返回 choice/probabilities/confidence，不生成自然语言，低延迟低 token，用于字幕校准歧义裁决、评论审核、工单分类等判定场景。触发词：决策模型、decision-model、systemone、置信度、歧义裁决、判定分流。
---

# 决策模型 · 技能卡（decision-model-preview）

> 按百炼官方《接入决策模型》部署文档落地（2026-11-12 实测通路）。
> **它不是对话模型**：走专用端点 `systemone`，走 chat/completions 必报 url error。

## 端点与凭据（当前 Token Plan 配置）

- 端点：`POST https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/systemone`
- 鉴权：`Authorization: Bearer <Token Plan 密钥>`（`sk-sp-` 前缀）。
  密钥存 `data/credentials.json` 的 `asr_api_key`（与 ASR 槽同一枚 Token Plan 键），
  配套脚本自动读取，**不硬编码、不打印、不贴对话**。
- 限制：仅 Token Plan 个人版支持。

## 调用方式

```bash
tools\python\python.exe .agents\skills\decision-model\decision_call.py <payload.json> [--base <BASE_URL>]
```

payload 即官方请求体：`{"model": "decision-model-preview", "state": {...}, "questions": {...}}`。
stdout 只落一个 JSON（成功=上游响应；失败=`{"error": ...}`，退出码 1）。

## 请求/响应契约

- `state`：待判定内容（任意 JSON，questions 的 instructions 里引用它）。
- `questions`：key 自定义；每个问题三型之一（可混合、一次并行评估）：
  - `choice`：`criteria` 为 dict，写各选项的判定边界（**边界写进 criteria 比改措辞有效**）；
  - `score`：`criteria` 必须是**有序 list**（等级描述，dict 会 400）；返回连续 `score` +
    0 起编号的 `legend` + 各等级 `probabilities`；
  - `noul`：无需 criteria，返回 0–1 概率 `noul`。
- 响应 `answers.<key>`：`choice`（选中结论）/ `probabilities`（分布，和为 1）/ `confidence`（把握 0–1，近似概率差，偏保守）。

## 实测能力矩阵（2026-11-12，必读）

| 场景 | 结果 | 结论 |
|---|---|---|
| 评论审核（含激烈批评/边界的广告） | 6/6 全对；清晰例 confidence≥0.98、边界例 0.53 | **强项**，置信度校准良好，可按阈值分流 |
| 请求路由（工具箱五能力） | 4/5；唯一错例 confidence 仅 0.27 | 可用**置信度阈值路由器**：高置信自动、低置信转人工/大模型 |
| score 自然度打分 / noul 广告概率 | 机翻腔判 1.87/4、广告判 0.95，均合理 | 可用 |
| 字幕术语校准裁决 | 三轮探针均近随机，confidence 不指示正确性 | **不可用**，校准继续走规则引擎 + AI 校准主链 |

延迟 30–60ms、批量并行、输出 token 极省。放量前仍先小批量测准确率。

## 校准场景格式示例（仅演示请求格式，勿用于校准裁决）

state 放 `lines`（序号→中文行）与 `official`（官方名表），每行一个 choice 问题：
「该行译名是否需校准为官方名？」criteria：`fix`=错形需改 / `ok`=正确不动。
拿回 answers 后按置信度分流：高置信 fix 才进改动候选，低置信**留痕转人工，不要重试**。
（文档的 0.9 阈值只是示例，按误判成本自定；实测 confidence 近似概率差，偏保守。）

## 错误处理

- 401：查密钥（须 sk-sp- Token Plan 键）；422：请求体校验失败，响应正文指出出错字段；
- 429/529：退避后重试；其余读 error 换方案，不要原样重试。
- 高风险动作（封号/资金类）保留人工复核——模型输出是判定与把握，不是事实担保。