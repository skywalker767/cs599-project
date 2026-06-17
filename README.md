<div align="center">

# Spec2Vision

**从一句模糊需求，到可下载的视觉资产 —— 先澄清，再规格化，再生成，再评估**

*Visual Spec 驱动的多智能体视觉内容生成 · CS599 课程项目原型*

<br>

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Tests](https://img.shields.io/badge/Tests-129_passed-22C55E?style=for-the-badge)](tests/)
[![CI](https://github.com/skywalker767/Spec2Vision/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

[效果展示](#-效果展示) · [快速开始](#-快速开始) · [核心能力](#-核心能力) · [架构](#-架构与流水线) · [API](#-api-一览) · [文档](#-文档)

<br>

</div>

---

## ✨ 效果展示

> 以下三张图由 **同一条 `/generate` 流水线** 产出（默认 Mock 模式，**零 API Key**）。
> Mock 占位图为确定性纯色 PNG，用于验证链路可复现；启发式评估分数偏低是**预期行为**。
> 切换 `IMAGE_PROVIDER=openai` 后可接入真实图像 API。

<table>
  <tr>
    <td align="center" width="33%">
      <a href="docs/images/examples/ecommerce_coffee.png">
        <img src="docs/images/examples/ecommerce_coffee.png" alt="电商促销主图示例" width="280"/>
      </a>
      <br><br>
      <b>🛒 电商主图</b><br>
      <code>ecommerce_banner</code> · 1:1 · 1024×1024<br>
      <sub>冰咖啡小红书促销 banner · offline score 41</sub>
    </td>
    <td align="center" width="33%">
      <a href="docs/images/examples/academic_pipeline.svg">
        <img src="docs/images/examples/academic_pipeline.svg" alt="学术方法流程图示例" width="280"/>
      </a>
      <br><br>
      <b>📊 学术配图</b><br>
      <code>academic_figure</code> · SVG 矢量流程图<br>
      <sub>五阶段双分支网络 pipeline · offline score 67</sub>
    </td>
    <td align="center" width="33%">
      <a href="docs/images/examples/ppt_cover.png">
        <img src="docs/images/examples/ppt_cover.png" alt="PPT 封面示例" width="280"/>
      </a>
      <br><br>
      <b>🎓 PPT 封面</b><br>
      <code>ppt_visual</code> · 16:9 · 1792×1024<br>
      <sub>AI 驱动软件开发课程封面 · offline score 56</sub>
    </td>
  </tr>
</table>

<details>
<summary><b>📋 对应输入 Prompt（点击展开）</b></summary>

| 场景 | 用户输入（节选） |
|------|------------------|
| 电商 | 为夏季新品「0蔗糖低卡冰咖啡」制作小红书推广主图，突出商品、促销标签、¥19.9 到手价与「立即抢购」CTA… |
| 学术 | 为机器学习论文绘制五阶段方法流程图：预处理 → 特征提取 → 双分支 CNN+Transformer → 融合 → 分类输出… |
| PPT | 为《人工智能驱动的软件开发》课程结课汇报制作封面，深色科技蓝、神经网络元素、左侧标题留白区… |

完整用例见 [`examples/`](examples/) · 重新生成展示图：`py scripts/generate_readme_examples.py`

</details>

---

## 💡 这个项目解决什么问题？

| 传统做法 | Spec2Vision |
|----------|-------------|
| 写一句 Prompt，碰运气等图 | **Router** 识别任务域（电商 / 学术 / PPT），低置信度时主动 **要求澄清** |
| 需求含糊，反复改 Prompt | **Clarification** 交互式问卷（平台、比例、风格、合规…） |
| 生成过程黑盒 | **Visual Spec** 结构化规格 + 全链路 **Agent Trace** JSON |
| 不知道图好不好 | **分层 Evaluator**：确定性校验 + 图像统计启发式 + **可解释 Rubric** |
| 本地 Demo 依赖付费 Key | 默认 **Mock Provider**，`clone → pytest → /generate` 全程离线可跑 |

> **诚实说明**：这是 **课程项目原型（course project prototype）**，不是生产级系统。
> 路由以规则 + 可选 LLM 精修为主；评估是启发式 rubric，不是人类审美模型。详见 [Architecture Notes](#-architecture-notes诚实说明)。

---

## 🚀 快速开始

**30 秒验收路径** — 无需任何 API Key：

```bash
git clone https://github.com/skywalker767/Spec2Vision.git
cd Spec2Vision

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env          # Windows
# cp .env.example .env          # Linux/macOS

pytest                          # 129 passed · 全程 Mock · 无网络
make demo                       # 命令行单次生成 Demo
python run.py                   # 启动 Streamlit UI + FastAPI
```

| 服务 | 地址 |
|------|------|
| Streamlit UI | http://localhost:8501 |
| FastAPI Docs | http://127.0.0.1:8000/docs |
| 健康检查 | http://127.0.0.1:8000/health |

**一条 curl 跑通生成 + 下载：**

```bash
curl -s -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"user_input":"电商促销主图 banner product sale","task_type":"auto","skip_clarification":true}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['task_id'])"
# 将输出的 task_id 代入：
# curl -OJ http://127.0.0.1:8000/tasks/<task_id>/asset
```

---

## 🧩 核心能力

### 1 · 智能路由（Router）

- 加权关键词 / 正则 → 电商 · 学术 · PPT 三类任务
- 输出 `confidence` · `reasoning` · `matched_signals` · `clarification_required`
- **模糊输入不再盲目归为 `ppt_visual`**；`confidence < 0.45` 时返回澄清问题

### 2 · 交互澄清（Clarification）

- 领域模板题库（平台 / 比例 / 风格 / 合规 / 图类型…）
- 可选 LLM 动态题（需 API Key）；Mock 模式下纯模板同样可跑通

### 3 · Visual Spec → Prompt → 生成

- 结构化规格：`title` · `key_elements` · `constraints` · 领域扩展字段
- PNG：`MockImageGenerator`（离线确定性）或 OpenAI Images API
- SVG：学术流程图由本地 `DiagramGenerator` 离线渲染

### 4 · 可解释评估（Evaluator）

| 层 | 离线 | 作用 |
|----|:----:|------|
| A · Deterministic | ✅ | 格式有效、尺寸合规、SVG 节点、prompt/spec 对齐 |
| B · Heuristic | ✅ | entropy / 对比度 / 边缘密度 / 空白检测 |
| C · VLM | 需 Key | 可选语义与美学评分 |
| **Rubric** | ✅ | 6 维可审计：`visual_validity` · `spec_completeness` · `requirement_alignment` · `domain_fit` · `traceability` · `reproducibility` |

### 5 · 全链路 Trace

每个 Agent 步骤记录 `pipeline_step` · 耗时 · provider · warnings，支持 UI 时间线与 JSON 导出。

---

## 🏗 架构与流水线

```mermaid
flowchart TB
    subgraph Input
        U[用户 Prompt / PDF 上传]
    end
    subgraph Pipeline
        R[TaskRouterAgent]
        CL[ClarificationAgent]
        REQ[RequirementAgent]
        VS[VisualSpecAgent]
        DOM[Domain Agent<br/>电商 / 学术 / PPT]
        PR[PromptAgent]
        AST[AssetManagerAgent]
        EV[CriticAgent · Evaluator]
    end
    subgraph Output
        OUT[PNG / SVG + EvaluationReport + Trace JSON]
    end
    U --> R --> CL --> REQ --> VS --> DOM --> PR --> AST --> EV --> OUT
```

**Trace 关键阶段：**

`router_decision` → `clarification_needed` → `visual_spec_created` → `prompt_created` → `provider_selected` → `output_generated` → `evaluation_completed`

<details>
<summary><b>Trace JSON 片段</b></summary>

```json
{
  "step": "generate_asset",
  "agent_name": "AssetManagerAgent",
  "metadata": {
    "pipeline_step": "output_generated",
    "provider": "mock",
    "generation_mode": "mock",
    "requested_aspect_ratio": "1:1",
    "resolved_width": 1024,
    "resolved_height": 1024
  },
  "duration_ms": 45
}
```

</details>

---

## ⚙️ 配置一览

`.env.example` 默认即可离线运行：

| 变量 | 默认 | 说明 |
|------|------|------|
| `IMAGE_PROVIDER` | `mock` | `mock` 离线占位图 · `openai` 真实图像 API |
| `LLM_PROVIDER` | `mock` | `mock` / `deepseek` / `openai` |
| `DEMO_MODE` | `false` | `true` 时强制 Mock LLM + Mock 图像 |
| `VISION_EVALUATOR_PROVIDER` | `none` | `openai` 启用可选 VLM（需 Key） |
| `OCR_PROVIDER` | `none` | 扫描 PDF OCR 预留，默认关闭 |

**Mock vs OpenAI：**

| 组件 | Mock（默认） | OpenAI |
|------|-------------|--------|
| 文本 LLM | `MockLLM` 确定性 JSON | DeepSeek / OpenAI |
| 图像 | 标准库 PNG + `.mock.json` 元数据 | Images API |
| 学术 SVG | 本地 `DiagramGenerator` | 同左 |
| 评估 | 确定性 + 启发式 + Rubric | 同左 + 可选 VLM |

---

## 📐 Aspect Ratio 映射

`app/tools/aspect_ratio.py`：**理想尺寸 → API 支持尺寸** 两层映射。

| 请求比例 | 理想尺寸 | API 实际尺寸 |
|----------|----------|-------------|
| 1:1 | 1024×1024 | 1024×1024 |
| 16:9 | 1536×864 | 1792×1024 |
| 9:16 | 864×1536 | 1024×1792 |
| 4:3 | 1280×960 | 1536×1024 |
| 4:5 | 1024×1280 | 1024×1536 |

元数据字段：`requested_aspect_ratio` · `resolved_width` · `resolved_height` · `provider`

---

## 📊 Benchmark

12 个基准用例（4 电商 + 4 学术 + 4 PPT），见 `benchmarks/examples.jsonl`：

```bash
IMAGE_PROVIDER=mock make benchmark
```

| 指标（Mock 模式示例） | 值 |
|----------------------|-----|
| routing_accuracy | 91.7% |
| generation_success_rate | 100% |
| evaluator_avg_score (offline) | ~58.6 |

> Mock 纯色占位图会触发 blank/low-entropy 检测，离线分偏低是**设计预期**。

---

## 🔌 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查（含 provider 信息） |
| `POST` | `/extract` | 上传 PDF/TXT；扫描件返回 `needs_ocr=true` |
| `POST` | `/clarify` | 澄清选择题 |
| `POST` | `/generate` | **完整生成流水线** |
| `GET` | `/tasks` | 分页任务列表 |
| `GET` | `/tasks/{id}` | 任务详情（含 evaluation.rubric） |
| `GET` | `/tasks/{id}/asset` | 下载 PNG/SVG |
| `DELETE` | `/tasks/{id}` | 删除任务 |

---

## 🖥 UI Usage

Streamlit 界面展示：

- 路由结果与 Visual Spec 结构化预览
- 生成资产预览 + **Rubric 分项评分**（含 rationale / evidence）
- Agent Trace 时间线（`pipeline_step` · 耗时 · warnings）
- Mock 模式与 OpenAI 模式 UI 一致

---

## 🧪 Testing

**129 个测试 · 默认 Mock · 无外部 API · 结果 deterministic**

```bash
cp .env.example .env && pytest        # 验收路径
make test                             # 同上
make coverage                         # 核心模块 ≥80%
make lint                             # ruff（CI 同款）
```

CI（`.github/workflows/ci.yml`）：Python 3.11 · `ruff check` · `pytest` · **无需 secrets**

覆盖亮点：Mock 端到端 · 配置一致性 · Router 澄清 edge cases · Evaluator rubric · API 错误路径 · PDF 边界

---

## 📄 PDF 处理

| 类型 | 行为 |
|------|------|
| 文本 PDF | 抽取 + LLM/启发式摘要 → `document_context` |
| 空 PDF | 明确错误 |
| 扫描 PDF | `needs_ocr=true` + `extraction_warning`（不误报成功） |
| .pptx 等 | 明确拒绝 |

---

## 📚 文档

| 文档 | 内容 |
|------|------|
| [`docs/specs/product_spec.md`](docs/specs/product_spec.md) | 产品范围与 MVP |
| [`docs/specs/architecture_spec.md`](docs/specs/architecture_spec.md) | 架构设计 |
| [`docs/specs/agent_workflow_spec.md`](docs/specs/agent_workflow_spec.md) | Agent 工作流 |
| [`docs/specs/evaluation_spec.md`](docs/specs/evaluation_spec.md) | 评估规范 |
| [`docs/specs/api_spec.md`](docs/specs/api_spec.md) | API 契约 |
| [`docs/demo/demo_script.md`](docs/demo/demo_script.md) | 课堂 Demo 脚本 |

架构图源：`docs/images/*.mmd`（Mermaid 源文件）

---

## 🔍 Architecture Notes（诚实说明）

| 能力 | 真实实现 | 需要 Key？ |
|------|----------|:----------:|
| 任务路由 | 规则基线 + 可选 LLM 精修；低置信 → `clarification_required` | 否 |
| 澄清 | 模板题库 + 哈希轮换；LLM 动态题可选 | 否 |
| 文本 LLM | Mock / DeepSeek / OpenAI | Mock 否 |
| 图像 | Mock PNG（标准库）/ OpenAI Images API | Mock 否 |
| 学术 SVG | 本地 DiagramGenerator | 否 |
| 评估 | 启发式 + Rubric；VLM 可选 | 离线否 |

**不是生产级系统**：无鉴权、限流、监控、多租户。它是一个**可复现、文档与实现一致、测试可信**的课程原型。

---

## 🛠 Makefile 命令

```bash
make install          # venv + 依赖 + .env.example
make test             # pytest（129 passed）
make coverage         # ≥80% 覆盖率
make demo             # 离线 CLI Demo
make benchmark        # 12 用例基准
make lint / format    # ruff / black
make dev              # python run.py
```

---

## 📁 项目结构

```
Spec2Vision/
├── app/
│   ├── agents/              # 11 个 Agent（Router / Clarification / Spec / …）
│   ├── graph/               # LangGraph 编排 + pipeline fallback
│   ├── tools/               # 图像 / 评估 / 文档 / benchmark
│   ├── services/            # GenerationService
│   ├── models/              # Pydantic + SQLite
│   └── ui/                  # Streamlit
├── docs/images/examples/    # README 展示图（可 regenerate）
├── examples/                # 三类端到端用例 JSON
├── benchmarks/              # 12 基准用例 + results
├── tests/                   # 129 个测试
├── scripts/
│   ├── run_demo.py
│   └── generate_readme_examples.py
├── .github/workflows/ci.yml
└── README.md
```

---

## ❓ Troubleshooting

| 问题 | 解决 |
|------|------|
| `Image API key required` | 设置 `IMAGE_PROVIDER=mock`（默认），或配置 `OPENAI_API_KEY` |
| `Unknown IMAGE_PROVIDER` | 仅支持 `mock` / `openai` |
| 测试失败 | `pip install -r requirements.txt` · Python 3.11+ · 无需 Key |
| Mock 评估分低 | 预期行为（纯色占位图） |
| 扫描 PDF 无文本 | 查看 `needs_ocr`；OCR 默认未启用 |

---

## License

[MIT](LICENSE)
