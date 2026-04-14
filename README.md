# ch.at for Python

Unofficial Python port of [ch.at](https://github.com/Deep-ai-inc/ch.at) — a multi-protocol LLM chat service accessible over HTTP, SSH, DNS, and an OpenAI-compatible API.

> [!WARNING]
> **Not an official release.** For production, use the original Go binary. This port exists for AI/ML engineering work: integrating with Python-native tooling, iterating on prompts at runtime, and embedding the service into larger pipelines — without a compile step.

## Acknowledgements

All credit for the original design goes to the [ch.at team at Deep AI Inc.](https://github.com/Deep-ai-inc/ch.at) — the Go implementation is the real work. If you find this useful, please star the original repository.

## Features

Same protocol surface as the original:

| Interface | How to use |
|-----------|-----------|
| Browser | `http://localhost:8080` |
| curl (streaming) | `curl -N localhost:8080/?q=hello` |
| curl (path-based) | `curl localhost:8080/what-is-python` |
| SSE | `curl -H "Accept: text/event-stream" localhost:8080/?q=hello` |
| OpenAI-compatible API | `POST /v1/chat/completions` |
| SSH | `ssh localhost -p 2222` |
| DNS TXT | `dig @localhost "what-is-2+2" TXT` |

## Quick start

```bash
# Clone the repository
git clone https://github.com/edujbarrios/ch.at-for-python.git
cd ch.at-for-python

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Configure your LLM provider
cp llm.py.example llm.py
# Edit llm.py and set your API_KEY

# Run (HTTP on 8080, SSH on 2222 by default)
python chat.py
```

## Configuration

Edit the constants at the top of `chat.py`:

```python
HTTP_PORT  = 8080   # set to 0 to disable
HTTPS_PORT = 0      # needs cert.pem / key.pem
SSH_PORT   = 2222   # set to 0 to disable
DNS_PORT   = 0      # needs port 53 / root privileges
```

LLM providers are configured in `llm.py` (copied from `llm.py.example`). Supports OpenAI, Anthropic Claude, and any OpenAI-compatible endpoint (Ollama, llama.cpp, etc.).

## Project structure

```
chat.py          # entry point and port configuration
llm.py.example   # LLM provider config — copy to llm.py and add your key
util.py          # per-IP token-bucket rate limiter
http_server.py   # HTTP/HTTPS server (Flask)
ssh_server.py    # SSH server (Paramiko)
dns_server.py    # DNS TXT server (stdlib only)
selftest/        # integration tests
pyproject.toml   # package definition
```

## Testing

```bash
# Run the server first, then:
python selftest/main.py http://localhost:8080

# Or with pytest
pytest selftest/ -v
```

## Privacy

Same guarantees as the original: no authentication, no server-side storage, no logs.

**Warning:** queries are sent to upstream LLM providers (OpenAI, Anthropic, etc.) who may log them. Never send passwords, API keys, or sensitive information.

## Author

Eduardo J. Barrios — [edujbarrios@outlook.com](mailto:edujbarrios@outlook.com)

Python port of the original [ch.at](https://github.com/Deep-ai-inc/ch.at) by Deep AI Inc., licensed under MIT.
