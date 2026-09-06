"""Fixed offline Debug decode workload; explicitly NOT serial or bench throughput.

Run: .venv/Scripts/python.exe scripts/benchmark_t10_samples.py --output build/t10-benchmark.json
"""
import argparse
import ctypes
import json
import os
import platform
from pathlib import Path
import struct
import sys
import time
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from power_scope.core.cffi_loader import DebugProtocol
from power_scope.core.debug_service import DebugService, SampleChannel
from power_scope.core.event_bus import EventBus


def rss_bytes():
    if os.name != 'nt':
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform == 'darwin' else value * 1024
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'paged_peak',
            'paged', 'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = ctypes.c_void_p
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not get_info(process(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.working


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='build/t10-benchmark.json')
    args = parser.parse_args()
    app = QApplication([])
    bus = EventBus.instance()
    svc = DebugService(writer=lambda _: None)
    channels = [SampleChannel('counter', 0x20000000, 8, 'uint64_t'),
                SampleChannel('negative', 0x20000008, 8, 'double')]
    svc.register_sample_layout(0, channels, period_us=10000)
    # Identical 32-row batches, 10,000 frames; each 97th frame omitted deliberately.
    raw = b''.join(struct.pack('<Qd', 2**64 - 1 - n, -0.125 * n) for n in range(32))
    frames = [DebugProtocol.build_stream_frame(seq=i+1, timestamp=i*320000,
              list_id=0, sample_count=32, data=raw) for i in range(10000)]
    rss_start = rss_bytes()
    rss_peak = rss_start
    cpu_start, start = time.process_time(), time.perf_counter()
    gaps = 0
    sent = 0
    for i, frame in enumerate(frames):
        if i and i % 97 == 0:
            continue
        svc.feed(frame)
        sent += 1
        if i % 8 == 0:
            gaps += sum('sequence_gap' in b.quality_flags for b in bus.samples.queues['plot'].drain())
        if i % 100 == 0:
            app.processEvents()
            rss_peak = max(rss_peak, rss_bytes())
        # Recorder intentionally never drained: deterministic slow-consumer pressure.
    gaps += sum('sequence_gap' in b.quality_flags for b in bus.samples.queues['plot'].drain())
    elapsed, cpu = time.perf_counter()-start, time.process_time()-cpu_start
    rss_end = rss_bytes()
    rss_peak = max(rss_peak, rss_end)
    result = dict(kind='offline_synthetic_debug_decode', bench_status='BENCH_PENDING',
        platform=platform.platform(), python=sys.version, channels=2, rows_per_frame=32,
        configured_frames=10000, delivered_frames=sent, deliberate_missing_frames=10000-sent,
        raw_dtype=['uint64_t', 'double'], effective_period_us=10000,
        wall_seconds=elapsed, cpu_seconds=cpu, cpu_percent_one_core=100*cpu/elapsed,
        rss_start_bytes=rss_start, rss_end_bytes=rss_end, rss_peak_bytes=rss_peak,
        observed_sequence_gap_blocks=gaps, compatibility_events=bus.data_stats,
        queues={name: dict(budget_bytes=q.budget_bytes, **asdict(q.stats))
                for name, q in bus.samples.queues.items()})
    Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
