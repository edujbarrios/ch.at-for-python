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

## Usage examples

### Browser
Open `http://localhost:8080` — no JavaScript required. Type a question and get a streamed response. History is kept client-side in a hidden form field.

### curl — streaming
```bash
# Stream a response (smooth output, no buffering)
curl -N "localhost:8080/?q=what+is+python"

# Path-based query (hyphens become spaces)
curl -N localhost:8080/explain-async-await-in-python

# POST raw body
curl -N -X POST localhost:8080 -d "what is the GIL?"
```

### curl — JSON response
```bash
curl -H "Accept: application/json" "localhost:8080/?q=hello"
# {"question": "hello", "answer": "..."}
```

### SSE (Server-Sent Events)
```bash
curl -N -H "Accept: text/event-stream" "localhost:8080/?q=hello"
# data: Hello
# data:  there
# data: [DONE]
```

### OpenAI-compatible API
Drop-in replacement for any OpenAI client:
```bash
curl localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4","messages":[{"role":"user","content":"What is RAG?"}]}'
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="none")
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "What is RAG?"}],
)
print(response.choices[0].message.content)
```

### SSH
```bash
ssh localhost -p 2222
# Welcome to ch.at
# Type your message and press Enter.
# Exit: type 'exit', Ctrl+C, or Ctrl+D
# > What is a transformer?
```

### Images (vision models)

Attach a base64-encoded image to any query. The model must support vision (e.g. `gpt-4o`, `claude-3-opus`, `llava`).

**Browser** — a file picker is shown below the text input. Select an image and type your question.

**curl — multipart form upload:**
```bash
curl -N -X POST localhost:8080 \
  -F "q=what is in this image?" \
  -F "img=@/path/to/photo.jpg"
```

**curl — pre-encoded base64:**
```bash
B64=$(base64 -w0 photo.jpg)
curl -N -X POST localhost:8080 \
  -F "q=describe this" \
  -F "img_b64=$B64" \
  -F "img_mime=image/jpeg"
```

**OpenAI-compatible API:**
```bash
curl localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"gpt-4o\",\"messages\":[{\"role\":\"user\",\"content\":\"What is this?\"}],\"image_b64\":\"$(base64 -w0 photo.jpg)\",\"image_mime\":\"image/jpeg\"}"
```

```python
import base64, requests

with open("photo.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

response = requests.post("http://localhost:8080/v1/chat/completions", json={
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Describe this image."}],
    "image_b64": img_b64,
    "image_mime": "image/jpeg",
})
print(response.json()["choices"][0]["message"]["content"])
```

> **Note:** If your configured model does not support vision, the API will return an error message rather than crashing.



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
