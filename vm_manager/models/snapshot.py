"""Snapshot model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Snapshot:
    """VM snapshot representation."""

    name: str
    description: str
    created_at: datetime
    state: str  # "running", "shutoff", etc.
    parent: str | None = None
    is_current: bool = False

    @property
    def age_display(self) -> str:
        """Format age for display."""
        delta = datetime.now() - self.created_at
        if delta.days > 365:
            years = delta.days // 365
            return f"{years}y ago"
        if delta.days > 30:
            months = delta.days // 30
            return f"{months}mo ago"
        if delta.days > 0:
            return f"{delta.days}d ago"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h ago"
        minutes = delta.seconds // 60
        return f"{minutes}m ago"
