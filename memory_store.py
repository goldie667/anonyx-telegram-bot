"""Small single-process Redis-compatible store for the HOKAS Free deployment.

Queue/chat/FSM state is ephemeral and is cleared when the process restarts.
Do not run multiple bot replicas with this adapter.
"""
import asyncio
import time
from contextlib import asynccontextmanager

class MemoryStore:
    def __init__(self):
        self.hashes = {}
        self.values = {}
        self.sorted_sets = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, _name, timeout=10, blocking_timeout=5):
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=blocking_timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Matching lock timeout") from exc
        try:
            yield
        finally:
            self._lock.release()

    async def get(self, key):
        item = self.values.get(key)
        if item and item[1] and item[1] < time.monotonic():
            self.values.pop(key, None)
            return None
        return item[0] if item else None

    async def set(self, key, value, ex=None):
        expiry = time.monotonic() + ex if ex else None
        self.values[key] = (value, expiry)

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    async def hset(self, name, key=None, value=None, mapping=None):
        target = self.hashes.setdefault(name, {})
        values = mapping if mapping is not None else {key: value}
        added = 0
        for k, v in values.items():
            k, v = str(k), str(v)
            added += int(k not in target)
            target[k] = v.encode()
        return added

    async def hdel(self, name, *keys):
        target = self.hashes.setdefault(name, {})
        count = 0
        for key in keys:
            count += int(target.pop(str(key), None) is not None)
        return count

    async def hkeys(self, name):
        return [k.encode() for k in self.hashes.get(name, {})]

    async def zadd(self, name, mapping):
        target = self.sorted_sets.setdefault(name, {})
        added = 0
        for member, score in mapping.items():
            member = str(member)
            added += int(member not in target)
            target[member] = float(score)
        return added

    async def zrem(self, name, *members):
        target = self.sorted_sets.setdefault(name, {})
        count = 0
        for member in members:
            count += int(target.pop(str(member), None) is not None)
        return count

    async def zrange(self, name, start, end):
        items = sorted(self.sorted_sets.get(name, {}).items(), key=lambda x: (x[1], x[0]))
        if end == -1:
            selected = items[start:]
        else:
            selected = items[start:end + 1]
        return [member.encode() for member, _ in selected]

    async def zcard(self, name):
        return len(self.sorted_sets.get(name, {}))

    async def close(self):
        return None
