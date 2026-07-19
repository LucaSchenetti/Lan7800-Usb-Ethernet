#!/usr/bin/env python3
"""
iperf3-based benchmark suite for USB -> Ethernet adapters.

Runs a series of tests as a client against an iperf3 server and prints
the results to the terminal, including a Markdown table ready for a README.

Methodology notes:
    - The two directions (TX and RX) are measured SEPARATELY with
      unidirectional runs: that is the correct way to find the maximum of
      each direction on a USB->Ethernet adapter (without hardware offload,
      in simultaneous full-duplex the two directions compete for the USB
      bus and CPU and one prevails over the other, giving misleading
      numbers).
    - The simultaneous full-duplex test (--bidir) is available as an
      optional EXTRA, clearly labeled as "simultaneous load" and not as
      a per-direction maximum.
    - CPU usage (client/server) is also reported in the Markdown table:
      on USB adapters the host, not the PCB, is often the limiting factor.

Usage:
    python iperf_benchmark.py <SERVER_IP> [--port 5201] [--duration 60]
                              [--quick] [--bidir] [--iperf3 PATH]

Requirements:
    - iperf3 installed and in PATH (or given with --iperf3)
    - a server listening on the other machine:  iperf3 -s
    - for the optional --bidir test: iperf3 >= 3.7 on both ends
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime

# With stdout redirected/piped, Windows uses the legacy codepage (cp1252)
# and characters like "—" or "·" get garbled: force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MBIT = 1_000_000

IPERF3 = "iperf3"  # set in main() after locating the executable


# --------------------------------------------------------------------------- #
#  Utilities
# --------------------------------------------------------------------------- #
def find_iperf3(user_path=None):
    """Look for iperf3: explicit path, PATH, then common locations."""
    if user_path:
        if shutil.which(user_path):
            return user_path
        sys.exit(f"ERROR: iperf3 not found at '{user_path}'.")
    found = shutil.which("iperf3")
    if found:
        return found
    import glob
    import os
    candidates = []
    for base in (os.path.expanduser("~/Downloads"), "C:\\iperf3",
                 "C:\\Program Files\\iperf3"):
        candidates += glob.glob(os.path.join(base, "**", "iperf3.exe"),
                                recursive=True)
    if candidates:
        return candidates[0]
    sys.exit("ERROR: iperf3 not found. Install it or point to it with "
             "--iperf3 <path\\iperf3.exe>.")


def run_iperf(args, timeout, retries=3):
    """Run iperf3 with JSON output and return the results dict.

    If the server replies "busy" (still tearing down the previous test),
    retry a few times before giving up.
    """
    cmd = [IPERF3, "-J"] + args
    print(f"  command: {' '.join(cmd)}")
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            print("  ERROR: timeout, the test did not finish in time.")
            return None
        except FileNotFoundError:
            print(f"  ERROR: could not run '{IPERF3}'.")
            return None

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            print(f"  ERROR: invalid output.\n{proc.stderr.strip()}")
            return None

        if "error" in data:
            if "busy" in data["error"] and attempt < retries - 1:
                print("  server busy, retrying in 2s...")
                time.sleep(2)
                continue
            print(f"  iperf3 ERROR: {data['error']}")
            return None
        return data
    return None


def mbps(bits_per_second):
    return (bits_per_second or 0) / MBIT


def stability(intervals, key="sum"):
    """Return (min, max) of the per-interval throughput in Mbit/s."""
    rates = []
    for i in intervals:
        s = i.get(key)
        if s and not s.get("omitted", False):
            rates.append(mbps(s["bits_per_second"]))
    if not rates:
        return None, None
    return min(rates), max(rates)


def cpu_string(data):
    """Extract 'client X% / server Y%' from the end section, or '' if absent."""
    cpu = data.get("end", {}).get("cpu_utilization_percent", {})
    if not cpu:
        return ""
    return (f"CPU client {cpu.get('host_total', 0):.0f}% / "
            f"server {cpu.get('remote_total', 0):.0f}%")


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #
def test_tx(host, port, duration, results, step):
    """Unidirectional TCP: client -> server (upload from the host's side)."""
    print(f"\n[{step}] TCP unidirectional TX ({duration}s) — client -> server")
    data = run_iperf(["-c", host, "-p", str(port), "-t", str(duration)],
                     timeout=duration + 30)
    if not data:
        return
    recv = data["end"]["sum_received"]
    lo, hi = stability(data.get("intervals", []))
    retr = data["end"]["sum_sent"].get("retransmits", "n/a")
    cpu = cpu_string(data)
    print(f"  TX throughput: {mbps(recv['bits_per_second']):.1f} Mbit/s")
    print(f"  TCP retransmits: {retr}")
    if lo is not None:
        print(f"  Per-second stability: min {lo:.1f} / max {hi:.1f} Mbit/s")
    if cpu:
        print(f"  {cpu}")
    note = f"Retr: {retr}"
    if lo is not None:
        note += f", min/max {lo:.0f}/{hi:.0f}"
    if cpu:
        note += f", {cpu}"
    results["TCP unidirectional TX"] = (
        f"{mbps(recv['bits_per_second']):.0f} Mbit/s", note)


def test_rx(host, port, duration, results, step):
    """Unidirectional reverse TCP: server -> client (download)."""
    print(f"\n[{step}] TCP unidirectional RX ({duration}s) — server -> client")
    data = run_iperf(["-c", host, "-p", str(port), "-t", str(duration), "-R"],
                     timeout=duration + 30)
    if not data:
        return
    recv = data["end"]["sum_received"]
    lo, hi = stability(data.get("intervals", []))
    cpu = cpu_string(data)
    print(f"  RX throughput: {mbps(recv['bits_per_second']):.1f} Mbit/s")
    if lo is not None:
        print(f"  Per-second stability: min {lo:.1f} / max {hi:.1f} Mbit/s")
    if cpu:
        print(f"  {cpu}")
    note = f"min/max {lo:.0f}/{hi:.0f}" if lo is not None else ""
    if cpu:
        note = f"{note}, {cpu}" if note else cpu
    results["TCP unidirectional RX"] = (
        f"{mbps(recv['bits_per_second']):.0f} Mbit/s", note)


def test_tcp_parallel(host, port, duration, streams, results, step):
    """TCP with N parallel streams: true aggregate maximum of the link."""
    print(f"\n[{step}] TCP {streams} parallel streams ({duration}s)")
    data = run_iperf(["-c", host, "-p", str(port), "-t", str(duration),
                      "-P", str(streams)], timeout=duration + 30)
    if not data:
        return
    recv = data["end"]["sum_received"]
    retr = data["end"]["sum_sent"].get("retransmits", "n/a")
    lo, hi = stability(data.get("intervals", []))
    cpu = cpu_string(data)
    print(f"  Aggregate throughput: {mbps(recv['bits_per_second']):.1f} Mbit/s")
    print(f"  TCP retransmits: {retr}")
    if lo is not None:
        print(f"  Per-second stability: min {lo:.1f} / max {hi:.1f} Mbit/s")
    if cpu:
        print(f"  {cpu}")
    note = f"Retr: {retr}"
    if cpu:
        note += f", {cpu}"
    results[f"TCP {streams} streams"] = (
        f"{mbps(recv['bits_per_second']):.0f} Mbit/s", note)


def test_udp(host, port, duration, bandwidth, results, step):
    """UDP: measures jitter and packet loss (link quality)."""
    print(f"\n[{step}] UDP at {bandwidth} ({duration}s) — jitter and packet loss")
    data = run_iperf(["-c", host, "-p", str(port), "-t", str(duration),
                      "-u", "-b", bandwidth], timeout=duration + 30)
    if not data:
        return
    s = data["end"]["sum"]
    loss = s.get("lost_percent", 0.0)
    jitter = s.get("jitter_ms", 0.0)
    # end.sum reports the bandwidth SENT by the client: with packet loss > 0
    # it overestimates. The bandwidth actually delivered is in
    # end.sum_received.
    recv = data["end"].get("sum_received", s)
    print(f"  Received throughput: {mbps(recv['bits_per_second']):.1f} Mbit/s "
          f"(sent {mbps(s['bits_per_second']):.1f})")
    print(f"  Jitter: {jitter:.3f} ms   Packet loss: {loss:.3f}%")
    results["UDP"] = (
        f"{mbps(recv['bits_per_second']):.0f} Mbit/s",
        f"jitter {jitter:.2f} ms, loss {loss:.2f}%")


def test_bidir(host, port, duration, results, step):
    """
    Simultaneous full-duplex TCP (--bidir). Optional EXTRA.

    CAREFUL when reading the result: on a USB->Ethernet adapter without
    hardware offload, TX and RX share the USB bus and the CPU. Under
    simultaneous load one direction prevails over the other: the lower
    number is NOT the maximum of that direction (for that, see the
    unidirectional tests).

    Robust parsing: bidir reports multiple streams, each with a 'sender'
    flag indicating its role. We sum per role instead of trusting the
    aggregate sum_* fields, which are version-dependent.
    """
    print(f"\n[{step}] TCP simultaneous full-duplex ({duration}s) — EXTRA")
    data = run_iperf(["-c", host, "-p", str(port), "-t", str(duration),
                      "--bidir"], timeout=duration + 30)
    if not data:
        print("  (note: --bidir requires iperf3 >= 3.7 on both ends)")
        return

    tx = rx = 0.0
    streams = data.get("end", {}).get("streams", [])
    for st in streams:
        # In --bidir every stream has a 'sender' and a 'receiver'
        # sub-section. The boolean 'sender' flag inside the section
        # indicates the direction:
        # True  -> stream transmitting from the client (TX)
        # False -> stream received by the client (RX)
        sender_info = st.get("sender", {})
        bps = mbps(sender_info.get("bits_per_second", 0))
        if sender_info.get("sender", False):
            tx += bps
        else:
            rx += bps

    # Fallback if the per-stream structure is not available in this
    # version: use the aggregate totals, less precise but better than zero.
    if tx == 0.0 and rx == 0.0:
        end = data["end"]
        tx = mbps(end.get("sum_sent", {}).get("bits_per_second", 0))
        rx = mbps(end.get("sum_received", {}).get("bits_per_second", 0))
        print("  (note: using aggregate totals, per-stream parsing not "
              "available in this iperf3 version)")

    print(f"  TX {tx:.0f} / RX {rx:.0f} Mbit/s (simultaneous load)")
    results["TCP simultaneous full-duplex"] = (
        f"TX {tx:.0f} / RX {rx:.0f} Mbit/s",
        "simultaneous load: shares USB bus/CPU, NOT the per-direction max "
        "(see unidirectional rows)")


# --------------------------------------------------------------------------- #
#  Output
# --------------------------------------------------------------------------- #
def print_markdown(results, host, chip=None):
    print("\n" + "=" * 64)
    print("Markdown table for the README:\n")
    print(f"### iperf3 results ({datetime.now():%Y-%m-%d})")
    hostline = f"**Test host:** {platform.system()} {platform.release()}"
    hostline += f" · iperf3 · server {host}"
    print(hostline)
    if chip:
        print(f"**Adapter:** {chip}")
    print()
    print("| Test | Throughput | Notes |")
    print("|------|-----------|-------|")
    for name, (value, note) in results.items():
        print(f"| {name} | {value} | {note} |")
    print()
    print("> The unidirectional TX/RX tests represent the maximum per "
          "direction. The simultaneous full-duplex test (if present) shows "
          "behavior under concurrent load in both directions and must not "
          "be read as the hardware limit.")


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="iperf3 benchmark for USB-Ethernet adapters")
    parser.add_argument("server", help="iperf3 server IP")
    parser.add_argument("--port", type=int, default=5201)
    parser.add_argument("--duration", type=int, default=60,
                        help="duration of the unidirectional TCP tests "
                             "(default 60s)")
    parser.add_argument("--udp-bandwidth", default="1000M",
                        help="target bandwidth of the UDP test (default 1000M)")
    parser.add_argument("--streams", type=int, default=4,
                        help="number of parallel streams (default 4)")
    parser.add_argument("--quick", action="store_true",
                        help="short 10s tests for a quick check")
    parser.add_argument("--bidir", action="store_true",
                        help="add the simultaneous full-duplex test (EXTRA); "
                             "requires iperf3 >= 3.7 on both ends")
    parser.add_argument("--chip", default=None,
                        help="adapter chip name for the table "
                             "(e.g. 'LAN7800T/VSX · USB 3.1 · link 1000/full')")
    parser.add_argument("--iperf3", default=None,
                        help="path to the iperf3 executable if not in PATH")
    args = parser.parse_args()

    global IPERF3
    IPERF3 = find_iperf3(args.iperf3)
    print(f"Using iperf3: {IPERF3}")

    long_t = 10 if args.quick else args.duration
    short_t = 10 if args.quick else 30

    print(f"\nUSB-Ethernet benchmark — server {args.server}:{args.port}")
    print(f"Date: {datetime.now():%Y-%m-%d %H:%M}   "
          f"Host: {platform.system()} {platform.release()}")

    # Total number of steps for the [n/tot] numbering
    total = 4 + (1 if args.bidir else 0)
    results = {}
    n = 1

    test_tx(args.server, args.port, long_t, results, f"{n}/{total}"); n += 1
    time.sleep(2)
    test_rx(args.server, args.port, long_t, results, f"{n}/{total}"); n += 1
    time.sleep(2)
    test_tcp_parallel(args.server, args.port, short_t, args.streams,
                      results, f"{n}/{total}"); n += 1
    time.sleep(2)
    test_udp(args.server, args.port, short_t, args.udp_bandwidth,
             results, f"{n}/{total}"); n += 1
    if args.bidir:
        time.sleep(2)
        test_bidir(args.server, args.port, short_t, results, f"{n}/{total}")

    if results:
        print_markdown(results, args.server, args.chip)
    else:
        print("\nNo test completed: check that the server is listening "
              "(iperf3 -s) and reachable.")


if __name__ == "__main__":
    main()
