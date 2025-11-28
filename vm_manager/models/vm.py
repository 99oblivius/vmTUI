"""VM model and related types."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class VMState(Enum):
    """Virtual machine state."""

    NOSTATE = 0
    RUNNING = 1
    BLOCKED = 2
    PAUSED = 3
    SHUTDOWN = 4
    SHUTOFF = 5
    CRASHED = 6
    PMSUSPENDED = 7

    @property
    def display_name(self) -> str:
        """Human-readable state name."""
        names: dict[VMState, str] = {
            VMState.NOSTATE: "no state",
            VMState.RUNNING: "running",
            VMState.BLOCKED: "blocked",
            VMState.PAUSED: "paused",
            VMState.SHUTDOWN: "shutting down",
            VMState.SHUTOFF: "shut off",
            VMState.CRASHED: "crashed",
            VMState.PMSUSPENDED: "suspended",
        }
        return names.get(self, "unknown")

    @property
    def color_key(self) -> str:
        """Color key for this state."""
        colors: dict[VMState, str] = {
            VMState.NOSTATE: "nostate",
            VMState.RUNNING: "running",
            VMState.BLOCKED: "blocked",
            VMState.PAUSED: "paused",
            VMState.SHUTDOWN: "in_shutdown",
            VMState.SHUTOFF: "shut_off",
            VMState.CRASHED: "crashed",
            VMState.PMSUSPENDED: "pmsuspended",
        }
        return colors.get(self, "nostate")


@dataclass
class VMStats:
    """Runtime statistics for a VM."""

    cpu_time_ns: int = 0
    cpu_percent: float = 0.0
    memory_used_kb: int = 0
    memory_percent: float = 0.0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    net_rx_bytes: int = 0
    net_tx_bytes: int = 0
    uptime_seconds: int = 0


@dataclass
class VMConfig:
    """Configuration for creating or modifying a VM."""

    name: str
    vcpus: int
    memory_mb: int
    disk_size_gb: int
    os_variant: str
    iso_path: Path | None = None
    network: str = "default"
    network_type: str = "network"  # "network" for libvirt, "bridge" for host bridge
    nic_model: str = "virtio"  # virtio, e1000, e1000e, rtl8139, vmxnet3
    disk_path: Path | None = None
    gpu_devices: list[str] = field(default_factory=list)
    usb_devices: list[str] = field(default_factory=list)  # vendor:product format
    audio_model: str = "ich9"  # none, ac97, ich6, ich9
    autostart: bool = False
    graphics: str = "spice"  # spice, vnc, none
    boot_device: str = "hd"
    cpu_pinning: str = ""  # e.g., "0-3" or "0,2,4,6"


@dataclass
class VM:
    """Virtual machine representation."""

    name: str
    uuid: str
    state: VMState
    vcpus: int
    memory_mb: int
    autostart: bool
    persistent: bool
    disks: list[Path] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    graphics_type: str = "none"  # spice, vnc, none
    graphics_port: int | None = None
    graphics_listen: str = "0.0.0.0"
    gpu_devices: list[str] = field(default_factory=list)
    usb_devices: list[str] = field(default_factory=list)  # vendor:product format
    stats: VMStats = field(default_factory=VMStats)
    snapshot_count: int = 0
    iso_path: Path | None = None
    cpu_pinning: str = ""  # e.g., "0-3" or "0,2,4"
    nic_model: str = "virtio"  # virtio, e1000, e1000e, rtl8139, vmxnet3
    audio_model: str = "none"  # none, ac97, ich6, ich9
    boot_devices: list[str] = field(default_factory=lambda: ["hd"])  # hd, cdrom, network

    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.state == VMState.RUNNING

    @property
    def is_stopped(self) -> bool:
        """Check if VM is stopped."""
        return self.state == VMState.SHUTOFF

    @property
    def can_start(self) -> bool:
        """Check if VM can be started."""
        return self.state in (VMState.SHUTOFF, VMState.CRASHED)

    @property
    def can_stop(self) -> bool:
        """Check if VM can be stopped."""
        return self.state in (VMState.RUNNING, VMState.PAUSED, VMState.BLOCKED)

    @property
    def memory_display(self) -> str:
        """Format memory for display."""
        if self.memory_mb >= 1024:
            return f"{self.memory_mb / 1024:.1f}G"
        return f"{self.memory_mb}M"
