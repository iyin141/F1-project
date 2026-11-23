"""Suite-wide guard: tests must never reach the network (FastF1, Jolpica, Hugging Face...).

Any connect to a non-loopback address raises, so a forgotten mock fails loudly and
deterministically instead of passing or failing depending on the machine's network.
"""
import socket

import pytest

_real_connect = socket.socket.connect


def _is_local(addr):
    host = addr[0] if isinstance(addr, tuple) else addr
    return isinstance(host, str) and (host in ("localhost", "::1") or host.startswith("127."))


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def guarded(self, addr):
        if self.family != socket.AF_UNIX and not _is_local(addr):
            raise RuntimeError(f"network access blocked in tests: {addr!r}")
        return _real_connect(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guarded)
