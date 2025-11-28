"""Network detection service."""

import subprocess
from pathlib import Path


class NetworkService:
    """Service for detecting available networks and bridges."""

    def list_bridges(self) -> list[str]:
        """List available host bridges."""
        bridges: list[str] = []

        # Check /sys/class/net for bridge interfaces
        net_path = Path("/sys/class/net")
        if net_path.exists():
            for iface in net_path.iterdir():
                bridge_path = iface / "bridge"
                if bridge_path.exists():
                    bridges.append(iface.name)

        return sorted(bridges)

    def list_all_interfaces(self) -> list[tuple[str, str, str]]:
        """List all network options: (value, display, type).

        Returns tuples of (identifier, display_name, type) where type is 'network' or 'bridge'.
        """
        options: list[tuple[str, str, str]] = []

        # Get host bridges first (usually preferred)
        for bridge in self.list_bridges():
            options.append((
                f"bridge:{bridge}",
                f"{bridge} (host bridge)",
                "bridge"
            ))

        return options

    def get_bridge_info(self, bridge_name: str) -> dict[str, str]:
        """Get info about a bridge (IP, state, etc.)."""
        info: dict[str, str] = {}

        try:
            result = subprocess.run(
                ["ip", "-br", "addr", "show", bridge_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout:
                parts = result.stdout.split()
                if len(parts) >= 2:
                    info["state"] = parts[1]
                if len(parts) >= 3:
                    info["ip"] = parts[2]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return info
