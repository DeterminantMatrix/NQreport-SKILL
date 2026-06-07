---
name: nodequality-report
description: Fetch, decode, and summarize NodeQuality report URLs or tokens. Use when the user gives a nodequality.com/r/... report link, asks to "nq测试", analyze a NodeQuality VPS benchmark, compare VPS network quality, inspect CN2/GIA/9929/CMIN2/163 return routes, or extract hardware/IP/network quality results from a NodeQuality report.
---

# NodeQuality Report

## Workflow

1. Accept either a full `https://nodequality.com/r/<token>` URL or a raw token.
2. Run the bundled parser:

```powershell
python "$env:USERPROFILE\.codex\skills\nodequality-report\scripts\parse_nodequality_report.py" "<url-or-token>"
```

3. Use the script's Markdown output as the factual basis for the response.
4. If the user asks for raw evidence, rerun with `--dump-dir <directory>` and cite the saved log snippets.

## What The Parser Does

The parser reproduces the NodeQuality frontend request flow:

- Extract the report token from the URL.
- Call `https://api.nodequality.com/api/v1/ipinfo` with browser-like `Origin` and `Referer` headers.
- Build `x-dynamic-sign-v` as SHA-1 over `method + url + userAgent + ip+ts + body`, separated by blank lines.
- Fetch `https://api.nodequality.com/api/v1/record/<token>`.
- Decode `data.result` from base64 ZIP.
- Clean ANSI terminal escapes from logs.
- Summarize metadata, hardware, IP quality, streaming/AI unlock, domestic speedtests, international transfer tests, and return routes.

## Response Guidance

Keep conclusions practical:

- Say whether the VPS is suitable for China-facing access, proxy use, streaming/AI unlock, hosting, or mail.
- Separate IPv4 and IPv6 when their routes differ.
- For China routing, call out `CN2GIA`, `CN2`, `9929`, `10099`, `CMIN2`, `163`, and obvious detours.
- Mention weak spots such as mobile-route failures, high retransmits, dirty IP signals, blacklist counts, or small hardware allocation.
- If API fetching fails with 403 or anti-bot behavior, ask the user for browser Copy-as-cURL of the record API request, then parse the response JSON with the same script using `--record-json <file>`.

## Useful Commands

Analyze a public report:

```powershell
python "$env:USERPROFILE\.codex\skills\nodequality-report\scripts\parse_nodequality_report.py" "https://nodequality.com/r/QyZRnH0cVRT7VMb3hNWQrg3E5ZcCUTAs"
```

Save decoded raw logs and the summary:

```powershell
python "$env:USERPROFILE\.codex\skills\nodequality-report\scripts\parse_nodequality_report.py" "<url-or-token>" --dump-dir ".\nodequality-report"
```

Parse an exported API JSON file:

```powershell
python "$env:USERPROFILE\.codex\skills\nodequality-report\scripts\parse_nodequality_report.py" --record-json ".\record.json"
```
