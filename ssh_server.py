"""ssh_server.py — Anonymous SSH chat server for ch.at-py.

Mirrors the Go ssh.go behaviour:
  - No client auth (anonymous access)
  - Ephemeral RSA host key generated on each start
  - Max 100 concurrent sessions
  - Per-IP rate limiting via util.rate_limit_allow
  - Line-editing with backspace support and Ctrl+C / Ctrl+D to exit
  - LLM responses streamed token-by-token
"""

import queue
import socket
import threading

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from util import rate_limit_allow

MAX_SESSIONS = 100
_semaphore = threading.Semaphore(MAX_SESSIONS)


# ---------------------------------------------------------------------------
# Host key
# ---------------------------------------------------------------------------

def _generate_host_key() -> paramiko.RSAKey:
    """Generate a fresh ephemeral 2048-bit RSA host key."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    import io
    return paramiko.RSAKey.from_private_key(io.StringIO(pem.decode()))


# ---------------------------------------------------------------------------
# SSH server interface handler
# ---------------------------------------------------------------------------

class _ChatServerInterface(paramiko.ServerInterface):
    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_none(self, username):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "none"

    def check_channel_shell_request(self, channel):
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


# ---------------------------------------------------------------------------
# Session handler
# ---------------------------------------------------------------------------

def _handle_session(channel: paramiko.Channel) -> None:
    def write(s: str) -> None:
        try:
            channel.sendall(s.encode())
        except Exception:
            pass

    write("Welcome to ch.at\r\n")
    write("Type your message and press Enter.\r\n")
    write("Exit: type 'exit', Ctrl+C, or Ctrl+D\r\n")
    write("> ")

    input_buf: list[str] = []
    stop_event = threading.Event()

    try:
        while True:
            try:
                data = channel.recv(1024)
            except Exception:
                break

            if not data:
                break

            for byte in data:
                ch = chr(byte) if isinstance(byte, int) else byte

                if ch == "\x03":  # Ctrl+C
                    write("^C\r\n")
                    return

                if ch in ("\x04",):  # Ctrl+D
                    return

                if ch in ("\r", "\n"):
                    write("\r\n")
                    line = "".join(input_buf).strip()
                    input_buf.clear()

                    if not line:
                        write("> ")
                        continue

                    if line == "exit":
                        return

                    # Stream LLM response
                    from llm import llm
                    q: queue.Queue = queue.Queue()
                    stop_event.clear()
                    threading.Thread(
                        target=llm, args=(line, q, stop_event), daemon=True
                    ).start()

                    while True:
                        chunk = q.get()
                        if chunk is None:
                            break
                        write(chunk)

                    write("\r\n> ")

                elif ch in ("\x7f", "\x08"):  # Backspace / Delete
                    if input_buf:
                        input_buf.pop()
                        write("\b \b")

                else:
                    input_buf.append(ch)
                    write(ch)

    finally:
        stop_event.set()
        channel.close()


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

def _handle_connection(sock: socket.socket, addr, host_key: paramiko.RSAKey) -> None:
    remote = f"{addr[0]}:{addr[1]}"

    if not rate_limit_allow(remote):
        try:
            sock.sendall(b"Rate limit exceeded\r\n")
        except Exception:
            pass
        sock.close()
        return

    transport = paramiko.Transport(sock)
    transport.add_server_key(host_key)
    server_iface = _ChatServerInterface()

    try:
        transport.start_server(server=server_iface)
    except Exception:
        transport.close()
        return

    channel = transport.accept(timeout=20)
    if channel is None:
        transport.close()
        return

    try:
        _handle_session(channel)
    finally:
        transport.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_ssh_server(port: int) -> None:
    """Block forever serving SSH connections on *port*."""
    host_key = _generate_host_key()

    server_sock = socket.socket(socket.AF_INET6 if _has_ipv6() else socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("", port))
    server_sock.listen(128)

    while True:
        try:
            client_sock, addr = server_sock.accept()
        except Exception:
            continue

        if _semaphore.acquire(blocking=False):
            def _run(s, a):
                try:
                    _handle_connection(s, a, host_key)
                finally:
                    _semaphore.release()

            threading.Thread(target=_run, args=(client_sock, addr), daemon=True).start()
        else:
            client_sock.close()  # too many connections


def _has_ipv6() -> bool:
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.close()
        return True
    except OSError:
        return False
