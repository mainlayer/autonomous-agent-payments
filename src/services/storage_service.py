"""
StorageService — purchases persistent storage slots from Mainlayer.

Resource ID: storage-mainlayer

The agent uses paid storage to persist cached summaries and intermediate
state across restarts, avoiding redundant recomputation.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import AutonomousAgent, PaymentError

logger = logging.getLogger(__name__)

RESOURCE_ID = "storage-mainlayer"


class StorageSlot:
    """A purchased storage slot with read/write access."""

    def __init__(self, slot_id: str, capacity_bytes: int, price_paid: float) -> None:
        self.slot_id = slot_id
        self.capacity_bytes = capacity_bytes
        self.price_paid = price_paid
        self._local_store: dict[str, Any] = {}

    def write(self, key: str, value: Any) -> None:
        """Write a value to the slot's local in-memory store."""
        self._local_store[key] = value
        logger.debug("[StorageSlot %s] write key=%r", self.slot_id, key)

    def read(self, key: str, default: Any = None) -> Any:
        """Read a value from the slot, returning *default* if not present."""
        return self._local_store.get(key, default)

    def keys(self) -> list[str]:
        return list(self._local_store.keys())

    def __repr__(self) -> str:
        return (
            f"<StorageSlot id={self.slot_id!r} "
            f"capacity={self.capacity_bytes}B keys={len(self._local_store)}>"
        )


class StorageService:
    """
    Wraps an AutonomousAgent to purchase and manage Mainlayer storage slots.

    Storage is the cheapest external service — the agent buys slots whenever
    it has headroom in its balance to persist summarization cache.

    Usage
    -----
    ::

        svc = StorageService(agent)
        slot = await svc.acquire_slot()
        if slot:
            slot.write("summary_abc", "The quick brown fox…")
    """

    def __init__(self, agent: AutonomousAgent) -> None:
        self.agent = agent
        self._slots: list[StorageSlot] = []

    async def acquire_slot(self) -> StorageSlot | None:
        """
        Purchase a single storage slot from Mainlayer.

        Returns a StorageSlot on success, or None if the purchase was skipped
        or delivery failed.
        """
        logger.info("[StorageService] Acquiring storage slot…")

        success = await self.agent.spend(
            resource_id=RESOURCE_ID,
            purpose="Persistent storage slot — cached summaries and agent state",
        )

        if not success:
            logger.warning("[StorageService] Storage purchase not completed.")
            return None

        try:
            raw = await self.agent._get(
                f"/resources/{RESOURCE_ID}/deliver",
                params={"buyer": self.agent.name},
            )
        except PaymentError as exc:
            logger.error("[StorageService] Delivery failed: %s", exc)
            return None

        slot_data: dict[str, Any] = raw.get("data", {})
        slot = StorageSlot(
            slot_id=slot_data.get("slot_id", f"slot-{len(self._slots) + 1}"),
            capacity_bytes=int(slot_data.get("capacity_bytes", 1_048_576)),  # 1 MiB default
            price_paid=self.agent.svc_prices.storage_slot,
        )
        self._slots.append(slot)
        logger.info("[StorageService] Slot acquired: %r", slot)
        return slot

    async def ensure_slot(self) -> StorageSlot | None:
        """
        Return an existing slot if available, otherwise purchase a new one.

        Prevents repeated slot purchases within the same session.
        """
        if self._slots:
            return self._slots[0]
        return await self.acquire_slot()

    def total_capacity(self) -> int:
        """Return combined capacity in bytes across all acquired slots."""
        return sum(s.capacity_bytes for s in self._slots)

    def slot_count(self) -> int:
        return len(self._slots)
