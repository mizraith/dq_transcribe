#!/usr/bin/env bash
# Read-only probe: which IPv4 addresses can Python find on the tablet (for the coach page link)?
python - <<'PY'
import socket, fcntl, struct
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); print("route trick:", s.getsockname()[0]); s.close()
except OSError as e:
    print("route trick failed:", e)
try:
    names = [n for _, n in socket.if_nameindex()]
    print("interfaces:", names)
    for name in names:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
            print(" ", name, socket.inet_ntoa(packed[20:24]))
        except OSError as e:
            print(" ", name, "no ipv4", e.errno)
except OSError as e:
    print("if_nameindex failed:", e)
PY
ip -4 addr 2>&1 | grep inet | head
