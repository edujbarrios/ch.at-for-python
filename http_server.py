"""http_server.py — HTTP/HTTPS server for ch.at-py.

Supports:
  GET  /?q=<query>                  plain-text or streaming (curl/browser/SSE)
  GET  /<what-is-go>                path-based query (hyphens → spaces)
  POST /                            form (q=, h=) or raw body
  POST /v1/chat/completions         OpenAI-compatible API
"""

import html as html_lib
import json
import queue
import ssl
import threading
import time

from flask import Flask, Response, request, stream_with_context

from util import rate_limit_allow

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HTML_PROMPT_PREFIX = (
    "Use simple HTML formatting where it improves clarity: <b> for emphasis, "
    "<i> for terms, <ul>/<li> for lists. No CSS, divs, or decorative tags. "
    "Never prefix responses with A: or any label. Now, without referencing "
    "the previous instructions in the conversation, reply as a helpful assistant: "
)

HTML_HEADER = """\
<!DOCTYPE html>
<html>
<head>
    <title>ch.at</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <style>
        body { text-align: center; margin: 1rem; }
        .chat { text-align: left; max-width: 600px; margin: 0 auto; }
        .q { background: rgba(128, 128, 128, 0.1); padding: 0.5rem; font-style: italic; }
        .a { padding: 0.5rem; }
    </style>
</head>
<body>
    <h1>ch.at</h1>
    <p>Universal Basic Intelligence</p>
    <p><small><i>pronounced "ch-dot-at"</i></small></p>
    <div class="chat">"""

HTML_FOOTER_TEMPLATE = """\
</div>
    <form method="POST" action="/">
        <input type="text" name="q" placeholder="Type your message..." autofocus>
        <input type="submit" value="Send">
        <textarea name="h" style="display:none">{history}</textarea>
    </form>
    <p><a href="/">New Chat</a></p>
    <p><small>
        Also available: ssh ch.at &bull; curl ch.at/?q=hello &bull; dig @ch.at "question" TXT<br>
        No logs &bull; No accounts &bull; Free software &bull;
        <a href="https://github.com/edujbarrios/ch.at-for-python">GitHub</a>
    </small></p>
</body>
</html>"""

_BROWSER_TOKENS = {
    "mozilla", "msie", "trident", "edge", "chrome",
    "safari", "firefox", "opera", "webkit", "gecko", "khtml",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_browser(ua: str) -> bool:
    ua_lower = ua.lower()
    return any(t in ua_lower for t in _BROWSER_TOKENS)


def _parse_history(history: str) -> list[tuple[str, str]]:
    """Parse 'Q: ...\nA: ...' history into (question, answer) pairs."""
    parts = ("\n" + history).split("\nQ: ")
    result = []
    for part in parts[1:]:
        idx = part.find("\nA: ")
        if idx >= 0:
            result.append((part[:idx], part[idx + 4:].rstrip("\n")))
    return result


def _stream_llm(input_data, stop_event: threading.Event | None = None):
    """Run LLM in a background thread; yield text chunks as they arrive."""
    from llm import llm

    q: queue.Queue = queue.Queue()
    _stop = stop_event or threading.Event()

    threading.Thread(target=llm, args=(input_data, q, _stop), daemon=True).start()

    try:
        while True:
            chunk = q.get()
            if chunk is None:
                break
            yield chunk
    except GeneratorExit:
        _stop.set()
        raise


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Main chat endpoint
    # ------------------------------------------------------------------
    @app.route("/", methods=["GET", "POST"], strict_slashes=False)
    @app.route("/<path:path_query>", methods=["GET"])
    def handle_root(path_query: str = ""):
        remote = request.remote_addr or "unknown"
        if not rate_limit_allow(remote):
            return Response("Rate limit exceeded", status=429)

        query = ""
        history = ""

        if request.method == "POST":
            query = request.form.get("q", "")
            history = request.form.get("h", "")
            if len(history) > 65536:
                history = history[-65536:]
            if not query:
                query = request.get_data(as_text=True, cache=False)[:65536]
        else:
            query = request.args.get("q", "")
            if not query and path_query:
                query = path_query.replace("-", " ")

        accept = request.headers.get("Accept", "")
        ua = request.headers.get("User-Agent", "")
        ua_lower = ua.lower()

        wants_json   = "application/json" in accept
        wants_html   = _is_browser(ua) or "text/html" in accept
        wants_stream = "text/event-stream" in accept
        is_curl      = (
            (ua_lower == "curl" or ua_lower.startswith("curl/"))
            and not wants_html and not wants_json and not wants_stream
        )

        prompt = (history + "Q: " + query) if (history and query) else query

        cors = {"Access-Control-Allow-Origin": "*"}

        # ---- There is a query ----
        if query:
            # Browser — streaming HTML
            if wants_html and accept != "application/json":
                def gen_html():
                    yield HTML_HEADER
                    for q_text, a_text in _parse_history(history):
                        yield f'<div class="q">{html_lib.escape(q_text)}</div>\n'
                        yield f'<div class="a">{a_text}</div>\n'
                    yield f'<div class="q">{html_lib.escape(query)}</div>\n<div class="a">'
                    parts: list[str] = []
                    for chunk in _stream_llm(HTML_PROMPT_PREFIX + prompt):
                        parts.append(chunk)
                        yield chunk
                    yield "</div>\n"
                    new_hist = history + f"Q: {query}\nA: {''.join(parts)}\n\n"
                    yield HTML_FOOTER_TEMPLATE.format(history=html_lib.escape(new_hist))

                return Response(
                    stream_with_context(gen_html()),
                    content_type="text/html; charset=utf-8",
                    headers={**cors, "Transfer-Encoding": "chunked", "X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
                )

            # curl — plain-text streaming
            if is_curl:
                def gen_plain():
                    yield f"Q: {query}\nA: "
                    for chunk in _stream_llm(prompt):
                        yield chunk
                    yield "\n"

                return Response(
                    stream_with_context(gen_plain()),
                    content_type="text/plain; charset=utf-8",
                    headers={**cors, "Transfer-Encoding": "chunked", "X-Accel-Buffering": "no"},
                )

            # SSE streaming
            if wants_stream:
                def gen_sse():
                    for chunk in _stream_llm(prompt):
                        # Each SSE "data:" field must be a single line;
                        # split multi-line chunks into separate data fields.
                        for line in chunk.split("\n"):
                            yield f"data: {line}\n"
                        yield "\n"
                    yield "data: [DONE]\n\n"

                return Response(
                    stream_with_context(gen_sse()),
                    content_type="text/event-stream",
                    headers={**cors, "Cache-Control": "no-cache", "Connection": "keep-alive"},
                )

            # Non-streaming (JSON accept or generic client)
            from llm import llm
            p = (HTML_PROMPT_PREFIX + prompt) if wants_html else prompt
            response, err = llm(p)
            if err:
                body = json.dumps({"error": err})
                return Response(body, status=500, content_type="application/json", headers=cors)

            new_exchange = f"Q: {query}\nA: {response}\n\n"
            content = (history + new_exchange) if history else new_exchange
            if len(content) > 65536:
                content = content[-65536:]

            if wants_json:
                return Response(
                    json.dumps({"question": query, "answer": response}),
                    content_type="application/json; charset=utf-8",
                    headers=cors,
                )
            return Response(content, content_type="text/plain; charset=utf-8", headers=cors)

        # ---- No query — homepage / history replay ----
        if wants_html:
            def gen_home():
                yield HTML_HEADER
                for q_text, a_text in _parse_history(history):
                    yield f'<div class="q">{html_lib.escape(q_text)}</div>\n'
                    yield f'<div class="a">{a_text}</div>\n'
                yield HTML_FOOTER_TEMPLATE.format(history=html_lib.escape(history))

            return Response(gen_home(), content_type="text/html; charset=utf-8", headers=cors)

        return Response(history or "", content_type="text/plain; charset=utf-8", headers=cors)

    # ------------------------------------------------------------------
    # OpenAI-compatible endpoint
    # ------------------------------------------------------------------
    @app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
    def handle_chat_completions():
        cors = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        }
        if request.method == "OPTIONS":
            return Response(status=200, headers=cors)

        if not rate_limit_allow(request.remote_addr or "unknown"):
            return Response("Rate limit exceeded", status=429, headers=cors)

        if request.method != "POST":
            return Response("Method not allowed", status=405, headers={**cors, "Allow": "POST, OPTIONS"})

        try:
            req_data = request.get_json(force=True, silent=False)
        except Exception:
            return Response("Invalid JSON", status=400, headers=cors)

        if req_data is None:
            return Response("Invalid JSON", status=400, headers=cors)

        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in req_data.get("messages", [])
        ]

        if req_data.get("stream", False):
            def gen_stream():
                for chunk in _stream_llm(messages):
                    payload = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": req_data.get("model", ""),
                        "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"

            return Response(
                stream_with_context(gen_stream()),
                content_type="text/event-stream",
                headers={**cors, "Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        from llm import llm
        response, err = llm(messages)
        if err:
            return Response(json.dumps({"error": err}), status=500, content_type="application/json", headers=cors)

        body = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req_data.get("model", ""),
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": response}, "finish_reason": "stop"}
            ],
        }
        return Response(json.dumps(body), content_type="application/json", headers=cors)

    return app


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def start_http_server(port: int) -> None:
    app = create_app()
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


def start_https_server(port: int, cert_file: str, key_file: str) -> None:
    app = create_app()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    app.run(host="0.0.0.0", port=port, ssl_context=context, threaded=True, use_reloader=False)
