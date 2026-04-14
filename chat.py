"""chat.py — Entry point for ch.at-py.

Configuration: edit the constants below and copy llm.py.example to llm.py.
To disable a service set its port to 0.
"""

import sys
import threading

# ---------------------------------------------------------------------------
# Configuration — edit here (mirrors chat.go constants)
# ---------------------------------------------------------------------------

HTTP_PORT  = 8080   # Web interface         (set to 0 to disable)
HTTPS_PORT = 0      # TLS web interface     (set to 0 to disable; needs cert.pem/key.pem)
SSH_PORT   = 2222   # Anonymous SSH chat    (set to 0 to disable)
DNS_PORT   = 0      # DNS TXT chat          (set to 0 to disable; needs port 53 / root)

HTTPS_CERT = "cert.pem"
HTTPS_KEY  = "key.pem"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Verify llm.py exists before binding any ports
    try:
        import llm  # noqa: F401
    except ImportError:
        print("ERROR: llm.py not found.")
        print("Copy llm.py.example to llm.py and add your API key, then try again.")
        sys.exit(1)

    threads: list[threading.Thread] = []

    if SSH_PORT > 0:
        from ssh_server import start_ssh_server
        t = threading.Thread(target=start_ssh_server, args=(SSH_PORT,), daemon=True, name="ssh")
        t.start()
        threads.append(t)
        print(f"SSH  server listening on port {SSH_PORT}")

    if DNS_PORT > 0:
        from dns_server import start_dns_server
        t = threading.Thread(target=start_dns_server, args=(DNS_PORT,), daemon=True, name="dns")
        t.start()
        threads.append(t)
        print(f"DNS  server listening on port {DNS_PORT}")

    if HTTPS_PORT > 0:
        from http_server import start_https_server
        t = threading.Thread(
            target=start_https_server,
            args=(HTTPS_PORT, HTTPS_CERT, HTTPS_KEY),
            daemon=True,
            name="https",
        )
        t.start()
        threads.append(t)
        print(f"HTTPS server listening on port {HTTPS_PORT}")

    if HTTP_PORT > 0:
        from http_server import start_http_server
        print(f"HTTP server listening on port {HTTP_PORT}")
        # Run in the main thread so the process stays alive
        start_http_server(HTTP_PORT)
    elif threads:
        # Keep process alive if only background servers are running
        for t in threads:
            t.join()
    else:
        print("No servers enabled. Set at least one port > 0 in chat.py.")
        sys.exit(1)


if __name__ == "__main__":
    main()
