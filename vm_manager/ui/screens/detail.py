"""VM detail/edit screen."""

from typing import Any

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.config import DEFAULT_NETWORK
from vm_manager.models import VM
from vm_manager.services import GPUService, LibvirtService, NetworkService, USBService
from vm_manager.services.system import SystemService, SystemResources
from vm_manager.ui.theme import Theme
from vm_manager.ui.widgets.dialog import InputDialog, MessageDialog
from vm_manager.ui.widgets.search_select import SearchSelect
from vm_manager.utils import format_bytes


class DetailField:
    """A field in the detail view."""

    def __init__(
        self,
        name: str,
        label: str,
        value: str,
        editable: bool = False,
        field_type: str = "text",  # text, select, multi
    ):
        self.name = name
        self.label = label
        self.value = value
        self.editable = editable
        self.field_type = field_type


class VMDetailScreen:
    """Full-screen VM detail view with edit mode."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        libvirt: LibvirtService,
        vm: VM,
        gpu_service: GPUService | None = None,
        system_service: SystemService | None = None,
        network_service: NetworkService | None = None,
    ) -> None:
        self.term = term
        self.theme = theme
        self.libvirt = libvirt
        self.vm = vm
        self.gpu_service = gpu_service or GPUService()
        self.system_service = system_service or SystemService()
        self.network_service = network_service or NetworkService()

        # Get system resources for limits
        self.resources: SystemResources = self.system_service.get_resources()

        # Edit mode state
        self.edit_mode = True  # Start in edit mode
        self.selected_index = 0
        self.button_focused = False  # True when focus is on buttons
        self.selected_button = 0  # 0 = Cancel, 1 = Save
        self.changes: dict[str, Any] = {}

        # Track GPU selections
        self.selected_gpus: list[str] = list(vm.gpu_devices) if vm.gpu_devices else []
        self.available_gpus = self.gpu_service.list_gpus()

        # Build fields
        self.fields: list[DetailField] = []
        self._build_fields()

        # Find first editable field
        for i, f in enumerate(self.fields):
            if f.editable:
                self.selected_index = i
                break

    def _build_fields(self) -> None:
        """Build the detail fields from VM data."""
        self.fields = []

        # Basic info (not editable)
        self.fields.append(DetailField("name", "Name", self.vm.name, editable=False))
        self.fields.append(DetailField("uuid", "UUID", self.vm.uuid, editable=False))
        self.fields.append(DetailField("state", "State", self.vm.state.display_name, editable=False))

        # Resources (editable)
        self.fields.append(DetailField(
            "vcpus", "vCPUs", str(self.vm.vcpus), editable=True, field_type="text"
        ))
        self.fields.append(DetailField(
            "memory", "Memory", f"{self.vm.memory_mb} MB", editable=True, field_type="text"
        ))

        # Storage (not editable)
        if self.vm.disks:
            disk_info = []
            for disk in self.vm.disks:
                if disk.exists():
                    size = format_bytes(disk.stat().st_size)
                    disk_info.append(f"{disk.name} ({size})")
                else:
                    disk_info.append(f"{disk.name} (missing)")
            self.fields.append(DetailField(
                "disks", "Disks", ", ".join(disk_info) if disk_info else "(none)", editable=False
            ))
        else:
            self.fields.append(DetailField("disks", "Disks", "(none)", editable=False))

        # ISO (could show but not edit for now)
        if self.vm.iso_path:
            self.fields.append(DetailField(
                "iso", "ISO", str(self.vm.iso_path.name), editable=False
            ))

        # Network (editable)
        if self.vm.networks:
            network_display = ", ".join(self.vm.networks)
        else:
            network_display = "(none)"
        self.fields.append(DetailField(
            "network", "Network", network_display, editable=True, field_type="select"
        ))

        # NIC Model (editable)
        self.fields.append(DetailField(
            "nic_model", "NIC Model", self.vm.nic_model or "virtio", editable=True, field_type="select"
        ))

        # Graphics/Display (editable)
        graphics_display = self.vm.graphics_type.upper() if self.vm.graphics_type else "None"
        if self.vm.is_running and self.vm.graphics_port:
            graphics_display += f" (:{self.vm.graphics_port})"
        self.fields.append(DetailField(
            "graphics", "Display", graphics_display, editable=True, field_type="select"
        ))

        # GPU Passthrough (editable)
        if self.selected_gpus:
            gpu_names = []
            for addr in self.selected_gpus:
                gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                if gpu:
                    gpu_names.append(gpu.display_name)
                else:
                    gpu_names.append(addr)
            gpu_display = ", ".join(gpu_names)
        else:
            gpu_display = "None"
        self.fields.append(DetailField(
            "gpu", "GPU Passthrough", gpu_display, editable=True, field_type="multi"
        ))

        # Audio (editable)
        audio_display = self.vm.audio_model.upper() if self.vm.audio_model != "none" else "None"
        self.fields.append(DetailField(
            "audio", "Audio", audio_display, editable=True, field_type="select"
        ))

        # Settings
        self.fields.append(DetailField(
            "autostart", "Autostart", "Yes" if self.vm.autostart else "No", editable=True, field_type="select"
        ))

        # Read-only metadata
        self.fields.append(DetailField(
            "snapshots", "Snapshots", str(self.vm.snapshot_count), editable=False
        ))
        self.fields.append(DetailField(
            "persistent", "Persistent", "Yes" if self.vm.persistent else "No", editable=False
        ))

    def run(self) -> dict[str, Any] | None:
        """Run the detail screen. Returns changes dict or None."""
        with self.term.cbreak(), self.term.hidden_cursor():
            while True:
                self._render()
                key: Keystroke = self.term.inkey(timeout=0.1)
                if not key:
                    continue

                result = self._handle_key(key)
                if result == "cancel":
                    return None
                elif result == "save":
                    return self._get_changes()

    def _render(self) -> None:
        """Render the detail screen."""
        print(self.term.home + self.term.clear, end="")

        # Header
        title = f" Edit: {self.vm.name} "
        print(
            self.term.move_xy(0, 0)
            + self.term.black_on_cyan(title.center(self.term.width)),
            end="",
        )

        # Fields
        y = 2
        label_width = max(len(f.label) for f in self.fields) + 2

        for i, field in enumerate(self.fields):
            is_selected = not self.button_focused and i == self.selected_index

            # Label
            if field.editable:
                if is_selected:
                    label = self.theme.colored(field.label + ":", "cyan")
                else:
                    label = field.label + ":"
            else:
                label = self.theme.dim(field.label + ":")

            # Value
            if is_selected:
                value = self.term.reverse(f" {field.value} ")
            elif not field.editable:
                value = self.theme.dim(field.value)
            else:
                value = field.value

            print(
                self.term.move_xy(2, y)
                + label.ljust(label_width)
                + value,
                end="",
            )
            y += 1

            # Add spacing after groups
            if field.name in ("state", "memory", "iso", "disks", "nic_model", "gpu", "autostart"):
                y += 1

        # Buttons
        y += 1
        cancel_btn = " Cancel "
        save_btn = " Save "

        if self.button_focused and self.selected_button == 0:
            cancel_btn = self.term.reverse(cancel_btn)
        else:
            cancel_btn = f"[{cancel_btn.strip()}]"

        if self.button_focused and self.selected_button == 1:
            save_btn = self.term.reverse(save_btn)
        else:
            save_btn = f"[{save_btn.strip()}]"

        print(
            self.term.move_xy(2, y)
            + cancel_btn + "  " + save_btn,
            end="",
        )

        # Footer hints
        hints = "↑/↓/Tab: Navigate  Enter: Select/Edit  Esc: Cancel"
        print(
            self.term.move_xy(0, self.term.height - 2)
            + self.theme.dim(hints[:self.term.width]),
            end="",
        )

        # Show changes summary if any
        if self.changes:
            changes_text = f"{len(self.changes)} change(s) pending"
            print(
                self.term.move_xy(0, self.term.height - 1)
                + self.theme.warning(changes_text),
                end="",
            )

        print("", end="", flush=True)

    def _handle_key(self, key: Keystroke) -> str | None:
        """Handle key input."""
        # Escape to cancel
        if key.name == "KEY_ESCAPE":
            if self.changes:
                # Confirm discard changes
                from vm_manager.ui.widgets.dialog import ConfirmDialog
                dialog = ConfirmDialog(
                    self.term, self.theme,
                    "Discard Changes",
                    "Discard all changes?"
                )
                if dialog.show():
                    return "cancel"
            else:
                return "cancel"
            return None

        # Navigation
        if key.name == "KEY_UP":
            if self.button_focused:
                # Move from buttons to last editable field
                self.button_focused = False
                # Find last editable field
                for i in range(len(self.fields) - 1, -1, -1):
                    if self.fields[i].editable:
                        self.selected_index = i
                        break
            else:
                moved = self._move_selection(-1)
                if not moved:
                    # At first field, wrap to buttons
                    self.button_focused = True
                    self.selected_button = 0  # Default to Cancel

        elif key.name == "KEY_DOWN" or key.name == "KEY_TAB":
            if self.button_focused:
                # Move from buttons to first editable field
                self.button_focused = False
                for i, f in enumerate(self.fields):
                    if f.editable:
                        self.selected_index = i
                        break
            else:
                # Try to move to next editable field
                moved = self._move_selection(1)
                if not moved:
                    # At last field, move to buttons
                    self.button_focused = True
                    self.selected_button = 1  # Default to Save

        elif key.name == "KEY_LEFT" and self.button_focused:
            self.selected_button = 0

        elif key.name == "KEY_RIGHT" and self.button_focused:
            self.selected_button = 1

        elif key.name == "KEY_ENTER":
            if self.button_focused:
                if self.selected_button == 0:
                    return "cancel"
                else:
                    return "save"
            else:
                field = self.fields[self.selected_index]
                if field.editable:
                    self._edit_field(field)

        return None

    def _move_selection(self, direction: int) -> bool:
        """Move selection to next/prev editable field. Returns True if moved."""
        start = self.selected_index
        idx = start

        while True:
            new_idx = idx + direction

            # Check bounds
            if new_idx < 0 or new_idx >= len(self.fields):
                return False  # Can't move further

            idx = new_idx
            if self.fields[idx].editable:
                self.selected_index = idx
                return True

            # Prevent infinite loop
            if idx == start:
                return False

        return False

    def _edit_field(self, field: DetailField) -> None:
        """Open editor for a field."""
        if field.name == "vcpus":
            max_cpus = self.resources.cpu_count
            dialog = InputDialog(
                self.term, self.theme,
                "Change vCPUs",
                f"Enter vCPU count (1-{max_cpus}):",
                str(self.vm.vcpus),
                validator=lambda x: None if x.isdigit() and 1 <= int(x) <= max_cpus else f"Must be 1-{max_cpus}"
            )
            result = dialog.show()
            if result:
                field.value = result
                self.changes["vcpus"] = int(result)

        elif field.name == "memory":
            max_mem = self.resources.memory_mb
            current = self.vm.memory_mb
            dialog = InputDialog(
                self.term, self.theme,
                "Change Memory",
                f"Enter memory in MB (256-{max_mem}):",
                str(current),
                validator=lambda x: None if x.isdigit() and 256 <= int(x) <= max_mem else f"Must be 256-{max_mem}"
            )
            result = dialog.show()
            if result:
                field.value = f"{result} MB"
                self.changes["memory"] = int(result)

        elif field.name == "network":
            # Get available networks
            options: list[tuple[str, str]] = []
            for bridge in self.network_service.list_bridges():
                options.append((f"bridge:{bridge}", f"{bridge} (bridge)"))
            try:
                for net in self.libvirt.list_networks():
                    options.append((f"network:{net}", f"{net} (libvirt)"))
            except Exception:
                pass

            if options:
                dialog = SearchSelect(
                    self.term, self.theme,
                    "Select Network",
                    options
                )
                result = dialog.show()
                if result:
                    display = result.split(":", 1)[1]
                    field.value = display
                    self.changes["network"] = result

        elif field.name == "nic_model":
            options = [
                ("virtio", "VirtIO (Best performance)"),
                ("e1000e", "Intel e1000e (Good compatibility)"),
                ("e1000", "Intel e1000 (Legacy)"),
                ("rtl8139", "Realtek RTL8139 (Wide compatibility)"),
                ("vmxnet3", "VMware vmxnet3"),
            ]
            dialog = SearchSelect(
                self.term, self.theme,
                "Select NIC Model",
                options
            )
            result = dialog.show()
            if result:
                field.value = result
                self.changes["nic_model"] = result

        elif field.name == "graphics":
            options = [
                ("spice", "SPICE - Remote desktop (recommended)"),
                ("vnc", "VNC - Basic remote viewer"),
                ("none", "None - Serial console only"),
            ]
            dialog = SearchSelect(
                self.term, self.theme,
                "Select Display Type",
                options
            )
            result = dialog.show()
            if result:
                field.value = result.upper()
                self.changes["graphics"] = result

        elif field.name == "gpu":
            self._edit_gpu(field)

        elif field.name == "audio":
            options = [
                ("ich9", "Intel ICH9 (Recommended)"),
                ("ich6", "Intel ICH6"),
                ("ac97", "AC97 (Legacy)"),
                ("none", "None"),
            ]
            dialog = SearchSelect(
                self.term, self.theme,
                "Select Audio Device",
                options
            )
            result = dialog.show()
            if result:
                field.value = result.upper()
                self.changes["audio"] = result

        elif field.name == "autostart":
            options = [
                ("yes", "Yes - Start on host boot"),
                ("no", "No"),
            ]
            dialog = SearchSelect(
                self.term, self.theme,
                "Autostart on Boot",
                options
            )
            result = dialog.show()
            if result:
                field.value = "Yes" if result == "yes" else "No"
                self.changes["autostart"] = result == "yes"

    def _edit_gpu(self, field: DetailField) -> None:
        """Edit GPU passthrough selection."""
        from vm_manager.ui.widgets.dialog import ToggleListDialog

        self.available_gpus = self.gpu_service.list_gpus()

        if not self.gpu_service.check_iommu_enabled():
            if self.available_gpus:
                MessageDialog(
                    self.term, self.theme,
                    "IOMMU Disabled",
                    "GPUs found but IOMMU is not enabled",
                    "warning"
                ).show()
            return

        if not self.available_gpus:
            MessageDialog(
                self.term, self.theme,
                "No GPUs",
                "No GPUs found for passthrough",
                "warning"
            ).show()
            return

        # Create options list with disabled flag for non-vfio GPUs
        gpu_options: list[tuple[str, str, bool]] = []
        for gpu in self.available_gpus:
            group = self.gpu_service.get_iommu_group(gpu.pci_address)
            if group and len(group.devices) > 1:
                device_types = [d.device_type for d in group.devices]
                type_summary = ", ".join(sorted(set(device_types)))
                label = f"{gpu.display_name} (IOMMU: {type_summary})"
            else:
                label = gpu.full_description

            # Add driver info and disabled flag
            if gpu.driver and gpu.driver != "vfio-pci":
                label = f"{label} [{gpu.driver}]"
                disabled = True
            else:
                if gpu.driver == "vfio-pci":
                    label = f"{label} [vfio-pci]"
                disabled = False

            gpu_options.append((gpu.pci_address, label, disabled))

        dialog = ToggleListDialog(
            self.term, self.theme,
            "Select GPUs for Passthrough",
            gpu_options,
            selected=self.selected_gpus,
            disabled_hint="GPU must use vfio-pci driver for passthrough"
        )

        result = dialog.show()

        # Process selections - add entire IOMMU groups
        new_selected: list[str] = []
        for addr in result:
            group = self.gpu_service.get_iommu_group(addr)
            group_addrs = group.pci_addresses if group else [addr]
            for group_addr in group_addrs:
                if group_addr not in new_selected:
                    new_selected.append(group_addr)

        self.selected_gpus = new_selected

        # Update field display
        if self.selected_gpus:
            gpu_names = []
            for addr in self.selected_gpus:
                gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                if gpu:
                    gpu_names.append(gpu.display_name)
                else:
                    gpu_names.append(addr)
            field.value = ", ".join(gpu_names)
        else:
            field.value = "None"

        self.changes["gpu_devices"] = self.selected_gpus.copy()

    def _get_changes(self) -> dict[str, Any]:
        """Get all changes."""
        return self.changes.copy()
