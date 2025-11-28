"""GPU detection and IOMMU group service."""

import re
import subprocess
from pathlib import Path

from vm_manager.models import GPUDevice, IOMMUGroup


class GPUService:
    """Service for detecting GPUs and IOMMU groups."""

    def list_gpus(self) -> list[GPUDevice]:
        """List all GPUs available for passthrough."""
        devices: list[GPUDevice] = []

        try:
            result = subprocess.run(
                ["lspci", "-nn"],
                capture_output=True,
                text=True,
                check=True,
            )

            # Pattern: 0b:00.0 VGA compatible controller [0300]: Vendor Device [1002:67df]
            pattern = re.compile(
                r"^([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s+"
                r"(VGA compatible controller|3D controller|Display controller)"
                r"\s+\[([0-9a-f]{4})\]:\s+"
                r"(.+?)\s+\[([0-9a-f]{4}):([0-9a-f]{4})\]",
                re.IGNORECASE | re.MULTILINE,
            )

            for match in pattern.finditer(result.stdout):
                pci_addr = match.group(1)
                device_type = match.group(2)
                full_name = match.group(4)
                vendor_id = match.group(5)
                device_id = match.group(6)

                # Parse vendor and device name
                vendor_name, device_name = self._parse_device_name(full_name)

                # Get IOMMU group
                iommu_group = self._get_iommu_group(pci_addr)

                # Get current driver
                driver = self._get_driver(pci_addr)

                devices.append(GPUDevice(
                    pci_address=pci_addr,
                    vendor_id=vendor_id,
                    device_id=device_id,
                    vendor_name=vendor_name,
                    device_name=device_name,
                    iommu_group=iommu_group,
                    device_type=device_type.split()[0],  # "VGA", "3D", "Display"
                    driver=driver,
                ))

        except subprocess.CalledProcessError:
            pass
        except FileNotFoundError:
            pass

        # Sort by PCI address to ensure correct order (00.0 before 00.1, etc.)
        devices.sort(key=lambda d: d.pci_address)
        return devices

    def _parse_device_name(self, full_name: str) -> tuple[str, str]:
        """Parse vendor and device name from lspci output."""
        # Common patterns
        if "NVIDIA" in full_name.upper():
            vendor = "NVIDIA"
            device = full_name.replace("NVIDIA Corporation", "").strip()
        elif "AMD" in full_name.upper() or "ATI" in full_name.upper():
            vendor = "AMD"
            device = re.sub(
                r"Advanced Micro Devices,?\s*Inc\.?\s*\[AMD(/ATI)?\]",
                "",
                full_name
            ).strip()
        elif "Intel" in full_name:
            vendor = "Intel"
            device = full_name.replace("Intel Corporation", "").strip()
        else:
            parts = full_name.split(" ", 1)
            vendor = parts[0] if parts else "Unknown"
            device = parts[1] if len(parts) > 1 else full_name

        return vendor, device

    def _get_driver(self, pci_addr: str) -> str:
        """Get the current driver for a PCI device."""
        driver_path = Path(f"/sys/bus/pci/devices/0000:{pci_addr}/driver")

        if not driver_path.exists():
            return ""  # No driver bound

        try:
            # The driver symlink points to the driver module
            driver_link = driver_path.resolve()
            return driver_link.name
        except (ValueError, OSError):
            return ""

    def _get_iommu_group(self, pci_addr: str) -> int | None:
        """Get IOMMU group for a PCI device."""
        iommu_path = Path(f"/sys/bus/pci/devices/0000:{pci_addr}/iommu_group")

        if not iommu_path.exists():
            return None

        try:
            group_path = iommu_path.resolve()
            return int(group_path.name)
        except (ValueError, OSError):
            return None

    def get_iommu_group(self, pci_addr: str) -> IOMMUGroup | None:
        """Get IOMMU group with all its devices."""
        group_id = self._get_iommu_group(pci_addr)
        if group_id is None:
            return None

        group_path = Path(f"/sys/bus/pci/devices/0000:{pci_addr}/iommu_group/devices")
        if not group_path.exists():
            return None

        devices: list[GPUDevice] = []

        try:
            for device_link in group_path.iterdir():
                dev_addr = device_link.name.replace("0000:", "")

                # Get device info from lspci
                result = subprocess.run(
                    ["lspci", "-nn", "-s", dev_addr],
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0 and result.stdout:
                    line = result.stdout.strip()
                    # Parse the line
                    parts = line.split(" ", 1)
                    if len(parts) >= 2:
                        desc = parts[1]

                        # Extract vendor:device IDs
                        id_match = re.search(r"\[([0-9a-f]{4}):([0-9a-f]{4})\]", desc)
                        vendor_id = id_match.group(1) if id_match else "0000"
                        device_id = id_match.group(2) if id_match else "0000"

                        # Determine device type
                        if "VGA" in desc or "3D" in desc or "Display" in desc:
                            device_type = "VGA"
                        elif "Audio" in desc:
                            device_type = "Audio"
                        elif "USB" in desc:
                            device_type = "USB"
                        elif "Serial" in desc or "Communication" in desc:
                            device_type = "Serial"
                        else:
                            device_type = "Other"

                        # Parse name
                        name_match = re.search(r":\s+(.+?)\s+\[", desc)
                        full_name = name_match.group(1) if name_match else desc
                        vendor_name, device_name = self._parse_device_name(full_name)

                        devices.append(GPUDevice(
                            pci_address=dev_addr,
                            vendor_id=vendor_id,
                            device_id=device_id,
                            vendor_name=vendor_name,
                            device_name=device_name,
                            iommu_group=group_id,
                            device_type=device_type,
                        ))

        except OSError:
            pass

        return IOMMUGroup(group_id=group_id, devices=devices)

    def check_iommu_enabled(self) -> bool:
        """Check if IOMMU is enabled."""
        # Check for IOMMU groups
        iommu_groups = Path("/sys/kernel/iommu_groups")
        if not iommu_groups.exists():
            return False

        # Check if there are any groups
        try:
            groups = list(iommu_groups.iterdir())
            return len(groups) > 0
        except OSError:
            return False

    def get_gpu_by_address(self, pci_addr: str) -> GPUDevice | None:
        """Get a specific GPU by PCI address."""
        for gpu in self.list_gpus():
            if gpu.pci_address == pci_addr:
                return gpu
        return None
