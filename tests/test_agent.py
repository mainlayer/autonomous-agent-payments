"""
test_agent.py — 25+ tests for AutonomousAgent using mocked HTTP.

Tests cover:
  - setup() / service registration
  - earn() success and failure paths
  - spend() with budget guard
  - check_balance() analytics query
  - get_price() lookup
  - run_cycle() integration
  - transaction recording
  - summary() snapshot
  - HTTP error propagation
  - agent state after multiple cycles
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.agent import AutonomousAgent, PaymentError, Transaction
from src.config import AgentConfig, ServicePrices


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_agent(budget_limit: float = 10.0) -> AutonomousAgent:
    cfg = AgentConfig(
        name="TestAgent",
        api_key="test-key-123",
        base_url="https://api.mainlayer.fr",
        budget_limit=budget_limit,
        min_balance_to_spend=0.50,
        http_timeout=5.0,
        http_connect_timeout=2.0,
    )
    prices = ServicePrices(data_feed=0.02, research_report=0.10, storage_slot=0.01)
    agent = AutonomousAgent(
        name="TestAgent",
        api_key="test-key-123",
        budget_limit=budget_limit,
        cfg=cfg,
        svc_prices=prices,
    )
    # Pre-set resource_id to avoid setup() dependency in most tests
    agent.own_resource_id = "resource-abc-123"
    return agent


def mock_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# setup() tests
# ---------------------------------------------------------------------------

class TestSetup:
    @pytest.mark.asyncio
    async def test_setup_registers_service(self):
        agent = make_agent()
        agent.own_resource_id = None  # reset

        post_resp = mock_response({"resource_id": "new-resource-999", "status": "active"})

        with patch.object(agent, "_post", new=AsyncMock(return_value={"resource_id": "new-resource-999"})):
            resource_id = await agent.setup()

        assert resource_id == "new-resource-999"
        assert agent.own_resource_id == "new-resource-999"

    @pytest.mark.asyncio
    async def test_setup_propagates_payment_error(self):
        agent = make_agent()
        agent.own_resource_id = None

        with patch.object(agent, "_post", new=AsyncMock(side_effect=PaymentError("503 error"))):
            with pytest.raises(PaymentError, match="503 error"):
                await agent.setup()

    @pytest.mark.asyncio
    async def test_setup_payload_includes_price(self):
        agent = make_agent()
        agent.own_resource_id = None
        captured = {}

        async def capture_post(path, payload):
            captured.update(payload)
            return {"resource_id": "r-001"}

        with patch.object(agent, "_post", new=AsyncMock(side_effect=capture_post)):
            await agent.setup()

        assert captured["price"] == agent.cfg.service_price
        assert captured["currency"] == "usd"


# ---------------------------------------------------------------------------
# earn() tests
# ---------------------------------------------------------------------------

class TestEarn:
    @pytest.mark.asyncio
    async def test_earn_updates_budget(self):
        agent = make_agent()
        earn_data = {"status": "completed", "amount": 0.05}

        with patch.object(agent, "_post", new=AsyncMock(return_value=earn_data)):
            await agent.earn("buyer-wallet-x")

        assert agent.budget == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_earn_records_transaction(self):
        agent = make_agent()
        earn_data = {"status": "completed", "amount": 0.05}

        with patch.object(agent, "_post", new=AsyncMock(return_value=earn_data)):
            await agent.earn("buyer-wallet-x")

        assert len(agent.transactions) == 1
        txn = agent.transactions[0]
        assert txn.kind == "earn"
        assert txn.success is True
        assert txn.amount == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_earn_multiple_times_accumulates(self):
        agent = make_agent()
        earn_data = {"status": "completed", "amount": 0.05}

        with patch.object(agent, "_post", new=AsyncMock(return_value=earn_data)):
            await agent.earn("buyer-a")
            await agent.earn("buyer-b")
            await agent.earn("buyer-c")

        assert agent.budget == pytest.approx(0.15)
        assert len(agent.transactions) == 3

    @pytest.mark.asyncio
    async def test_earn_failed_payment_marks_transaction(self):
        agent = make_agent()
        earn_data = {"status": "failed", "amount": 0.05}

        with patch.object(agent, "_post", new=AsyncMock(return_value=earn_data)):
            await agent.earn("buyer-bad")

        # Failed earn does not increase budget
        assert agent.budget == pytest.approx(0.0)
        txn = agent.transactions[0]
        assert txn.success is False

    @pytest.mark.asyncio
    async def test_earn_raises_if_not_setup(self):
        agent = make_agent()
        agent.own_resource_id = None

        with pytest.raises(RuntimeError, match="setup()"):
            await agent.earn("some-buyer")

    @pytest.mark.asyncio
    async def test_earn_propagates_payment_error(self):
        agent = make_agent()

        with patch.object(agent, "_post", new=AsyncMock(side_effect=PaymentError("network error"))):
            with pytest.raises(PaymentError):
                await agent.earn("buyer-x")


# ---------------------------------------------------------------------------
# spend() tests
# ---------------------------------------------------------------------------

class TestSpend:
    @pytest.mark.asyncio
    async def test_spend_deducts_budget(self):
        agent = make_agent()
        agent.budget = 1.00  # pre-fund

        spend_data = {"status": "completed"}
        with patch.object(agent, "_post", new=AsyncMock(return_value=spend_data)):
            result = await agent.spend("market-data-mainlayer", "test purchase")

        assert result is True
        assert agent.budget == pytest.approx(0.98)  # 1.00 - 0.02
        assert agent.total_spent == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_spend_skips_when_insufficient_balance(self):
        agent = make_agent()
        agent.budget = 0.01  # not enough for research report (0.10)

        result = await agent.spend("research-reports-mainlayer", "too expensive")

        assert result is False
        assert agent.budget == pytest.approx(0.01)  # unchanged
        assert agent.total_spent == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_spend_skips_when_exceeds_lifetime_limit(self):
        agent = make_agent(budget_limit=0.05)
        agent.budget = 1.00
        agent.total_spent = 0.04  # only 0.01 remaining budget headroom

        # research report costs 0.10 — more than 0.01 headroom
        result = await agent.spend("research-reports-mainlayer", "over limit")

        assert result is False

    @pytest.mark.asyncio
    async def test_spend_records_failed_api_transaction(self):
        agent = make_agent()
        agent.budget = 1.00

        with patch.object(agent, "_post", new=AsyncMock(side_effect=PaymentError("api down"))):
            result = await agent.spend("market-data-mainlayer", "test")

        assert result is False
        assert len(agent.transactions) == 1
        txn = agent.transactions[0]
        assert txn.kind == "spend"
        assert txn.success is False
        # budget should NOT be deducted for failed spend
        assert agent.budget == pytest.approx(1.00)

    @pytest.mark.asyncio
    async def test_spend_unknown_resource_uses_default_price(self):
        agent = make_agent()
        agent.budget = 1.00

        spend_data = {"status": "completed"}
        with patch.object(agent, "_post", new=AsyncMock(return_value=spend_data)):
            result = await agent.spend("unknown-resource-xyz", "mystery service")

        assert result is True
        # default price = 0.01
        assert agent.total_spent == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# get_price() tests
# ---------------------------------------------------------------------------

class TestGetPrice:
    def test_known_data_feed_price(self):
        agent = make_agent()
        assert agent.get_price("market-data-mainlayer") == pytest.approx(0.02)

    def test_known_research_price(self):
        agent = make_agent()
        assert agent.get_price("research-reports-mainlayer") == pytest.approx(0.10)

    def test_known_storage_price(self):
        agent = make_agent()
        assert agent.get_price("storage-mainlayer") == pytest.approx(0.01)

    def test_unknown_resource_returns_default(self):
        agent = make_agent()
        price = agent.get_price("some-random-vendor")
        assert price == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# check_balance() tests
# ---------------------------------------------------------------------------

class TestCheckBalance:
    @pytest.mark.asyncio
    async def test_check_balance_updates_budget(self):
        agent = make_agent()
        agent.budget = 0.0

        analytics_data = {"total_revenue": 3.75}
        with patch.object(agent, "_get", new=AsyncMock(return_value=analytics_data)):
            balance = await agent.check_balance()

        assert balance == pytest.approx(3.75)
        assert agent.budget == pytest.approx(3.75)

    @pytest.mark.asyncio
    async def test_check_balance_raises_if_not_setup(self):
        agent = make_agent()
        agent.own_resource_id = None

        with pytest.raises(RuntimeError, match="setup()"):
            await agent.check_balance()

    @pytest.mark.asyncio
    async def test_check_balance_falls_back_to_current(self):
        agent = make_agent()
        agent.budget = 2.50
        # API returns missing key → falls back to self.budget
        with patch.object(agent, "_get", new=AsyncMock(return_value={})):
            balance = await agent.check_balance()

        assert balance == pytest.approx(2.50)


# ---------------------------------------------------------------------------
# summary() / net_profit() tests
# ---------------------------------------------------------------------------

class TestSummary:
    @pytest.mark.asyncio
    async def test_summary_after_earn_and_spend(self):
        agent = make_agent()

        with patch.object(agent, "_post", new=AsyncMock(return_value={"status": "completed", "amount": 0.05})):
            await agent.earn("buyer-1")
            await agent.earn("buyer-2")

        agent.budget = 0.10  # mock direct set after two earns
        agent.total_spent = 0.0

        spend_data = {"status": "completed"}
        with patch.object(agent, "_post", new=AsyncMock(return_value=spend_data)):
            await agent.spend("market-data-mainlayer", "data")  # costs 0.02

        snap = agent.summary()
        assert snap["agent"] == "TestAgent"
        assert snap["transaction_count"] == 3  # 2 earns + 1 spend

    def test_net_profit_is_budget(self):
        agent = make_agent()
        agent.budget = 5.00
        assert agent.net_profit() == pytest.approx(5.00)


# ---------------------------------------------------------------------------
# run_cycle() integration test
# ---------------------------------------------------------------------------

class TestRunCycle:
    @pytest.mark.asyncio
    async def test_run_cycle_returns_summary(self):
        agent = make_agent()
        agent.budget = 1.00

        analytics = {"total_revenue": 1.00}
        spend_ok = {"status": "completed"}

        with patch.object(agent, "_get", new=AsyncMock(return_value=analytics)):
            with patch.object(agent, "_post", new=AsyncMock(return_value=spend_ok)):
                snap = await agent.run_cycle()

        assert "balance" in snap
        assert "transaction_count" in snap

    @pytest.mark.asyncio
    async def test_run_cycle_handles_balance_error_gracefully(self):
        agent = make_agent()
        agent.budget = 0.10

        with patch.object(agent, "_get", new=AsyncMock(side_effect=PaymentError("timeout"))):
            with patch.object(agent, "_post", new=AsyncMock(return_value={"status": "completed"})):
                # Should not raise — error is caught and logged
                snap = await agent.run_cycle()

        assert snap is not None


# ---------------------------------------------------------------------------
# Transaction dataclass
# ---------------------------------------------------------------------------

class TestTransaction:
    def test_str_earn(self):
        from datetime import datetime, timezone
        txn = Transaction(
            kind="earn",
            amount=0.05,
            description="sold service",
            resource_id="r-1",
        )
        s = str(txn)
        assert "+$0.0500" in s
        assert "sold service" in s

    def test_str_spend(self):
        txn = Transaction(
            kind="spend",
            amount=0.02,
            description="bought data",
            resource_id="r-2",
        )
        s = str(txn)
        assert "-$0.0200" in s

    def test_failed_transaction_str(self):
        txn = Transaction(
            kind="spend",
            amount=0.10,
            description="failed purchase",
            resource_id="r-3",
            success=False,
        )
        assert "[FAILED]" in str(txn)
