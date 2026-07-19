# USB-Ethernet Adapter Benchmark (iperf3)

A single-file Python script that benchmarks USB → Ethernet adapters with
[iperf3](https://github.com/esnet/iperf) and prints the results both to the
terminal and as a Markdown table ready to paste into a README.

## Why a dedicated script?

On USB adapters the interesting questions are not just "how fast is it":

- **TX and RX are measured separately** with unidirectional runs. Without
  hardware offload, simultaneous full-duplex makes the two directions compete
  for the USB bus and CPU, giving misleading per-direction numbers.
- **CPU usage (client and server) is reported** — on USB adapters the host is
  often the limiting factor, not the adapter itself.
- **UDP reports the *received* throughput**, not the send rate, together with
  jitter and packet loss.
- Per-second min/max is shown for every TCP test to spot instability
  (bus contention, driver issues, thermal throttling).

## Requirements

- Python 3.7+ (no third-party packages)
- iperf3 on the client, either in `PATH` or passed with `--iperf3`
  (on Windows the script also looks in `~/Downloads`, `C:\iperf3` and
  `C:\Program Files\iperf3`)
- an iperf3 server running on the other machine: `iperf3 -s`
- for the optional `--bidir` test: iperf3 ≥ 3.7 on both ends

## Usage

```console
python iperf_benchmark.py <SERVER_IP> [options]
```

| Option | Description |
|--------|-------------|
| `--port N` | server port (default 5201) |
| `--duration N` | duration of the unidirectional TCP tests in seconds (default 60) |
| `--udp-bandwidth B` | target bandwidth of the UDP test (default `1000M`) |
| `--streams N` | number of parallel TCP streams (default 4) |
| `--quick` | short 10 s tests for a quick check |
| `--bidir` | add the simultaneous full-duplex test (extra) |
| `--chip NAME` | adapter description shown in the Markdown table |
| `--iperf3 PATH` | path to the iperf3 executable if not in `PATH` |

Example:

```console
python iperf_benchmark.py 192.168.1.10 --duration 30 --chip "LAN7800T/VSX · USB 3.1 · link 1000/full"
```

## Example results

### iperf3 results (2026-07-19)
**Test host:** Windows 11 · iperf3 · server on a gigabit LAN
**Adapter:** LAN7800T/VSX · USB 3.1 · link 1000/full

| Test | Throughput | Notes |
|------|-----------|-------|
| TCP unidirectional TX | 949 Mbit/s | Retr: n/a, min/max 935/950, CPU client 3% / server 10% |
| TCP unidirectional RX | 948 Mbit/s | min/max 936/950, CPU client 20% / server 6% |
| TCP 4 streams | 949 Mbit/s | Retr: n/a, CPU client 3% / server 13% |
| UDP | 952 Mbit/s | jitter 0.01 ms, loss 0.42% |

> The unidirectional TX/RX tests represent the maximum per direction. The
> simultaneous full-duplex test (if present) shows behavior under concurrent
> load in both directions and must not be read as the hardware limit.

~949 Mbit/s is the theoretical TCP payload limit of Gigabit Ethernet with a
1500-byte MTU: this adapter saturates the link in both directions.

## Reading the numbers

- **TCP unidirectional TX/RX** — the real maximum of each direction.
- **TCP N streams** — aggregate maximum of the link; if it is much higher
  than the single stream, the bottleneck is per-connection, not the adapter.
- **UDP** — link quality: jitter and packet loss at the target rate. Small
  loss at full line rate is expected (the send rate slightly exceeds what the
  link can carry).
- **Simultaneous full-duplex** (`--bidir`) — behavior under concurrent load
  in both directions. On USB adapters the two directions share bus and CPU,
  so these numbers are *not* per-direction maximums.

## License

[MIT](LICENSE)
