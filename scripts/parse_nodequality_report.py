#!/usr/bin/env python3
import argparse
import base64
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "https://api.nodequality.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TOKEN_RE = re.compile(r"(?:/r/)?([A-Za-z0-9_-]{16,})")


def request_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read().decode("utf-8", errors="replace")
    return json.loads(body)


def base_headers():
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://nodequality.com",
        "Referer": "https://nodequality.com/",
    }


def extract_token(value):
    if not value:
        raise ValueError("missing URL or token")
    match = TOKEN_RE.search(value.strip())
    if not match:
        raise ValueError(f"cannot extract NodeQuality token from: {value}")
    return match.group(1)


def fetch_record(url_or_token):
    token = extract_token(url_or_token)
    headers = base_headers()
    ipinfo = request_json(f"{API_BASE}/api/v1/ipinfo", headers)
    record_url = f"{API_BASE}/api/v1/record/{token}"
    sign_payload = "\n\n".join(
        ["GET", record_url, USER_AGENT, f"{ipinfo['ip']}{ipinfo['ts']}", ""]
    )
    headers["x-dynamic-sign-v"] = hashlib.sha1(sign_payload.encode("utf-8")).hexdigest()
    headers["x-dynamic-sign-t"] = str(ipinfo["ts"])
    return request_json(record_url, headers)


def clean(text):
    text = ANSI_RE.sub("", text)
    text = text.replace("\r", "")
    text = text.replace("\b", "")
    return "\n".join(line.rstrip() for line in text.splitlines())


def decode_entries(record):
    data = record.get("data", record)
    encoded = data.get("result")
    if not encoded:
        raise ValueError("record JSON does not contain data.result")
    blob = base64.b64decode(encoded)
    entries = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            entries[item.filename] = archive.read(item).decode("utf-8", errors="replace")
    return data, entries


def first_match(text, pattern, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


def first_line(text, pattern, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(0).strip() if match else default


def extract_labeled_value(text, label):
    return first_match(text, rf"{re.escape(label)}\s*[:：]\s*(.+)")


def parse_hardware(log):
    return {
        "os": extract_labeled_value(log, "操作系统/内核"),
        "virt": extract_labeled_value(log, "容器/虚拟化"),
        "cpu": extract_labeled_value(log, "CPU"),
        "gb5_single": first_match(log, r"GB5单核[：:]\s*\|?([0-9]+)"),
        "gb5_multi": first_match(log, r"GB5多核[：:]\s*\|?([0-9]+)"),
        "memory": extract_labeled_value(log, "内存"),
        "disk": extract_labeled_value(log, "硬盘"),
        "score": first_match(log, r"分数[：:]\s*([0-9]+)"),
    }


def parse_ip_quality(log):
    ipv4 = {}
    ipv6 = {}
    sections = re.split(r"\n(?=.*IP质量体检报告)", log)
    for section in sections:
        if "IP质量体检报告" not in section:
            continue
        target = ipv6 if "260" in section[:300] or "IPv6" in section[:300] else ipv4
        target["org"] = extract_labeled_value(section, "组织")
        target["city"] = extract_labeled_value(section, "城市")
        target["ip_type"] = extract_labeled_value(section, "IP类型")
        target["blacklist"] = first_line(
            section, r"IP地址黑名单数据库：\s*有效\s*[0-9]+\s*正常\s*[0-9]+\s*已标记\s*[0-9]+\s*黑名单\s*[0-9]+"
        )
        risks = []
        for provider in ["IP2Location", "Scamalytics", "ipapi", "AbuseIPDB", "IPQS", "DB-IP"]:
            line = first_match(section, rf"({provider}：.+)")
            if line:
                risks.append(line)
        target["risks"] = risks
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
    return {"ipv4": ipv4, "ipv6": ipv6}


def parse_speedtest(log):
    lines = log.splitlines()
    out = []
    for i, line in enumerate(lines):
        if "国内测速" not in line:
            continue
        for row in lines[i + 1 : i + 5]:
            if "国际互连" in row:
                break
            parts = [p.strip() for p in row.split("||")]
            for part in parts:
                if part:
                    out.append(part)
    return out


def parse_international(log):
    lines = log.splitlines()
    out = []
    for i, line in enumerate(lines):
        if "国际互连" not in line:
            continue
        for row in lines[i + 1 : i + 7]:
            if "====" in row or "报告链接" in row:
                break
            parts = [p.strip() for p in row.split("||")]
            for part in parts:
                if part:
                    out.append(part)
        break
    return out


def parse_route_matrix(net_log):
    matrix = []
    for line in net_log.splitlines():
        if re.search(r"(北京|上海|广州)(TCP|UDP)", line):
            line = re.sub(r"\s+", " ", line).strip()
            matrix.append(line)
    return matrix


def parse_route_evidence(backroute_log):
    evidence = []
    current = None
    for line in backroute_log.splitlines():
        header = re.search(r"^\s*(北京|上海|广东|广州)\s+(电信|联通|移动)\s+(.+?->.+?)\s*$", line)
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
        if current and any(key in line for key in ["59.43", "AS4809", "AS9929", "AS10099", "AS58807", "AS9808", "AS4134", "AS4812"]):
            current["hops"].append(re.sub(r"\s+", " ", line).strip())
    return evidence


def summarize(meta, entries):
    header = clean(entries.get("header_info.log", ""))
    hw_log = clean(entries.get("hardware_quality.log", ""))
    ip_log = clean(entries.get("ip_quality.log", ""))
    net_log = clean(entries.get("net_quality.log", ""))
    backroute_log = clean(entries.get("backroute_trace.log", ""))

    hardware = parse_hardware(hw_log)
    ip_quality = parse_ip_quality(ip_log)
    domestic = parse_speedtest(net_log)
    international = parse_international(net_log)
    route_matrix = parse_route_matrix(net_log)
    evidence = parse_route_evidence(backroute_log)

    lines = []
    lines.append("# NodeQuality Report Summary")
    lines.append("")
    lines.append(f"- Token: `{meta.get('token', '')}`")
    lines.append(f"- Provider: `{meta.get('provider', '')}`")
    lines.append(
        f"- ASN/Org: `AS{meta.get('asn', '')}` / `{meta.get('asOrganization', '')}`"
    )
    location = meta.get("location") or {}
    lines.append(
        f"- Location: `{location.get('city', '')}, {location.get('region', '')}` colo `{location.get('colo', '')}`"
    )
    report_time = first_match(header, r"报告时间：\s*([^ ]+ [^ ]+ [^ ]+)")
    if report_time:
        lines.append(f"- Report time: `{report_time}`")

    lines.append("")
    lines.append("## Hardware")
    for label, key in [
        ("Virtualization", "virt"),
        ("OS", "os"),
        ("CPU", "cpu"),
        ("Geekbench 5", "gb5_single"),
        ("Memory", "memory"),
        ("Disk", "disk"),
        ("HQ score", "score"),
    ]:
        value = hardware.get(key)
        if key == "gb5_single" and value:
            value = f"single {hardware.get('gb5_single')} / multi {hardware.get('gb5_multi')}"
        if value:
            lines.append(f"- {label}: {value}")

    lines.append("")
    lines.append("## IP Quality")
    for name, data in [("IPv4", ip_quality["ipv4"]), ("IPv6", ip_quality["ipv6"])]:
        if not data:
            continue
        lines.append(f"### {name}")
        for key, label in [("org", "Org"), ("city", "City"), ("ip_type", "Type")]:
            if data.get(key):
                lines.append(f"- {label}: {data[key]}")
        if data.get("risks"):
            lines.append("- Risk lines: " + " | ".join(data["risks"][:6]))
        if data.get("blacklist"):
            lines.append("- Mail blacklist: " + data["blacklist"])
        if data.get("unlock"):
            lines.append("- Unlock:")
            for item in data["unlock"][:4]:
                lines.append(f"  - {item}")

    lines.append("")
    lines.append("## China Return Routes")
    if route_matrix:
        for item in route_matrix:
            lines.append(f"- {item}")
    else:
        lines.append("- No route matrix found in net_quality.log.")

    sh_ct = [item for item in evidence if item["name"] in ["上海电信", "广东电信", "北京电信"]]
    if sh_ct:
        lines.append("")
        lines.append("## Route Evidence")
        for item in sh_ct[:6]:
            lines.append(f"- {item['name']}: {item['route']}")
            if item["path"]:
                lines.append(f"  - {item['path']}")
            for hop in item["hops"][:4]:
                lines.append(f"  - {hop}")

    lines.append("")
    lines.append("## Domestic Speedtest")
    for item in domestic[:8]:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## International Transfer")
    for item in international[:12]:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## Practical Reading Checklist")
    lines.append("- Treat IPv4 and IPv6 independently if route labels differ.")
    lines.append("- CN2GIA is preferred for China Telecom latency and stability.")
    lines.append("- 9929/10099 are premium China Unicom routes; CMIN2 is premium China Mobile.")
    lines.append("- 163, high retransmits, ERROR rows, or near-zero download are weak spots.")
    lines.append("- IPQS/proxy/VPN flags and blacklist counts matter for mail and strict platforms.")
    return "\n".join(lines).strip() + "\n"


def dump_files(dump_dir, meta, entries, summary):
    target = Path(dump_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "record_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, text in entries.items():
        safe = name.replace("/", "_").replace("\\", "_")
        (target / safe).write_text(text, encoding="utf-8", errors="replace")
    (target / "summary.md").write_text(summary, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Parse NodeQuality report URL/token.")
    parser.add_argument("url_or_token", nargs="?", help="NodeQuality report URL or token")
    parser.add_argument("--record-json", help="Path to exported record API JSON")
    parser.add_argument("--dump-dir", help="Directory to save decoded logs and summary")
    args = parser.parse_args()

    try:
        if args.record_json:
            record = json.loads(Path(args.record_json).read_text(encoding="utf-8"))
        else:
            record = fetch_record(args.url_or_token)
        if not record.get("success", True):
            raise RuntimeError(record.get("message") or "NodeQuality API returned success=false")
        meta, entries = decode_entries(record)
        summary = summarize(meta, entries)
        if args.dump_dir:
            dump_files(args.dump_dir, meta, entries, summary)
        sys.stdout.write(summary)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
