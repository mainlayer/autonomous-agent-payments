"""
profit_maximizer.py — Agent that dynamically adjusts its service price
to maximize revenue based on observed demand.

Strategy:
  - Track how many buyers paid per cycle.
  - If demand is high (>= HIGH_DEMAND_THRESHOLD buyers), raise the price.
  - If demand is low (< LOW_DEMAND_THRESHOLD buyers), lower the price to attract more.
  - Always maintain price within [MIN_PRICE, MAX_PRICE] bounds.

Run:
    export MAINLAYER_API_KEY=your_key
    python examples/profit_maximizer.py
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table
from rich import box

from src.agent import AutonomousAgent
from src.config import AgentConfig, ServicePrices

console = Console()

API_KEY = os.environ.get("MAINLAYER_API_KEY", "demo-key")

MIN_PRICE = 0.01
MAX_PRICE = 0.50
PRICE_STEP = 0.01
HIGH_DEMAND_THRESHOLD = 3   # buyers/cycle — raise price
LOW_DEMAND_THRESHOLD = 1    # buyers/cycle — lower price


@dataclass
class PricingState:
    current_price: float = 0.05
    history: list[dict] = field(default_factory=list)

    def record(self, cycle: int, buyers: int, revenue: float) -> None:
        self.history.append({"cycle": cycle, "buyers": buyers, "price": self.current_price, "revenue": revenue})

    def adjust(self, buyers_this_cycle: int) -> None:
        if buyers_this_cycle >= HIGH_DEMAND_THRESHOLD:
            new_price = min(self.current_price + PRICE_STEP, MAX_PRICE)
            if new_price != self.current_price:
                console.print(f"  [green]Demand high ({buyers_this_cycle} buyers) — raising price "
                               f"${self.current_price:.2f} -> ${new_price:.2f}[/green]")
            self.current_price = new_price
        elif buyers_this_cycle < LOW_DEMAND_THRESHOLD:
            new_price = max(self.current_price - PRICE_STEP, MIN_PRICE)
            if new_price != self.current_price:
                console.print(f"  [yellow]Demand low ({buyers_this_cycle} buyers) — lowering price "
                               f"${self.current_price:.2f} -> ${new_price:.2f}[/yellow]")
            self.current_price = new_price

    def total_revenue(self) -> float:
        return sum(r["revenue"] for r in self.history)

    def print_report(self) -> None:
        table = Table(title="Pricing History", box=box.SIMPLE_HEAVY)
        table.add_column("Cycle", style="dim")
        table.add_column("Buyers", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Revenue", justify="right", style="green")

        for row in self.history:
            table.add_row(
                str(row["cycle"]),
                str(row["buyers"]),
                f"${row['price']:.2f}",
                f"${row['revenue']:.4f}",
            )

        console.print(table)
        console.print(f"\n  [bold]Total revenue:[/bold] [green]${self.total_revenue():.4f}[/green]")
        console.print(f"  [bold]Final price:[/bold]   ${self.current_price:.2f}")


# Simulated buyer demand — varies by cycle to make the demo interesting
SIMULATED_DEMAND = [1, 1, 2, 4, 5, 3, 1, 0, 2, 4, 6, 3, 2, 1, 3]


async def main() -> None:
    cfg = AgentConfig(
        name="ProfitMaximizer",
        api_key=API_KEY,
        service_price=0.05,
        budget_limit=20.0,
    )
    agent = AutonomousAgent(
        name=cfg.name,
        api_key=API_KEY,
        budget_limit=cfg.budget_limit,
        cfg=cfg,
    )

    pricing = PricingState(current_price=cfg.service_price)

    console.rule("[bold blue]Profit Maximizer Agent")

    await agent.setup()

    for cycle, demand in enumerate(SIMULATED_DEMAND, start=1):
        console.print(f"\n[bold]Cycle {cycle}[/bold] — simulated demand: {demand} buyers")

        # Update agent's price for this cycle
        agent.cfg.service_price = pricing.current_price

        # Simulate each buyer paying
        cycle_revenue = 0.0
        for b in range(demand):
            try:
                await agent.earn(buyer_wallet=f"buyer-{cycle}-{b}")
                cycle_revenue += pricing.current_price
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]earn failed: {exc}[/red]")

        pricing.record(cycle=cycle, buyers=demand, revenue=cycle_revenue)
        pricing.adjust(buyers_this_cycle=demand)

        # Run standard cycle (balance check + optional spending)
        await agent.run_cycle()

    console.print()
    pricing.print_report()

    snap = agent.summary()
    console.print(f"\n  Agent balance: [green]${snap['balance']:.4f}[/green]")

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
