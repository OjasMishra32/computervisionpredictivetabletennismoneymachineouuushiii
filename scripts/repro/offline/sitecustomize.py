"""Loaded by every Python process of a snapshot reproduction (reproduce.sh puts this directory on PYTHONPATH).

With COURTSIDE_OFFLINE=1, any connection to a non-local address raises OSError: a reproduction of the submitted
snapshot reads only the verified inputs on disk and never refetches mutable public APIs (Polymarket listings,
factor files). Local connections (127.0.0.1, ::1, Unix sockets) still work. Tectonic is a separate binary and is not
affected (it may fetch its LaTeX support bundle on first use).
"""
import os

if os.environ.get("COURTSIDE_OFFLINE") == "1":
    import socket

    _LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
    _connect, _connect_ex, _getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def _host(address):
        return address[0] if isinstance(address, tuple) and address else None

    def _refuse(host):
        raise OSError(f"COURTSIDE_OFFLINE=1: network access to {host!r} refused (snapshot reproduction reads only "
                      "the verified local inputs; use `bash run.sh fresh-fetch` or `bash run.sh data` to fetch)")

    def connect(self, address):
        h = _host(address)
        if self.family in (socket.AF_INET, socket.AF_INET6) and h not in _LOCAL:
            _refuse(h)
        return _connect(self, address)

    def connect_ex(self, address):
        h = _host(address)
        if self.family in (socket.AF_INET, socket.AF_INET6) and h not in _LOCAL:
            _refuse(h)
        return _connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if isinstance(host, bytes):
            host = host.decode()
        if host not in _LOCAL and host is not None:
            _refuse(host)
        return _getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
