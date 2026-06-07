#!/usr/bin/env python3
"""
Save NodeQuality report to local VPS library (JSON + CSV).

Usage:
  # Direct mode: parses and saves JSON + CSV automatically
  python save_report.py --model "KVM-2G" --price "$5/mo" "https://nodequality.com/r/<token>"

  # Optional stdin mode for pre-parsed JSON
  python parse_nodequality_report.py --json "<url>" | python save_report.py --stdin --model "KVM-2G"

  # List saved reports
  python save_report.py --list

  # Force overwrite existing token
  python save_report.py --force --model "..." "<url>"
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- Paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
PARSER = SCRIPT_DIR / "parse_nodequality_report.py"
REPORTS_DIR = Path("vps-reports")
JSON_DIR = REPORTS_DIR / "json"
CSV_PATH = REPORTS_DIR / "reports.csv"
APPROX_USD_RATES = {
    "USD": 1.0,
    "CNY": 0.14,
    "EUR": 1.08,
    "HKD": 0.128,
}

CSV_COLUMNS = [
    "token", "型号", "日期", "商家", "ASN", "位置",
    "月费USD", "价格备注",
    "总评", "总分",
    "硬件评级", "硬件分", "CPU型号", "GB5单核", "内存GB", "磁盘GB",
    "IP类型", "IP组织", "黑名单数", "风控警告数",
    "电信评级", "电信最佳路由",
    "联通评级", "联通最佳路由",
    "移动评级", "移动最佳路由",
    "国内均速Mbps", "国际均速Mbps",
    "重传最差", "重传评级",
    "流媒体解锁数", "Netflix", "Disney+", "ChatGPT",
]


def ensure_dirs():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)


def configure_library_dir(path):
    global REPORTS_DIR, JSON_DIR, CSV_PATH
    REPORTS_DIR = Path(path)
    JSON_DIR = REPORTS_DIR / "json"
    CSV_PATH = REPORTS_DIR / "reports.csv"


def init_csv():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)


def token_exists(token):
    if not CSV_PATH.exists():
        return False
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("token") == token:
                return True
    return False


def remove_token_from_csv(token):
    if not CSV_PATH.exists():
        return
    with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows = [row for row in rows if row.get("token") != token]
    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def parse_monthly_usd(price_raw):
    if not price_raw:
        return None
    price = extract_price_amount(price_raw)
    if not price:
        return None
    amount, currency = price
    if re.search(r"年付|年缴|年费|annual|annually|yearly|/年|/yr|/year", price_raw, re.IGNORECASE):
        amount = amount / 12
    return round(amount * APPROX_USD_RATES[currency], 2)


def extract_price_amount(price_raw):
    patterns = [
        ("HKD", r"(?:HK\$|HKD)\s*([0-9]+(?:\.[0-9]+)?)"),
        ("EUR", r"(?:€|EUR)\s*([0-9]+(?:\.[0-9]+)?)"),
        ("CNY", r"(?:￥|¥|CNY|RMB)\s*([0-9]+(?:\.[0-9]+)?)"),
        ("CNY", r"([0-9]+(?:\.[0-9]+)?)\s*(?:元|CNY|RMB)"),
        ("USD", r"(?:USD|US\$)\s*([0-9]+(?:\.[0-9]+)?)"),
        ("USD", r"(?<!HK)\$\s*([0-9]+(?:\.[0-9]+)?)"),
    ]
    for currency, pattern in patterns:
        m = re.search(pattern, price_raw, re.IGNORECASE)
        if m:
            return float(m.group(1)), currency
    return None


def safe_get(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d if d is not None else default


def extract_row(data, model, price_raw):
    meta = data.get("meta", {})
    hw = data.get("hardware", {})
    ip = data.get("ip_quality", {}).get("ipv4", {})
    grades = data.get("grades", {})
    speedtests = data.get("speedtests", [])
    intl = data.get("international", [])

    # Location
    loc = meta.get("location", {})
    location = f"{loc.get('city','')}, {loc.get('region','')} ({loc.get('colo','')})"

    # Price
    price_monthly = None
    price_note = ""
    pi = grades.get("price_info", {})
    if pi and pi.get("monthly_usd") is not None:
        price_monthly = pi["monthly_usd"]
    elif price_raw:
        price_monthly = parse_monthly_usd(price_raw)
    if price_raw:
        price_note = price_raw

    # CPU
    cpu = hw.get("cpu", "")

    # IP risks
    risks = ip.get("risk_scores", {})
    warn_count = sum(1 for v in risks.values() if v in ("warn", "high"))

    # Unlock
    unlock_parsed = ip.get("unlock_parsed", {})
    unlocked_count = sum(1 for s in unlock_parsed.values() if isinstance(s, dict) and s.get("status") == "解锁")
    netflix = safe_get(unlock_parsed, "Netflix", "status", default="?")
    disney = safe_get(unlock_parsed, "Disney+", "status", default="?")
    chatgpt = safe_get(unlock_parsed, "ChatGPT", "status", default="?")

    # Routes
    def _route_grade(isp):
        g = grades.get(f"route_{isp}", {})
        return safe_get(g, "grade"), safe_get(g, "best_route")

    telecom_grade, telecom_best = _route_grade("电信")
    unicom_grade, unicom_best = _route_grade("联通")
    mobile_grade, mobile_best = _route_grade("移动")

    # Domestic speed
    dl_cn = [s.get("receive_mbps", s.get("download_mbps", 0)) or 0 for s in speedtests]
    avg_dl_cn = round(sum(dl_cn) / len(dl_cn), 1) if dl_cn else 0

    # International speed
    dl_intl = [s.get("receive_mbps", s.get("download_mbps", 0)) or 0 for s in intl]
    avg_dl_intl = round(sum(dl_intl) / len(dl_intl), 1) if dl_intl else 0

    # Retransmit
    retrans_all = []
    for item in intl:
        for key in ("retransmit_send", "retransmit_recv"):
            value = item.get(key)
            if value is not None:
                retrans_all.append(value)
    retrans_worst = max(retrans_all) if retrans_all else 0
    retrans_grade = safe_get(grades, "retransmit", "grade")

    # Report date
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    return {
        "token": meta.get("token", ""),
        "型号": model,
        "日期": date_str,
        "商家": meta.get("provider", ""),
        "ASN": str(meta.get("asn", "")),
        "位置": location,
        "月费USD": f"{price_monthly:.2f}" if price_monthly else "",
        "价格备注": price_note,
        "总评": safe_get(grades, "overall", "grade"),
        "总分": safe_get(grades, "overall", "score"),
        "硬件评级": safe_get(grades, "hardware", "grade"),
        "硬件分": safe_get(grades, "hardware", "score"),
        "CPU型号": cpu,
        "GB5单核": hw.get("gb5_single", ""),
        "内存GB": hw.get("memory_gb", ""),
        "磁盘GB": hw.get("disk_gb", ""),
        "IP类型": ip.get("ip_type", ""),
        "IP组织": ip.get("org", ""),
        "黑名单数": ip.get("bl_blacklist", ""),
        "风控警告数": warn_count,
        "电信评级": telecom_grade,
        "电信最佳路由": telecom_best,
        "联通评级": unicom_grade,
        "联通最佳路由": unicom_best,
        "移动评级": mobile_grade,
        "移动最佳路由": mobile_best,
        "国内均速Mbps": avg_dl_cn,
        "国际均速Mbps": avg_dl_intl,
        "重传最差": retrans_worst,
        "重传评级": retrans_grade,
        "流媒体解锁数": f"{unlocked_count}/7",
        "Netflix": netflix,
        "Disney+": disney,
        "ChatGPT": chatgpt,
    }


def append_csv(row):
    init_csv()
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([row.get(col, "") for col in CSV_COLUMNS])


def save_json(data):
    token = data.get("meta", {}).get("token", "unknown")
    path = JSON_DIR / f"{token}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def list_reports():
    if not CSV_PATH.exists():
        print("📭 报告库为空。先用 save_report.py 保存几份报告。")
        return
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        print("📭 报告库为空。")
        return

    # Short display columns
    display_cols = [
        ("token", 24), ("型号", 12), ("总评", 6), ("电信评级", 8),
        ("联通评级", 8), ("移动评级", 8), ("国内均速Mbps", 12),
        ("Netflix", 8), ("Disney+", 8), ("ChatGPT", 8), ("月费USD", 10),
    ]

    header = "".join(f"{c[0]:<{c[1]}}" for c in display_cols)
    sep = "".join("-" * c[1] for c in display_cols)
    print(header)
    print(sep)
    for row in rows:
        line = "".join(f"{str(row.get(c[0],''))[:c[1]-1]:<{c[1]}}" for c in display_cols)
        print(line)

    print(f"\n共 {len(rows)} 份报告。JSON 归档: {JSON_DIR}/")


def fetch_report(url, skip_ipv6=False, price=""):
    """Run the parser and return JSON dict."""
    cmd = [sys.executable, str(PARSER), "--json"]
    if skip_ipv6:
        cmd.append("--skip-ipv6")
    if price:
        cmd.extend(["--price", price])
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"❌ 解析失败:\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout)


def main():
    parser = argparse.ArgumentParser(description="Save NodeQuality report to local library")
    parser.add_argument("url", nargs="?", help="NodeQuality URL or token")
    parser.add_argument("--model", "-m", default="", help="型号（如 KVM-2G、Standard-1C）")
    parser.add_argument("--price", "-p", default="", help="价格信息（如 '$5/月'）")
    parser.add_argument("--skip-ipv6", action="store_true", help="跳过 IPv6")
    parser.add_argument("--force", "-f", action="store_true", help="覆盖已存在的报告")
    parser.add_argument("--list", "-l", action="store_true", help="列出已存报告")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读取 JSON（管道模式）")
    parser.add_argument("--library-dir", default="vps-reports", help="报告库目录（默认：vps-reports）")

    args = parser.parse_args()

    configure_library_dir(args.library_dir)
    ensure_dirs()

    if args.list:
        list_reports()
        return

    # --- Determine JSON source ---
    if args.stdin or not sys.stdin.isatty():
        # Pipe mode: JSON on stdin
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"❌ stdin 不是有效 JSON: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.url:
        # Direct mode: fetch via parser
        data = fetch_report(args.url, skip_ipv6=args.skip_ipv6, price=args.price)
    else:
        print("用法: 提供 URL 直接保存\n  python save_report.py --model KVM-2G --price '$5/mo' URL", file=sys.stderr)
        sys.exit(1)

    # --- Dedup check ---
    token = data.get("meta", {}).get("token", "")
    if not token:
        print("❌ 无法提取 token", file=sys.stderr)
        sys.exit(1)

    if token_exists(token) and not args.force:
        print(f"⏭️  报告 {token} 已存在，跳过。用 --force 覆盖。")
        return
    if args.force:
        remove_token_from_csv(token)

    if not args.model:
        print("⚠️  未指定 --model（型号），CSV 中型号列将留空。")

    # --- Save ---
    json_path = save_json(data)
    row = extract_row(data, args.model, args.price)
    append_csv(row)

    print(f"✅ 已保存: {token}")
    print(f"   JSON → {json_path}")
    print(f"   CSV  → {CSV_PATH}")
    print(f"   总评: {row['总评']} ({row['总分']}) | 电信: {row['电信评级']} | {row['电信最佳路由']}")


if __name__ == "__main__":
    main()
