import csv
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT.parent / ".nodequality-cache"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parser = load_module("parse_nodequality_report", "scripts/parse_nodequality_report.py")
save_report = load_module("save_report", "scripts/save_report.py")


def cached_tokens():
    return sorted(p.stem for p in CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []


def test_price_parsing_periods_and_currencies():
    cases = {
        "$5/mo": ("USD", 5.0),
        "$60/year": ("USD", 5.0),
        "29\u5143/\u6708": ("CNY", 4.06),
        "\u20ac4/\u6708": ("EUR", 4.32),
        "HK$30/mo": ("HKD", 3.84),
        "\u5e74\u4ed8\uffe5120": ("CNY", 1.4),
        "CNY 70/year": ("CNY", 0.82),
    }
    for raw, (currency, monthly_usd) in cases.items():
        parsed = parser.parse_price(raw)
        assert parsed["currency"] == currency
        assert parsed["monthly_usd"] == monthly_usd


@pytest.mark.skipif(not cached_tokens(), reason="NodeQuality cache fixtures not present")
def test_cached_reports_schema_and_grades():
    carriers = ["\u7535\u4fe1", "\u8054\u901a", "\u79fb\u52a8"]
    for token in cached_tokens():
        meta, parsed = parser.analyze_one(token, cache_dir=str(CACHE_DIR))
        grades = parser.grade_all(parsed)
        assert "result" not in meta
        assert all(f"route_{carrier}" in grades for carrier in carriers)
        assert all("ip_version" in item for item in parsed["route_matrix"])
        assert all("send_mbps" in item and "receive_mbps" in item for item in parsed["speedtests"])
        assert all("send_mbps" in item and "receive_mbps" in item for item in parsed["international"])


@pytest.mark.skipif(not cached_tokens(), reason="NodeQuality cache fixtures not present")
def test_skip_ipv6_json_output_strips_ipv6():
    token = cached_tokens()[0]
    meta, parsed = parser.analyze_one(token, cache_dir=str(CACHE_DIR))
    grades = parser.grade_all(parsed)
    report = {"meta": meta, "parsed": parsed, "grades": grades}
    output = parser.json.loads(parser.format_json_output([report], skip_ipv6=True))
    assert "ipv6" not in output["ip_quality"]
    assert "ipv6" not in output["grades"]
    assert {item["ip_version"] for item in output["route_matrix"]} == {"ipv4"}


def test_save_report_library_dir(tmp_path):
    save_report.configure_library_dir(tmp_path / "library")
    save_report.ensure_dirs()
    data = {
        "meta": {"token": "tok123", "provider": "vendor", "asn": "123", "location": {"city": "A", "region": "B", "colo": "C"}},
        "hardware": {},
        "ip_quality": {"ipv4": {}},
        "grades": {"overall": {"grade": "B", "score": 60}, "price_info": {"monthly_usd": 5}},
        "speedtests": [],
        "international": [],
    }
    json_path = save_report.save_json(data)
    row = save_report.extract_row(data, "model-a", "$5/mo")
    save_report.append_csv(row)
    assert json_path == tmp_path / "library" / "json" / "tok123.json"
    assert (tmp_path / "library" / "reports.csv").exists()

    save_report.remove_token_from_csv("tok123")
    row["型号"] = "model-b"
    save_report.append_csv(row)
    with open(tmp_path / "library" / "reports.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["型号"] == "model-b"
