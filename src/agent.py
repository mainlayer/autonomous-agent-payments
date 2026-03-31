"""AutonomousAgent — earns and spends via Mainlayer payment infrastructure.

The agent lifecycle:
  1. Registers a summarization service as a Mainlayer payable resource.
  2. Accepts payments from buyer agents for that service.
  3. Checks its revenue balance periodically.
  4. Autonomously decides which external services to purchase based on budget.
  5. Respects hard budget limits and tiered spending thresholds.

Example:
    agent = AutonomousAgent(name="Summarizer", api_key="ml_...", budget_limit=10.0)
    await agent.setup()
    await agent.run_forever(interval_seconds=60)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import AgentConfig, ServicePrices, config as default_config, prices as default_prices

logger = logging.getLogger(__name__)


@dataclass
class Transaction:
    """Lightweight record of a single earn or spend event."""

    kind: str  # "earn" | "spend"
    amount: float
    description: str
    resource_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True

    def __str__(self) -> str:
        sign = "+" if self.kind == "earn" else "-"
        status = "" if self.success else " [FAILED]"
        return (
            f"[{self.timestamp.strftime('%H:%M:%S')}] "
            f"{sign}${self.amount:.4f} — {self.description}{status}"
        )


class PaymentError(Exception):
    """Raised when a Mainlayer API call fails."""


class AutonomousAgent:
    """A self-managing agent that earns and spends via Mainlayer.

    Earns revenue by selling a service and spends that revenue autonomously
    on external data, research, and storage services based on budget constraints.

    Parameters
    ----------
    name : str
        Human-readable agent identifier shown in logs and dashboards.
    api_key : str
        Mainlayer API key (Bearer token).
    budget_limit : float, default=10.0
        Maximum cumulative spend allowed over the agent's lifetime (USD).
    cfg : AgentConfig, optional
        Full AgentConfig; if not provided, default_config is used.
    svc_prices : ServicePrices, optional
        ServicePrices override; if not provided, default_prices is used.

    Attributes
    ----------
    budget : float
        Current available balance (revenue earned minus spent).
    total_spent : float
        Cumulative amount spent since initialization.
    transactions : list[Transaction]
        Complete ledger of earn/spend events.

    Example
    -------
    >>> agent = AutonomousAgent("Summarizer", api_key="ml_live_...", budget_limit=10.0)
    >>> await agent.setup()  # Register service
    >>> await agent.run_cycle()  # Single cycle: check balance, earn, spend
    >>> await agent.run_forever(interval_seconds=60)  # Run continuously
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        budget_limit: float = 10.0,
        cfg: AgentConfig | None = None,
        svc_prices: ServicePrices | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.budget_limit = budget_limit
        self.cfg = cfg or default_config
        self.svc_prices = svc_prices or default_prices

        # Financial state
        self.budget: float = 0.0          # cumulative revenue earned
        self.total_spent: float = 0.0     # cumulative spend
        self.transactions: list[Transaction] = []

        # Mainlayer resource IDs assigned after setup
        self.own_resource_id: str | None = None

        self._client: httpx.AsyncClient | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.cfg.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=httpx.Timeout(
                    self.cfg.http_timeout,
                    connect=self.cfg.http_connect_timeout,
                ),
            )
        return self._client

    async def close(self) -> None:
        """Cleanly close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _record(self, txn: Transaction) -> None:
        self.transactions.append(txn)
        if txn.kind == "earn" and txn.success:
            self.budget += txn.amount
        elif txn.kind == "spend" and txn.success:
            self.total_spent += txn.amount
            self.budget -= txn.amount
        logger.info(str(txn))

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to Mainlayer and return the parsed JSON response."""
        try:
            resp = await self.client.post(path, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise PaymentError(
                f"Mainlayer {path} returned {exc.response.status_code}: {body}"
            ) from exc
        except httpx.RequestError as exc:
            raise PaymentError(f"Network error calling {path}: {exc}") from exc

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET from Mainlayer and return the parsed JSON response."""
        try:
            resp = await self.client.get(path, params=params or {})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise PaymentError(
                f"Mainlayer {path} returned {exc.response.status_code}: {body}"
            ) from exc
        except httpx.RequestError as exc:
            raise PaymentError(f"Network error calling {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def setup(self) -> str:
        """
        Register this agent's summarization service as a Mainlayer resource.

        Returns the resource_id assigned by Mainlayer.
        """
        logger.info("[%s] Registering service with Mainlayer…", self.name)

        data = await self._post(
            "/resources",
            {
                "name": self.cfg.service_name,
                "description": self.cfg.service_description,
                "price": self.cfg.service_price,
                "currency": "usd",
                "metadata": {
                    "agent": self.name,
                    "version": "1.0",
                    "capabilities": ["summarize", "condense", "tldr"],
                },
            },
        )

        self.own_resource_id = data["resource_id"]
        logger.info(
            "[%s] Service registered — resource_id=%s", self.name, self.own_resource_id
        )
        return self.own_resource_id

    async def earn(self, buyer_wallet: str) -> dict[str, Any]:
        """
        Accept a payment from *buyer_wallet* for this agent's service.

        Parameters
        ----------
        buyer_wallet:
            Wallet address or agent identifier of the paying party.

        Returns the full Mainlayer payment response dict.
        """
        if self.own_resource_id is None:
            raise RuntimeError("Agent not set up — call setup() first.")

        logger.info("[%s] Accepting payment from %s…", self.name, buyer_wallet)

        data = await self._post(
            "/payments",
            {
                "resource_id": self.own_resource_id,
                "buyer": buyer_wallet,
                "amount": self.cfg.service_price,
                "currency": "usd",
                "description": f"Payment for {self.cfg.service_name}",
            },
        )

        txn = Transaction(
            kind="earn",
            amount=data.get("amount", self.cfg.service_price),
            description=f"Service sold to {buyer_wallet}",
            resource_id=self.own_resource_id,
            success=data.get("status") == "completed",
        )
        self._record(txn)
        return data

    async def spend(self, resource_id: str, purpose: str) -> bool:
        """
        Purchase an external service resource if this agent can afford it.

        Parameters
        ----------
        resource_id:
            Mainlayer resource_id of the service to purchase.
        purpose:
            Human-readable description for the audit log.

        Returns True if the purchase succeeded, False if it was skipped.
        """
        price = self.get_price(resource_id)

        # Budget guard — don't overspend
        remaining_budget = self.budget_limit - self.total_spent
        if self.budget < price:
            logger.warning(
                "[%s] Skipping purchase of %s — balance $%.4f < price $%.4f",
                self.name,
                resource_id,
                self.budget,
                price,
            )
            return False

        if remaining_budget < price:
            logger.warning(
                "[%s] Skipping purchase of %s — would exceed lifetime budget limit",
                self.name,
                resource_id,
            )
            return False

        logger.info("[%s] Purchasing %s for %s (price=$%.4f)…", self.name, resource_id, purpose, price)

        try:
            data = await self._post(
                "/payments",
                {
                    "resource_id": resource_id,
                    "buyer": self.name,
                    "amount": price,
                    "currency": "usd",
                    "description": purpose,
                },
            )
            success = data.get("status") == "completed"
        except PaymentError as exc:
            logger.error("[%s] Purchase of %s failed: %s", self.name, resource_id, exc)
            success = False

        txn = Transaction(
            kind="spend",
            amount=price,
            description=purpose,
            resource_id=resource_id,
            success=success,
        )
        self._record(txn)
        return success

    def get_price(self, resource_id: str) -> float:
        """
        Return the known price for a resource_id.

        Falls back to a small default if the resource is unknown.
        """
        price_map: dict[str, float] = {
            "market-data-mainlayer": self.svc_prices.data_feed,
            "research-reports-mainlayer": self.svc_prices.research_report,
            "storage-mainlayer": self.svc_prices.storage_slot,
        }
        return price_map.get(resource_id, 0.01)

    async def check_balance(self) -> float:
        """
        Query Mainlayer analytics to get current revenue for this agent.

        Updates self.budget and returns the queried value.
        """
        if self.own_resource_id is None:
            raise RuntimeError("Agent not set up — call setup() first.")

        logger.info("[%s] Checking balance via analytics…", self.name)

        data = await self._get(
            "/analytics/revenue",
            params={"resource_id": self.own_resource_id},
        )

        revenue: float = data.get("total_revenue", self.budget)
        self.budget = revenue
        logger.info("[%s] Balance = $%.4f", self.name, self.budget)
        return revenue

    def net_profit(self) -> float:
        """Return revenue minus total spend."""
        return self.budget

    def summary(self) -> dict[str, Any]:
        """Return a snapshot of the agent's financial state."""
        earns = [t for t in self.transactions if t.kind == "earn" and t.success]
        spends = [t for t in self.transactions if t.kind == "spend" and t.success]
        return {
            "agent": self.name,
            "balance": round(self.budget, 6),
            "total_earned": round(sum(t.amount for t in earns), 6),
            "total_spent": round(self.total_spent, 6),
            "net_profit": round(self.net_profit(), 6),
            "transaction_count": len(self.transactions),
            "earn_count": len(earns),
            "spend_count": len(spends),
        }

    # ------------------------------------------------------------------
    # Autonomous decision logic
    # ------------------------------------------------------------------

    async def _decide_and_spend(self) -> None:
        """
        Evaluate balance and decide which services to purchase this cycle.

        Strategy:
          - Always buy cheap data feeds when above min balance.
          - Buy research reports when comfortably funded (>= 3× their price).
          - Buy storage when there is budget headroom.
        """
        min_bal = self.cfg.min_balance_to_spend

        if self.budget < min_bal:
            logger.info("[%s] Balance $%.4f below threshold — skipping purchases.", self.name, self.budget)
            return

        # Tier 1 — cheap data feed
        if self.budget >= self.svc_prices.data_feed:
            await self.spend("market-data-mainlayer", "Real-time market data for strategy updates")

        # Tier 2 — research report (only when comfortable)
        if self.budget >= self.svc_prices.research_report * 3:
            await self.spend("research-reports-mainlayer", "Research report to improve summarization quality")

        # Tier 3 — persistent storage
        if self.budget >= self.svc_prices.storage_slot:
            await self.spend("storage-mainlayer", "Persistent storage for cached summaries")

    async def run_cycle(self) -> dict[str, Any]:
        """
        Execute one autonomous cycle:
          1. Check current balance.
          2. Decide which services to purchase.

        Returns the summary snapshot after the cycle.
        """
        logger.info("[%s] --- Cycle start ---", self.name)

        try:
            await self.check_balance()
        except PaymentError as exc:
            logger.warning("[%s] Could not refresh balance: %s", self.name, exc)

        await self._decide_and_spend()

        snap = self.summary()
        logger.info("[%s] --- Cycle end: %s ---", self.name, snap)
        return snap

    async def run_forever(self, interval_seconds: int | None = None) -> None:
        """
        Run the agent autonomously, cycling every *interval_seconds*.

        This coroutine runs until cancelled.
        """
        interval = interval_seconds or self.cfg.cycle_interval_seconds
        self._running = True
        logger.info("[%s] Starting autonomous loop (interval=%ds)…", self.name, interval)

        try:
            while self._running:
                await self.run_cycle()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[%s] Loop cancelled — shutting down.", self.name)
        finally:
            self._running = False
            await self.close()

    def stop(self) -> None:
        """Signal the agent to stop after the current cycle."""
        self._running = False
