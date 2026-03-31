"""
simple_agent.py — Minimal autonomous agent in ~30 lines.

Demonstrates the core earn/spend loop with the fewest possible lines of code.
The agent earns from one buyer, then decides whether to purchase a data feed.

Run:
    export MAINLAYER_API_KEY=your_key
    python examples/simple_agent.py
"""

import asyncio
import os
from src.agent import AutonomousAgent

API_KEY = os.environ.get("MAINLAYER_API_KEY", "demo-key")


async def main() -> None:
    agent = AutonomousAgent(name="SimpleAgent", api_key=API_KEY, budget_limit=5.0)

    # Register service with Mainlayer
    await agent.setup()
    print(f"Registered: {agent.own_resource_id}")

    # Earn revenue from a buyer agent
    await agent.earn(buyer_wallet="buyer-agent-001")
    print(f"Balance after earning: ${agent.budget:.4f}")

    # Autonomously decide whether to spend
    await agent.run_cycle()

    # Print final state
    print(agent.summary())
    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
