# NQreport-SKILL

解析 NodeQuality 报告：解码 token，输出硬件、IP、三网回国、测速、流媒体、性价比和 SABCD 评级；支持多报告对比、跳过 IPv6、JSON、缓存、CSV/JSON 归档。

首次使用：Python 3.9+。运行 `python scripts/parse_nodequality_report.py <url>`，`<url>` 为 `https://nodequality.com/r/<token>`。可加 `--focus-routes`、`--price`；归档用 `--json` 接 `save_report.py`。
