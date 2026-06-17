# Demo: E-commerce product visual

Generated offline with `IMAGE_PROVIDER=mock` (deterministic, no API key).

| File | Description |
|------|-------------|
| `request.json` | Input to `/generate` |
| `visual_spec.json` | Structured Visual Spec |
| `prompt.txt` | Final generation prompt |
| `asset.png` | Generated asset (mock PNG or local SVG) |
| `evaluation.json` | Heuristic rubric evaluation (not human/VLM judgment) |
| `trace.json` | Agent trace timeline |
| `summary.json` | Quick overview |

Reproduce:

```bash
python benchmark.py --demo examples/ecommerce_case.json
```
