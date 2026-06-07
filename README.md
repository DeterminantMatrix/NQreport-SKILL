# NQreport-SKILL

NQreport-SKILL 是 NodeQuality VPS 测试报告解析与评分工具，也可作为 Codex/AI 代理技能使用。它接受 `https://nodequality.com/r/<token>` 或 token，自动抓取、解码，并整理厂商型号、硬件、IP 质量、三网回国、测速、流媒体/AI 解锁、价格性价比等信息。

工具会生成 SABCD 评级，帮助判断 VPS 是否值得购买或续费；支持多报告横向对比、跳过 IPv6、结构化输出和本地缓存，适合在不同商家、型号和线路之间做取舍。

## 第一次开始使用

这是一个给大模型调用的 skill，不是要求用户手动先运行 Python。安装或启用后，在支持 skills 的大模型/Codex 中直接输入：

```text
使用 nodequality-report 分析 https://nodequality.com/r/<token>
```

或把 token/多个 URL 直接发给模型，并明确要用 `nodequality-report`。技能会先询问厂商名称及型号、重点线路、价格、是否分析 IPv6，然后抓取报告并输出结论。

示例：

```text
用 nodequality-report 分析这台 VPS：https://nodequality.com/r/<token>
厂商型号：DMIT PVM.HKG.Pro
重点线路：上海电信,北京联通,广州移动
价格：$5/mo
IPv6：分析
```

只拿到 token 时也可以直接给 token。价格支持 USD/CNY/EUR/HKD 及月付、年付，如 `$5/mo`、`29元/月`、`$60/year`。

## 常用场景

对比多台 VPS：

```text
使用 nodequality-report 对比 URL1 URL2 URL3，重点看上海电信和广州移动。
```

需要保存到本地库时，告诉模型“保存报告”。技能会使用 `save_report.py`，自动解析并写入 JSON 和 CSV，不需要用户额外写 `--json` 管道。

本地开发或调试时才需要直接运行脚本：`python scripts/parse_nodequality_report.py "<url>"`。

归档写入 `vps-reports/json/` 和 `vps-reports/reports.csv`，便于长期追踪价格和线路表现。

## 结果怎么看

优先看综合评级和三网回国评级。电信关注 CN2GIA/CN2，联通关注 9929/10099，移动关注 CMIN2/CMI。测速重点看国内接收速度、国际吞吐量和重传；重传过高通常意味着高峰期不稳。IP 质量和流媒体解锁适合判断建站、代理、AI、Netflix 等用途。

若 API 返回 403、报告过期或私密，可从浏览器复制 record API JSON，再用 `--record-json FILE` 解析。AI 代理流程见 `SKILL.md`。
