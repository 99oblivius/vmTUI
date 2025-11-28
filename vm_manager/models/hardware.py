"""Hardware-related models."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiskInfo:
    """Disk information."""

    path: Path
    device: str  # e.g., "vda", "sda"
    format: str  # e.g., "qcow2", "raw"
    size_bytes: int
    used_bytes: int = 0

    @property
    def size_display(self) -> str:
        """Format size for display."""
        gb = self.size_bytes / (1024**3)
        if gb >= 1:
            return f"{gb:.1f} GB"
        mb = self.size_bytes / (1024**2)
        return f"{mb:.1f} MB"


@dataclass
class MemoryInfo:
    """Memory information."""

    total_kb: int
    used_kb: int = 0
    available_kb: int = 0

    @property
    def percent_used(self) -> float:
        """Percentage of memory used."""
        if self.total_kb == 0:
            return 0.0
        return (self.used_kb / self.total_kb) * 100


@dataclass
class NetworkInterface:
    """Network interface information."""

    name: str  # e.g., "vnet0"
    mac_address: str
    network: str  # e.g., "default"
    model: str  # e.g., "virtio"
    bridge: str | None = None


@dataclass
class GPUDevice:
    """GPU/PCI device for passthrough."""

    pci_address: str  # e.g., "0b:00.0"
    vendor_id: str  # e.g., "1002"
    device_id: str  # e.g., "67df"
    vendor_name: str  # e.g., "AMD"
    device_name: str  # e.g., "Radeon RX 580"
    iommu_group: int | None = None
    device_type: str = "VGA"  # VGA, 3D, Audio, etc.
    driver: str = ""  # Current driver: vfio-pci, nvidia, amdgpu, etc.

    @property
    def is_vfio_bound(self) -> bool:
        """Check if GPU is bound to vfio-pci driver."""
        return self.driver == "vfio-pci"

    @property
    def can_passthrough(self) -> bool:
        """Check if GPU can be used for passthrough."""
        # vfio-pci or no driver (unbound) are OK
        return self.driver in ("vfio-pci", "")

    @property
    def display_name(self) -> str:
        """Format for display."""
        return f"{self.vendor_name} {self.device_name}"

    @property
    def full_description(self) -> str:
        """Full description with PCI address."""
        return f"[{self.pci_address}] {self.display_name}"


@dataclass
class IOMMUGroup:
    """IOMMU group containing related devices."""

    group_id: int
    devices: list[GPUDevice] = field(default_factory=list)

    @property
    def pci_addresses(self) -> list[str]:
        """Get all PCI addresses in this group."""
        return [dev.pci_address for dev in self.devices]


@dataclass
class USBDevice:
    """USB device for passthrough."""

    vendor_id: str  # e.g., "046d"
    product_id: str  # e.g., "c52b"
    vendor_name: str  # e.g., "Logitech"
    product_name: str  # e.g., "Wireless Mouse"
    bus: str = ""
    device: str = ""

    @property
    def id_string(self) -> str:
        """Get vendor:product ID string."""
        return f"{self.vendor_id}:{self.product_id}"

    @property
    def display_name(self) -> str:
        """Format for display."""
        return f"{self.vendor_name} {self.product_name}"

    @property
    def full_description(self) -> str:
        """Full description with IDs."""
        return f"[{self.id_string}] {self.display_name}"
