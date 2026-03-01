from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time

log = logging.getLogger(__name__)

_BASE_PORT = 18080
_STARTUP_TIMEOUT = 10.0
_POLL_INTERVAL = 0.25


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _can_connect(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (OSError, ConnectionRefusedError):
            return False


def _find_available_ports(count: int, base: int = _BASE_PORT) -> list[int]:
    ports: list[int] = []
    port = base
    while len(ports) < count:
        if port > 65535:
            raise RuntimeError(
                f"Could not find {count} available ports (found {len(ports)})"
            )
        if _is_port_available(port):
            ports.append(port)
        port += 1
    return ports


def _wait_for_ports(
    ports: list[int],
    timeout: float = _STARTUP_TIMEOUT,
) -> list[int]:
    """Block until each port is accepting TCP connections. Returns ports that came up."""
    remaining = set(ports)
    ready: list[int] = []
    deadline = time.monotonic() + timeout
    while remaining and time.monotonic() < deadline:
        for port in list(remaining):
            if _can_connect(port):
                remaining.discard(port)
                ready.append(port)
        if remaining:
            time.sleep(_POLL_INTERVAL)
    if remaining:
        log.warning(
            "Proxies on ports %s did not become ready within %.1fs",
            sorted(remaining), timeout,
        )
    return ready


class ProxyManager:
    def __init__(self) -> None:
        self._processes: list[subprocess.Popen] = []
        self._ports: list[int] = []

    @property
    def urls(self) -> list[str]:
        return [f"http://127.0.0.1:{p}" for p in self._ports]

    @property
    def running(self) -> bool:
        return len(self._processes) > 0

    def start(self, count: int) -> list[str]:
        if count <= 0:
            return []

        ports = _find_available_ports(count)
        proc_map: dict[int, subprocess.Popen] = {}

        for port in ports:
            proc = subprocess.Popen(
                [sys.executable, "-m", "proxy", "--port", str(port),
                 "--hostname", "127.0.0.1", "--log-level", "WARNING",
                 "--num-acceptors", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc_map[port] = proc

        ready_ports = _wait_for_ports(ports)

        for port, proc in proc_map.items():
            if port in ready_ports and proc.poll() is None:
                self._processes.append(proc)
                self._ports.append(port)
            else:
                if proc.poll() is None:
                    proc.terminate()
                log.warning("Proxy on port %d failed to start", port)

        if not self._ports:
            log.error("No proxy instances started successfully")
            return []

        urls = self.urls
        os.environ["PROXY_URLS"] = ",".join(urls)
        log.info(
            "Started %d proxy instances on ports %s",
            len(self._ports), self._ports,
        )
        return urls

    def stop(self) -> None:
        if not self._processes:
            return
        for proc in self._processes:
            try:
                proc.terminate()
            except Exception:
                pass
        deadline = time.monotonic() + 5
        for proc in self._processes:
            remaining = max(0, deadline - time.monotonic())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                log.debug("Error stopping proxy pid=%s", proc.pid, exc_info=True)
        self._processes.clear()
        self._ports.clear()
        os.environ.pop("PROXY_URLS", None)
        log.info("All proxy instances stopped")


proxy_manager = ProxyManager()
