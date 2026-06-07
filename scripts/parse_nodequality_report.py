#!/usr/bin/env python3
"""
NodeQuality Report Parser v2
============================
Fetch, decode, grade, and compare NodeQuality VPS benchmark reports.

New in v2:
  - Multi-report comparison (--compare or multiple positional args)
  - JSON output (--json)
  - SABCD letter-grade scoring across 8 dimensions
  - Retransmit / speedtest auto-interpretation
  - Route visualization grouped by carrier × protocol
  - Enhanced Chinese-language error messages
  - Local cache (default: ./.nodequality-cache/)
  - Focus-route and price-aware analysis (--focus-routes, --price)
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api.nodequality.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_CACHE_DIR = "./.nodequality-cache"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TOKEN_RE = re.compile(r"(?:/r/)?([A-Za-z0-9_-]{16,})")

# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------


def cache_path(cache_dir, token):
    return os.path.join(cache_dir, f"{token}.json")


def load_cache(cache_dir, token):
    path = cache_path(cache_dir, token)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        # simple freshness: expire after 7 days
        age = time.time() - cached.get("_cached_at", 0)
        if age > 7 * 86400:
            return None
        return cached.get("_record")
    except Exception:
        return None


def save_cache(cache_dir, token, record):
    os.makedirs(cache_dir, exist_ok=True)
    path = cache_path(cache_dir, token)
    payload = {"_cached_at": time.time(), "_record": record}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------


def request_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError(
                "API 返回 403：报告可能已过期、设为私有，或触发了反爬机制。\n"
                "请在浏览器中打开报告页面，按 F12 → Network → 找到 /api/v1/record/... 请求 → "
                "右键 Copy as cURL → 保存响应 JSON → 使用 --record-json 文件路径 解析。"
            )
        if e.code == 404:
            raise RuntimeError("API 返回 404：报告不存在或 token 错误，请检查链接是否完整。")
        raise RuntimeError(f"API 请求失败 (HTTP {e.code}): {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络连接失败: {e.reason}，请检查网络或稍后重试。")


def base_headers():
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://nodequality.com",
        "Referer": "https://nodequality.com/",
    }


def extract_token(value):
    if not value:
        raise ValueError("缺少 URL 或 token")
    match = TOKEN_RE.search(value.strip())
    if not match:
        raise ValueError(f"无法从输入中提取 NodeQuality token: {value}")
    return match.group(1)


def fetch_record(url_or_token, cache_dir=None, refresh=False):
    """Fetch a report record, with optional caching."""
    token = extract_token(url_or_token)

    if cache_dir and not refresh:
        cached = load_cache(cache_dir, token)
        if cached:
            return token, cached

    headers = base_headers()
    ipinfo = request_json(f"{API_BASE}/api/v1/ipinfo", headers)
    record_url = f"{API_BASE}/api/v1/record/{token}"
    sign_payload = "\n\n".join(
        ["GET", record_url, USER_AGENT, f"{ipinfo['ip']}{ipinfo['ts']}", ""]
    )
    headers["x-dynamic-sign-v"] = hashlib.sha1(sign_payload.encode("utf-8")).hexdigest()
    headers["x-dynamic-sign-t"] = str(ipinfo["ts"])
    record = request_json(record_url, headers)

    if cache_dir:
        save_cache(cache_dir, token, record)

    return token, record


# ---------------------------------------------------------------------------
# Text cleaning / helpers
# ---------------------------------------------------------------------------


def clean(text):
    text = ANSI_RE.sub("", text)
    text = text.replace("\r", "")
    text = text.replace("\b", "")
    return "\n".join(line.rstrip() for line in text.splitlines())


def first_match(text, pattern, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


def first_line(text, pattern, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(0).strip() if match else default


def extract_labeled_value(text, label):
    return first_match(text, rf"{re.escape(label)}\s*[:：]\s*(.+)")


# ---------------------------------------------------------------------------
# Decode & parse
# ---------------------------------------------------------------------------


def decode_entries(record):
    data = record.get("data", record)
    encoded = data.get("result")
    if not encoded:
        raise ValueError("record JSON 不包含 data.result 字段")
    blob = base64.b64decode(encoded)
    entries = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            entries[item.filename] = archive.read(item).decode("utf-8", errors="replace")
    return data, entries


def parse_hardware(log):
    mem_str = extract_labeled_value(log, "内存")
    disk_str = extract_labeled_value(log, "硬盘")
    gb5_single = first_match(log, r"GB5单核[：:]\s*\|?([0-9]+)")
    gb5_multi = first_match(log, r"GB5多核[：:]\s*\|?([0-9]+)")
    return {
        "os": extract_labeled_value(log, "操作系统/内核"),
        "virt": extract_labeled_value(log, "容器/虚拟化"),
        "cpu": extract_labeled_value(log, "CPU"),
        "gb5_single": gb5_single,
        "gb5_multi": gb5_multi,
        "memory_raw": mem_str,
        "memory_gb": _parse_memory_gb(mem_str),
        "disk_raw": disk_str,
        "disk_gb": _parse_disk_gb(disk_str),
        "score": first_match(log, r"分数[：:]\s*([0-9]+)"),
    }


def _parse_memory_gb(text):
    m = re.search(r"总容量\s*([0-9.]+)\s*(MB|GB|TB|mb|gb|tb)?", text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "MB").upper()
    if unit == "TB":
        return val * 1024
    if unit == "MB":
        return val / 1024
    return val


def _parse_disk_gb(text):
    m = re.search(r"总容量\s*([0-9.]+)\s*(G|T|g|t)", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "T":
        return val * 1024
    return val


def parse_ip_quality(log):
    ipv4 = {}
    ipv6 = {}
    sections = re.split(r"\n(?=.*IP质量体检报告)", log)
    for section in sections:
        if "IP质量体检报告" not in section:
            continue
        target = ipv6 if ("260" in section[:300] or "IPv6" in section[:300]) else ipv4
        target["org"] = extract_labeled_value(section, "组织")
        target["city"] = extract_labeled_value(section, "城市")
        target["ip_type"] = extract_labeled_value(section, "IP类型")
        target["blacklist"] = first_line(
            section, r"IP地址黑名单数据库：\s*有效\s*[0-9]+\s*正常\s*[0-9]+\s*已标记\s*[0-9]+\s*黑名单\s*[0-9]+"
        )
        # Parse blacklist counts
        bl_match = re.search(
            r"有效\s*([0-9]+)\s*正常\s*([0-9]+)\s*已标记\s*([0-9]+)\s*黑名单\s*([0-9]+)",
            section,
        )
        if bl_match:
            target["bl_valid"] = int(bl_match.group(1))
            target["bl_normal"] = int(bl_match.group(2))
            target["bl_marked"] = int(bl_match.group(3))
            target["bl_blacklist"] = int(bl_match.group(4))
        risks = []
        risk_scores = {}
        for provider in ["IP2Location", "Scamalytics", "ipapi", "AbuseIPDB", "IPQS", "DB-IP"]:
            line = first_match(section, rf"({provider}：.+)")
            if line:
                risks.append(line)
                low_match = re.search(r"(\d+)\s*\|\s*低风险|极低风险|低风险", line)
                risk_scores[provider] = "low" if low_match else "warn"
        target["risks"] = risks
        target["risk_scores"] = risk_scores
        # Unlock
        unlock_lines = []
        capture = False
        for line in section.splitlines():
            if "流媒体及AI服务解锁检测" in line:
                capture = True
            elif capture and ("邮局连通性" in line or "今日IP检测量" in line):
                break
            elif capture and line.strip():
                unlock_lines.append(line.strip())
        target["unlock"] = unlock_lines
        # Parse structured unlock data
        target["unlock_parsed"] = _parse_unlock_table(unlock_lines)
    return {"ipv4": ipv4, "ipv6": ipv6}


def _parse_unlock_table(lines):
    """Try to parse the structured unlock table into dict."""
    # The format is typically:
    # 服务商： TikTok Disney+ Netflix ...
    # 状态：   失败   解锁    解锁   ...
    # 地区：          [CA]    [CA]  ...
    # 方式：          原生    原生   ...
    if not lines:
        return {}
    services = []
    statuses = []
    regions = []
    methods = []
    for line in lines:
        stripped = re.sub(r"\s+", " ", line)
        if stripped.startswith("服务商"):
            services = [s.strip() for s in stripped.replace("服务商：", "").replace("服务商:", "").split()]
        elif stripped.startswith("状态"):
            statuses = [s.strip() for s in stripped.replace("状态：", "").replace("状态:", "").split()]
        elif stripped.startswith("地区"):
            regions_raw = re.findall(r"\[([^\]]*)\]", stripped)
            regions = regions_raw
        elif stripped.startswith("方式"):
            methods = [s.strip() for s in stripped.replace("方式：", "").replace("方式:", "").split()]
    result = {}
    for i, svc in enumerate(services):
        result[svc] = {
            "status": statuses[i] if i < len(statuses) else "",
            "region": regions[i] if i < len(regions) else "",
            "method": methods[i] if i < len(methods) else "",
        }
    return result


def parse_speedtest(log):
    """Parse domestic speedtest rows. Returns list of dicts."""
    lines = log.splitlines()
    results = []
    for i, line in enumerate(lines):
        if "国内测速" not in line:
            continue
        for row in lines[i + 1 : i + 12]:
            if "国际互连" in row or "====" in row:
                break
            parts = [p.strip() for p in row.split("||")]
            for part in parts:
                if not part:
                    continue
                # Format: "节点名  下载  上传  重传  延迟" or similar
                tokens = part.split()
                if len(tokens) >= 3:
                    entry = {
                        "raw": part,
                        "node": tokens[0],
                        "download_mbps": _parse_int(tokens[1]) if len(tokens) > 1 else None,
                        "upload_mbps": _parse_int(tokens[2]) if len(tokens) > 2 else None,
                        "retransmits": _parse_int(tokens[3]) if len(tokens) > 3 else None,
                        "latency_ms": _parse_int(tokens[4]) if len(tokens) > 4 else None,
                    }
                    results.append(entry)
    return results


# Unicode braille block chars (U+2800–U+28FF) used for bar charts in NodeQuality logs
_BRAILLE_RE = re.compile(r"[\u2800-\u28ff]+")


def parse_international(log):
    """Parse international transfer speedtest rows."""
    lines = log.splitlines()
    results = []
    for i, line in enumerate(lines):
        if "国际互连" not in line:
            continue
        for row in lines[i + 1 : i + 25]:
            if "====" in row or "报告链接" in row:
                break
            parts = [p.strip() for p in row.split("||")]
            for part in parts:
                if not part or part.startswith("报告链接"):
                    continue
                # Strip braille bar-chart chars that may be glued to the city name
                cleaned = _BRAILLE_RE.sub(" ", part)
                # Also strip other common unicode block-drawing / bar chars
                cleaned = re.sub(r"[\u2580-\u259f]", " ", cleaned)
                tokens = cleaned.split()
                if len(tokens) >= 3:
                    # NodeQuality international format:
                    #   城市  延迟(ms)  下载(Mbps)  重传(发)  上传(Mbps)  重传(收)
                    entry = {
                        "raw": part,
                        "city": tokens[0],
                        "latency_ms": _parse_int(tokens[1]) if len(tokens) > 1 else None,
                        "download_mbps": _parse_int(tokens[2]) if len(tokens) > 2 else None,
                        "retransmit_send": _parse_int(tokens[3]) if len(tokens) > 3 else None,
                        "upload_mbps": _parse_int(tokens[4]) if len(tokens) > 4 else None,
                        "retransmit_recv": _parse_int(tokens[5]) if len(tokens) > 5 else None,
                    }
                    results.append(entry)
        break
    return results


def _parse_int(s):
    """Parse int from string, returning None on failure (includes ERROR)."""
    if not s:
        return None
    s = s.strip()
    if s.upper() == "ERROR":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_route_matrix(net_log):
    """Parse the TCP/UDP return route summary lines."""
    matrix = []
    for line in net_log.splitlines():
        if re.search(r"(北京|上海|广州)(TCP|UDP)", line):
            line = re.sub(r"\s+", " ", line).strip()
            # Parse structured
            parts = line.split("：")
            if len(parts) >= 2:
                direction = parts[0].strip()
                detail = parts[1].strip()
                carriers = detail.split("||")
                parsed = {"direction": direction, "routes": {}}
                for c in carriers:
                    c = c.strip()
                    cm = re.match(r"(电信|联通|移动)\s+(.+)", c)
                    if cm:
                        parsed["routes"][cm.group(1)] = cm.group(2).strip()
                matrix.append(parsed)
            else:
                matrix.append({"direction": line, "routes": {}})
    return matrix


def parse_route_evidence(backroute_log):
    """Parse detailed backroute trace log."""
    evidence = []
    current = None
    for line in backroute_log.splitlines():
        header = re.search(
            r"^\s*(北京|上海|广东|广州)\s+(电信|联通|移动)\s+(.+?->.+?)\s*$", line
        )
        if header:
            current = {
                "name": f"{header.group(1)}{header.group(2)}",
                "route": re.sub(r"\s+", " ", header.group(3)).strip(),
                "path": "",
                "hops": [],
            }
            evidence.append(current)
            continue
        if current and "地理路径" in line:
            current["path"] = re.sub(r"\s+", " ", line).strip()
            continue
        if current and re.search(
            r"(AS4809|AS9929|AS10099|AS58807|AS9808|AS4134|AS4812|AS4837|AS4847|AS23724|AS4811|AS4816|AS58453|AS9808)",
            line,
        ):
            current["hops"].append(re.sub(r"\s+", " ", line).strip())
    return evidence


# ---------------------------------------------------------------------------
# Grading engine
# ---------------------------------------------------------------------------

GRADE_LABELS = {
    "S": "卓越",
    "A": "优秀",
    "B": "良好",
    "C": "一般",
    "D": "较差",
    "?": "未知",
}


def _score_to_grade(score):
    """Map a numeric score (0-100) to SABCD."""
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 30:
        return "C"
    return "D"


def _avg_grade(grades):
    """Average multiple (grade_str, score) tuples into one grade."""
    if not grades:
        return "?", 0
    total = sum(s for _, s in grades)
    avg = total / len(grades)
    return _score_to_grade(avg), avg


def grade_hardware(hw):
    """Grade hardware: memory, disk, CPU GB5."""
    scores = []
    details = []

    mem_gb = hw.get("memory_gb")
    if mem_gb is not None:
        if mem_gb >= 8:
            scores.append(("S", 95))
            details.append(f"内存 {mem_gb:.0f}GB S")
        elif mem_gb >= 4:
            scores.append(("A", 80))
            details.append(f"内存 {mem_gb:.0f}GB A")
        elif mem_gb >= 2:
            scores.append(("B", 60))
            details.append(f"内存 {mem_gb:.0f}GB B")
        elif mem_gb >= 1:
            scores.append(("C", 35))
            details.append(f"内存 {mem_gb:.0f}GB C")
        else:
            scores.append(("D", 15))
            details.append(f"内存 {mem_gb:.1f}GB D")

    disk_gb = hw.get("disk_gb")
    if disk_gb is not None:
        if disk_gb >= 50:
            scores.append(("S", 90))
            details.append(f"磁盘 {disk_gb:.0f}GB S")
        elif disk_gb >= 30:
            scores.append(("A", 78))
            details.append(f"磁盘 {disk_gb:.0f}GB A")
        elif disk_gb >= 20:
            scores.append(("B", 58))
            details.append(f"磁盘 {disk_gb:.0f}GB B")
        elif disk_gb >= 10:
            scores.append(("C", 33))
            details.append(f"磁盘 {disk_gb:.0f}GB C")
        else:
            scores.append(("D", 15))
            details.append(f"磁盘 {disk_gb:.0f}GB D")

    gb5 = hw.get("gb5_single")
    if gb5 and gb5.isdigit():
        s = int(gb5)
        if s >= 2000:
            scores.append(("S", 92))
            details.append(f"GB5单核 {s} S")
        elif s >= 1500:
            scores.append(("A", 78))
            details.append(f"GB5单核 {s} A")
        elif s >= 1000:
            scores.append(("B", 60))
            details.append(f"GB5单核 {s} B")
        elif s >= 700:
            scores.append(("C", 35))
            details.append(f"GB5单核 {s} C")
        else:
            scores.append(("D", 18))
            details.append(f"GB5单核 {s} D")

    grade, score = _avg_grade(scores)
    return {"grade": grade, "score": score, "label": GRADE_LABELS.get(grade, "?"), "details": details}


def grade_ip(ip_data):
    """Grade IP quality based on type, risk flags, blacklists."""
    if not ip_data:
        return {"grade": "?", "score": 0, "label": "无数据", "details": []}
    scores = []
    details = []

    # IP type
    ip_type = ip_data.get("ip_type", "")
    if "原生" in ip_type:
        scores.append(("A", 80))
        details.append("原生IP A")
    elif "广播" in ip_type:
        scores.append(("C", 35))
        details.append("广播IP C")
    else:
        scores.append(("B", 55))
        details.append(f"IP类型: {ip_type} B")

    # Risk flags
    risk_scores = ip_data.get("risk_scores", {})
    risk_count = sum(1 for v in risk_scores.values() if v == "warn")
    total_risk = len(risk_scores)
    if total_risk > 0:
        if risk_count == 0:
            scores.append(("S", 95))
            details.append("风控: 全部低风险 S")
        elif risk_count <= 1:
            scores.append(("A", 78))
            details.append(f"风控: {risk_count}/{total_risk} 有标记 A")
        elif risk_count <= 3:
            scores.append(("B", 55))
            details.append(f"风控: {risk_count}/{total_risk} 有标记 B")
        else:
            scores.append(("D", 20))
            details.append(f"风控: {risk_count}/{total_risk} 有标记 D")

    # Blacklist
    bl = ip_data.get("bl_blacklist", 0)
    if bl > 0:
        scores.append(("D", 15))
        details.append(f"黑名单: {bl} 条 D")
    else:
        bl_marked = ip_data.get("bl_marked", 0)
        if bl_marked > 2:
            scores.append(("C", 35))
            details.append(f"已标记: {bl_marked} 条 C")
        else:
            scores.append(("A", 82))
            details.append("黑名单: 0 条 A")

    grade, score = _avg_grade(scores)
    return {"grade": grade, "score": score, "label": GRADE_LABELS.get(grade, "?"), "details": details}


def grade_route(route_matrix, carrier, focus_routes=None):
    """Grade return route for a specific carrier (电信/联通/移动)."""
    if not route_matrix:
        return {"grade": "?", "score": 0, "label": "无数据", "details": [], "best_route": ""}

    best_grade = "?"
    best_score = 0
    best_detail = ""
    all_details = []

    for entry in route_matrix:
        routes = entry.get("routes", {})
        route_str = routes.get(carrier, "")
        if not route_str:
            continue

        direction = entry.get("direction", "")
        detail = f"{direction}: {route_str}"
        all_details.append(detail)

        route_upper = route_str.upper()

        # Scoring
        if "CN2GIA" in route_upper or "CN2-GIA" in route_upper:
            grade, score = "S", 95
        elif "CN2" in route_upper:
            grade, score = "A", 85
        elif "9929" in route_upper or "10099" in route_upper:
            grade, score = "A", 83
        elif "CMIN2" in route_upper:
            grade, score = "A", 82
        elif "CMI" in route_upper and carrier == "移动":
            grade, score = "B", 65
        elif "CMI" in route_upper:
            grade, score = "B", 58
        elif "4837" in route_upper and carrier == "联通":
            grade, score = "B", 60
        elif "4837" in route_upper:
            grade, score = "B-", 50
        elif "163" in route_upper:
            grade, score = "C", 30
        elif "HE" in route_upper or "HURRICANE" in route_upper:
            grade, score = "D", 15
        elif "AS4134" in route_upper:
            grade, score = "B-", 52
        else:
            grade, score = "C", 38

        if score > best_score:
            best_score = score
            best_grade = grade
            best_detail = detail

    return {
        "grade": best_grade,
        "score": best_score,
        "label": GRADE_LABELS.get(best_grade[0] if len(best_grade) > 1 else best_grade, "?"),
        "best_route": best_detail,
        "details": all_details,
    }


def grade_retransmit(retransmits):
    """Grade retransmit count. Returns (grade, score, label)."""
    if retransmits is None:
        return "?", 0, "无数据"
    if retransmits < 100:
        return "S", 95, "极低丢包"
    if retransmits < 300:
        return "A", 80, "低丢包"
    if retransmits < 800:
        return "B", 58, "轻微丢包"
    if retransmits < 2000:
        return "C", 35, "偏高丢包"
    return "D", 15, "严重丢包"


def grade_speedtest_download(mbps):
    """Grade domestic speedtest download speed."""
    if mbps is None:
        return "?", 0, "无数据"
    if mbps >= 500:
        return "S", 93, f"{mbps}Mbps"
    if mbps >= 300:
        return "A", 78, f"{mbps}Mbps"
    if mbps >= 200:
        return "B", 58, f"{mbps}Mbps"
    if mbps >= 100:
        return "C", 35, f"{mbps}Mbps"
    return "D", 15, f"{mbps}Mbps"


def grade_international(results):
    """Grade international bandwidth. Average download across regions."""
    if not results:
        return {"grade": "?", "score": 0, "label": "无数据", "details": []}
    downloads = [r.get("download_mbps") for r in results if r.get("download_mbps") is not None]
    if not downloads:
        return {"grade": "?", "score": 0, "label": "无数据", "details": []}

    avg = sum(downloads) / len(downloads)
    if avg >= 1000:
        grade, score = "S", 93
    elif avg >= 500:
        grade, score = "A", 78
    elif avg >= 200:
        grade, score = "B", 55
    elif avg >= 100:
        grade, score = "C", 33
    else:
        grade, score = "D", 15

    return {
        "grade": grade,
        "score": score,
        "label": GRADE_LABELS.get(grade, "?"),
        "avg_mbps": round(avg, 1),
        "details": [f"{r['city']} {r.get('download_mbps','?')}Mbps" for r in results[:10]],
    }


def grade_unlock(unlock_parsed):
    """Grade streaming/AI unlock coverage."""
    if not unlock_parsed:
        return {"grade": "?", "score": 0, "label": "无数据", "details": []}
    total = len(unlock_parsed)
    unlocked = sum(1 for v in unlock_parsed.values() if v.get("status") == "解锁")
    pct = unlocked / total * 100 if total > 0 else 0
    details = [f"{k}: {v.get('status','?')} {v.get('region','')}" for k, v in unlock_parsed.items()]

    if pct >= 80:
        return {"grade": "S", "score": 95, "label": f"{unlocked}/{total} 解锁", "details": details}
    if pct >= 60:
        return {"grade": "A", "score": 78, "label": f"{unlocked}/{total} 解锁", "details": details}
    if pct >= 40:
        return {"grade": "B", "score": 55, "label": f"{unlocked}/{total} 解锁", "details": details}
    if pct >= 20:
        return {"grade": "C", "score": 30, "label": f"{unlocked}/{total} 解锁", "details": details}
    return {"grade": "D", "score": 12, "label": f"{unlocked}/{total} 解锁", "details": details}


def parse_price(price_str):
    """Try to extract monthly cost in USD from a free-form price string."""
    if not price_str:
        return {"raw": "", "monthly_usd": None, "note": ""}
    # Try to find $XX.XX/月 or $XX/月
    m = re.search(r'\$([0-9]+(?:\.[0-9]+)?)\s*/?\s*月', price_str)
    if m:
        return {"raw": price_str, "monthly_usd": float(m.group(1)), "note": ""}
    # Try just $XX.XX
    m = re.search(r'\$([0-9]+(?:\.[0-9]+)?)', price_str)
    if m:
        return {"raw": price_str, "monthly_usd": float(m.group(1)), "note": "（从价格字符串提取，可能不含周期）"}
    return {"raw": price_str, "monthly_usd": None, "note": "无法解析月费"}


def calculate_cost_performance(overall_score, price_info):
    """Calculate cost-performance score."""
    if not price_info or price_info.get("monthly_usd") is None:
        return {"grade": "?", "score": 0, "label": "未提供价格", "ratio": None}

    monthly = price_info["monthly_usd"]
    if monthly <= 0:
        return {"grade": "?", "score": 0, "label": "价格异常", "ratio": None}

    ratio = overall_score / monthly
    if ratio >= 20:
        grade, score = "S", 95
    elif ratio >= 12:
        grade, score = "A", 78
    elif ratio >= 7:
        grade, score = "B", 55
    elif ratio >= 3:
        grade, score = "C", 33
    else:
        grade, score = "D", 15

    return {
        "grade": grade,
        "score": score,
        "label": f"${monthly}/月 → {ratio:.1f} 分/$",
        "ratio": round(ratio, 1),
    }


def grade_all(parsed, focus_routes=None, price_str=None):
    """Run all grading modules and return a full report card."""
    price_info = parse_price(price_str)

    grades = {}

    grades["hardware"] = grade_hardware(parsed["hardware"])
    grades["ipv4"] = grade_ip(parsed["ip_quality"].get("ipv4", {}))
    grades["ipv6"] = grade_ip(parsed["ip_quality"].get("ipv6", {}))

    route_matrix = parsed["route_matrix"]
    for carrier in ["电信", "联通", "移动"]:
        grades[f"route_{carrier}"] = grade_route(route_matrix, carrier, focus_routes)

    # Retransmit analysis
    speedtests = parsed.get("speedtests", [])
    retrans_grades = []
    speed_grades = []
    for st in speedtests:
        r = st.get("retransmits")
        if r is not None:
            g, s, l = grade_retransmit(r)
            retrans_grades.append((g, s, f"{st['node']}: {l}"))
        dl = st.get("download_mbps")
        if dl is not None:
            g, s, l = grade_speedtest_download(dl)
            speed_grades.append((g, s, f"{st['node']}: {l}"))

    if retrans_grades:
        worst = min(retrans_grades, key=lambda x: x[1])
        grades["retransmit"] = {
            "grade": worst[0],
            "score": worst[1],
            "label": worst[2],
            "details": [d for _, _, d in retrans_grades],
        }
    else:
        grades["retransmit"] = {"grade": "?", "score": 0, "label": "无数据", "details": []}

    if speed_grades:
        avg_score = sum(s for _, s, _ in speed_grades) / len(speed_grades)
        grades["domestic_speed"] = {
            "grade": _score_to_grade(avg_score),
            "score": round(avg_score, 1),
            "label": f"平均 {avg_score:.0f} 分",
            "details": [d for _, _, d in speed_grades],
        }
    else:
        grades["domestic_speed"] = {"grade": "?", "score": 0, "label": "无数据", "details": []}

    grades["international"] = grade_international(parsed.get("international", []))

    unlock = parsed["ip_quality"].get("ipv4", {}).get("unlock_parsed", {})
    grades["unlock"] = grade_unlock(unlock)

    # Overall score (weighted)
    weights = {
        "hardware": 0.10,
        "ipv4": 0.15,
        "route_电信": 0.20,
        "route_联通": 0.12,
        "route_移动": 0.10,
        "retransmit": 0.08,
        "domestic_speed": 0.10,
        "international": 0.08,
        "unlock": 0.07,
    }
    overall = 0
    total_weight = 0
    for key, w in weights.items():
        if key in grades and grades[key]["score"] > 0:
            overall += grades[key]["score"] * w
            total_weight += w
    if total_weight > 0:
        overall /= total_weight
    grades["overall"] = {
        "grade": _score_to_grade(overall),
        "score": round(overall, 1),
        "label": f"{round(overall, 1)} 分",
    }

    # Cost performance
    grades["cost_performance"] = calculate_cost_performance(overall, price_info)
    grades["price_info"] = price_info

    return grades


# ---------------------------------------------------------------------------
# Route visualization
# ---------------------------------------------------------------------------


# Transit/IX carriers that indicate IPv6 or unoptimized routes
_TRANSIT_CARRIERS = {"HE", "HURRICANE", "NTT", "TELIA", "GTT", "COGENT", "LEVEL3", "ZAYO", "LUMEN"}


def _is_transit_route(route_str):
    """Check if a route goes through international transit (not direct China optimization)."""
    upper = route_str.upper()
    return any(t in upper for t in _TRANSIT_CARRIERS)


def _all_transit(routes_dict):
    """True if all route values in the dict are transit routes."""
    if not routes_dict:
        return True
    return all(_is_transit_route(v) for v in routes_dict.values())


def visualize_routes(route_matrix, focus_routes=None):
    """
    Group routes by carrier and protocol, separating IPv4 and IPv6.
    NodeQuality prints two route matrix blocks: IPv4 (premium/optimized) then IPv6 (HE/transit).
    We detect the split by checking whether ALL carriers in an entry use transit.
    """
    # First pass: group entries into IPv4 and IPv6 blocks
    v4_entries = []
    v6_entries = []
    for entry in route_matrix:
        routes = entry.get("routes", {})
        if _all_transit(routes):
            v6_entries.append(entry)
        else:
            v4_entries.append(entry)

    def _build_viz(entries):
        viz = {}
        for entry in entries:
            direction = entry.get("direction", "")
            proto_match = re.search(r"(TCP|UDP)", direction)
            proto = proto_match.group(1) if proto_match else "?"
            loc_match = re.search(r"(北京|上海|广州)", direction)
            loc = loc_match.group(1) if loc_match else direction

            for carrier, route_str in entry.get("routes", {}).items():
                if carrier not in viz:
                    viz[carrier] = {"TCP": {}, "UDP": {}}
                viz[carrier][proto][loc] = route_str

        result = {}
        for carrier in ["电信", "联通", "移动"]:
            if carrier not in viz:
                continue
            result[carrier] = {}
            for proto in ["TCP", "UDP"]:
                routes = viz[carrier].get(proto, {})
                if not routes:
                    continue
                unique = set(routes.values())
                if len(unique) == 1:
                    result[carrier][proto] = list(unique)[0]
                else:
                    result[carrier][proto] = ", ".join(
                        f"{loc}:{r}" for loc, r in routes.items()
                    )
        return result

    v4 = _build_viz(v4_entries)
    v6 = _build_viz(v6_entries) if v6_entries else {}

    # Detect detours: IPv6 transit routes for China-bound traffic
    detours = []
    for carrier, protos in v6.items():
        for proto, route in protos.items():
            if _is_transit_route(route):
                detours.append(f"{carrier} {proto}: {route} ⚠️ 绕路")

    return v4, v6, detours


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _focus_match(route_name, focus_routes):
    """Check if a route name matches any focus route."""
    if not focus_routes:
        return False
    for fr in focus_routes:
        if fr in route_name or route_name in fr:
            return True
    return False


def _is_ipv6_evidence(item):
    """Detect whether a route evidence entry is IPv6 (HE transit).
    IPv6 entries typically have:
    - Hops with `:` (IPv6 address like 240e:...)
    - Path going through 加拿大/美国 (HE detour)
    """
    hops_text = " ".join(item.get("hops", []))
    path_text = item.get("path", "")
    # IPv6 address pattern
    if re.search(r"[0-9a-fA-F]{4}:", hops_text):
        return True
    # HE detour indicators
    if any(x in path_text for x in ["加拿大", "美国", "HE", "HURRICANE"]):
        return True
    return False


def format_markdown_single(meta, parsed, grades, focus_routes=None, skip_ipv6=False):
    """Format a single report as Markdown."""
    lines = []
    header = clean(parsed["entries"].get("header_info.log", ""))

    # Title
    provider = meta.get("provider", "未知")
    location = meta.get("location") or {}
    lines.append(f"# NodeQuality 报告: {provider} — {location.get('colo', '')}")
    lines.append("")

    # Meta
    lines.append("| 项目 | 详情 |")
    lines.append("| --- | --- |")
    lines.append(f"| Token | `{meta.get('token', '')}` |")
    lines.append(f"| 商家 | `{provider}` |")
    lines.append(f"| ASN | `AS{meta.get('asn', '')}` |")
    lines.append(f"| 位置 | `{location.get('city', '')}, {location.get('region', '')}` — `{location.get('colo', '')}` |")
    report_time = first_match(header, r"报告时间：\s*([^ ]+ [^ ]+ [^ ]+)")
    if report_time:
        lines.append(f"| 报告时间 | `{report_time}` |")

    price_info = grades.get("price_info", {})
    if price_info.get("raw"):
        lines.append(f"| 价格 | `{price_info['raw']}` |")

    lines.append("")

    # Overall grade badge
    ov = grades.get("overall", {})
    ov_grade = ov.get("grade", "?")
    ov_score = ov.get("score", 0)
    lines.append(f"## 综合评级: **{ov_grade}** ({ov_score} 分)")
    lines.append("")

    # Grade summary table
    lines.append("### 各维度评分")
    lines.append("")
    lines.append("| 维度 | 评级 | 分数 | 说明 |")
    lines.append("| --- | --- | --- | --- |")
    dim_order = [
        ("hardware", "硬件"),
        ("ipv4", "IP 质量"),
        ("route_电信", "电信回国"),
        ("route_联通", "联通回国"),
        ("route_移动", "移动回国"),
        ("retransmit", "重传控制"),
        ("domestic_speed", "国内速度"),
        ("international", "国际带宽"),
        ("unlock", "流媒体解锁"),
        ("cost_performance", "性价比"),
    ]
    for key, label in dim_order:
        g = grades.get(key, {})
        grade_str = g.get("grade", "?")
        score_str = g.get("score", 0)
        label_str = g.get("label", "")
        # Highlight focus routes
        marker = ""
        if key.startswith("route_") and focus_routes:
            carrier = key.replace("route_", "")
            if any(carrier in fr for fr in focus_routes):
                marker = " 🎯"
        lines.append(f"| {label}{marker} | **{grade_str}** | {score_str} | {label_str} |")

    # Hardware
    hw = parsed["hardware"]
    lines.append("")
    lines.append("## 硬件配置")
    lines.append(f"- CPU: {hw.get('cpu', '?')}")
    lines.append(f"- 虚拟化: {hw.get('virt', '?')}")
    lines.append(f"- 系统: {hw.get('os', '?')}")
    lines.append(f"- GB5: 单核 {hw.get('gb5_single','?')} / 多核 {hw.get('gb5_multi','?')}")
    lines.append(f"- 内存: {hw.get('memory_raw','?')}")
    lines.append(f"- 磁盘: {hw.get('disk_raw','?')}")
    lines.append(f"- HQ 分: {hw.get('score','?')}")

    # IP Quality
    lines.append("")
    lines.append("## IP 质量")
    ip_sections = [("IPv4", parsed["ip_quality"].get("ipv4", {}))]
    if not skip_ipv6:
        ip_sections.append(("IPv6", parsed["ip_quality"].get("ipv6", {})))
    for name, data in ip_sections:
        if not data:
            continue
        lines.append(f"### {name}")
        lines.append(f"- 类型: {data.get('ip_type', '?')} | 组织: {data.get('org', '?')}")
        if data.get("risks"):
            lines.append("- 风控: " + " | ".join(data["risks"][:6]))
        if data.get("blacklist"):
            lines.append(f"- 黑名单: {data['blacklist']}")
        if data.get("unlock"):
            lines.append("- 流媒体解锁:")
            for item in data["unlock"][:6]:
                lines.append(f"  - {item}")

    # Route summary — show IPv4 (preferred) and IPv6 separately if both exist
    lines.append("")
    lines.append("## 回国路由")
    route_matrix = parsed["route_matrix"]
    v4, v6, detours = visualize_routes(route_matrix, focus_routes)

    def _render_route_block(viz, label):
        if not viz:
            return
        if label:
            lines.append(f"### {label}")
        for carrier in ["电信", "联通", "移动"]:
            if carrier not in viz:
                continue
            focus_mark = " 🎯" if focus_routes and any(carrier in fr for fr in focus_routes) else ""
            lines.append(f"#### {carrier}{focus_mark}")
            for proto in ["TCP", "UDP"]:
                if proto in viz[carrier]:
                    route_str = viz[carrier][proto]
                    route_grade = _route_grade_label(route_str)
                    lines.append(f"- **{proto}**: {route_str} {route_grade}")

    _render_route_block(v4, "IPv4 优化路由")
    if v6 and not skip_ipv6:
        _render_route_block(v6, "IPv6 (HE 穿透)")

    if detours and not skip_ipv6:
        lines.append("")
        lines.append("### ⚠️ IPv6 绕路警告")
        for d in detours:
            lines.append(f"- {d}")

    # Focus route evidence
    if focus_routes:
        lines.append("")
        lines.append("## 🎯 重点线路详情")
        evidence = parsed.get("route_evidence", [])
        for item in evidence:
            if _focus_match(item["name"], focus_routes):
                # Skip IPv6 evidence when --skip-ipv6 is set
                if skip_ipv6 and _is_ipv6_evidence(item):
                    continue
                lines.append(f"### {item['name']}")
                lines.append(f"- 路径: {item.get('path', item.get('route', ''))}")
                for hop in item.get("hops", [])[:5]:
                    lines.append(f"  - {hop}")

    # Speedtest
    lines.append("")
    lines.append("## 国内测速")
    speedtests = parsed.get("speedtests", [])
    if speedtests:
        lines.append("| 节点 | 下载 | 上传 | 重传 | 重传评级 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for st in speedtests[:10]:
            r = st.get("retransmits")
            rg, _, rl = grade_retransmit(r)
            node = st.get("node", "?")
            dl = f"{st['download_mbps']}Mbps" if st.get("download_mbps") is not None else "ERROR"
            ul = f"{st['upload_mbps']}Mbps" if st.get("upload_mbps") is not None else "ERROR"
            ret = str(r) if r is not None else "N/A"
            focus_mark = " 🎯" if _focus_match(node, focus_routes) else ""
            lines.append(f"| {node}{focus_mark} | {dl} | {ul} | {ret} | {rg} {rl} |")
    else:
        lines.append("无数据")

    # International
    lines.append("")
    lines.append("## 国际带宽")
    intl = parsed.get("international", [])
    if intl:
        lines.append("| 区域 | 下载 | 上传 | 延迟 | 重传(收) |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in intl[:12]:
            city = item.get("city", "?")
            dl = f"{item['download_mbps']}Mbps" if item.get("download_mbps") is not None else "ERROR"
            ul = f"{item['upload_mbps']}Mbps" if item.get("upload_mbps") is not None else "?"
            lat = f"{item['latency_ms']}ms" if item.get("latency_ms") is not None else "?"
            retr = str(item.get("retransmit_recv", "?")) if item.get("retransmit_recv") is not None else "?"
            lines.append(f"| {city} | {dl} | {ul} | {lat} | {retr} |")
    else:
        lines.append("无数据")

    # Cost-performance note
    cp = grades.get("cost_performance", {})
    if cp.get("ratio"):
        lines.append("")
        lines.append("## 性价比分析")
        lines.append(f"- 月费: ${price_info.get('monthly_usd', '?')}")
        lines.append(f"- 性价比指数: {cp['ratio']} 分/$ — **{cp['grade']}** ({cp['label']})")

    return "\n".join(lines).strip() + "\n"


def _route_grade_label(route_str):
    """Return a short grade label for a route string."""
    upper = route_str.upper()
    if "CN2GIA" in upper:
        return "🔥 S"
    if "9929" in upper or "10099" in upper:
        return "⭐ A"
    if "CMIN2" in upper:
        return "⭐ A"
    if "CMI" in upper:
        return "✅ B"
    if "4837" in upper:
        return "✅ B"
    if "163" in upper:
        return "⚠️ C"
    if any(x in upper for x in ["HE", "HURRICANE", "NTT"]):
        return "❌ D"
    return ""


def format_markdown_compare(reports, focus_routes=None, skip_ipv6=False):
    """Generate comparison Markdown for multiple reports."""
    lines = []
    lines.append("# NodeQuality 对比分析")
    lines.append("")

    # Short names
    names = []
    for r in reports:
        meta = r["meta"]
        provider = meta.get("provider", "?")
        location = meta.get("location") or {}
        colo = location.get("colo", "?")
        names.append(f"{provider} ({colo})")
    n = len(reports)

    # Overview table
    lines.append("## 概览")
    lines.append("")
    header_cols = "| 维度 | " + " | ".join(names) + " |"
    sep = "| --- | " + " | ".join(["---"] * n) + " |"
    lines.append(header_cols)
    lines.append(sep)

    rows = [
        ("商家", [r["meta"].get("provider", "?") for r in reports]),
        ("机房", [(r["meta"].get("location") or {}).get("colo", "?") for r in reports]),
        ("ASN", [f"AS{r['meta'].get('asn','?')}" for r in reports]),
        ("价格", [r["grades"].get("price_info", {}).get("raw", "未提供") for r in reports]),
        ("综合评级", [f"**{r['grades'].get('overall',{}).get('grade','?')}** ({r['grades'].get('overall',{}).get('score',0)}分)" for r in reports]),
    ]
    for label, vals in rows:
        lines.append(f"| {label} | " + " | ".join(str(v) for v in vals) + " |")

    # Grade comparison
    lines.append("")
    lines.append("## 评分对比")
    lines.append("")
    dims = [
        ("hardware", "硬件"),
        ("ipv4", "IP 质量"),
        ("route_电信", "电信回国"),
        ("route_联通", "联通回国"),
        ("route_移动", "移动回国"),
        ("retransmit", "重传控制"),
        ("domestic_speed", "国内速度"),
        ("international", "国际带宽"),
        ("unlock", "流媒体解锁"),
        ("cost_performance", "性价比"),
    ]
    lines.append("| 维度 | " + " | ".join(names) + " |")
    lines.append("| --- | " + " | ".join(["---"] * n) + " |")
    for key, label in dims:
        vals = []
        for r in reports:
            g = r["grades"].get(key, {})
            grade_str = g.get("grade", "?")
            score_str = g.get("score", 0)
            vals.append(f"**{grade_str}** ({score_str})")
        focus_mark = ""
        if key.startswith("route_") and focus_routes:
            carrier = key.replace("route_", "")
            if any(carrier in fr for fr in focus_routes):
                focus_mark = " 🎯"
        lines.append(f"| {label}{focus_mark} | " + " | ".join(vals) + " |")

    # Route comparison (focused)
    if focus_routes:
        lines.append("")
        lines.append("## 🎯 重点线路对比")
        for fr in focus_routes:
            lines.append(f"### {fr}")
            lines.append("")
            for i, r in enumerate(reports):
                route_matrix = r["parsed"]["route_matrix"]
                for entry in route_matrix:
                    direction = entry.get("direction", "")
                    if fr.split("电信")[0].split("联通")[0].split("移动")[0].strip() in direction:
                        for carrier in ["电信", "联通", "移动"]:
                            if carrier in fr:
                                route_str = entry.get("routes", {}).get(carrier, "?")
                                lines.append(f"- **{names[i]}**: {direction} → {route_str}")

    # Winner selection
    lines.append("")
    lines.append("## 综合推荐")
    overalls = [(i, r["grades"].get("overall", {}).get("score", 0)) for i, r in enumerate(reports)]
    overalls.sort(key=lambda x: x[1], reverse=True)
    for rank, (i, score) in enumerate(overalls, 1):
        r = reports[i]
        grade = r["grades"].get("overall", {}).get("grade", "?")
        lines.append(f"{rank}. **{names[i]}** — {grade} ({score} 分)")

    # Cost-performance winner
    cp_scores = [(i, r["grades"].get("cost_performance", {}).get("ratio", 0) or 0) for i, r in enumerate(reports)]
    cp_scores.sort(key=lambda x: x[1], reverse=True)
    if any(s > 0 for _, s in cp_scores):
        lines.append("")
        lines.append("### 性价比最优")
        i, ratio = cp_scores[0]
        if ratio > 0:
            lines.append(f"- **{names[i]}** — {ratio:.1f} 分/$")

    return "\n".join(lines).strip() + "\n"


def format_json_output(reports, skip_ipv6=False):
    """Output full structured JSON."""
    output = []
    for r in reports:
        entry = {
            "meta": r["meta"],
            "hardware": r["parsed"]["hardware"],
            "ip_quality": r["parsed"]["ip_quality"],
            "speedtests": r["parsed"].get("speedtests", []),
            "international": r["parsed"].get("international", []),
            "route_matrix": r["parsed"].get("route_matrix", []),
            "grades": r["grades"],
        }
        if skip_ipv6:
            entry["ipv6_skipped"] = True
            # Strip IPv6 from ip_quality
            entry["ip_quality"] = {
                k: v for k, v in entry["ip_quality"].items() if k == "ipv4"
            }
            # Strip transit (IPv6) entries from route_matrix
            entry["route_matrix"] = [
                rm for rm in entry["route_matrix"]
                if not _all_transit(rm.get("routes", {}))
            ]
        output.append(entry)
    if len(output) == 1:
        return json.dumps(output[0], ensure_ascii=False, indent=2) + "\n"
    return json.dumps(output, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Core analysis pipeline
# ---------------------------------------------------------------------------


def analyze_one(url_or_token, cache_dir=None, refresh=False, record_json=None):
    """Fetch + parse + grade a single report."""
    if record_json:
        record = json.loads(Path(record_json).read_text(encoding="utf-8"))
        token = "local"
        meta = record.get("data", record)
    else:
        token, record = fetch_record(url_or_token, cache_dir=cache_dir, refresh=refresh)
        if not record.get("success", True):
            raise RuntimeError(record.get("message") or "NodeQuality API returned success=false")
        meta = record.get("data", record)

    data, entries = decode_entries(record)
    meta["token"] = meta.get("token", token)

    # Parse all log files
    hw_log = clean(entries.get("hardware_quality.log", ""))
    ip_log = clean(entries.get("ip_quality.log", ""))
    net_log = clean(entries.get("net_quality.log", ""))
    backroute_log = clean(entries.get("backroute_trace.log", ""))

    parsed = {
        "entries": entries,
        "hardware": parse_hardware(hw_log),
        "ip_quality": parse_ip_quality(ip_log),
        "speedtests": parse_speedtest(net_log),
        "international": parse_international(net_log),
        "route_matrix": parse_route_matrix(net_log),
        "route_evidence": parse_route_evidence(backroute_log),
    }

    return meta, parsed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="NodeQuality Report Parser v2 — fetch, grade, compare VPS benchmarks."
    )
    parser.add_argument(
        "urls_or_tokens", nargs="*", help="One or more NodeQuality report URLs or tokens"
    )
    parser.add_argument(
        "--record-json", nargs="*", help="Path(s) to exported record API JSON file(s)"
    )
    parser.add_argument("--json", action="store_true", dest="json_out", help="Output structured JSON")
    parser.add_argument(
        "--focus-routes",
        help="Comma-separated key routes to highlight, e.g. '上海电信,北京联通'",
    )
    parser.add_argument(
        "--price",
        action="append",
        dest="prices",
        help="Price info per report, e.g. '续费$5/月,二手溢价$50'. Repeat for multiple reports.",
    )
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help=f"Cache directory (default: {DEFAULT_CACHE_DIR})")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch, ignore cache")
    parser.add_argument("--dump-dir", help="Save decoded raw logs and summary to directory")
    parser.add_argument("--no-cache", action="store_true", help="Disable caching entirely")
    parser.add_argument("--skip-ipv6", action="store_true", help="Omit IPv6 route blocks and IP quality sections")

    args = parser.parse_args()

    if not args.urls_or_tokens and not args.record_json:
        parser.print_help()
        return 1

    focus_routes = None
    if args.focus_routes:
        focus_routes = [r.strip() for r in args.focus_routes.split(",") if r.strip()]

    prices = args.prices or []
    cache_dir = None if args.no_cache else args.cache_dir
    refresh = args.refresh
    skip_ipv6 = args.skip_ipv6

    # Collect all inputs
    inputs = list(args.urls_or_tokens)
    if args.record_json:
        # --record-json mode: each JSON file is a separate report
        inputs = [(None, p) for p in args.record_json]
    else:
        inputs = [(u, None) for u in inputs]

    if not inputs:
        print("ERROR: 至少需要一个 URL/Token 或 --record-json 文件", file=sys.stderr)
        return 1

    reports = []
    for idx, (url, rec_json) in enumerate(inputs):
        price_str = prices[idx] if idx < len(prices) else None
        try:
            meta, parsed = analyze_one(
                url, cache_dir=cache_dir, refresh=refresh, record_json=rec_json
            )
            grades = grade_all(parsed, focus_routes=focus_routes, price_str=price_str)
            reports.append({"meta": meta, "parsed": parsed, "grades": grades})
        except Exception as exc:
            label = url or rec_json
            print(f"ERROR [{label}]: {exc}", file=sys.stderr)
            return 1

    # Output
    if args.json_out:
        sys.stdout.write(format_json_output(reports, skip_ipv6=skip_ipv6))
    elif len(reports) == 1:
        meta, parsed, grades = reports[0]["meta"], reports[0]["parsed"], reports[0]["grades"]
        sys.stdout.write(format_markdown_single(meta, parsed, grades, focus_routes=focus_routes, skip_ipv6=skip_ipv6))
    else:
        sys.stdout.write(format_markdown_compare(reports, focus_routes=focus_routes, skip_ipv6=skip_ipv6))

    # Dump if requested
    if args.dump_dir:
        dump_dir = Path(args.dump_dir)
        dump_dir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(reports):
            prefix = f"report_{i}_" if len(reports) > 1 else ""
            (dump_dir / f"{prefix}meta.json").write_text(
                json.dumps(r["meta"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (dump_dir / f"{prefix}grades.json").write_text(
                json.dumps(r["grades"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for name, text in r["parsed"]["entries"].items():
                safe = name.replace("/", "_").replace("\\", "_")
                (dump_dir / f"{prefix}{safe}").write_text(text, encoding="utf-8", errors="replace")
            summary = format_markdown_single(
                r["meta"], r["parsed"], r["grades"], focus_routes=focus_routes, skip_ipv6=skip_ipv6
            )
            (dump_dir / f"{prefix}summary.md").write_text(summary, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
