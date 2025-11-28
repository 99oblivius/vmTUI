"""OS variant information service."""

import subprocess
import sys
from dataclasses import dataclass


@dataclass
class OSVariant:
    """Operating system variant information."""

    short_id: str
    name: str
    version: str = ""
    family: str = ""


class OSInfoService:
    """Service for querying OS variant information."""

    def __init__(self) -> None:
        self._cache: list[OSVariant] | None = None
        self._osinfo_available: bool | None = None

    def is_osinfo_available(self) -> bool:
        """Check if osinfo-query command is available."""
        if self._osinfo_available is None:
            try:
                result = subprocess.run(
                    ["osinfo-query", "os", "--fields=short-id"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self._osinfo_available = result.returncode == 0
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                self._osinfo_available = False
        return self._osinfo_available

    def get_install_hint(self) -> str | None:
        """Get installation hint for osinfo tools if on Linux and not installed."""
        if self.is_osinfo_available():
            return None

        if sys.platform == "linux":
            return (
                "For the complete OS variant database, install libosinfo-bin:\n"
                "  Debian/Ubuntu: sudo apt install libosinfo-bin\n"
                "  Fedora/RHEL:   sudo dnf install libosinfo\n"
                "  Arch:          sudo pacman -S libosinfo"
            )
        return None

    def list_variants(self) -> list[OSVariant]:
        """List all available OS variants."""
        if self._cache is not None:
            return self._cache

        variants: list[OSVariant] = []

        try:
            result = subprocess.run(
                ["osinfo-query", "os", "--fields=short-id,name"],
                capture_output=True,
                text=True,
                check=True,
            )

            # Skip header lines
            lines = result.stdout.strip().split("\n")
            for line in lines[2:]:  # Skip header and separator
                parts = line.split("|")
                if len(parts) >= 2:
                    short_id = parts[0].strip()
                    name = parts[1].strip()
                    if short_id and name:
                        variants.append(OSVariant(short_id=short_id, name=name))

        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to built-in list
            variants = self._get_builtin_variants()

        self._cache = variants
        return variants

    def search_variants(self, query: str) -> list[OSVariant]:
        """Search for OS variants matching query."""
        query_lower = query.lower()
        return [
            v for v in self.list_variants()
            if query_lower in v.short_id.lower() or query_lower in v.name.lower()
        ]

    def get_variant(self, short_id: str) -> OSVariant | None:
        """Get a specific OS variant by short ID."""
        for variant in self.list_variants():
            if variant.short_id == short_id:
                return variant
        return None

    def is_valid_variant(self, short_id: str) -> bool:
        """Check if a variant ID is valid."""
        # 'generic' is always valid
        if short_id == "generic":
            return True
        return self.get_variant(short_id) is not None

    def _get_builtin_variants(self) -> list[OSVariant]:
        """Get built-in list of common OS variants."""
        return [
            # Linux - Ubuntu
            OSVariant("ubuntu24.04", "Ubuntu 24.04 LTS"),
            OSVariant("ubuntu22.04", "Ubuntu 22.04 LTS"),
            OSVariant("ubuntu20.04", "Ubuntu 20.04 LTS"),
            # Linux - Debian
            OSVariant("debian12", "Debian 12 (Bookworm)"),
            OSVariant("debian11", "Debian 11 (Bullseye)"),
            OSVariant("debian10", "Debian 10 (Buster)"),
            # Linux - Fedora
            OSVariant("fedora40", "Fedora 40"),
            OSVariant("fedora39", "Fedora 39"),
            OSVariant("fedora38", "Fedora 38"),
            # Linux - CentOS/RHEL
            OSVariant("centos-stream9", "CentOS Stream 9"),
            OSVariant("rhel9", "Red Hat Enterprise Linux 9"),
            OSVariant("rhel8", "Red Hat Enterprise Linux 8"),
            # Linux - Arch/Others
            OSVariant("archlinux", "Arch Linux"),
            OSVariant("gentoo", "Gentoo Linux"),
            OSVariant("alpinelinux3.19", "Alpine Linux 3.19"),
            OSVariant("opensuse15.5", "openSUSE Leap 15.5"),
            OSVariant("nixos-unstable", "NixOS Unstable"),
            # BSD
            OSVariant("freebsd14.0", "FreeBSD 14.0"),
            OSVariant("freebsd13.2", "FreeBSD 13.2"),
            OSVariant("openbsd7.4", "OpenBSD 7.4"),
            OSVariant("netbsd9", "NetBSD 9"),
            # Windows
            OSVariant("win11", "Windows 11"),
            OSVariant("win10", "Windows 10"),
            OSVariant("win2k22", "Windows Server 2022"),
            OSVariant("win2k19", "Windows Server 2019"),
            # Other
            OSVariant("macos13", "macOS 13 (Ventura)"),
            OSVariant("solaris11", "Oracle Solaris 11"),
            OSVariant("haiku", "Haiku"),
            OSVariant("reactos", "ReactOS"),
            OSVariant("freedos1.3", "FreeDOS 1.3"),
            OSVariant("msdos6.22", "MS-DOS 6.22"),
            # Generic fallback
            OSVariant("generic", "Generic OS (any)"),
        ]

    def get_common_variants(self) -> dict[str, list[OSVariant]]:
        """Get common variants organized by category."""
        return {
            "Linux": [
                OSVariant("ubuntu24.04", "Ubuntu 24.04 LTS"),
                OSVariant("ubuntu22.04", "Ubuntu 22.04 LTS"),
                OSVariant("debian12", "Debian 12"),
                OSVariant("fedora39", "Fedora 39"),
                OSVariant("archlinux", "Arch Linux"),
                OSVariant("centos-stream9", "CentOS Stream 9"),
                OSVariant("nixos-unstable", "NixOS Unstable"),
            ],
            "BSD": [
                OSVariant("freebsd14.0", "FreeBSD 14.0"),
                OSVariant("openbsd7.4", "OpenBSD 7.4"),
                OSVariant("netbsd9", "NetBSD 9"),
            ],
            "Windows": [
                OSVariant("win11", "Windows 11"),
                OSVariant("win10", "Windows 10"),
                OSVariant("win2k22", "Windows Server 2022"),
            ],
            "Other": [
                OSVariant("haiku", "Haiku"),
                OSVariant("reactos", "ReactOS"),
                OSVariant("freedos1.3", "FreeDOS 1.3"),
                OSVariant("generic", "Generic (any OS)"),
            ],
        }
