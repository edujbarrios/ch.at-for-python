"""selftest — Integration tests for ch.at-py.

Usage:
    python -m pytest selftest/ -v
    python selftest/main.py http://localhost:8080
"""

import json
import sys
import urllib.request
import urllib.error
import urllib.parse


PASS_PROMPT = "Reply with just the single word: pass"


def _extract_response(body: str, content_type: str) -> str:
    body = body.strip()
    if "error" in body.lower():
        return ""
    if "application/json" in content_type:
        try:
            data = json.loads(body)
            return (data.get("answer") or "").strip()
        except Exception:
            return ""
    if "\nA: " in body:
        for line in body.splitlines():
            if line.startswith("A: "):
                return line[3:].strip()
    return body


def _check(label: str, url: str, *, method="GET", data=None, headers=None,
           passed: list, failed: list) -> None:
    print(f"  {label} ... ", end="", flush=True)
    try:
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            ct = resp.headers.get("Content-Type", "")
            answer = _extract_response(body, ct)
            if answer == "pass":
                print("✓")
                passed.append(label)
            else:
                preview = answer[:50] + "..." if len(answer) > 50 else (answer or "empty/error")
                print(f"✗  (got: {preview!r})")
                failed.append(label)
    except Exception as exc:
        print(f"✗  ({exc})")
        failed.append(label)


def run(base_url: str) -> int:
    base = base_url.rstrip("/")
    passed: list = []
    failed: list = []

    print(f"\nRunning self-tests against {base}\n")

    # GET /?q=
    _check(
        "GET  /?q=...",
        f"{base}/?q={urllib.parse.quote(PASS_PROMPT)}",
        passed=passed, failed=failed,
    )

    # GET /path-based
    _check(
        "GET  /path-based",
        f"{base}/{urllib.parse.quote(PASS_PROMPT.replace(' ', '-'))}",
        passed=passed, failed=failed,
    )

    # POST / form
    form_data = urllib.parse.urlencode({"q": PASS_PROMPT}).encode()
    _check(
        "POST / form",
        f"{base}/",
        method="POST",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        passed=passed, failed=failed,
    )

    # POST / raw body
    _check(
        "POST / raw body",
        f"{base}/",
        method="POST",
        data=PASS_PROMPT.encode(),
        headers={"Content-Type": "text/plain"},
        passed=passed, failed=failed,
    )

    # POST /v1/chat/completions
    api_body = json.dumps({
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": PASS_PROMPT}],
    }).encode()
    _check(
        "POST /v1/chat/completions",
        f"{base}/v1/chat/completions",
        method="POST",
        data=api_body,
        headers={"Content-Type": "application/json"},
        passed=passed, failed=failed,
    )

    total = len(passed) + len(failed)
    print(f"\n{len(passed)}/{total} tests passed")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    return 0 if not failed else 1


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python selftest/main.py <base-url>")
        print("Example: python selftest/main.py http://localhost:8080")
        sys.exit(1)
    sys.exit(run(sys.argv[1]))


if __name__ == "__main__":
    main()
