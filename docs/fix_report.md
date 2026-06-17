# Spec2Vision Fix Report

> 工程可信度修复说明 · 2026-06-17

## 1. 修复了哪些问题

### 1.1 可运行性与格式

| 项目 | 状态 | 说明 |
|------|------|------|
| Python 源码单行压缩 | **已验证正常** | 当前 `main` 分支文件均为多行合法 Python；新增 `scripts/validate_repo_format.py` + CI 防止回归 |
| `requirements.txt` | **已验证正常** | 每行一个依赖，pip 可解析 |
| `Dockerfile` | **已验证正常** | 标准多行 `FROM` / `WORKDIR` / `COPY` / `RUN` / `CMD` |
| `.env.example` | **已加强** | 多行格式 + 必填/可选变量说明；默认 `mock` 无需 API Key |
| `.gitattributes` | **新增** | 强制文本文件 LF，避免 Windows 换行导致 GitHub Raw 显示异常 |

### 1.2 测试与 CI

- 测试套件：**129 passed, 1 skipped**（见 [`docs/test_report.md`](test_report.md)）
- 新增 [`.github/workflows/test.yml`](../.github/workflows/test.yml)：format 校验 + compileall + pytest
- 保留 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)：ruff + pytest
- `tests/conftest.py` 默认 **Mock provider**，不依赖外部 API

### 1.3 Benchmark

- `routing_accuracy >= 0.5` 提升为 **`>= 0.75`**（smoke 阈值）
- `app/tools/benchmark.py` 文档明确：这是 **smoke/regression 套件**，不是严谨 ML benchmark

### 1.4 评估模块（诚实描述）

- 评估器为 **rule-based / offline heuristic rubric**，见 `app/tools/evaluator.py`
- **不能**替代人工评审、CLIP、VLM judge 或真实视觉检测
- 六维 rubric：`visual_validity`, `spec_completeness`, `requirement_alignment`, `domain_fit`, `traceability`, `reproducibility`
- Mock 纯色 PNG 会触发低 entropy/blank 检测 → 分数偏低是**预期**

### 1.5 端到端 Demo 样例

新增 [`examples/demo/`](../examples/demo/)（Mock 模式导出，可离线复现）：

| 目录 | 类型 | 包含文件 |
|------|------|----------|
| `examples/demo/ecommerce/` | 电商 PNG | request, visual_spec, prompt, asset, evaluation, trace, summary |
| `examples/demo/academic/` | 学术 SVG | 同上 |
| `examples/demo/ppt/` | PPT PNG | 同上 |

### 1.6 CLI

- 根目录 [`benchmark.py`](../benchmark.py)：
  - `python benchmark.py --demo examples/ecommerce_case.json`
  - `python benchmark.py --benchmark`

---

## 2. README 表述调整（降级 / 澄清）

| 原表述风险 | 现表述 |
|------------|--------|
| production-ready / enterprise-grade | **course project prototype**（课程项目原型） |
| 默认即真实 OpenAI 图像生成 | **默认 Mock**；OpenAI 仅当 `IMAGE_PROVIDER=openai` 且配置 Key |
| automated visual quality evaluation | **heuristic rubric evaluator**（启发式，非审美模型） |
| 41 passed | **129 passed** + CI badge + `docs/test_report.md` |
| 严谨 benchmark | **smoke benchmark**（JSONL 回归，阈值 0.75） |
| `docs/images/examples/` 真实图 | 标注为**维护者可选生成的预览图**；复现请用 `examples/demo/` 或 Mock CLI |

---

## 3. 如何安装

```bash
git clone https://github.com/skywalker767/Spec2Vision.git
cd Spec2Vision

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env    # Windows
# cp .env.example .env    # Linux/macOS
```

**无需 API Key** 即可完成安装与测试（默认 `.env.example` 使用 Mock）。

---

## 4. 如何运行 API

```bash
# 确保 storage/ 目录存在（首次启动自动创建）
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 健康检查：http://127.0.0.1:8000/health
- API 文档：http://127.0.0.1:8000/docs

---

## 5. 如何运行 Streamlit 前端

```bash
python run.py
# 或分别启动：
# python -m uvicorn app.main:app --port 8000
# streamlit run app/ui/streamlit_app.py --server.port 8501
```

---

## 6. 如何运行测试

```bash
# 验收路径（无 API Key）
python -m pytest tests/ -v

# 与 CI 相同
python scripts/validate_repo_format.py
python -m compileall -q app tests scripts benchmark.py
python -m ruff check app tests
python -m pytest tests/ -v --tb=short -m "not slow"
```

---

## 7. 如何运行 Demo（5 分钟内）

```bash
# 单案例（Mock，与 examples/demo/ 同类输出）
python benchmark.py --demo examples/ecommerce_case.json

# 导出三份完整 demo 工件到 examples/demo/
python scripts/export_demo_cases.py

# 一键 CLI
make demo

# Benchmark smoke 套件（12 JSONL 用例）
python benchmark.py --benchmark
```

---

## 8. Docker

```bash
docker build -t spec2vision .
docker run -p 8000:8000 -e IMAGE_PROVIDER=mock -e LLM_PROVIDER=mock spec2vision
```

---

## 9. 当前仍然存在的限制

1. **非生产级**：无鉴权、限流、多租户、监控
2. **路由**：规则 + 可选 LLM，非端到端学习分类器
3. **图像生成（默认）**：Mock 确定性 PNG + 本地 SVG；OpenAI 需显式配置
4. **评估**：启发式 rubric，非真实视觉质量模型
5. **OCR**：扫描 PDF 仅返回 `needs_ocr` 警告，默认不启用
6. **Benchmark**：smoke 回归，不代表真实业务指标

---

## 10. 环境变量速查

| 变量 | 默认 | 必填？ | 说明 |
|------|------|--------|------|
| `LLM_PROVIDER` | `mock` | 否 | `mock` 离线；`openai`/`deepseek` 需 Key |
| `IMAGE_PROVIDER` | `mock` | 否 | `mock` 离线 PNG；`openai` 需 Key |
| `OPENAI_API_KEY` | 空 | 仅 openai 模式 | 图像/LLM OpenAI |
| `DEEPSEEK_API_KEY` | 空 | 仅 deepseek 模式 | 文本 LLM |
| `DEMO_MODE` | `false` | 否 | `true` 强制 Mock |
| `VISION_EVALUATOR_PROVIDER` | `none` | 否 | `openai` 启用可选 VLM（需 Key） |
