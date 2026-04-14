"""dns_server.py — DNS TXT chat server for ch.at-py.

Mirrors the Go dns.go behaviour:
  - Listens on UDP port (default 53)
  - Responds to TXT queries for any name / ch.at. zone
  - Query is taken from the DNS name, hyphens replaced with spaces
  - LLM response truncated to 500 chars, split into 255-byte TXT chunks
  - 4-second hard deadline for LLM responses
  - Per-IP rate limiting via util.rate_limit_allow
"""

import queue
import socket
import struct
import threading
import time

from util import rate_limit_allow

# ---------------------------------------------------------------------------
# Minimal DNS wire-format helpers (no external deps needed)
# ---------------------------------------------------------------------------

DNS_TYPE_TXT   = 16
DNS_CLASS_IN   = 1
DNS_QR_MASK    = 0x8000
DNS_AA_MASK    = 0x0400
DNS_RCODE_MASK = 0x000F


def _parse_name(data: bytes, offset: int) -> tuple[str, int]:
    """Decode a DNS name from *data* starting at *offset*.
    Returns (name_str, new_offset).
    """
    labels: list[str] = []
    visited = set()
    while offset < len(data):
        if offset in visited:
            break
        visited.add(offset)
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:  # pointer
            if offset + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[offset + 1]
            offset += 2
            sub, _ = _parse_name(data, ptr)
            labels.append(sub)
            break
        offset += 1
        labels.append(data[offset: offset + length].decode("ascii", errors="ignore"))
        offset += length
    return ".".join(labels), offset


def _build_txt_response(request_data: bytes, txt_strings: list[str]) -> bytes:
    """Build a minimal DNS TXT response matching the question section."""
    if len(request_data) < 12:
        return b""

    txn_id = request_data[:2]
    flags  = struct.pack(">H", DNS_QR_MASK | DNS_AA_MASK)
    qdcount = request_data[4:6]
    ancount = struct.pack(">H", len(txt_strings) > 0 and 1 or 0)
    nscount = b"\x00\x00"
    arcount = b"\x00\x00"

    # Copy the question section verbatim
    offset = 12
    _, offset = _parse_name(request_data, offset)
    qtype  = request_data[offset: offset + 2]
    qclass = request_data[offset + 2: offset + 4]
    offset += 4
    question_section = request_data[12:offset]

    if not txt_strings:
        header = txn_id + flags + qdcount + struct.pack(">H", 0) + nscount + arcount
        return header + question_section

    # Build single TXT RR with all 255-byte chunks
    rdata = b""
    for s in txt_strings:
        encoded = s.encode("utf-8")
        rdata += bytes([len(encoded)]) + encoded

    # Name pointer back to question name (offset 12)
    name_ptr = b"\xc0\x0c"
    rtype    = struct.pack(">H", DNS_TYPE_TXT)
    rclass   = struct.pack(">H", DNS_CLASS_IN)
    ttl      = struct.pack(">I", 60)
    rdlength = struct.pack(">H", len(rdata))
    answer   = name_ptr + rtype + rclass + ttl + rdlength + rdata

    header = txn_id + flags + qdcount + ancount + nscount + arcount
    return header + question_section + answer


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

def _handle_dns(data: bytes, addr, sock: socket.socket) -> None:
    remote = f"{addr[0]}:{addr[1]}"
    if not rate_limit_allow(remote):
        return

    if len(data) < 12:
        return

    # Parse question section
    offset = 12
    try:
        name_str, offset = _parse_name(data, offset)
    except Exception:
        return

    if offset + 4 > len(data):
        return

    qtype = struct.unpack(">H", data[offset: offset + 2])[0]
    if qtype != DNS_TYPE_TXT:
        # Respond with empty answer so the client doesn't hang
        response = _build_txt_response(data, [])
        try:
            sock.sendto(response, addr)
        except Exception:
            pass
        return

    # Build prompt from DNS name
    name_clean = name_str.rstrip(".")
    if name_clean.endswith(".ch.at"):
        name_clean = name_clean[: -len(".ch.at")]
    prompt = name_clean.replace("-", " ")
    dns_prompt = f"Answer in 500 characters or less, no markdown formatting: {prompt}"

    # Run LLM with 4-second deadline
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    def run_llm():
        from llm import llm
        llm(dns_prompt, q, stop)

    threading.Thread(target=run_llm, daemon=True).start()

    deadline = time.monotonic() + 4.0
    parts: list[str] = []
    total = 0
    timed_out = False

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            stop.set()
            break
        try:
            chunk = q.get(timeout=min(remaining, 0.1))
        except queue.Empty:
            continue
        if chunk is None:
            break
        parts.append(chunk)
        total += len(chunk)
        if total >= 500:
            stop.set()
            break

    response_text = "".join(parts)

    if not response_text:
        response_text = "Request timed out" if timed_out else ""
    elif timed_out and total < 500:
        response_text += "... (incomplete)"

    if len(response_text) > 500:
        response_text = response_text[:497] + "..."

    # Split into ≤255-byte chunks for DNS TXT records.
    # Slice on character boundaries, not byte boundaries, to avoid
    # splitting multi-byte UTF-8 sequences.
    txt_chunks: list[str] = []
    chars = list(response_text)
    i = 0
    while i < len(chars):
        chunk_chars: list[str] = []
        byte_count = 0
        while i < len(chars):
            c_bytes = len(chars[i].encode("utf-8"))
            if byte_count + c_bytes > 255:
                break
            chunk_chars.append(chars[i])
            byte_count += c_bytes
            i += 1
        if chunk_chars:
            txt_chunks.append("".join(chunk_chars))

    response = _build_txt_response(data, txt_chunks)
    try:
        sock.sendto(response, addr)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_dns_server(port: int) -> None:
    """Block forever serving DNS TXT queries on *port* (UDP)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))

    while True:
        try:
            data, addr = sock.recvfrom(512)  # standard DNS max UDP payload
        except Exception:
            continue
        threading.Thread(target=_handle_dns, args=(data, addr, sock), daemon=True).start()
