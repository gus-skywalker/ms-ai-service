from __future__ import annotations

import socket
from unittest.mock import Mock

import pytest

import app.serve as serve


@pytest.mark.skipif(not socket.has_dualstack_ipv6(), reason="dual-stack IPv6 is unavailable")
def test_dual_stack_socket_accepts_ipv4_and_ipv6_connections():
    listener = serve.create_dual_stack_socket(0)
    port = listener.getsockname()[1]

    try:
        assert listener.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0

        with socket.create_connection(("127.0.0.1", port), timeout=1):
            ipv4_connection, _ = listener.accept()
            ipv4_connection.close()

        with socket.create_connection(("::1", port), timeout=1):
            ipv6_connection, _ = listener.accept()
            ipv6_connection.close()
    finally:
        listener.close()


def test_main_passes_the_prebound_socket_to_uvicorn(monkeypatch):
    listener = Mock()
    config = object()
    server = Mock()
    config_factory = Mock(return_value=config)
    server_factory = Mock(return_value=server)

    monkeypatch.setenv("PORT", "8080")
    create_socket = Mock(return_value=listener)
    monkeypatch.setattr(serve, "create_dual_stack_socket", create_socket)
    monkeypatch.setattr(serve.uvicorn, "Config", config_factory)
    monkeypatch.setattr(serve.uvicorn, "Server", server_factory)

    serve.main()

    create_socket.assert_called_once_with(8080)
    config_factory.assert_called_once_with("app.main:app", host="::", port=8080, log_level="info")
    server_factory.assert_called_once_with(config)
    server.run.assert_called_once_with(sockets=[listener])
    listener.close.assert_called_once_with()
