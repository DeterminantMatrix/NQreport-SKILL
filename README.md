# NQreport-SKILL

> 抓取、解码、评分、对比 [NodeQuality](https://nodequality.com) VPS 基准测试报告 — 面向人类和 AI 代理。

## 功能

- **单报告 & 多报告对比** — 单机分析或最多 N 台横向对比
- **SABCD 字母评级** — 覆盖 9 个维度（硬件、IP 质量、三网回国、国内速度、国际带宽、流媒体解锁、性价比）
- **路由可视化** — 运营商 × 协议矩阵，自动识别优质线路（CN2GIA / 9929 / CMIN2）
- **价格感知** — `--price` 参数启用性价比评级
- **重点线路聚焦** — `--focus-routes` 指定运营商/城市深度分析
- **IPv4 / IPv6 切换** — `--skip-ipv6` 跳过所有 IPv6 相关内容
- **JSON 输出** — 管道友好的结构化输出
- **本地缓存** — 自动缓存 API 响应（7 天有效期），`--refresh` 强制刷新
- **VPS 库** — `save_report.py` 将报告保存为 JSON + CSV，方便长期追踪

## 快速开始

```bash
# 环境要求：Python 3.9+，无额外依赖
python --version   # ≥ 3.9

# 分析一个报告
python scripts/parse_nodequality_report.py "https://nodequality.com/r/<token>"

# 带上下文分析
python scripts/parse_nodequality_report.py \
  --focus-routes "上海电信,北京联通" \
  --price "续费$5.99/月" \
  "https://nodequality.com/r/<token>"

# 对比两台 VPS
python scripts/parse_nodequality_report.py \
  --price "续费$5/月" --price "续费$8/月" \
  "URL1" "URL2"

# 存入本地 VPS 库
python scripts/parse_nodequality_report.py --json "<url>" | python scripts/save_report.py -m "KVM-2G"
```

## CLI 参考

```
parse_nodequality_report.py [URL_OR_TOKEN ...] [选项]

核心:
  URL_OR_TOKEN           一个或多个链接/token（多个即对比模式）

输出:
  --json                 输出结构化 JSON
  --dump-dir DIR         保存原始日志 + 元数据 + 摘要

上下文:
  --focus-routes ROUTES  逗号分隔的重点线路，如 "上海电信,北京联通"
  --price PRICE          价格信息（对比模式下可重复使用）
  --skip-ipv6            跳过所有 IPv6 相关部分

缓存:
  --cache-dir DIR        缓存目录（默认：./.nodequality-cache/）
  --refresh              强制重新抓取，忽略缓存

容错:
  --record-json FILE     从浏览器导出的 API JSON 解析（API 反爬时使用）
```

## 评分体系

每个维度获得 **S / A / B / C / D / ?** 字母评级：

| 维度 | 评估内容 |
|------|---------|
| 硬件 | 内存、磁盘、CPU（Geekbench 5 单核） |
| IP 质量 | 原生/广播 IP、风控标记、黑名单数量 |
| 电信回国 | CN2GIA > CN2 > 10099 > CMI > 4837 > 163 > HE |
| 联通回国 | 10099/9929 > CMI > 4837 > 163 > HE |
| 移动回国 | CMIN2 > CMI > 163 > HE |
| 国内速度 | 到国内节点的下载速率 + 重传率 |
| 国际带宽 | 到全球主要区域的跨境吞吐量 |
| 流媒体解锁 | 流媒体 + AI（ChatGPT）解锁数量 |
| 性价比 | 综合评分 ÷ 月付价格（需提供 `--price`） |

### 重传率解读

| 重传次数 | 等级 | 说明 |
|---------|------|------|
| < 100 | ✅ 正常 | 线路干净，无丢包 |
| 100–500 | ⚠️ 轻微 | 偶发丢包，可接受 |
| 500–1000 | ⚠️ 偏高 | 有明显劣化 |
| 1000–2000 | ❌ 严重 | 显著丢包 |
| > 2000 | ❌ 极差 | 实时应用基本不可用 |

### 路由梯队

| 梯队 | 线路 | 典型体验 |
|------|------|---------|
| **S** | CN2GIA (AS4809) | 电信旗舰，上海 <40ms |
| **A** | 9929、10099、CMIN2 | 联通/移动旗舰 |
| **B** | CMI 直连、4837（联通精品） | 稳定，高峰期偶有拥堵 |
| **C** | 163 (CHINANET)、58453 (CMI 国际) | 普通线路，高峰期拥堵 |
| **D** | HE、Cogent、NTT、绕路 >300ms | 未优化，高延迟 |

## VPS 库（save_report.py）

`save_report.py` 将解析后的报告保存到 `vps_library.json` + `vps_library.csv`：

```bash
# 管道模式（推荐）
python scripts/parse_nodequality_report.py --json "<url>" | python scripts/save_report.py -m "KVM-2G" -p "$5/月"

# 直接模式
python scripts/save_report.py -m "KVM-2G" -p "$5/月" "<url>"

# 列出已保存的报告
python scripts/save_report.py --list
```

## 错误处理

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| `403 Forbidden` | API 反爬 / 报告过期或设为私密 | 从浏览器导出 JSON → `--record-json` |
| `404 Not Found` | Token 无效或报告已删除 | 检查 URL 是否正确 |
| `Connection timeout` | 网络问题或 API 宕机 | 重试；持续失败则用 `--record-json` |
| `success=false` | 服务端拒绝请求 | 检查 token 有效性 |
| `Cannot decode ZIP` | 报告数据损坏 | `--refresh` 重新抓取 |

## 面向 AI 代理

本仓库被设计为 AI 编程助手的 **skill**。详见 [`SKILL.md`](SKILL.md) 了解代理工作流（Phase 1 采集上下文 → Phase 2 解析 → Phase 3 生成回复）。

## 许可证

MIT
