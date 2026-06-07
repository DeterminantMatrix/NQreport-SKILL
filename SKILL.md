---
name: nodequality-report
description: Fetch, decode, and summarize NodeQuality report URLs or tokens. Supports single-report analysis, multi-report comparison, SABCD grading, route visualization, JSON output, and local caching. Use when the user gives a nodequality.com/r/... report link, asks to analyze/compare VPS benchmarks, inspect CN2/GIA/9929/CMIN2/163 return routes, or extract hardware/IP/network quality results.
---

# NodeQuality Report v2

## Workflow

### Phase 1 — Collect Context (ALWAYS do this first)

Before running the parser, ask the user THREE questions:

1. **重点分析线路** — "请输入重点分析的线路（如：上海电信,北京联通），多个用逗号分隔。直接回车则默认分析所有线路："

2. **价格信息** — "请输入价格信息（如：续费$5.99/月,二手溢价约$50）。直接回车则跳过性价比分析："

3. **IPv6 分析** — "是否需要分析 IPv6？（直接回车默认分析，输入 n/no/skip 跳过 IPv6 相关部分）："
   - If user says no → pass `--skip-ipv6` to the parser.
   - If user says yes or just hits Enter → don't pass the flag (IPv6 included by default).

- For **single report**: ask once.
- For **multiple reports** (comparison): ask focus routes and IPv6 preference once, then price **per report** in order.
- Pass collected info to the parser via `--focus-routes`, `--price`, and `--skip-ipv6` flags.

### Phase 2 — Fetch & Analyze

Run the parser with collected context:

```bash
# Single report with focus routes and price
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,北京联通" \
  --price "续费$5.99/月,二手溢价约$50" \
  "https://nodequality.com/r/<token>"

# Comparison mode (multiple URLs = auto comparison)
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,广州移动" \
  --price "续费$5/月" --price "续费$8/月" \
  "URL1" "URL2"
```

### Phase 3 — Respond

Use the script's output as the factual basis. Highlight:
- S/A 级维度 (green lights) and C/D 级维度 (red flags)
- Focus routes performance
- Cost-performance if price was provided
- Concrete use-case recommendations

## Grading System (SABCD)

Every dimension receives a letter grade:

| Grade | Meaning | Threshold |
|-------|---------|-----------|
| **S** | 顶级/旗舰 | Best-in-class |
| **A** | 优秀 | Well above average |
| **B** | 良好 | Solid, minor tradeoffs |
| **C** | 一般 | Noticeable weaknesses |
| **D** | 较差 | Dealbreaker for most uses |
| **?** | 无法评估 | Missing data |

### Dimensions graded

| Dimension | Key factors |
|-----------|-------------|
| **硬件** | Memory, disk, CPU (GB5 single) |
| **IP 质量** | Native/broadcast, risk flags, blacklists |
| **电信回国** | CN2GIA > CN2 > 10099 > CMI > 4837 > 163 > HE |
| **联通回国** | 10099/9929 > CMI > 4837 > 163 > HE |
| **移动回国** | CMIN2 > CMI > 163 > HE |
| **国内速度** | Download Mbps to China, retransmit rate |
| **国际带宽** | Cross-border throughput to major regions |
| **流媒体解锁** | Count of unlocked services + AI (ChatGPT) |
| **性价比** | (only when --price provided) Composite vs monthly cost |

### Retransmit interpretation

| Retransmits | Level | Meaning |
|-------------|-------|---------|
| < 100 | ✅ 正常 | Clean line, no packet loss |
| 100–500 | ⚠️ 轻微 | Occasional loss, acceptable |
| 500–1000 | ⚠️ 偏高 | Noticeable degradation |
| 1000–2000 | ❌ 严重 | Significant packet loss |
| > 2000 | ❌ 极差 | Likely unusable for real-time |

### Route tier ranking

| Tier | Routes | Typical experience |
|------|--------|--------------------|
| **S** | CN2GIA (AS4809) | Telecom premium, <40ms to Shanghai |
| **A** | 9929, 10099, CMIN2 | Unicom/Mobile premium |
| **B** | CMI direct, 4837 (CU premium) | Solid, some congestion |
| **C** | 163 (CHINANET), 58453 (CMI intl) | Standard, congestion-prone |
| **D** | HE, Cogent, NTT,绕路 >300ms | Unoptimized, high latency |

## CLI Reference

```
usage: parse_nodequality_report.py [URL_OR_TOKEN ...] [options]

Core:
  URL_OR_TOKEN             One or more NodeQuality URLs/tokens. Multiple = comparison mode.

Output:
  --json                   Output structured JSON instead of Markdown.
  --dump-dir DIR           Save decoded raw logs + meta + summary to DIR.

Context (collected in Phase 1):
  --focus-routes ROUTES    Comma-separated route names to highlight.
                           e.g. "上海电信,北京联通,广州移动"
  --price PRICE            Price info string. Repeatable for comparison mode.
                           e.g. --price "续费$5.99/月"
  --skip-ipv6             Omit IPv6 route blocks, detour warnings, and IPv6
                           IP quality sections from output.

Cache:
  --cache-dir DIR          Cache directory (default: ./.nodequality-cache/).
  --refresh                Force re-fetch, ignore cache.

Fallback:
  --record-json FILE       Parse from an exported record API JSON file
                           (use when API fetching fails with 403).
```

### Common patterns

```bash
# Minimal: single report, Markdown output
python scripts/parse_nodequality_report.py "<url>"

# Full: single report with all context
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,北京联通" \
  --price "续费$4.99/月" \
  "<url>"

# Comparison: 3 reports side-by-side
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,广州移动" \
  --price "续费$5/月" --price "续费$8/月" --price "续费$12/月" \
  "URL1" "URL2" "URL3"

# JSON output for scripting
python scripts/parse_nodequality_report.py --json "<url>" | jq .

# Dump everything for raw evidence
python scripts/parse_nodequality_report.py --dump-dir "./report-dump" "<url>"

# Force refresh cached report
python scripts/parse_nodequality_report.py --refresh "<url>"

# Skip IPv6 (only show IPv4 routes and IP quality)
python scripts/parse_nodequality_report.py --skip-ipv6 "<url>"

# From browser-exported JSON (API anti-bot fallback)
python scripts/parse_nodequality_report.py --record-json "./record.json"
```

## Save Report (VPS Library)

The bundled `save_report.py` persists parsed reports to a local JSON + CSV library:

```bash
# Pipe from parser (recommended)
python scripts/parse_nodequality_report.py --json "<url>" | python scripts/save_report.py --model "KVM-2G"

# Direct mode (calls parser internally)
python scripts/save_report.py --model "KVM-2G" --price "$5/mo" "https://nodequality.com/r/<token>"

# List saved reports
python scripts/save_report.py --list
```

## Error Handling

When API fetch fails, the parser prints a Chinese diagnostic:

| Error | Likely cause | Action |
|-------|-------------|--------|
| `403 Forbidden` | Report expired/private or API anti-bot | Ask user for browser Copy-as-cURL → save JSON → use `--record-json` |
| `404 Not Found` | Invalid token or report deleted | Double-check the URL |
| `Connection timeout` | Network issue or API down | Retry; if persistent, try `--record-json` |
| `success=false` | Server rejected request | Check token validity |
| `Cannot decode ZIP` | Corrupted report data | Try `--refresh` |

## Response Guidance

Keep conclusions practical and actionable:

- **Start with the verdict**: one sentence saying what this VPS is good/bad for.
- **Separate IPv4 and IPv6** when their routes differ significantly.
- **Call out premium routes** explicitly: `CN2GIA`, `CN2`, `9929`, `10099`, `CMIN2`.
- **Flag dealbreakers**: high retransmits, ERROR rows, near-zero download, dirty IP, blacklists.
- **Include cost-performance** when price was provided: is it worth it vs market alternatives?
- **For comparison mode**: declare a clear winner per use case (not just "depends").
- **Use the SABCD grades** as shorthand — users can scan grades without reading details.
