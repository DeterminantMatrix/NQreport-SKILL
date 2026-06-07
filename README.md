# NQreport-SKILL

> Fetch, decode, grade, and compare [NodeQuality](https://nodequality.com) VPS benchmark reports — for humans and AI agents.

## Features

- **Single & multi-report** — analyze one VPS or compare up to N side-by-side
- **SABCD letter grading** — 9 dimensions (hardware, IP quality, 3× return routes, speed, international bandwidth, streaming, cost-performance)
- **Route visualization** — carrier × protocol matrix, premium route detection (CN2GIA / 9929 / CMIN2)
- **Price-aware analysis** — `--price` flag enables cost-performance grading
- **Focus routes** — `--focus-routes` for targeted deep-dive on specific carriers/cities
- **IPv4 / IPv6 toggle** — `--skip-ipv6` to omit IPv6 sections
- **JSON output** — pipe-friendly structured output
- **Local caching** — auto-caches API responses (7-day freshness), `--refresh` to bust
- **VPS library** — `save_report.py` persists reports to JSON + CSV for tracking

## Quick Start

```bash
# Install deps (Python 3.9+, no extra packages needed)
python --version   # ≥ 3.9

# Analyze a report
python scripts/parse_nodequality_report.py "https://nodequality.com/r/<token>"

# With context
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,北京联通" \
  --price "续费$5.99/月" \
  "https://nodequality.com/r/<token>"

# Compare two VPS
python scripts/parse_nodequality_report.py \
  --price "续费$5/月" --price "续费$8/月" \
  "URL1" "URL2"

# Save to local library
python scripts/parse_nodequality_report.py --json "<url>" | python scripts/save_report.py -m "KVM-2G"
```

## CLI Reference

```
parse_nodequality_report.py [URL_OR_TOKEN ...] [options]

Core:
  URL_OR_TOKEN           One or more URLs/tokens (multiple = comparison mode)

Output:
  --json                 Structured JSON output
  --dump-dir DIR         Save raw logs + meta + summary

Context:
  --focus-routes ROUTES  Comma-separated route names to highlight
  --price PRICE          Price string (repeatable for comparison)
  --skip-ipv6            Omit all IPv6 sections

Cache:
  --cache-dir DIR        Cache directory (default: ./.nodequality-cache/)
  --refresh              Force re-fetch, ignore cache

Fallback:
  --record-json FILE     Parse from browser-exported API JSON
```

## Grading System

Every dimension receives an **S / A / B / C / D / ?** letter grade:

| Dimension | What it measures |
|-----------|-----------------|
| 硬件 | Memory, disk, CPU (GB5 single-core) |
| IP 质量 | Native/broadcast, risk flags, blacklist count |
| 电信回国 | CN2GIA > CN2 > 10099 > CMI > 4837 > 163 > HE |
| 联通回国 | 10099/9929 > CMI > 4837 > 163 > HE |
| 移动回国 | CMIN2 > CMI > 163 > HE |
| 国内速度 | Download Mbps to China + retransmit rate |
| 国际带宽 | Cross-border throughput to major regions |
| 流媒体解锁 | Streaming services + AI (ChatGPT) unlock count |
| 性价比 | Composite score ÷ monthly cost (requires `--price`) |

## Save Report (VPS Library)

`save_report.py` persists parsed reports to `vps_library.json` + `vps_library.csv`:

```bash
# Pipe mode (recommended)
python scripts/parse_nodequality_report.py --json "<url>" | python scripts/save_report.py -m "KVM-2G" -p "$5/mo"

# Direct mode
python scripts/save_report.py -m "KVM-2G" -p "$5/mo" "<url>"

# List all saved
python scripts/save_report.py --list
```

## Error Recovery

| Error | Cause | Fix |
|-------|-------|-----|
| `403 Forbidden` | API anti-bot / expired report | Export JSON from browser → `--record-json` |
| `404 Not Found` | Invalid token | Double-check URL |
| `Cannot decode ZIP` | Corrupted data | `--refresh` to re-fetch |

## For AI Agents

This repo is designed as a **skill** for AI coding assistants. See [`SKILL.md`](SKILL.md) for the agent-facing workflow (Phase 1 context collection → Phase 2 parse → Phase 3 respond).

## License

MIT
