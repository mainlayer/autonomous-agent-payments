"""
multi_agent_swarm.py — Three autonomous agents trading with each other.

Architecture:
  - Summarizer  — sells text summarization, buys research reports
  - Researcher  — sells research reports, buys data feeds and storage
  - DataBroker  — sells real-time data feeds, buys storage

Each agent runs concurrently. They pay each other for services, creating a
self-sustaining micro-economy powered by Mainlayer.

Run:
    export MAINLAYER_API_KEY=your_key
    python examples/multi_agent_swarm.py
"""

from __future__ import annotations

import asyncio
import os

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.agent import AutonomousAgent
from src.config import AgentConfig, ServicePrices

console = Console()

API_KEY = os.environ.get("MAINLAYER_API_KEY", "demo-key")

CYCLES = 6
CYCLE_DELAY = 0.5  # seconds between cycles in the demo


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

def make_summarizer() -> AutonomousAgent:
    cfg = AgentConfig(
        name="Summarizer",
        api_key=API_KEY,
        service_name="text-summarization",
        service_price=0.05,
        min_balance_to_spend=0.05,
        budget_limit=20.0,
    )
    prices = ServicePrices(data_feed=0.02, research_report=0.10, storage_slot=0.01)
    agent = AutonomousAgent("Summarizer", API_KEY, budget_limit=20.0, cfg=cfg, svc_prices=prices)
    agent.own_resource_id = "resource-summarizer"
    return agent


def make_researcher() -> AutonomousAgent:
    cfg = AgentConfig(
        name="Researcher",
        api_key=API_KEY,
        service_name="research-reports",
        service_price=0.10,
        min_balance_to_spend=0.02,
        budget_limit=20.0,
    )
    prices = ServicePrices(data_feed=0.02, research_report=0.10, storage_slot=0.01)
    agent = AutonomousAgent("Researcher", API_KEY, budget_limit=20.0, cfg=cfg, svc_prices=prices)
    agent.own_resource_id = "resource-researcher"
    return agent


def make_data_broker() -> AutonomousAgent:
    cfg = AgentConfig(
        name="DataBroker",
        api_key=API_KEY,
        service_name="market-data",
        service_price=0.02,
        min_balance_to_spend=0.01,
        budget_limit=20.0,
    )
    prices = ServicePrices(data_feed=0.02, research_report=0.10, storage_slot=0.01)
    agent = AutonomousAgent("DataBroker", API_KEY, budget_limit=20.0, cfg=cfg, svc_prices=prices)
    agent.own_resource_id = "resource-data-broker"
    return agent


# ---------------------------------------------------------------------------
# Inter-agent payment graph
# ---------------------------------------------------------------------------
#
#   Summarizer  --pays research--> Researcher
#   Researcher  --pays data-----> DataBroker
#   DataBroker  --pays summary--> Summarizer
#
# Each agent also receives inbound payments from the others.

async def run_swarm_cycle(
    summarizer: AutonomousAgent,
    researcher: AutonomousAgent,
    data_broker: AutonomousAgent,
    cycle: int,
) -> None:
    console.print(f"\n[bold]--- Swarm Cycle {cycle} ---[/bold]")

    # Payments flow: DataBroker pays Summarizer, Summarizer pays Researcher, Researcher pays DataBroker
    payment_tasks = [
        summarizer.earn(buyer_wallet="DataBroker"),      # DataBroker buys summarization
        researcher.earn(buyer_wallet="Summarizer"),       # Summarizer buys research
        data_broker.earn(buyer_wallet="Researcher"),      # Researcher buys data
    ]
    await asyncio.gather(*payment_tasks, return_exceptions=True)

    # Each agent makes its own autonomous spending decisions
    cycle_tasks = [
        summarizer.run_cycle(),
        researcher.run_cycle(),
        data_broker.run_cycle(),
    ]
    await asyncio.gather(*cycle_tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def agent_panel(agent: AutonomousAgent) -> Panel:
    snap = agent.summary()
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")

    color = "green" if snap["net_profit"] >= 0 else "red"
    table.add_row("Balance", f"[{color}]${snap['balance']:.4f}[/{color}]")
    table.add_row("Earned", f"[green]${snap['total_earned']:.4f}[/green]")
    table.add_row("Spent", f"[red]${snap['total_spent']:.4f}[/red]")
    table.add_row("Profit", f"[{color}]${snap['net_profit']:.4f}[/{color}]")
    table.add_row("Txns", str(snap["transaction_count"]))

    return Panel(table, title=f"[bold]{agent.name}", border_style="cyan")


def print_swarm_status(agents: list[AutonomousAgent]) -> None:
    panels = [agent_panel(a) for a in agents]
    console.print(Columns(panels, equal=True, expand=True))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    console.rule("[bold blue]Multi-Agent Swarm — Mainlayer Economy")
    console.print(
        "\n[dim]Three agents trade with each other autonomously:[/dim]\n"
        "  [cyan]Summarizer[/cyan]  sells summaries → buys research\n"
        "  [cyan]Researcher[/cyan]  sells reports   → buys data feeds\n"
        "  [cyan]DataBroker[/cyan]  sells data      → buys summaries\n"
    )

    summarizer = make_summarizer()
    researcher = make_researcher()
    data_broker = make_data_broker()
    agents = [summarizer, researcher, data_broker]

    console.print("[bold]Initial state:[/bold]")
    print_swarm_status(agents)

    for cycle in range(1, CYCLES + 1):
        await run_swarm_cycle(summarizer, researcher, data_broker, cycle)
        await asyncio.sleep(CYCLE_DELAY)

    console.print("\n[bold]Final state after swarm run:[/bold]")
    print_swarm_status(agents)

    # Economy summary
    total_volume = sum(a.summary()["total_earned"] for a in agents)
    console.print(f"\n[bold]Total economic volume:[/bold] [green]${total_volume:.4f}[/green]")

    # Shutdown
    await asyncio.gather(*(a.close() for a in agents))
    console.print("[dim]All agents shut down.[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
