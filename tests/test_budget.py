"""
test_budget.py — Budget management and financial constraint tests.

Validates that the agent:
  - Never exceeds its lifetime budget_limit
  - Applies per-tier spending thresholds correctly
  - Tracks net profit accurately across many transactions
  - Handles edge cases (zero balance, exact-match budget, floating point)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.agent import AutonomousAgent
from src.config import AgentConfig, ServicePrices


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(
    budget_limit: float = 5.00,
    min_balance_to_spend: float = 0.50,
    data_fee: float = 0.02,
    research_fee: float = 0.10,
    storage_fee: float = 0.01,
) -> AutonomousAgent:
    cfg = AgentConfig(
        name="BudgetBot",
        api_key="key-budget-test",
        budget_limit=budget_limit,
        min_balance_to_spend=min_balance_to_spend,
        http_timeout=5.0,
        http_connect_timeout=2.0,
    )
    prices = ServicePrices(
        data_feed=data_fee,
        research_report=research_fee,
        storage_slot=storage_fee,
    )
    agent = AutonomousAgent(
        name="BudgetBot",
        api_key="key-budget-test",
        budget_limit=budget_limit,
        cfg=cfg,
        svc_prices=prices,
    )
    agent.own_resource_id = "resource-budget-test"
    return agent


SPEND_OK = {"status": "completed"}
EARN_OK = {"status": "completed", "amount": 0.05}


# ---------------------------------------------------------------------------
# Lifetime budget limit
# ---------------------------------------------------------------------------

class TestLifetimeBudgetLimit:
    @pytest.mark.asyncio
    async def test_spend_blocked_when_at_limit(self):
        agent = make_agent(budget_limit=0.10)
        agent.budget = 0.50
        agent.total_spent = 0.10  # already at limit

        result = await agent.spend("market-data-mainlayer", "over limit")
        assert result is False

    @pytest.mark.asyncio
    async def test_spend_allowed_when_just_under_limit(self):
        agent = make_agent(budget_limit=0.10)
        agent.budget = 0.50
        agent.total_spent = 0.08  # 0.02 remaining headroom — exactly enough for data feed

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            result = await agent.spend("market-data-mainlayer", "just fits")  # costs 0.02

        assert result is True

    @pytest.mark.asyncio
    async def test_total_spent_never_exceeds_limit(self):
        agent = make_agent(budget_limit=0.05)
        agent.budget = 10.00  # plenty of balance

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            # Try to buy research report (0.10) — exceeds remaining 0.05 limit
            result = await agent.spend("research-reports-mainlayer", "expensive")

        assert result is False
        assert agent.total_spent == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_cumulative_spend_tracked_correctly(self):
        agent = make_agent(budget_limit=1.00)
        agent.budget = 5.00

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            await agent.spend("storage-mainlayer", "slot 1")   # 0.01
            await agent.spend("storage-mainlayer", "slot 2")   # 0.01
            await agent.spend("market-data-mainlayer", "data") # 0.02

        assert agent.total_spent == pytest.approx(0.04)
        assert agent.budget == pytest.approx(5.00 - 0.04)


# ---------------------------------------------------------------------------
# Minimum balance threshold
# ---------------------------------------------------------------------------

class TestMinBalanceThreshold:
    @pytest.mark.asyncio
    async def test_no_spend_below_min_balance(self):
        agent = make_agent(min_balance_to_spend=0.50)
        agent.budget = 0.30  # below threshold

        # _decide_and_spend should bail out immediately without calling _post
        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)) as mock_post:
            await agent._decide_and_spend()

        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_spend_enabled_at_exactly_min_balance(self):
        agent = make_agent(min_balance_to_spend=0.50)
        agent.budget = 0.50  # exactly at threshold — should attempt to buy data feed

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)) as mock_post:
            await agent._decide_and_spend()

        # At least one spend should have been attempted (data feed at 0.02)
        mock_post.assert_called()

    @pytest.mark.asyncio
    async def test_zero_balance_triggers_no_spend(self):
        agent = make_agent()
        agent.budget = 0.0

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)) as mock_post:
            await agent._decide_and_spend()

        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Tiered spending decisions
# ---------------------------------------------------------------------------

class TestTieredSpending:
    @pytest.mark.asyncio
    async def test_only_data_feed_when_barely_funded(self):
        """With balance below 3× research price (0.30), agent buys data feed but not research."""
        # min_balance_to_spend=0.05 so we pass the threshold; budget=0.29 < 3×0.10=0.30
        agent = make_agent(min_balance_to_spend=0.05)
        agent.budget = 0.29  # below the 0.30 research threshold

        calls: list[str] = []

        async def capture_post(path, payload):
            calls.append(payload.get("resource_id", ""))
            return SPEND_OK

        with patch.object(agent, "_post", new=AsyncMock(side_effect=capture_post)):
            await agent._decide_and_spend()

        assert "market-data-mainlayer" in calls
        assert "research-reports-mainlayer" not in calls

    @pytest.mark.asyncio
    async def test_research_bought_when_well_funded(self):
        """With balance >= 3× research price (0.30), agent purchases a research report."""
        agent = make_agent()
        # 0.50 >= 3 × 0.10 (0.30) — research threshold clearly met
        agent.budget = 0.50

        calls: list[str] = []

        async def capture_post(path, payload):
            calls.append(payload.get("resource_id", ""))
            return SPEND_OK

        with patch.object(agent, "_post", new=AsyncMock(side_effect=capture_post)):
            await agent._decide_and_spend()

        assert "research-reports-mainlayer" in calls

    @pytest.mark.asyncio
    async def test_storage_bought_when_above_min(self):
        agent = make_agent()
        agent.budget = 0.50

        calls: list[str] = []

        async def capture_post(path, payload):
            calls.append(payload.get("resource_id", ""))
            return SPEND_OK

        with patch.object(agent, "_post", new=AsyncMock(side_effect=capture_post)):
            await agent._decide_and_spend()

        assert "storage-mainlayer" in calls


# ---------------------------------------------------------------------------
# Net profit tracking
# ---------------------------------------------------------------------------

class TestNetProfit:
    @pytest.mark.asyncio
    async def test_profit_equals_earned_minus_spent(self):
        agent = make_agent()

        with patch.object(agent, "_post", new=AsyncMock(return_value=EARN_OK)):
            await agent.earn("buyer-1")  # +0.05
            await agent.earn("buyer-2")  # +0.05

        agent.budget = 0.10  # direct set consistent with earns
        agent.total_spent = 0.0

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            await agent.spend("market-data-mainlayer", "data")  # -0.02

        assert agent.net_profit() == pytest.approx(0.08)

    def test_net_profit_zero_on_fresh_agent(self):
        agent = make_agent()
        assert agent.net_profit() == pytest.approx(0.0)

    def test_net_profit_negative_impossible_via_api(self):
        """spend() guard prevents spending more than balance."""
        agent = make_agent()
        agent.budget = 0.0
        # net_profit cannot go below 0 via the normal API
        assert agent.net_profit() >= 0.0


# ---------------------------------------------------------------------------
# Floating-point safety
# ---------------------------------------------------------------------------

class TestFloatingPoint:
    @pytest.mark.asyncio
    async def test_many_small_transactions_stay_accurate(self):
        agent = make_agent(budget_limit=100.0)
        agent.budget = 10.00

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            for _ in range(50):
                await agent.spend("storage-mainlayer", "storage")  # 0.01 each

        assert agent.total_spent == pytest.approx(0.50)
        assert agent.budget == pytest.approx(9.50)

    @pytest.mark.asyncio
    async def test_exact_budget_limit_not_exceeded(self):
        agent = make_agent(budget_limit=0.10)
        agent.budget = 5.00
        agent.total_spent = 0.09  # one cent below limit

        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            # storage costs 0.01 — exactly fills the remaining budget
            result = await agent.spend("storage-mainlayer", "last slot")

        assert result is True
        assert agent.total_spent == pytest.approx(0.10)

        # Next spend should be blocked
        with patch.object(agent, "_post", new=AsyncMock(return_value=SPEND_OK)):
            result2 = await agent.spend("storage-mainlayer", "over limit")

        assert result2 is False
        assert agent.total_spent == pytest.approx(0.10)  # unchanged
