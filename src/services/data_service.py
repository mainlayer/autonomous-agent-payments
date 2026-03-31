"""
DataService — purchases real-time market data from the Mainlayer data marketplace.

Resource ID: market-data-mainlayer
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import AutonomousAgent, PaymentError

logger = logging.getLogger(__name__)

# Stable Mainlayer resource ID for the data feed service
RESOURCE_ID = "market-data-mainlayer"


class DataService:
    """
    Wraps an AutonomousAgent to provide a high-level interface for purchasing
    and consuming market data via Mainlayer.

    Usage
    -----
    ::

        service = DataService(agent)
        data = await service.fetch_latest()
    """

    def __init__(self, agent: AutonomousAgent) -> None:
        self.agent = agent
        self._last_payload: dict[str, Any] | None = None

    async def fetch_latest(self) -> dict[str, Any] | None:
        """
        Pay for and retrieve the latest market data snapshot.

        Returns the data payload on success, or None if the purchase was
        skipped (e.g. insufficient balance) or if the API call failed.
        """
        logger.info("[DataService] Requesting market data purchase…")

        success = await self.agent.spend(
            resource_id=RESOURCE_ID,
            purpose="Real-time market data — price signals for autonomous decision-making",
        )

        if not success:
            logger.warning("[DataService] Purchase not completed — returning cached or None.")
            return self._last_payload

        # After a successful payment Mainlayer makes the resource accessible.
        # In a real integration you would call the vendor's delivery endpoint;
        # here we simulate the retrieved payload structure.
        try:
            raw = await self.agent._get(
                f"/resources/{RESOURCE_ID}/deliver",
                params={"buyer": self.agent.name},
            )
        except PaymentError as exc:
            logger.error("[DataService] Delivery call failed: %s", exc)
            return self._last_payload

        payload: dict[str, Any] = {
            "source": RESOURCE_ID,
            "feed": raw.get("data", {}),
            "timestamp": raw.get("timestamp"),
            "price_paid": self.agent.svc_prices.data_feed,
        }

        self._last_payload = payload
        logger.info("[DataService] Data received: %s", payload)
        return payload

    async def subscribe(self, cycles: int = 5) -> list[dict[str, Any]]:
        """
        Fetch market data *cycles* times, collecting the results.

        Useful for agents that want a short rolling window of price data.
        """
        results: list[dict[str, Any]] = []
        for i in range(cycles):
            logger.info("[DataService] Subscribe cycle %d/%d", i + 1, cycles)
            payload = await self.fetch_latest()
            if payload:
                results.append(payload)
        return results
