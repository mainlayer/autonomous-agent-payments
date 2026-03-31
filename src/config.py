"""
Configuration for the Autonomous Agent Payments demo.

All settings can be overridden via environment variables.
"""

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Core agent configuration."""

    # Identity
    name: str = os.environ.get("AGENT_NAME", "AutonomousAgent-1")

    # Mainlayer API
    api_key: str = os.environ.get("MAINLAYER_API_KEY", "")
    base_url: str = os.environ.get("MAINLAYER_BASE_URL", "https://api.mainlayer.xyz")

    # Budget management
    budget_limit: float = float(os.environ.get("BUDGET_LIMIT", "10.0"))
    min_balance_to_spend: float = float(os.environ.get("MIN_BALANCE_TO_SPEND", "0.50"))
    low_balance_threshold: float = float(os.environ.get("LOW_BALANCE_THRESHOLD", "1.00"))

    # Cycle timing
    cycle_interval_seconds: int = int(os.environ.get("CYCLE_INTERVAL_SECONDS", "60"))

    # Service this agent offers
    service_name: str = os.environ.get("SERVICE_NAME", "text-summarization")
    service_price: float = float(os.environ.get("SERVICE_PRICE", "0.05"))
    service_description: str = os.environ.get(
        "SERVICE_DESCRIPTION",
        "High-quality text summarization — condenses any document to its key points",
    )

    # HTTP timeouts (seconds)
    http_timeout: float = float(os.environ.get("HTTP_TIMEOUT", "30.0"))
    http_connect_timeout: float = float(os.environ.get("HTTP_CONNECT_TIMEOUT", "10.0"))

    # Logging / display
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")
    rich_output: bool = os.environ.get("RICH_OUTPUT", "true").lower() == "true"

    def validate(self) -> None:
        """Raise ValueError for obviously wrong configuration."""
        if not self.api_key:
            raise ValueError(
                "MAINLAYER_API_KEY is not set. "
                "Export it before running: export MAINLAYER_API_KEY=your_key"
            )
        if self.budget_limit <= 0:
            raise ValueError("BUDGET_LIMIT must be positive.")
        if self.service_price <= 0:
            raise ValueError("SERVICE_PRICE must be positive.")


@dataclass
class ServicePrices:
    """Known prices for external services this agent can purchase."""

    data_feed: float = float(os.environ.get("PRICE_DATA_FEED", "0.02"))
    research_report: float = float(os.environ.get("PRICE_RESEARCH_REPORT", "0.10"))
    storage_slot: float = float(os.environ.get("PRICE_STORAGE_SLOT", "0.01"))


# Module-level singletons so importers get one shared config
config = AgentConfig()
prices = ServicePrices()
