"""
main.py — Entry point for the Autonomous Agent Payments demo.

Starts a single AutonomousAgent, shows a live Rich dashboard of its
earn/spend activity, and runs for a configurable number of cycles.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from src.agent import AutonomousAgent, Transaction
from src.config import AgentConfig, ServicePrices

# ---------------------------------------------------------------------------
# Logging — route structured logs through Rich for pretty output
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,  # suppress library noise; we display via Rich
    format="%(levelname)s %(name)s %(message)s",
)

console = Console()


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def build_header(agent: AutonomousAgent) -> Panel:
    text = Text()
    text.append("  Autonomous Agent Payments  ", style="bold white on dark_blue")
    text.append(f"\n  Agent: {agent.name}", style="cyan")
    text.append(f"  |  Budget limit: ${agent.budget_limit:.2f}", style="yellow")
    return Panel(text, box=box.DOUBLE_EDGE, border_style="blue")


def build_balance_panel(agent: AutonomousAgent) -> Panel:
    snap = agent.summary()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold dim")
    table.add_column("Value", style="bold green")

    table.add_row("Balance", f"${snap['balance']:.4f}")
    table.add_row("Total Earned", f"${snap['total_earned']:.4f}")
    table.add_row("Total Spent", f"${snap['total_spent']:.4f}")
    table.add_row("Net Profit", f"${snap['net_profit']:.4f}")
    table.add_row("Transactions", str(snap["transaction_count"]))

    return Panel(table, title="[bold]Financials", border_style="green")


def build_txn_table(transactions: list[Transaction], max_rows: int = 12) -> Panel:
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
    table.add_column("Time", style="dim", width=10)
    table.add_column("Type", width=7)
    table.add_column("Amount", justify="right", width=10)
    table.add_column("Description", no_wrap=False)
    table.add_column("Status", width=8)

    recent = transactions[-max_rows:]
    for txn in reversed(recent):
        color = "green" if txn.kind == "earn" else "red"
        sign = "+" if txn.kind == "earn" else "-"
        status_icon = "[green]OK[/green]" if txn.success else "[red]FAIL[/red]"
        table.add_row(
            txn.timestamp.strftime("%H:%M:%S"),
            f"[{color}]{txn.kind.upper()}[/{color}]",
            f"[{color}]{sign}${txn.amount:.4f}[/{color}]",
            txn.description[:55],
            status_icon,
        )

    return Panel(table, title="[bold]Transaction Log", border_style="magenta")


def build_layout(agent: AutonomousAgent) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(build_header(agent), size=5, name="header"),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(build_balance_panel(agent), name="left", ratio=1),
        Layout(build_txn_table(agent.transactions), name="right", ratio=2),
    )
    return layout


# ---------------------------------------------------------------------------
# Demo cycle — simulate earnings and let agent decide spending
# ---------------------------------------------------------------------------

DEMO_BUYERS = [
    "agent-alpha-7f3a",
    "agent-beta-2c8d",
    "agent-gamma-9b1e",
    "orchestrator-prime",
    "research-bot-44x",
]


async def demo_loop(agent: AutonomousAgent, cycles: int, live: Live) -> None:
    """Simulate an agent earning and spending over *cycles* iterations."""
    for cycle_num in range(1, cycles + 1):
        console.log(f"[dim]Cycle {cycle_num}/{cycles}…[/dim]")

        # Simulate an incoming payment from a rotating buyer
        buyer = DEMO_BUYERS[(cycle_num - 1) % len(DEMO_BUYERS)]
        try:
            await agent.earn(buyer_wallet=buyer)
        except Exception as exc:  # noqa: BLE001
            console.log(f"[red]earn() error: {exc}[/red]")

        # Refresh balance and make spending decisions
        try:
            await agent.run_cycle()
        except Exception as exc:  # noqa: BLE001
            console.log(f"[red]run_cycle() error: {exc}[/red]")

        # Redraw dashboard
        live.update(build_layout(agent))

        await asyncio.sleep(1.5)  # pacing for demo visibility


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    api_key = os.environ.get("MAINLAYER_API_KEY", "demo-key-placeholder")
    cycles = int(os.environ.get("DEMO_CYCLES", "8"))

    cfg = AgentConfig(
        name="SummarizerAgent",
        api_key=api_key,
        budget_limit=10.0,
        cycle_interval_seconds=60,
    )
    svc_prices = ServicePrices()

    agent = AutonomousAgent(
        name=cfg.name,
        api_key=api_key,
        budget_limit=cfg.budget_limit,
        cfg=cfg,
        svc_prices=svc_prices,
    )

    console.rule("[bold blue]Autonomous Agent Payments — Mainlayer Demo")
    console.print()
    console.print(
        "[bold]How it works:[/bold]\n"
        "  1. Agent registers its [cyan]summarization service[/cyan] with Mainlayer.\n"
        "  2. Each cycle, a buyer agent pays for the service ([green]earn[/green]).\n"
        "  3. The agent autonomously purchases data / research / storage ([red]spend[/red]).\n"
        "  4. Budget decisions are made automatically based on current balance.\n"
    )

    # Register service
    try:
        await agent.setup()
        console.print(f"[green]Service registered:[/green] resource_id={agent.own_resource_id}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]setup() skipped (demo mode): {exc}[/yellow]")
        agent.own_resource_id = "demo-resource-summarize"

    console.print()

    with Live(build_layout(agent), console=console, refresh_per_second=4, screen=False) as live:
        await demo_loop(agent, cycles=cycles, live=live)

    # Final summary
    console.rule("[bold green]Final Summary")
    snap = agent.summary()
    for key, val in snap.items():
        console.print(f"  [bold]{key}:[/bold] {val}")

    await agent.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(0)
