"""Formatting utilities."""


def format_bytes(num_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes = int(num_bytes / 1024)
    return f"{num_bytes:.1f} PB"


def format_duration(seconds: int) -> str:
    """Format duration as human-readable string."""
    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60
    if minutes < 60:
        secs = seconds % 60
        return f"{minutes}m {secs}s"

    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins}m"

    days = hours // 24
    hrs = hours % 24
    return f"{days}d {hrs}h"


def format_percent(value: float) -> str:
    """Format percentage value."""
    return f"{value:.1f}%"


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to max length with suffix."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
