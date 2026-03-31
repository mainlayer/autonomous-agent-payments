"""
ResearchService — purchases structured research reports from Mainlayer.

Resource ID: research-reports-mainlayer

Research reports help the agent improve its summarization quality by
providing ground-truth reference material and topic context.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import AutonomousAgent, PaymentError

logger = logging.getLogger(__name__)

RESOURCE_ID = "research-reports-mainlayer"


class ResearchReport:
    """Structured representation of a purchased research report."""

    def __init__(self, raw: dict[str, Any], price_paid: float) -> None:
        self.title: str = raw.get("title", "Untitled")
        self.abstract: str = raw.get("abstract", "")
        self.sections: list[dict[str, str]] = raw.get("sections", [])
        self.keywords: list[str] = raw.get("keywords", [])
        self.price_paid: float = price_paid
        self.resource_id: str = RESOURCE_ID

    def __repr__(self) -> str:
        return f"<ResearchReport title={self.title!r} sections={len(self.sections)}>"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "abstract": self.abstract,
            "sections": self.sections,
            "keywords": self.keywords,
            "price_paid": self.price_paid,
            "resource_id": self.resource_id,
        }


class ResearchService:
    """
    Wraps an AutonomousAgent to purchase and cache research reports.

    Reports are more expensive than data feeds but provide richer context.
    The agent only purchases them when it has sufficient budget headroom.

    Usage
    -----
    ::

        svc = ResearchService(agent)
        report = await svc.get_report(topic="natural language processing")
    """

    def __init__(self, agent: AutonomousAgent) -> None:
        self.agent = agent
        self._cache: dict[str, ResearchReport] = {}

    async def get_report(self, topic: str = "general") -> ResearchReport | None:
        """
        Pay for and retrieve a research report on *topic*.

        Results are cached by topic so repeated calls within a session
        do not trigger duplicate purchases.

        Returns a ResearchReport on success, or None if budget is insufficient
        or the delivery endpoint fails.
        """
        cache_key = topic.lower().strip()
        if cache_key in self._cache:
            logger.info("[ResearchService] Cache hit for topic=%r", topic)
            return self._cache[cache_key]

        logger.info("[ResearchService] Purchasing research report on topic=%r…", topic)

        success = await self.agent.spend(
            resource_id=RESOURCE_ID,
            purpose=f"Research report: {topic} — context enrichment for summarization",
        )

        if not success:
            logger.warning("[ResearchService] Purchase not completed for topic=%r.", topic)
            return None

        try:
            raw = await self.agent._get(
                f"/resources/{RESOURCE_ID}/deliver",
                params={"buyer": self.agent.name, "topic": topic},
            )
        except PaymentError as exc:
            logger.error("[ResearchService] Delivery failed: %s", exc)
            return None

        report = ResearchReport(
            raw=raw.get("data", {}),
            price_paid=self.agent.svc_prices.research_report,
        )
        self._cache[cache_key] = report
        logger.info("[ResearchService] Report received: %r", report)
        return report

    def cached_topics(self) -> list[str]:
        """Return the list of topics already cached in this session."""
        return list(self._cache.keys())

    def clear_cache(self) -> None:
        """Evict all cached reports (useful between long-running cycles)."""
        self._cache.clear()
        logger.info("[ResearchService] Cache cleared.")
