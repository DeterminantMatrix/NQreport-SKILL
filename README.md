# NQreport-SKILL

NQreport-SKILL 是 NodeQuality VPS 测试报告解析与评分工具，也可作为 Codex/AI 代理技能使用。它接受 `https://nodequality.com/r/<token>` 或 token，自动抓取、解码，并整理厂商型号、硬件、IP 质量、三网回国、测速、流媒体/AI 解锁、价格性价比等信息。

工具会生成 SABCD 评级，帮助判断 VPS 是否值得购买或续费；支持多报告横向对比、`--skip-ipv6`、`--json` 和本地缓存，适合在不同商家、型号和线路之间做取舍。

## 第一次开始使用

要求 Python 3.9+，无需额外依赖。克隆后在根目录运行：

```bash
python scripts/parse_nodequality_report.py "https://nodequality.com/r/<token>"
```

只拿到 token 时也可直接传 token。建议同时提供重点线路和价格：

```bash
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,北京联通,广州移动" \
  --price "$5/mo" \
  "https://nodequality.com/r/<token>"
```

`--focus-routes` 用逗号分隔线路；`--price` 支持 USD/CNY/EUR/HKD 及月付、年付，如 `$5/mo`、`29元/月`、`$60/year`。

## 常用场景

对比多台 VPS：

```bash
python scripts/parse_nodequality_report.py "URL1" "URL2" "URL3"
```

保存到本地库时直接运行 `save_report.py`，它会自动解析并写入 JSON 和 CSV：

```bash
python scripts/save_report.py -m "KVM-2G" -p "$5/mo" "<url>"
```

归档写入 `vps-reports/json/` 和 `vps-reports/reports.csv`，便于长期追踪价格和线路表现。

## 结果怎么看

优先看综合评级和三网回国评级。电信关注 CN2GIA/CN2，联通关注 9929/10099，移动关注 CMIN2/CMI。测速重点看国内接收速度、国际吞吐量和重传；重传过高通常意味着高峰期不稳。IP 质量和流媒体解锁适合判断建站、代理、AI、Netflix 等用途。

若 API 返回 403、报告过期或私密，可从浏览器复制 record API JSON，再用 `--record-json FILE` 解析。AI 代理流程见 `SKILL.md`。
