from __future__ import annotations

import os
import socket

import uvicorn


def create_dual_stack_socket(port: int) -> socket.socket:
    """Create one listener that accepts both IPv6 and IPv4 connections."""
    listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        listener.bind(("::", port))
        listener.listen(socket.SOMAXCONN)
    except Exception:
        listener.close()
        raise
    return listener


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    listener = create_dual_stack_socket(port)
    config = uvicorn.Config("app.main:app", host="::", port=port, log_level="info")
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
