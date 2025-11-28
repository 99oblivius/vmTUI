"""System resource detection service."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SystemResources:
    """Available system resources."""
    cpu_count: int
    memory_mb: int
    disk_free_gb: int
    disk_path: Path


class SystemService:
    """Service for detecting available system resources."""

    def __init__(self, disk_path: Path | None = None) -> None:
        from vm_manager.config import DISK_DIR
        self.disk_path = disk_path or DISK_DIR

    def get_resources(self) -> SystemResources:
        """Get available system resources."""
        return SystemResources(
            cpu_count=self._get_cpu_count(),
            memory_mb=self._get_memory_mb(),
            disk_free_gb=self._get_disk_free_gb(),
            disk_path=self.disk_path,
        )

    def _get_cpu_count(self) -> int:
        """Get number of CPU cores."""
        return os.cpu_count() or 1

    def _get_memory_mb(self) -> int:
        """Get total system memory in MB."""
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        # MemTotal: 16384000 kB
                        parts = line.split()
                        kb = int(parts[1])
                        return kb // 1024
        except (OSError, ValueError, IndexError):
            pass

        # Fallback
        return 4096

    def _get_disk_free_gb(self) -> int:
        """Get free disk space in GB at disk path."""
        try:
            # Ensure parent directory exists for checking
            check_path = self.disk_path
            while not check_path.exists() and check_path.parent != check_path:
                check_path = check_path.parent

            usage = shutil.disk_usage(check_path)
            return int(usage.free // (1024 ** 3))
        except (OSError, ValueError):
            pass

        return 100  # Fallback
