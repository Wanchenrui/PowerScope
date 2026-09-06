"""Independent byte-budgeted sample consumers. No Qt event per sample."""
from collections import deque
from dataclasses import dataclass, replace
from threading import RLock

from .contracts import Quality, SampleBlock


@dataclass
class QueueStats:
    queued_bytes: int = 0
    peak_bytes: int = 0
    accepted_blocks: int = 0
    dropped_blocks: int = 0
    dropped_samples: int = 0
    overflow_events: int = 0
    invalidated_blocks: int = 0
    device_overflows: int = 0


def block_bytes(block: SampleBlock) -> int:
    # Conservative accounting includes Python metadata, not only payload.
    return len(block.raw_data) + 512 + sum(
        256 + 4 * len(c.alias + c.symbol + (c.dtype or '') + (c.unit or ''))
        for c in block.channels)


def stream_key(block):
    return (block.epoch, block.layout_generation, block.list_id, block.capture_id,
            tuple(c.alias for c in block.channels))


class SampleQueue:
    def __init__(self, budget_bytes: int):
        if budget_bytes <= 0:
            raise ValueError('budget_bytes must be positive')
        self.budget_bytes = budget_bytes
        self.stats = QueueStats()
        self._items = deque()
        self._lock = RLock()
        self._gaps = {}
        self._future_gaps = {}

    def push(self, block: SampleBlock) -> None:
        size = block_bytes(block)
        with self._lock:
            self.stats.device_overflows += block.overflow_count or 0
            if size > self.budget_bytes:
                self._drop(block, future=True)
                return
            future_gap = self._future_gaps.pop(stream_key(block), None)
            if future_gap is not None:
                block = self._mark_loss(block, future_gap)
            while self.stats.queued_bytes + size > self.budget_bytes:
                old, old_size = self._items.popleft()
                self.stats.queued_bytes -= old_size
                self._drop(old)
            self._items.append((block, size))
            self.stats.queued_bytes += size
            self.stats.peak_bytes = max(self.stats.peak_bytes, self.stats.queued_bytes)
            self.stats.accepted_blocks += 1

    def _drop(self, block, future=False):
        self.stats.dropped_blocks += 1
        self.stats.dropped_samples += block.sample_count
        self.stats.overflow_events += 1
        key = stream_key(block)
        gaps = self._future_gaps if future else self._gaps
        count, device_missing, unknown = gaps.get(key, (0, 0, False))
        if block.missing_samples is not None:
            device_missing += max(0, block.missing_samples - block.consumer_dropped_samples)
        else:
            unknown = True
        gaps[key] = (count + block.sample_count + block.consumer_dropped_samples,
                     device_missing, unknown)

    @staticmethod
    def _mark_loss(block, loss):
        gap, device_missing, unknown = loss
        quality = block.quality
        if quality in (Quality.VALID, Quality.GAP):
            quality = Quality.GAP
        missing = block.missing_samples
        flags = block.quality_flags | {'consumer_drop'}
        if unknown:
            missing = None
        elif missing is not None:
            missing += gap + device_missing
        return replace(block, quality=quality, missing_samples=missing,
                       consumer_dropped_samples=block.consumer_dropped_samples + gap,
                       quality_flags=flags)

    def drain(self, max_blocks: int = 64) -> list[SampleBlock]:
        result = []
        with self._lock:
            for _ in range(max_blocks):
                if not self._items:
                    break
                block, size = self._items.popleft()
                self.stats.queued_bytes -= size
                gap = self._gaps.pop(stream_key(block), None)
                if gap is not None:
                    block = self._mark_loss(block, gap)
                result.append(block)
        return result

    def invalidate(self, list_id=None):
        with self._lock:
            kept = deque()
            for block, size in self._items:
                if list_id is None or block.list_id == list_id:
                    self.stats.invalidated_blocks += 1
                    self.stats.queued_bytes -= size
                else:
                    kept.append((block, size))
            self._items = kept
            self._gaps = {k: v for k, v in self._gaps.items()
                          if list_id is not None and k[2] != list_id}
            self._future_gaps = {k: v for k, v in self._future_gaps.items()
                                 if list_id is not None and k[2] != list_id}

    def invalidate_wave(self):
        with self._lock:
            kept = deque()
            for block, size in self._items:
                if block.capture_id is not None:
                    self.stats.invalidated_blocks += 1
                    self.stats.queued_bytes -= size
                else:
                    kept.append((block, size))
            self._items = kept
            self._gaps = {k: v for k, v in self._gaps.items() if k[3] is None}
            self._future_gaps = {k: v for k, v in self._future_gaps.items() if k[3] is None}


class SampleHub:
    """Each named subscriber owns its queue and loss counters; drop oldest."""
    def __init__(self):
        self._lock = RLock()
        self.queues = {}
        self.subscribe('plot', 2 * 1024 * 1024)
        self.subscribe('recorder', 8 * 1024 * 1024)

    def subscribe(self, name: str, budget_bytes: int = 2 * 1024 * 1024):
        with self._lock:
            if name not in self.queues:
                self.queues[name] = SampleQueue(budget_bytes)
            return self.queues[name]

    def unsubscribe(self, name):
        with self._lock:
            self.queues.pop(name, None)

    def publish(self, block):
        with self._lock:
            for queue in self.queues.values():
                queue.push(block)

    def invalidate(self, list_id=None):
        with self._lock:
            for queue in self.queues.values():
                queue.invalidate(list_id)
