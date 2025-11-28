"""Libvirt service for managing VMs."""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import libvirt

from vm_manager.config import DISK_DIR, LIBVIRT_URI
from vm_manager.models import Snapshot, VM, VMConfig, VMState, VMStats


class LibvirtError(Exception):
    """Libvirt operation error."""

    pass


class LibvirtService:
    """Service for interacting with libvirt."""

    def __init__(self, uri: str = LIBVIRT_URI) -> None:
        self._uri = uri
        self._conn: libvirt.virConnect | None = None

    def connect(self) -> None:
        """Connect to libvirt."""
        import subprocess

        # Register global error handler to suppress libvirt error messages
        def libvirt_error_handler(ctx, err):
            pass  # Ignore all libvirt errors

        libvirt.registerErrorHandler(libvirt_error_handler, None)

        # First check if libvirtd is responsive with a timeout
        try:
            result = subprocess.run(
                ["virsh", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise LibvirtError("libvirtd not responding. Try: sudo systemctl restart libvirtd")
        except subprocess.TimeoutExpired:
            raise LibvirtError("libvirtd timeout. Try: sudo systemctl restart libvirtd")
        except FileNotFoundError:
            raise LibvirtError("virsh not found. Install libvirt-clients.")

        try:
            self._conn = libvirt.open(self._uri)
            if self._conn is None:
                raise LibvirtError(f"Failed to connect to {self._uri}")
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Connection failed: {e}") from e

    def disconnect(self) -> None:
        """Disconnect from libvirt."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> libvirt.virConnect:
        """Get connection, connecting if needed."""
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    def list_vms(self) -> list[VM]:
        """List all VMs."""
        vms: list[VM] = []

        # Get all domains (running and defined)
        try:
            domains = self.conn.listAllDomains()
            if not domains:
                return []
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to list VMs: {e}") from e

        for domain in domains:
            try:
                vm = self._domain_to_vm(domain)
                vms.append(vm)
            except Exception:
                # Skip VMs we can't parse
                continue

        return sorted(vms, key=lambda v: v.name.lower()) if vms else []

    def get_vm(self, name: str) -> VM:
        """Get a specific VM by name."""
        try:
            domain = self.conn.lookupByName(name)
            return self._domain_to_vm(domain)
        except libvirt.libvirtError as e:
            raise LibvirtError(f"VM '{name}' not found: {e}") from e

    def _domain_to_vm(self, domain: libvirt.virDomain) -> VM:
        """Convert libvirt domain to VM model."""
        state, _ = domain.state()
        info = domain.info()

        # Parse XML for details
        xml_str = domain.XMLDesc()
        xml = ET.fromstring(xml_str)

        # Get disks
        disks: list[Path] = []
        for disk in xml.findall(".//disk[@device='disk']/source"):
            file_path = disk.get("file")
            if file_path:
                disks.append(Path(file_path))

        # Get ISO/CDROM path
        iso_path: Path | None = None
        cdrom = xml.find(".//disk[@device='cdrom']/source")
        if cdrom is not None:
            iso_file = cdrom.get("file")
            if iso_file:
                iso_path = Path(iso_file)

        # Get networks and NIC model
        networks: list[str] = []
        nic_model = "virtio"  # default
        for iface in xml.findall(".//interface"):
            source = iface.find("source")
            if source is not None:
                # Check for libvirt network
                network = source.get("network")
                if network:
                    networks.append(network)
                # Check for bridge interface
                bridge = source.get("bridge")
                if bridge:
                    networks.append(bridge)
            # Get NIC model
            model = iface.find("model")
            if model is not None:
                nic_model = model.get("type", "virtio")

        # Get audio model
        audio_model = "none"
        sound = xml.find(".//sound")
        if sound is not None:
            audio_model = sound.get("model", "ich9")

        # Get boot devices
        boot_devices: list[str] = []
        for boot in xml.findall(".//os/boot"):
            dev = boot.get("dev")
            if dev:
                boot_devices.append(dev)
        if not boot_devices:
            boot_devices = ["hd"]  # default

        # Get graphics type and port
        graphics_type = "none"
        graphics_port: int | None = None
        graphics_listen = "0.0.0.0"

        # Check for SPICE first, then VNC
        graphics = xml.find(".//graphics[@type='spice']")
        if graphics is not None:
            graphics_type = "spice"
        else:
            graphics = xml.find(".//graphics[@type='vnc']")
            if graphics is not None:
                graphics_type = "vnc"

        if graphics is not None:
            port = graphics.get("port")
            if port and port != "-1":
                graphics_port = int(port)
            listen = graphics.get("listen")
            if listen:
                graphics_listen = listen

        # Get GPU devices (hostdev type=pci)
        gpu_devices: list[str] = []
        for hostdev in xml.findall(".//hostdev[@type='pci']"):
            addr = hostdev.find(".//source/address")
            if addr is not None:
                bus = addr.get("bus", "0x00").replace("0x", "")
                slot = addr.get("slot", "0x00").replace("0x", "")
                func = addr.get("function", "0x0").replace("0x", "")
                pci_addr = f"{bus}:{slot}.{func}"
                gpu_devices.append(pci_addr)

        # Get USB devices (hostdev type=usb)
        usb_devices: list[str] = []
        for hostdev in xml.findall(".//hostdev[@type='usb']"):
            source = hostdev.find(".//source")
            if source is not None:
                vendor = source.find("vendor")
                product = source.find("product")
                if vendor is not None and product is not None:
                    vendor_id = vendor.get("id", "0x0000").replace("0x", "")
                    product_id = product.get("id", "0x0000").replace("0x", "")
                    usb_devices.append(f"{vendor_id}:{product_id}")

        # Get autostart
        try:
            autostart = bool(domain.autostart())
        except libvirt.libvirtError:
            autostart = False

        # Get snapshot count
        try:
            snapshot_count = domain.snapshotNum()
        except libvirt.libvirtError:
            snapshot_count = 0

        # Get stats if running
        stats = VMStats()
        if state == libvirt.VIR_DOMAIN_RUNNING:
            stats = self._get_vm_stats(domain, info)

        return VM(
            name=domain.name(),
            uuid=domain.UUIDString(),
            state=VMState(state),
            vcpus=info[3],
            memory_mb=info[2] // 1024,
            autostart=autostart,
            persistent=domain.isPersistent(),
            disks=disks,
            networks=networks,
            graphics_type=graphics_type,
            graphics_port=graphics_port,
            graphics_listen=graphics_listen,
            gpu_devices=gpu_devices,
            usb_devices=usb_devices,
            stats=stats,
            snapshot_count=snapshot_count,
            iso_path=iso_path,
            nic_model=nic_model,
            audio_model=audio_model,
            boot_devices=boot_devices,
        )

    def _get_vm_stats(self, domain: libvirt.virDomain, info: list[Any]) -> VMStats:
        """Get runtime statistics for a VM."""
        stats = VMStats()

        try:
            # CPU time
            stats.cpu_time_ns = info[4]

            # Memory stats
            mem_stats = domain.memoryStats()
            if "actual" in mem_stats:
                stats.memory_used_kb = mem_stats.get("actual", 0)
            if "available" in mem_stats:
                total = mem_stats.get("available", 0)
                used = stats.memory_used_kb
                if total > 0:
                    stats.memory_percent = (used / total) * 100

            # Block stats
            xml_str = domain.XMLDesc()
            xml = ET.fromstring(xml_str)
            for disk in xml.findall(".//disk[@device='disk']/target"):
                dev = disk.get("dev")
                if dev:
                    try:
                        block_stats = domain.blockStats(dev)
                        stats.disk_read_bytes += block_stats[1]
                        stats.disk_write_bytes += block_stats[3]
                    except libvirt.libvirtError:
                        pass

            # Network stats
            for iface in xml.findall(".//interface/target"):
                dev = iface.get("dev")
                if dev:
                    try:
                        net_stats = domain.interfaceStats(dev)
                        stats.net_rx_bytes += net_stats[0]
                        stats.net_tx_bytes += net_stats[4]
                    except libvirt.libvirtError:
                        pass

        except libvirt.libvirtError:
            pass

        return stats

    def create_vm(self, config: VMConfig) -> None:
        """Create and define a new VM."""
        # Create disk if needed
        if config.disk_path is None:
            config.disk_path = DISK_DIR / f"{config.name}.qcow2"

        if not config.disk_path.exists():
            self._create_disk(config.disk_path, config.disk_size_gb)

        # Generate XML
        xml = self._generate_vm_xml(config)

        # Define the domain
        try:
            domain = self.conn.defineXML(xml)
            if domain is None:
                raise LibvirtError("Failed to define VM")

            # Set autostart if requested
            if config.autostart:
                domain.setAutostart(True)

        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to create VM: {e}") from e

    def _create_disk(self, path: Path, size_gb: int) -> None:
        """Create a qcow2 disk image."""
        import subprocess

        path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(path), f"{size_gb}G"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise LibvirtError(f"Failed to create disk: {result.stderr}")

    def get_disk_info(self, disk_path: Path) -> tuple[int, int] | None:
        """Get disk actual and virtual size in bytes using qemu-img info.

        Returns (actual_size, virtual_size) or None if failed.
        """
        import json
        import subprocess

        if not disk_path.exists():
            return None

        try:
            result = subprocess.run(
                ["qemu-img", "info", "--output=json", str(disk_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return None

            info = json.loads(result.stdout)
            actual_size = info.get("actual-size", 0)
            virtual_size = info.get("virtual-size", 0)
            return (actual_size, virtual_size)

        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
            return None

    def _generate_network_xml(self, config: VMConfig) -> str:
        """Generate network interface XML based on network type."""
        if config.network_type == "bridge":
            return f"""<interface type="bridge">
      <source bridge="{config.network}"/>
      <model type="{config.nic_model}"/>
    </interface>"""
        else:
            return f"""<interface type="network">
      <source network="{config.network}"/>
      <model type="{config.nic_model}"/>
    </interface>"""

    def _generate_vm_xml(self, config: VMConfig) -> str:
        """Generate libvirt XML for a VM configuration."""
        # Determine graphics settings
        if config.graphics == "none":
            graphics_xml = ""
        elif config.graphics == "spice":
            graphics_xml = """<graphics type="spice" port="-1" autoport="yes" listen="0.0.0.0">
      <listen type="address" address="0.0.0.0"/>
    </graphics>
    <channel type="spicevmc">
      <target type="virtio" name="com.redhat.spice.0"/>
    </channel>"""
        else:  # vnc
            graphics_xml = '<graphics type="vnc" port="-1" autoport="yes" listen="0.0.0.0"/>'

        # Build hostdev entries for GPU passthrough
        hostdev_xml = ""
        for pci_addr in config.gpu_devices:
            parts = pci_addr.replace(".", ":").split(":")
            if len(parts) >= 3:
                bus = parts[0]
                slot = parts[1]
                func = parts[2] if len(parts) > 2 else "0"
                hostdev_xml += f"""
    <hostdev mode="subsystem" type="pci" managed="yes">
      <source>
        <address domain="0x0000" bus="0x{bus}" slot="0x{slot}" function="0x{func}"/>
      </source>
    </hostdev>"""

        # CDROM if ISO provided
        cdrom_xml = ""
        if config.iso_path:
            cdrom_xml = f"""
    <disk type="file" device="cdrom">
      <driver name="qemu" type="raw"/>
      <source file="{config.iso_path}"/>
      <target dev="sda" bus="sata"/>
      <readonly/>
    </disk>"""

        # Audio device
        audio_xml = ""
        if config.audio_model and config.audio_model != "none":
            audio_xml = f"""
    <sound model="{config.audio_model}">
      <codec type="duplex"/>
    </sound>"""

        # USB passthrough
        usb_hostdev_xml = ""
        for usb_id in config.usb_devices:
            parts = usb_id.split(":")
            if len(parts) == 2:
                vendor_id = parts[0]
                product_id = parts[1]
                usb_hostdev_xml += f"""
    <hostdev mode="subsystem" type="usb" managed="yes">
      <source>
        <vendor id="0x{vendor_id}"/>
        <product id="0x{product_id}"/>
      </source>
    </hostdev>"""

        # CPU pinning
        cputune_xml = ""
        if config.cpu_pinning:
            # Parse CPU pinning string (e.g., "0-3" or "0,2,4,6")
            cpus: list[int] = []
            for part in config.cpu_pinning.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    cpus.extend(range(int(start), int(end) + 1))
                else:
                    cpus.append(int(part))

            # Generate vcpupin elements
            if cpus:
                pin_lines = []
                for i in range(config.vcpus):
                    # Map vCPU to physical CPU (round-robin if more vCPUs than pinned CPUs)
                    pcpu = cpus[i % len(cpus)]
                    pin_lines.append(f'    <vcpupin vcpu="{i}" cpuset="{pcpu}"/>')
                cputune_xml = "\n  <cputune>\n" + "\n".join(pin_lines) + "\n  </cputune>"

        # Determine boot order
        if config.iso_path:
            # Boot from CDROM first (for installation), then HD
            boot_xml = """<boot dev="cdrom"/>
    <boot dev="hd"/>"""
        else:
            # Boot from HD only
            boot_xml = f'<boot dev="{config.boot_device}"/>'

        xml = f"""<domain type="kvm">
  <name>{config.name}</name>
  <memory unit="MiB">{config.memory_mb}</memory>
  <vcpu placement="static">{config.vcpus}</vcpu>{cputune_xml}
  <os>
    <type arch="x86_64" machine="q35">hvm</type>
    {boot_xml}
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <cpu mode="host-passthrough"/>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type="file" device="disk">
      <driver name="qemu" type="qcow2"/>
      <source file="{config.disk_path}"/>
      <target dev="vda" bus="virtio"/>
    </disk>{cdrom_xml}
    {self._generate_network_xml(config)}
    {graphics_xml}
    <video>
      <model type="virtio"/>
    </video>
    <serial type="pty">
      <target port="0"/>
    </serial>
    <console type="pty">
      <target type="serial" port="0"/>
    </console>
    <serial type="file">
      <source path="/var/log/libvirt/qemu/{config.name}-console.log"/>
      <target port="1"/>
    </serial>
    <channel type="unix">
      <target type="virtio" name="org.qemu.guest_agent.0"/>
    </channel>{hostdev_xml}{audio_xml}{usb_hostdev_xml}
  </devices>
</domain>"""
        return xml

    def delete_vm(self, name: str, remove_storage: bool = True) -> None:
        """Delete a VM and optionally its storage."""
        try:
            domain = self.conn.lookupByName(name)

            # Get disk paths before undefining
            disks: list[Path] = []
            if remove_storage:
                xml_str = domain.XMLDesc()
                xml = ET.fromstring(xml_str)
                for disk in xml.findall(".//disk[@device='disk']/source"):
                    file_path = disk.get("file")
                    if file_path:
                        disks.append(Path(file_path))

            # Stop if running
            state, _ = domain.state()
            if state == libvirt.VIR_DOMAIN_RUNNING:
                domain.destroy()

            # Remove snapshots
            try:
                snapshots = domain.listAllSnapshots()
                for snap in snapshots:
                    snap.delete()
            except libvirt.libvirtError:
                pass

            # Undefine
            try:
                domain.undefineFlags(
                    libvirt.VIR_DOMAIN_UNDEFINE_NVRAM |
                    libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
                )
            except libvirt.libvirtError:
                domain.undefine()

            # Remove storage
            if remove_storage:
                for disk in disks:
                    if disk.exists():
                        disk.unlink()

        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to delete VM: {e}") from e

    def start_vm(self, name: str) -> None:
        """Start a VM, recreating missing storage if needed."""
        try:
            domain = self.conn.lookupByName(name)

            # Check for missing storage and recreate if needed
            xml_str = domain.XMLDesc()
            xml = ET.fromstring(xml_str)

            for disk in xml.findall(".//disk[@device='disk']/source"):
                file_path = disk.get("file")
                if file_path:
                    disk_path = Path(file_path)
                    if not disk_path.exists():
                        # Get disk size from domain config or use default
                        # Try to determine size from filename or use 20GB default
                        self._create_disk(disk_path, 20)

            domain.create()
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to start VM: {e}") from e

    def delete_storage(self, name: str) -> None:
        """Delete storage for a VM without removing the VM definition."""
        try:
            domain = self.conn.lookupByName(name)

            # Get disk paths
            xml_str = domain.XMLDesc()
            xml = ET.fromstring(xml_str)

            deleted_count = 0
            for disk in xml.findall(".//disk[@device='disk']/source"):
                file_path = disk.get("file")
                if file_path:
                    disk_path = Path(file_path)
                    if disk_path.exists():
                        disk_path.unlink()
                        deleted_count += 1

            if deleted_count == 0:
                raise LibvirtError("No storage files found to delete")

        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to delete storage: {e}") from e

    def stop_vm(self, name: str, force: bool = False) -> None:
        """Stop a VM."""
        try:
            domain = self.conn.lookupByName(name)
            if force:
                domain.destroy()
            else:
                domain.shutdown()
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to stop VM: {e}") from e

    def pause_vm(self, name: str) -> None:
        """Pause a VM."""
        try:
            domain = self.conn.lookupByName(name)
            domain.suspend()
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to pause VM: {e}") from e

    def resume_vm(self, name: str) -> None:
        """Resume a paused VM."""
        try:
            domain = self.conn.lookupByName(name)
            domain.resume()
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to resume VM: {e}") from e

    def set_autostart(self, name: str, enabled: bool) -> None:
        """Set VM autostart."""
        try:
            domain = self.conn.lookupByName(name)
            domain.setAutostart(enabled)
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set autostart: {e}") from e

    def set_vcpus(self, name: str, vcpus: int) -> None:
        """Set VM vCPU count (requires restart)."""
        try:
            domain = self.conn.lookupByName(name)
            domain.setVcpusFlags(
                vcpus,
                libvirt.VIR_DOMAIN_AFFECT_CONFIG | libvirt.VIR_DOMAIN_VCPU_MAXIMUM
            )
            domain.setVcpusFlags(vcpus, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set vCPUs: {e}") from e

    def set_memory(self, name: str, memory_mb: int) -> None:
        """Set VM memory (requires restart)."""
        try:
            domain = self.conn.lookupByName(name)
            memory_kb = memory_mb * 1024
            domain.setMaxMemory(memory_kb)
            domain.setMemoryFlags(memory_kb, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set memory: {e}") from e

    def set_graphics(self, name: str, graphics_type: str) -> None:
        """Set VM graphics type (requires restart)."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Remove existing graphics
            for graphics in devices.findall("graphics"):
                devices.remove(graphics)

            # Remove spicevmc channels (only valid with SPICE graphics)
            for channel in devices.findall("channel[@type='spicevmc']"):
                devices.remove(channel)

            # Remove SPICE-specific audio elements
            for audio in devices.findall("audio[@type='spice']"):
                devices.remove(audio)

            # Remove all audio elements to reconfigure properly
            for audio in devices.findall("audio"):
                devices.remove(audio)

            # Update sound devices to reference the new audio backend
            for sound in devices.findall("sound"):
                # Remove existing audio attribute if present
                if "audio" in sound.attrib:
                    del sound.attrib["audio"]

            # Add new graphics if not "none"
            if graphics_type and graphics_type != "none":
                graphics = ET.SubElement(devices, "graphics")
                graphics.set("type", graphics_type)
                graphics.set("autoport", "yes")
                graphics.set("listen", "0.0.0.0")

                listen = ET.SubElement(graphics, "listen")
                listen.set("type", "address")
                listen.set("address", "0.0.0.0")

                if graphics_type == "spice":
                    # Add spicevmc channel for SPICE (clipboard/USB redirection)
                    channel = ET.SubElement(devices, "channel")
                    channel.set("type", "spicevmc")
                    target = ET.SubElement(channel, "target")
                    target.set("type", "virtio")
                    target.set("name", "com.redhat.spice.0")

                    # Add SPICE audio backend
                    audio = ET.SubElement(devices, "audio")
                    audio.set("id", "1")
                    audio.set("type", "spice")

                    # Link sound devices to SPICE audio
                    for sound in devices.findall("sound"):
                        sound.set("audio", "1")

                # VNC doesn't need an audio element - sound will use default backend

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set graphics: {e}") from e

    def set_network(self, name: str, network: str, nic_model: str = "virtio") -> None:
        """Set VM network interface (requires restart)."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Remove existing interfaces
            for iface in devices.findall("interface"):
                devices.remove(iface)

            # Parse network type
            if network.startswith("bridge:"):
                net_type = "bridge"
                net_name = network.split(":", 1)[1]
            elif network.startswith("network:"):
                net_type = "network"
                net_name = network.split(":", 1)[1]
            else:
                net_type = "network"
                net_name = network

            # Add new interface
            iface = ET.SubElement(devices, "interface")
            iface.set("type", net_type)
            source = ET.SubElement(iface, "source")
            if net_type == "bridge":
                source.set("bridge", net_name)
            else:
                source.set("network", net_name)
            model = ET.SubElement(iface, "model")
            model.set("type", nic_model)

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set network: {e}") from e

    def set_audio(self, name: str, audio_type: str) -> None:
        """Set VM audio device (requires restart)."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Remove existing sound devices
            for sound in devices.findall("sound"):
                devices.remove(sound)

            # Add new sound if not "none"
            if audio_type and audio_type != "none":
                sound = ET.SubElement(devices, "sound")
                sound.set("model", audio_type)

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set audio: {e}") from e

    def set_gpu_passthrough(self, name: str, gpu_devices: list[str]) -> None:
        """Set VM GPU passthrough devices (requires restart)."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Remove existing PCI hostdev entries (GPUs)
            for hostdev in devices.findall("hostdev[@type='pci']"):
                devices.remove(hostdev)

            # Add new GPU devices
            for pci_addr in gpu_devices:
                # Parse PCI address (format: 01:00.0)
                parts = pci_addr.replace(".", ":").split(":")
                if len(parts) >= 3:
                    bus = parts[0]
                    slot = parts[1]
                    func = parts[2] if len(parts) > 2 else "0"

                    hostdev = ET.SubElement(devices, "hostdev")
                    hostdev.set("mode", "subsystem")
                    hostdev.set("type", "pci")
                    hostdev.set("managed", "yes")

                    source = ET.SubElement(hostdev, "source")
                    address = ET.SubElement(source, "address")
                    address.set("domain", "0x0000")
                    address.set("bus", f"0x{bus}")
                    address.set("slot", f"0x{slot}")
                    address.set("function", f"0x{func}")

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set GPU passthrough: {e}") from e

    def get_xml(self, name: str) -> str:
        """Get VM XML configuration."""
        try:
            domain = self.conn.lookupByName(name)
            return domain.XMLDesc()
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to get XML: {e}") from e

    def eject_iso(self, name: str) -> None:
        """Eject ISO from VM's CDROM drive."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Find CDROM and remove source
            cdrom = devices.find(".//disk[@device='cdrom']")
            if cdrom is not None:
                source = cdrom.find("source")
                if source is not None:
                    cdrom.remove(source)

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to eject ISO: {e}") from e

    def attach_iso(self, name: str, iso_path: Path) -> None:
        """Attach ISO to VM's CDROM drive."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Find or create CDROM
            cdrom = devices.find(".//disk[@device='cdrom']")
            if cdrom is None:
                # Create CDROM device
                cdrom = ET.SubElement(devices, "disk")
                cdrom.set("type", "file")
                cdrom.set("device", "cdrom")
                driver = ET.SubElement(cdrom, "driver")
                driver.set("name", "qemu")
                driver.set("type", "raw")
                target = ET.SubElement(cdrom, "target")
                target.set("dev", "sda")
                target.set("bus", "sata")
                ET.SubElement(cdrom, "readonly")

            # Remove old source if exists
            old_source = cdrom.find("source")
            if old_source is not None:
                cdrom.remove(old_source)

            # Add new source
            source = ET.SubElement(cdrom, "source")
            source.set("file", str(iso_path))

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to attach ISO: {e}") from e

    def set_boot_order(self, name: str, boot_devices: list[str]) -> None:
        """Set VM boot order. boot_devices is list like ['hd', 'cdrom']."""
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            os_elem = xml.find("os")
            if os_elem is None:
                raise LibvirtError("No os section in VM XML")

            # Remove existing boot entries
            for boot in os_elem.findall("boot"):
                os_elem.remove(boot)

            # Add new boot entries in order
            for dev in boot_devices:
                boot = ET.SubElement(os_elem, "boot")
                boot.set("dev", dev)

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set boot order: {e}") from e

    def get_usb_device_usage(self) -> dict[str, str]:
        """Get mapping of USB device IDs to VM names that use them.

        Returns dict like {'046d:c52b': 'win10-vm', '1234:5678': 'ubuntu-vm'}
        """
        usage: dict[str, str] = {}

        try:
            for vm in self.list_vms():
                for usb_id in vm.usb_devices:
                    usage[usb_id] = vm.name
        except libvirt.libvirtError:
            pass

        return usage

    def get_gpu_device_usage(self) -> dict[str, str]:
        """Get mapping of GPU PCI addresses to VM names that use them.

        Returns dict like {'0b:00.0': 'gaming-vm', '0b:00.1': 'gaming-vm'}
        """
        usage: dict[str, str] = {}

        try:
            for vm in self.list_vms():
                for pci_addr in vm.gpu_devices:
                    usage[pci_addr] = vm.name
        except libvirt.libvirtError:
            pass

        return usage

    def set_usb_passthrough(self, name: str, usb_device_ids: list[str]) -> None:
        """Set USB device passthrough for a VM.

        Args:
            name: VM name
            usb_device_ids: List of USB device IDs in format "vendor_id:product_id" (e.g. "046d:c52b")
        """
        try:
            domain = self.conn.lookupByName(name)
            xml = ET.fromstring(domain.XMLDesc())
            devices = xml.find("devices")
            if devices is None:
                raise LibvirtError("No devices section in VM XML")

            # Remove existing USB hostdev entries
            for hostdev in devices.findall("hostdev[@type='usb']"):
                devices.remove(hostdev)

            # Add new USB hostdev entries
            for usb_id in usb_device_ids:
                parts = usb_id.split(":")
                if len(parts) != 2:
                    continue

                vendor_id, product_id = parts

                hostdev = ET.SubElement(devices, "hostdev")
                hostdev.set("mode", "subsystem")
                hostdev.set("type", "usb")
                hostdev.set("managed", "yes")

                source = ET.SubElement(hostdev, "source")
                vendor = ET.SubElement(source, "vendor")
                vendor.set("id", f"0x{vendor_id}")
                product = ET.SubElement(source, "product")
                product.set("id", f"0x{product_id}")

            # Update domain
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to set USB passthrough: {e}") from e

    def get_console_output(self, name: str, max_lines: int = 50) -> list[str]:
        """Get recent console output from a VM."""
        import subprocess

        try:
            # Use virsh to get console log
            # First check if VM has a serial console log file
            result = subprocess.run(
                ["virsh", "dumpxml", name],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return []

            # Check for console log file in XML
            xml = ET.fromstring(result.stdout)
            console_log = None

            # Look for serial console with log file
            for serial in xml.findall(".//serial/log"):
                log_file = serial.get("file")
                if log_file:
                    console_log = Path(log_file)
                    break

            # Also check console elements
            for console in xml.findall(".//console/log"):
                log_file = console.get("file")
                if log_file:
                    console_log = Path(log_file)
                    break

            if console_log and console_log.exists():
                # Read last N lines from log file
                with open(console_log) as f:
                    lines = f.readlines()
                    return [line.rstrip() for line in lines[-max_lines:]]

            # Try default log paths
            for log_name in [f"{name}-console.log", f"{name}-serial.log"]:
                default_log = Path(f"/var/log/libvirt/qemu/{log_name}")
                if default_log.exists():
                    with open(default_log) as f:
                        lines = f.readlines()
                        return [line.rstrip() for line in lines[-max_lines:]]

            return []

        except subprocess.TimeoutExpired:
            return ["Console read timed out"]
        except Exception:
            return []

    def list_networks(self) -> list[str]:
        """List available networks."""
        try:
            networks = self.conn.listAllNetworks()
            return [net.name() for net in networks]
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to list networks: {e}") from e

    # Snapshot operations
    def list_snapshots(self, name: str) -> list[Snapshot]:
        """List snapshots for a VM."""
        try:
            domain = self.conn.lookupByName(name)
            snapshots: list[Snapshot] = []

            try:
                current = domain.snapshotCurrent()
                current_name = current.getName() if current else None
            except libvirt.libvirtError:
                current_name = None

            all_snaps = domain.listAllSnapshots()

            for snap in all_snaps:
                xml_str = snap.getXMLDesc()
                xml = ET.fromstring(xml_str)

                desc_elem = xml.find("description")
                description = desc_elem.text if desc_elem is not None and desc_elem.text else ""

                time_elem = xml.find("creationTime")
                created_at = datetime.fromtimestamp(
                    int(time_elem.text) if time_elem is not None and time_elem.text else 0
                )

                state_elem = xml.find("state")
                state = state_elem.text if state_elem is not None and state_elem.text else "unknown"

                parent_elem = xml.find("parent/name")
                parent = parent_elem.text if parent_elem is not None else None

                snapshots.append(Snapshot(
                    name=snap.getName(),
                    description=description,
                    created_at=created_at,
                    state=state,
                    parent=parent,
                    is_current=snap.getName() == current_name,
                ))

            return sorted(snapshots, key=lambda s: s.created_at, reverse=True)

        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to list snapshots: {e}") from e

    def create_snapshot(self, name: str, snap_name: str, description: str = "") -> None:
        """Create a snapshot."""
        try:
            domain = self.conn.lookupByName(name)
            xml = f"""<domainsnapshot>
  <name>{snap_name}</name>
  <description>{description}</description>
</domainsnapshot>"""
            domain.snapshotCreateXML(xml)
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to create snapshot: {e}") from e

    def revert_snapshot(self, name: str, snap_name: str) -> None:
        """Revert to a snapshot."""
        try:
            domain = self.conn.lookupByName(name)
            snapshot = domain.snapshotLookupByName(snap_name)
            domain.revertToSnapshot(snapshot)
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to revert snapshot: {e}") from e

    def delete_snapshot(self, name: str, snap_name: str) -> None:
        """Delete a snapshot."""
        try:
            domain = self.conn.lookupByName(name)
            snapshot = domain.snapshotLookupByName(snap_name)
            snapshot.delete()
        except libvirt.libvirtError as e:
            raise LibvirtError(f"Failed to delete snapshot: {e}") from e

    # Checkpoint operations (disk clones)
    def create_checkpoint(self, vm_name: str, checkpoint_name: str, description: str = "") -> bool:
        """Create checkpoint by copying VM disk.

        Returns True on success, False on failure.
        """
        import json
        import shutil
        import subprocess

        try:
            domain = self.conn.lookupByName(vm_name)

            # Get current disk path
            xml_str = domain.XMLDesc()
            xml = ET.fromstring(xml_str)
            disk_elem = xml.find(".//disk[@device='disk']/source")
            if disk_elem is None:
                return False

            disk_path = Path(disk_elem.get("file", ""))
            if not disk_path.exists():
                return False

            # Create checkpoint directory
            checkpoint_dir = DISK_DIR / "checkpoints" / vm_name
            checkpoint_dir.mkdir(parents=True, exist_ok=True)

            # Checkpoint disk filename
            checkpoint_disk = checkpoint_dir / f"{checkpoint_name}.qcow2"
            if checkpoint_disk.exists():
                return False  # Already exists

            # Copy disk file
            shutil.copy2(disk_path, checkpoint_disk)

            # Save metadata
            metadata = {
                "name": checkpoint_name,
                "description": description,
                "created": datetime.now().isoformat(),
                "original_disk": str(disk_path),
                "vm_name": vm_name,
            }

            metadata_file = checkpoint_dir / f"{checkpoint_name}.json"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            return True

        except (libvirt.libvirtError, OSError, IOError):
            return False

    def list_checkpoints(self, vm_name: str) -> list[tuple[str, str, bool]]:
        """List all checkpoints for a VM.

        Returns list of (name, created_timestamp, is_active).
        """
        import json

        checkpoints: list[tuple[str, str, bool]] = []

        try:
            # Get persistent disk path to determine active checkpoint
            # Use INACTIVE flag to get the disk that will be used on next boot
            domain = self.conn.lookupByName(vm_name)
            xml_str = domain.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
            xml = ET.fromstring(xml_str)
            disk_elem = xml.find(".//disk[@device='disk']/source")
            current_disk = Path(disk_elem.get("file", "")) if disk_elem is not None else None

            # Find checkpoint directory
            checkpoint_dir = DISK_DIR / "checkpoints" / vm_name
            if not checkpoint_dir.exists():
                return []

            # Read all checkpoint metadata files
            for metadata_file in checkpoint_dir.glob("*.json"):
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)

                    name = metadata.get("name", metadata_file.stem)
                    created = metadata.get("created", "")
                    checkpoint_disk = checkpoint_dir / f"{name}.qcow2"

                    # Check if this is the active checkpoint
                    is_active = current_disk == checkpoint_disk

                    # Format timestamp for display
                    try:
                        dt = datetime.fromisoformat(created)
                        created_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, AttributeError):
                        created_str = created

                    checkpoints.append((name, created_str, is_active))

                except (json.JSONDecodeError, OSError):
                    continue

            # Sort by creation time (newest first)
            checkpoints.sort(key=lambda x: x[1], reverse=True)
            return checkpoints

        except libvirt.libvirtError:
            return []

    def switch_checkpoint(self, vm_name: str, checkpoint_name: str) -> bool:
        """Switch VM to use checkpoint disk.

        All disk states are kept in the checkpoints directory. The active checkpoint
        is determined by which one the VM XML points to. This ensures all states
        are preserved and can be switched between freely.
        Only updates the configuration - VM must be restarted for changes to take effect.
        Returns True on success.
        """
        import json
        import shutil

        try:
            domain = self.conn.lookupByName(vm_name)

            # Get persistent (inactive) disk configuration
            # Use INACTIVE flag to read the config that will be used on next boot,
            # not the currently running config (if VM is running)
            xml_str = domain.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)
            xml = ET.fromstring(xml_str)
            disk_elem = xml.find(".//disk[@device='disk']/source")

            if disk_elem is None:
                return False

            current_disk = Path(disk_elem.get("file", ""))
            if not current_disk.exists():
                return False

            # Find checkpoint directory
            checkpoint_dir = DISK_DIR / "checkpoints" / vm_name
            checkpoint_dir.mkdir(parents=True, exist_ok=True)

            target_checkpoint_disk = checkpoint_dir / f"{checkpoint_name}.qcow2"
            if not target_checkpoint_disk.exists():
                return False

            # Check if we're already on this checkpoint
            if current_disk == target_checkpoint_disk:
                return True  # Already active, nothing to do

            # If current disk is not in checkpoints directory, save it as a checkpoint
            # This ensures we don't lose the current state
            if current_disk.parent != checkpoint_dir:
                # Generate name for current state checkpoint
                current_checkpoint_name = f"auto-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                current_checkpoint_disk = checkpoint_dir / f"{current_checkpoint_name}.qcow2"
                current_checkpoint_metadata = checkpoint_dir / f"{current_checkpoint_name}.json"

                # Copy current disk to checkpoint (preserve original)
                shutil.copy2(current_disk, current_checkpoint_disk)

                # Create metadata for auto-saved checkpoint
                metadata = {
                    "name": current_checkpoint_name,
                    "description": "Auto-saved before switch",
                    "created": datetime.now().isoformat(),
                }
                with open(current_checkpoint_metadata, "w") as f:
                    json.dump(metadata, f, indent=2)

            # Update disk path to target checkpoint
            disk_elem.set("file", str(target_checkpoint_disk))

            # Update persistent configuration (takes effect on next VM boot)
            self.conn.defineXML(ET.tostring(xml, encoding="unicode"))

            return True

        except (libvirt.libvirtError, OSError, IOError):
            return False

    def delete_checkpoint(self, vm_name: str, checkpoint_name: str) -> bool:
        """Delete checkpoint disk and metadata.

        Returns True on success.
        """
        try:
            checkpoint_dir = DISK_DIR / "checkpoints" / vm_name
            checkpoint_disk = checkpoint_dir / f"{checkpoint_name}.qcow2"
            metadata_file = checkpoint_dir / f"{checkpoint_name}.json"

            # Delete disk file
            if checkpoint_disk.exists():
                checkpoint_disk.unlink()

            # Delete metadata
            if metadata_file.exists():
                metadata_file.unlink()

            return True

        except (OSError, IOError):
            return False

    def separate_checkpoint_to_vm(self, checkpoint_name: str, new_vm_name: str, source_vm_name: str) -> bool:
        """Create new independent VM from checkpoint disk by moving it.

        This moves the checkpoint disk to become the new VM's disk, removing the checkpoint.
        Returns True on success.
        """
        try:
            # Get source VM domain
            source_domain = self.conn.lookupByName(source_vm_name)

            # Find checkpoint disk and metadata
            checkpoint_dir = DISK_DIR / "checkpoints" / source_vm_name
            checkpoint_disk = checkpoint_dir / f"{checkpoint_name}.qcow2"
            checkpoint_metadata = checkpoint_dir / f"{checkpoint_name}.json"

            if not checkpoint_disk.exists():
                return False

            # Create new disk path for the new VM
            new_disk = DISK_DIR / f"{new_vm_name}.qcow2"
            if new_disk.exists():
                return False  # VM disk already exists

            # Move checkpoint disk to new location (instant operation)
            checkpoint_disk.rename(new_disk)

            # Remove checkpoint metadata
            if checkpoint_metadata.exists():
                checkpoint_metadata.unlink()

            # Clone VM XML with new name and disk
            xml_str = source_domain.XMLDesc()
            xml = ET.fromstring(xml_str)

            # Update name
            name_elem = xml.find("name")
            if name_elem is not None:
                name_elem.text = new_vm_name

            # Update UUID (generate new one)
            uuid_elem = xml.find("uuid")
            if uuid_elem is not None:
                xml.remove(uuid_elem)

            # Update disk path
            disk_elem = xml.find(".//disk[@device='disk']/source")
            if disk_elem is not None:
                disk_elem.set("file", str(new_disk))

            # Define new VM
            new_domain = self.conn.defineXML(ET.tostring(xml, encoding="unicode"))
            if new_domain is None:
                # Clean up if failed - move disk back
                new_disk.rename(checkpoint_disk)
                return False

            return True

        except (libvirt.libvirtError, OSError, IOError):
            return False

    def restore_snapshot(self, vm_name: str, snap_name: str) -> bool:
        """Restore VM to a snapshot state.

        Same as revert_snapshot but returns bool.
        Returns True on success.
        """
        try:
            self.revert_snapshot(vm_name, snap_name)
            return True
        except LibvirtError:
            return False
