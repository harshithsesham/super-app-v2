"""Run the daemon listening on both IPv4 and IPv6.

asyncio marks an AF_INET6 listener v6-only, so `uvicorn --host ::` cannot be
reached at 127.0.0.1 (connector CLIs inside a cell) while `--host 0.0.0.0`
cannot be reached over Fly's IPv6 private network (the gateway). Two sockets
cover both.
"""
from __future__ import annotations
import os, socket, sys
import uvicorn


def main():
    port = int(os.environ.get("SUPERAPP_PORT", "18792"))
    log_level = os.environ.get("SUPERAPP_LOG_LEVEL", "info")
    socks = []
    for family, host in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind((host, port))
            s.listen(2048)
            s.set_inheritable(True)
            socks.append(s)
        except OSError as e:
            print(f"serve: not listening on {host}: {e}", file=sys.stderr)
    if not socks:
        sys.exit("serve: could not bind any socket")
    config = uvicorn.Config("superapp.server:app", port=port, log_level=log_level, proxy_headers=True)
    uvicorn.Server(config).run(sockets=socks)


if __name__ == "__main__":
    main()
