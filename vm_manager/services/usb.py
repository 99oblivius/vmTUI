"""USB device detection service."""

import re
import subprocess

from vm_manager.models import USBDevice


class USBService:
    """Service for detecting USB devices for passthrough."""

    def list_devices(self) -> list[USBDevice]:
        """List all USB devices available for passthrough."""
        devices: list[USBDevice] = []

        try:
            result = subprocess.run(
                ["lsusb"],
                capture_output=True,
                text=True,
                check=True,
            )

            # Pattern: Bus 001 Device 002: ID 046d:c52b Logitech, Inc. Unifying Receiver
            pattern = re.compile(
                r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-f]{4}):([0-9a-f]{4})\s+(.+)",
                re.IGNORECASE,
            )

            for line in result.stdout.strip().split("\n"):
                match = pattern.match(line)
                if match:
                    bus = match.group(1)
                    device = match.group(2)
                    vendor_id = match.group(3)
                    product_id = match.group(4)
                    full_name = match.group(5).strip()

                    # Parse vendor and product name
                    vendor_name, product_name = self._parse_device_name(full_name)

                    # Skip root hubs and other system devices
                    if self._is_system_device(vendor_id, product_id, full_name):
                        continue

                    devices.append(USBDevice(
                        vendor_id=vendor_id,
                        product_id=product_id,
                        vendor_name=vendor_name,
                        product_name=product_name,
                        bus=bus,
                        device=device,
                    ))

        except subprocess.CalledProcessError:
            pass
        except FileNotFoundError:
            pass

        return devices

    def _parse_device_name(self, full_name: str) -> tuple[str, str]:
        """Parse vendor and product name from lsusb output."""
        # Common patterns: "Vendor, Inc. Product Name" or "Vendor Product"

        # Try to split on common separators
        if ", Inc." in full_name:
            parts = full_name.split(", Inc.", 1)
            vendor = parts[0].strip()
            product = parts[1].strip() if len(parts) > 1 else ""
        elif ", Ltd" in full_name:
            parts = full_name.split(", Ltd", 1)
            vendor = parts[0].strip()
            product = parts[1].strip(".").strip() if len(parts) > 1 else ""
        elif " - " in full_name:
            parts = full_name.split(" - ", 1)
            vendor = parts[0].strip()
            product = parts[1].strip() if len(parts) > 1 else ""
        else:
            # Split on first space that looks like a boundary
            parts = full_name.split(" ", 1)
            vendor = parts[0] if parts else "Unknown"
            product = parts[1] if len(parts) > 1 else full_name

        return vendor, product

    def _is_system_device(self, vendor_id: str, product_id: str, name: str) -> bool:
        """Check if this is a system device that shouldn't be passed through."""
        name_lower = name.lower()

        # Root hubs
        if "root hub" in name_lower:
            return True

        # Linux Foundation devices (virtual)
        if vendor_id == "1d6b":
            return True

        return False

    def get_device_by_id(self, id_string: str) -> USBDevice | None:
        """Get a specific USB device by vendor:product ID."""
        for device in self.list_devices():
            if device.id_string == id_string:
                return device
        return None
