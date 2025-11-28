"""Main screen with VM list and details pane."""

from pathlib import Path
from typing import Any

from blessed import Terminal

from vm_manager.models import VM
from vm_manager.services import GPUService, LibvirtService, NetworkService, USBService
from vm_manager.services.system import SystemService, SystemResources
from vm_manager.ui.theme import Theme
from vm_manager.ui.widgets.list_view import ListView
from vm_manager.utils import format_bytes, format_duration


class EditableField:
    """A field that can be edited inline."""

    def __init__(
        self,
        name: str,
        label: str,
        value: str,
        editable: bool = False,
        field_type: str = "text",  # text, select, multi
        edit_value: str | None = None,  # Raw value for editing (if different from display)
    ):
        self.name = name
        self.label = label
        self.value = value  # Display value
        self.edit_value = edit_value if edit_value is not None else value  # Value used for editing
        self.editable = editable
        self.field_type = field_type


class MainScreen:
    """Main application screen with split-pane layout."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        libvirt: LibvirtService,
        gpu_service: GPUService | None = None,
        usb_service: USBService | None = None,
        system_service: SystemService | None = None,
        network_service: NetworkService | None = None,
    ) -> None:
        self.term = term
        self.theme = theme
        self.libvirt = libvirt
        self.gpu_service = gpu_service or GPUService()
        self.usb_service = usb_service or USBService()
        self.system_service = system_service or SystemService()
        self.network_service = network_service or NetworkService()
        self.vms: list[VM] = []
        self.vm_list: ListView[VM] = ListView(
            term=term,
            theme=theme,
            items=[],
            format_func=self._format_vm_list_item,
            height=20,  # Will be updated on first render
        )
        self.status_message = ""
        self.search_query = ""
        self.search_mode = False
        self.console_mode = False  # Toggle between info and console view
        self.console_buffer: list[str] = []  # Buffer for console output

        # Edit mode state
        self.edit_mode = False
        self.edit_fields: list[EditableField] = []
        self.edit_selected_index = 0
        self.edit_changes: dict[str, Any] = {}
        self.edit_vm: VM | None = None
        self.edit_button_focused = False  # True when focus is on Save/Cancel buttons
        self.edit_selected_button = 0  # 0 = Cancel, 1 = Save

        # System resources for validation
        self.resources: SystemResources = self.system_service.get_resources()

        # Track GPU selections for editing
        self.selected_gpus: list[str] = []
        self.available_gpus = self.gpu_service.list_gpus()

    def refresh_vms(self) -> None:
        """Refresh the VM list from libvirt."""
        try:
            self.vms = self.libvirt.list_vms()
            if self.search_query:
                filtered = [
                    vm
                    for vm in self.vms
                    if self.search_query.lower() in vm.name.lower()
                ]
                self.vm_list.set_items(filtered)
            else:
                self.vm_list.set_items(self.vms)
        except Exception as e:
            self.vms = []
            self.vm_list.set_items([])
            self.status_message = f"Error: {e}"

    def enter_edit_mode(self) -> bool:
        """Enter edit mode for the selected VM. Returns True if successful."""
        vm = self.vm_list.selected_item
        if not vm:
            return False

        self.edit_mode = True
        self.edit_vm = vm
        self.edit_changes = {}
        self.edit_devices_to_steal: dict[str, tuple[str, str]] = {}  # device_id -> (from_vm, device_type)
        self.edit_button_focused = False
        self.edit_selected_button = 0
        self.selected_gpus = list(vm.gpu_devices) if vm.gpu_devices else []
        self.selected_usb = list(vm.usb_devices) if vm.usb_devices else []
        self.available_gpus = self.gpu_service.list_gpus()
        self._build_edit_fields()
        self.console_mode = False  # Exit console mode if active

        # Find first editable field
        for i, f in enumerate(self.edit_fields):
            if f.editable:
                self.edit_selected_index = i
                break

        return True

    def exit_edit_mode(self, save: bool = False) -> dict[str, Any] | None:
        """Exit edit mode. Returns changes dict if save=True, None otherwise."""
        if save:
            changes = self.edit_changes.copy()
            # Include devices to steal in the changes dict
            if hasattr(self, 'edit_devices_to_steal') and self.edit_devices_to_steal:
                changes["_devices_to_steal"] = self.edit_devices_to_steal.copy()
        else:
            changes = None

        self.edit_mode = False
        self.edit_vm = None
        self.edit_fields = []
        self.edit_selected_index = 0
        self.edit_changes = {}
        self.edit_devices_to_steal = {}
        self.edit_button_focused = False
        self.edit_selected_button = 0
        return changes

    def _build_vm_fields(self, vm: VM) -> list[EditableField]:
        """Build field definitions for a VM (used for both view and edit modes)."""
        fields: list[EditableField] = []

        # Use selected_gpus for edit mode, vm.gpu_devices for view mode
        gpu_list = self.selected_gpus if self.edit_mode else (list(vm.gpu_devices) if vm.gpu_devices else [])

        # Basic info (not editable)
        fields.append(EditableField("name", "Name", vm.name, editable=False))
        fields.append(EditableField("uuid", "UUID", vm.uuid, editable=False))

        # State with uptime
        state_display = vm.state.display_name
        if vm.is_running and vm.stats.uptime_seconds > 0:
            uptime = format_duration(vm.stats.uptime_seconds)
            state_display += f" (up {uptime})"
        fields.append(EditableField("state", "State", state_display, editable=False))

        # Resources (editable)
        cpu_info = str(vm.vcpus)
        if vm.is_running:
            cpu_info += f" ({vm.stats.cpu_percent:.1f}%)"
        fields.append(EditableField(
            "vcpus", "vCPUs", cpu_info, editable=True, field_type="text",
            edit_value=str(vm.vcpus)  # Raw value for editing
        ))

        mem_info = f"{vm.memory_mb} MB"
        if vm.is_running:
            mem_info += f" ({vm.stats.memory_percent:.1f}%)"
        fields.append(EditableField(
            "memory", "Memory", mem_info, editable=True, field_type="text",
            edit_value=str(vm.memory_mb)  # Raw value for editing
        ))

        # Storage (not editable)
        if vm.disks:
            disk_info = []
            for disk in vm.disks:
                if disk.exists():
                    # Get disk usage and max size from qcow2 info
                    disk_sizes = self.libvirt.get_disk_info(disk)
                    if disk_sizes:
                        actual_size, virtual_size = disk_sizes
                        used = format_bytes(actual_size)
                        max_size = format_bytes(virtual_size)
                        disk_info.append(f"{disk.name} ({used}/{max_size})")
                    else:
                        # Fallback to file size if qemu-img info fails
                        size = format_bytes(disk.stat().st_size)
                        disk_info.append(f"{disk.name} ({size})")
                else:
                    disk_info.append(f"{disk.name} (missing)")
            disk_display = ", ".join(disk_info) if disk_info else "(none)"
        else:
            disk_display = "(none)"
        fields.append(EditableField(
            "disks", "Disks", disk_display, editable=False
        ))

        # ISO (always show, editable)
        iso_display = vm.iso_path.name if vm.iso_path else "(none)"
        fields.append(EditableField(
            "iso", "ISO", iso_display, editable=True, field_type="select"
        ))

        # Network (editable)
        network_display = ", ".join(vm.networks) if vm.networks else "(none)"
        fields.append(EditableField(
            "network", "Network", network_display, editable=True, field_type="select"
        ))

        # NIC Model (editable)
        fields.append(EditableField(
            "nic_model", "NIC Model", vm.nic_model or "virtio", editable=True, field_type="select"
        ))

        # Graphics/Display (editable)
        graphics_display = vm.graphics_type.upper() if vm.graphics_type else "None"
        if vm.is_running and vm.graphics_port:
            graphics_display += f" (:{vm.graphics_port})"
        fields.append(EditableField(
            "graphics", "Display", graphics_display, editable=True, field_type="select"
        ))

        # GPU Passthrough (editable)
        if gpu_list:
            gpu_names = []
            for addr in gpu_list:
                gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                if gpu:
                    gpu_names.append(gpu.display_name)
                else:
                    gpu_names.append(addr)
            gpu_display = ", ".join(gpu_names)
        else:
            gpu_display = "None"
        fields.append(EditableField(
            "gpu", "GPU Passthrough", gpu_display, editable=True, field_type="multi"
        ))

        # USB Passthrough (editable)
        available_usb = self.usb_service.list_devices()
        if vm.usb_devices:
            usb_names = []
            for usb_id in vm.usb_devices:
                usb = next((u for u in available_usb if u.id_string == usb_id), None)
                if usb:
                    usb_names.append(usb.display_name)
                else:
                    usb_names.append(usb_id)
            usb_display = ", ".join(usb_names)
        else:
            usb_display = "None"
        fields.append(EditableField(
            "usb", "USB Passthrough", usb_display, editable=True, field_type="multi"
        ))

        # Audio (editable)
        audio_display = vm.audio_model.upper() if vm.audio_model != "none" else "None"
        fields.append(EditableField(
            "audio", "Audio", audio_display, editable=True, field_type="select"
        ))

        # Settings
        autostart_display = "Yes" if vm.autostart else "No"
        fields.append(EditableField(
            "autostart", "Autostart", autostart_display, editable=True, field_type="select"
        ))

        # Boot Order (always show, editable)
        boot_display = ", ".join(vm.boot_devices) if vm.boot_devices else "hd"
        fields.append(EditableField(
            "boot_order", "Boot Order", boot_display, editable=True, field_type="select"
        ))

        # Read-only metadata
        fields.append(EditableField(
            "snapshots", "Snapshots", str(vm.snapshot_count), editable=False
        ))

        persistent_display = "Yes" if vm.persistent else "No"
        fields.append(EditableField(
            "persistent", "Persistent", persistent_display, editable=False
        ))

        return fields

    def _build_edit_fields(self) -> None:
        """Build editable fields from the current VM."""
        if not self.edit_vm:
            return
        self.edit_fields = self._build_vm_fields(self.edit_vm)

    def _format_vm_list_item(self, vm: VM) -> str:
        """Format a VM for the list view."""
        # State indicator
        if vm.is_running:
            indicator = self.theme.colored("●", "green")
        elif vm.state.display_name == "paused":
            indicator = self.theme.colored("●", "yellow")
        else:
            indicator = self.theme.dim("○")

        # Truncate name if needed
        name = vm.name[:20].ljust(20)

        # State and memory (both right-aligned)
        state = vm.state.display_name[:10].rjust(10)
        memory = vm.memory_display.rjust(6)

        return f"{indicator} {name} {state} {memory}"

    def render(self) -> None:
        """Render the entire screen."""
        # Clear screen
        print(self.term.home + self.term.clear, end="")

        # Calculate layout
        list_width = min(45, self.term.width // 2)
        details_width = self.term.width - list_width - 1
        content_height = self.term.height - 6  # Account for header, hints, separator, and status

        # Draw header and hints
        self._draw_header()

        # Draw VM list
        self._draw_vm_list(0, 3, list_width, content_height)

        # Draw details pane
        self._draw_details_pane(list_width + 1, 3, details_width, content_height)

        # Draw status at bottom
        self._draw_status()

        # Flush output
        print("", end="", flush=True)

    def _draw_header(self) -> None:
        """Draw the header bar."""
        title = " VM Manager "
        vm_count = f" {len(self.vms)} VMs "

        # Center title
        padding = self.term.width - len(title) - len(vm_count)
        header = (
            self.term.black_on_cyan(title)
            + self.term.cyan("─" * padding)
            + self.term.black_on_cyan(vm_count)
        )

        print(self.term.move_xy(0, 0) + header, end="")

        # Hints at line 1
        self._draw_hints()

        # Separator line at line 2
        separator = "─" * self.term.width
        print(self.term.move_xy(0, 2) + self.theme.dim(separator), end="")

    def _draw_vm_list(self, x: int, y: int, width: int, height: int) -> None:
        """Draw the VM list pane."""
        # Header
        header = "VMs".center(width - 2)
        print(
            self.term.move_xy(x, y) + self.theme.header("┌" + "─" * (width - 2) + "┐"),
            end="",
        )
        print(
            self.term.move_xy(x, y + 1)
            + self.theme.header("│")
            + self.theme.bold(header)
            + self.theme.header("│"),
            end="",
        )
        print(
            self.term.move_xy(x, y + 2) + self.theme.header("├" + "─" * (width - 2) + "┤"),
            end="",
        )

        # VM list
        list_height = height - 4
        self.vm_list.height = list_height
        lines = self.vm_list.render(x + 1, y + 3, width - 2)
        for line in lines:
            print(line, end="")

        # Draw side borders for list area
        for i in range(list_height):
            print(self.term.move_xy(x, y + 3 + i) + self.theme.header("│"), end="")
            print(
                self.term.move_xy(x + width - 1, y + 3 + i) + self.theme.header("│"),
                end="",
            )

        # Bottom border
        print(
            self.term.move_xy(x, y + height - 1)
            + self.theme.header("└" + "─" * (width - 2) + "┘"),
            end="",
        )

    def _draw_details_pane(self, x: int, y: int, width: int, height: int) -> None:
        """Draw the VM details pane."""
        vm = self.vm_list.selected_item

        # Header
        if self.edit_mode:
            title = f"{vm.name} [EDIT]" if vm else "Edit Mode"
        elif vm and self.console_mode and vm.is_running:
            title = f"{vm.name} [Console]"
        else:
            title = vm.name if vm else "No VM Selected"
        title = title[:width - 4].center(width - 2)

        print(
            self.term.move_xy(x, y) + self.theme.header("┌" + "─" * (width - 2) + "┐"),
            end="",
        )
        print(
            self.term.move_xy(x, y + 1)
            + self.theme.header("│")
            + self.theme.bold(title)
            + self.theme.header("│"),
            end="",
        )
        print(
            self.term.move_xy(x, y + 2) + self.theme.header("├" + "─" * (width - 2) + "┤"),
            end="",
        )

        # Details content
        content_start = y + 3
        content_height = height - 4

        # Content width accounting for borders and left padding
        content_width = width - 3  # 1 left border + 1 padding + 1 right border

        if self.edit_mode and vm:
            details = self._get_edit_details(content_width)
        elif vm:
            if self.console_mode and vm.is_running:
                details = self._get_console_output(vm, content_width, content_height)
            else:
                details = self._get_vm_details(vm, content_width)
        else:
            details = [self.theme.dim("Select a VM to view details")]

        for i in range(content_height):
            print(self.term.move_xy(x, content_start + i) + self.theme.header("│"), end="")
            if i < len(details):
                # Add left padding space, then truncate/pad properly handling ANSI codes
                line = " " + self._truncate_with_ansi(details[i], content_width)
            else:
                line = " " * (width - 2)
            print(line, end="")
            print(self.theme.header("│"), end="")

        # Bottom border
        print(
            self.term.move_xy(x, y + height - 1)
            + self.theme.header("└" + "─" * (width - 2) + "┘"),
            end="",
        )

    def _truncate_with_ansi(self, text: str, max_width: int) -> str:
        """Truncate text with ANSI codes to visible width and pad to exact width."""
        visible_len = self.term.length(text)

        if visible_len <= max_width:
            # Pad to exact width
            padding_needed = max_width - visible_len
            return text + " " * padding_needed

        # Need to truncate - find approximate position
        ratio = max_width / visible_len
        truncate_pos = int(len(text) * ratio)

        # Adjust position to get exact visible width
        truncated = text[:truncate_pos]
        while self.term.length(truncated) > max_width and truncate_pos > 0:
            truncate_pos -= 1
            truncated = text[:truncate_pos]

        # Pad to exact width
        visible_len = self.term.length(truncated)
        padding_needed = max_width - visible_len
        return truncated + " " * padding_needed

    def _render_vm_fields(self, vm: VM, width: int, edit_mode: bool = False) -> list[str]:
        """Parameterized method to render VM fields in view or edit mode."""
        details: list[str] = []

        # In edit mode, use the existing edit_fields (which have updated values)
        # In view mode, build fresh fields from VM data
        if edit_mode and self.edit_fields:
            fields = self.edit_fields
        else:
            fields = self._build_vm_fields(vm)

        if not fields:
            return [self.theme.dim("No fields available")]

        # Calculate label width for consistent spacing
        label_width = max(len(f.label) for f in fields)

        # Render each field
        for i, field in enumerate(fields):
            is_selected = edit_mode and not self.edit_button_focused and i == self.edit_selected_index
            has_changes = edit_mode and field.name in self.edit_changes

            # Add change marker to label if field has pending changes
            if has_changes:
                label_text = field.label + ": *"
            else:
                label_text = field.label + ":"

            # Determine styling based on mode and field state
            if edit_mode:
                # EDIT MODE styling
                if is_selected and field.editable:
                    # Highlight selected editable field
                    value = self.term.reverse(f" {field.value} ")
                    if has_changes:
                        # Changed field that's selected - use warning color with cyan
                        label = self.theme.warning(label_text.ljust(label_width + 2))
                    else:
                        label = self.theme.colored(label_text.ljust(label_width + 2), "cyan")
                elif has_changes and field.editable:
                    # Changed field (not selected) - highlight in warning color
                    label = self.theme.warning(label_text.ljust(label_width + 2))
                    value = self.theme.warning(field.value)
                elif not field.editable:
                    # Grey out non-editable fields
                    label = self.theme.dim(label_text.ljust(label_width + 2))
                    value = self.theme.dim(field.value)
                else:
                    # Normal editable field
                    label = label_text.ljust(label_width + 2)
                    value = field.value
            else:
                # VIEW MODE styling
                label = label_text.ljust(label_width + 1)
                value = field.value

                # Apply color to special fields in view mode
                if field.name == "state":
                    value = self.theme.state_color(vm.state)
                    if vm.is_running and vm.stats.uptime_seconds > 0:
                        uptime = format_duration(vm.stats.uptime_seconds)
                        value += f" (up {uptime})"
                elif field.name == "autostart":
                    value = self.theme.colored(value, "green") if vm.autostart else self.theme.colored(value, "red")
                elif field.name == "persistent":
                    value = self.theme.colored(value, "green") if vm.persistent else self.theme.colored(value, "red")

            details.append(f"{label} {value}")

            # Add spacing after groups
            if field.name in ("state", "memory", "iso", "nic_model", "gpu", "autostart"):
                details.append("")

        # EDIT MODE: Add buttons with pending changes in Save label
        if edit_mode:
            details.append("")

            # Build button labels
            cancel_label = " Cancel "
            if self.edit_changes:
                save_label = f" Save ({len(self.edit_changes)}) "
            else:
                save_label = " Save "

            # Apply highlighting
            if self.edit_button_focused and self.edit_selected_button == 0:
                cancel_btn = self.term.reverse(cancel_label)
            else:
                cancel_btn = f"[{cancel_label.strip()}]"

            if self.edit_button_focused and self.edit_selected_button == 1:
                save_btn = self.term.reverse(save_label)
            elif self.edit_changes:
                # Highlight save button when there are pending changes
                save_btn = self.theme.colored(f"[{save_label.strip()}]", "green")
            else:
                save_btn = f"[{save_label.strip()}]"

            details.append(cancel_btn + "  " + save_btn)

        return details

    def _get_vm_details(self, vm: VM, width: int) -> list[str]:
        """Get formatted VM details in view mode."""
        return self._render_vm_fields(vm, width, edit_mode=False)

    def _get_edit_details(self, width: int) -> list[str]:
        """Get formatted VM details in edit mode."""
        if not self.edit_vm:
            return [self.theme.dim("No VM selected for editing")]
        return self._render_vm_fields(self.edit_vm, width, edit_mode=True)

    def _get_console_output(self, vm: VM, width: int, max_lines: int) -> list[str]:
        """Get console output for display."""
        lines: list[str] = []

        # Header info
        lines.append(self.theme.dim("Serial Console Output"))
        lines.append(self.theme.dim("─" * min(width, 30)))
        lines.append("")

        # Try to get console output from libvirt
        try:
            console_data = self.libvirt.get_console_output(vm.name, max_lines - 5)
            if console_data:
                for line in console_data:
                    # Truncate long lines
                    if len(line) > width:
                        line = line[:width - 3] + "..."
                    lines.append(line)
            else:
                lines.append(self.theme.dim("No console output available"))
                lines.append("")
                lines.append(self.theme.dim("Tip: VM needs serial console"))
                lines.append(self.theme.dim("configured for output here"))
        except Exception as e:
            lines.append(self.theme.error(f"Error: {e}"))

        lines.append("")
        lines.append(self.theme.dim("Press 'v' to toggle view"))

        return lines

    def _draw_hints(self) -> None:
        """Draw keyboard hints at line 1."""
        # Edit mode has different keybindings
        if self.edit_mode:
            keys: list[str] = [
                "↑/↓/Tab: Navigate",
                "Enter: Edit/Select",
                "←/→: Select button",
                "Esc: Cancel",
            ]
            hints_text = "  ".join(keys)
        else:
            # Keybindings
            vm = self.vm_list.selected_item

            keys: list[str] = []
            keys.append(self.theme.key_hint("n", "ew"))
            if vm:
                keys.append(self.theme.key_hint("e", "dit"))
                keys.append(self.theme.key_hint("d", "el"))
                if vm.can_start:
                    keys.append(self.theme.key_hint("s", "tart"))
                if vm.can_stop:
                    keys.append("s" + self.theme.key_hint("t", "op"))
                if vm.is_running:
                    keys.append(self.theme.key_hint("c", "onsole"))
                    keys.append(self.theme.key_hint("v", "iew"))
                keys.append("sna" + self.theme.key_hint("p", "shots"))
            keys.append(self.theme.key_hint("/", "search"))
            keys.append(self.theme.key_hint("r", "efresh"))
            keys.append(self.theme.key_hint("?", "help"))
            keys.append(self.theme.key_hint("q", "uit"))

            hints_text = "  ".join(keys)

        # Truncate if too long (calculate visible length, not including ANSI codes)
        visible_len = self.term.length(hints_text)
        if visible_len > self.term.width:
            # Truncate to fit, accounting for "..."
            ratio = self.term.width / visible_len
            truncate_at = int(len(hints_text) * ratio * 0.95)  # 0.95 for safety margin
            hints_text = hints_text[:truncate_at] + "..."

        # Draw hints with search indicator if in search mode
        if self.search_mode:
            search_indicator = f"[Search: {self.search_query}█] "
            combined = search_indicator + hints_text
            visible_combined = self.term.length(combined)
            if visible_combined > self.term.width:
                # Truncate hints to fit with search
                available = self.term.width - self.term.length(search_indicator) - 3
                ratio = available / self.term.length(hints_text)
                truncate_at = int(len(hints_text) * ratio * 0.95)
                hints_text = hints_text[:truncate_at] + "..."
            print(self.term.move_xy(0, 1) + self.theme.warning(search_indicator) + hints_text, end="")
        else:
            print(self.term.move_xy(0, 1) + hints_text, end="")

    def _draw_status(self) -> None:
        """Draw status message at bottom."""
        status_y = self.term.height - 1
        if self.status_message:
            print(
                self.term.move_xy(0, status_y)
                + self.status_message[: self.term.width],
                end="",
            )
        else:
            print(self.term.move_xy(0, status_y) + " " * self.term.width, end="")

    def set_status(self, message: str, message_type: str = "info") -> None:
        """Set status message."""
        if message_type == "error":
            self.status_message = self.theme.error(message)
        elif message_type == "success":
            self.status_message = self.theme.success(message)
        elif message_type == "warning":
            self.status_message = self.theme.warning(message)
        else:
            self.status_message = message

    def handle_key(self, key: str) -> str | None:
        """Handle key input. Returns action name or None."""
        # Edit mode handling
        if self.edit_mode:
            # Escape key - try multiple key names
            if key == "KEY_ESCAPE" or key == "\x1b" or (len(key) == 1 and ord(key) == 27):
                # Confirm if there are changes
                if self.edit_changes:
                    from vm_manager.ui.widgets.dialog import ConfirmDialog
                    dialog = ConfirmDialog(
                        self.term, self.theme,
                        "Discard Changes",
                        "Discard all changes?"
                    )
                    if dialog.show():
                        self.exit_edit_mode(save=False)
                else:
                    self.exit_edit_mode(save=False)
                return None
            elif key == "KEY_UP":
                if self.edit_button_focused:
                    # Move from buttons to last editable field
                    self.edit_button_focused = False
                    for i in range(len(self.edit_fields) - 1, -1, -1):
                        if self.edit_fields[i].editable:
                            self.edit_selected_index = i
                            break
                else:
                    # Try to move to previous field
                    if not self._move_edit_selection(-1):
                        # At first field, wrap to buttons
                        self.edit_button_focused = True
                        self.edit_selected_button = 0
                return None
            elif key == "KEY_DOWN" or key == "KEY_TAB":
                if self.edit_button_focused:
                    # Move from buttons to first editable field
                    self.edit_button_focused = False
                    for i, f in enumerate(self.edit_fields):
                        if f.editable:
                            self.edit_selected_index = i
                            break
                else:
                    # Try to move to next field
                    if not self._move_edit_selection(1):
                        # At last field, move to buttons
                        self.edit_button_focused = True
                        self.edit_selected_button = 1  # Default to Save
                return None
            elif key == "KEY_LEFT" and self.edit_button_focused:
                self.edit_selected_button = 0
                return None
            elif key == "KEY_RIGHT" and self.edit_button_focused:
                self.edit_selected_button = 1
                return None
            elif key == "KEY_ENTER" or key == "\r" or key == "\n":
                if self.edit_button_focused:
                    if self.edit_selected_button == 0:
                        # Cancel button
                        if self.edit_changes:
                            from vm_manager.ui.widgets.dialog import ConfirmDialog
                            dialog = ConfirmDialog(
                                self.term, self.theme,
                                "Discard Changes",
                                "Discard all changes?"
                            )
                            if dialog.show():
                                self.exit_edit_mode(save=False)
                        else:
                            self.exit_edit_mode(save=False)
                    else:
                        # Save button
                        return "save_edit"
                else:
                    # Edit field
                    if self.edit_fields and 0 <= self.edit_selected_index < len(self.edit_fields):
                        field = self.edit_fields[self.edit_selected_index]
                        if field.editable:
                            self._edit_field(field)
                return None
            return None

        # Search mode handling
        if self.search_mode:
            if key == "KEY_ESCAPE":
                self.search_mode = False
                self.search_query = ""
                self.vm_list.set_items(self.vms)
            elif key == "KEY_ENTER":
                self.search_mode = False
            elif key == "KEY_BACKSPACE":
                self.search_query = self.search_query[:-1]
                self._apply_search()
            elif len(key) == 1 and key.isprintable():
                self.search_query += key
                self._apply_search()
            return None

        # List navigation
        if self.vm_list.handle_key(key):
            # Reset console mode when changing selection
            self.console_mode = False
            return None

        # Actions
        if key == "q":
            return "quit"
        elif key == "n":
            return "new"
        elif key == "e" and self.vm_list.selected_item:
            # Enter inline edit mode instead of navigating to separate screen
            if self.enter_edit_mode():
                return None
        elif key == "d" and self.vm_list.selected_item:
            return "delete"
        elif key == "s" and self.vm_list.selected_item:
            if self.vm_list.selected_item.can_start:
                return "start"
        elif key == "t" and self.vm_list.selected_item:
            if self.vm_list.selected_item.can_stop:
                return "stop"
        elif key == "c" and self.vm_list.selected_item:
            if self.vm_list.selected_item.is_running:
                return "console"
        elif key == "p" and self.vm_list.selected_item:
            return "snapshots"
        elif key == "/":
            self.search_mode = True
            self.search_query = ""
            return None
        elif key == "r":
            return "refresh"
        elif key == "?":
            return "help"
        elif key == "v" and self.vm_list.selected_item:
            # Toggle console view
            if self.vm_list.selected_item.is_running:
                self.console_mode = not self.console_mode
            return None
        elif key == "KEY_ENTER" and self.vm_list.selected_item:
            return "details"

        return None

    def _apply_search(self) -> None:
        """Apply search filter to VM list."""
        if self.search_query:
            filtered = [
                vm for vm in self.vms if self.search_query.lower() in vm.name.lower()
            ]
            self.vm_list.set_items(filtered)
        else:
            self.vm_list.set_items(self.vms)

    def _move_edit_selection(self, direction: int) -> bool:
        """Move selection to next/prev editable field in edit mode. Returns True if moved."""
        if not self.edit_fields:
            return False

        start = self.edit_selected_index
        idx = start

        while True:
            new_idx = idx + direction

            # Check bounds
            if new_idx < 0 or new_idx >= len(self.edit_fields):
                return False  # Can't move further

            idx = new_idx
            if self.edit_fields[idx].editable:
                self.edit_selected_index = idx
                return True

            # Prevent infinite loop
            if idx == start:
                return False

        return False

    def _edit_field(self, field: EditableField) -> None:
        """Open editor for a field in inline edit mode."""
        if not self.edit_vm:
            return

        from vm_manager.ui.widgets.dialog import InputDialog, MessageDialog, SelectDialog
        from vm_manager.ui.widgets.search_select import SearchSelect

        if field.name == "vcpus":
            max_cpus = self.resources.cpu_count
            dialog = InputDialog(
                self.term, self.theme,
                "Change vCPUs",
                f"Enter vCPU count (1-{max_cpus}):",
                field.edit_value,
                validator=lambda x: None if x.isdigit() and 1 <= int(x) <= max_cpus else f"Must be 1-{max_cpus}"
            )
            result = dialog.show()
            if result:
                # Always update field value
                field.edit_value = result
                field.value = result
                # Stage if different from original, unstage if same
                if int(result) != self.edit_vm.vcpus:
                    self.edit_changes["vcpus"] = int(result)
                else:
                    self.edit_changes.pop("vcpus", None)

        elif field.name == "memory":
            max_mem = self.resources.memory_mb
            dialog = InputDialog(
                self.term, self.theme,
                "Change Memory",
                f"Enter memory in MB (256-{max_mem}):",
                field.edit_value,
                validator=lambda x: None if x.isdigit() and 256 <= int(x) <= max_mem else f"Must be 256-{max_mem}"
            )
            result = dialog.show()
            if result:
                # Always update field value
                field.edit_value = result
                field.value = f"{result} MB"
                # Stage if different from original, unstage if same
                if int(result) != self.edit_vm.memory_mb:
                    self.edit_changes["memory"] = int(result)
                else:
                    self.edit_changes.pop("memory", None)

        elif field.name == "network":
            # Get available networks
            bridges = self.network_service.list_bridges()
            libvirt_networks: list[str] = []
            try:
                libvirt_networks = self.libvirt.list_networks()
            except Exception:
                pass

            options: list[tuple[str, str]] = []
            for bridge in bridges:
                options.append((f"bridge:{bridge}", f"{bridge} (bridge)"))
            for net in libvirt_networks:
                options.append((f"network:{net}", f"{net} (libvirt)"))

            if options:
                # Determine current network value with correct prefix
                current_network = self.edit_vm.networks[0] if self.edit_vm.networks else None
                current_value = None

                if current_network:
                    # Check if it's a bridge or libvirt network
                    if current_network in bridges:
                        current_value = f"bridge:{current_network}"
                    elif current_network in libvirt_networks:
                        current_value = f"network:{current_network}"
                    else:
                        # Unknown - try to find it in options as-is
                        current_value = current_network

                # Find current value index
                selected_idx = next((i for i, (val, _) in enumerate(options) if val == current_value), 0)

                dialog = SelectDialog(
                    self.term, self.theme,
                    "Select Network",
                    options,
                    selected_index=selected_idx
                )
                result = dialog.show()
                if result:
                    # Always update field value
                    field.value = result.split(":", 1)[1] if ":" in result else result
                    # Stage if different from original, unstage if same
                    if result != current_value:
                        self.edit_changes["network"] = result
                    else:
                        self.edit_changes.pop("network", None)

        elif field.name == "iso":
            # ISO selection - use SearchSelect (can have many ISOs)
            from vm_manager.config import ISO_DIR
            options: list[tuple[str, str]] = [("none", "None (no ISO attached)")]

            if ISO_DIR.exists():
                for iso_file in sorted(ISO_DIR.glob("*.iso")):
                    options.append((str(iso_file), iso_file.name))

            current_iso = str(self.edit_vm.iso_path) if self.edit_vm.iso_path else "none"
            dialog = SearchSelect(
                self.term, self.theme,
                "Select ISO",
                options,
                selected_value=current_iso
            )
            result = dialog.show()
            if result:
                # Always update field value
                if result == "none":
                    field.value = "(none)"
                else:
                    from pathlib import Path
                    field.value = Path(result).name
                # Stage if different from original, unstage if same
                if result != current_iso:
                    if result == "none":
                        self.edit_changes["iso"] = None
                    else:
                        from pathlib import Path
                        self.edit_changes["iso"] = Path(result)
                else:
                    self.edit_changes.pop("iso", None)

        elif field.name == "nic_model":
            options = [
                ("virtio", "VirtIO (Best performance)"),
                ("e1000e", "Intel e1000e (Good compatibility)"),
                ("e1000", "Intel e1000 (Legacy)"),
                ("rtl8139", "Realtek RTL8139 (Wide compatibility)"),
                ("vmxnet3", "VMware vmxnet3"),
            ]
            # Find current value index
            current_value = self.edit_vm.nic_model or "virtio"
            selected_idx = next((i for i, (val, _) in enumerate(options) if val == current_value), 0)

            dialog = SelectDialog(
                self.term, self.theme,
                "Select NIC Model",
                options,
                selected_index=selected_idx
            )
            result = dialog.show()
            if result:
                # Always update field value
                field.value = result
                # Stage if different from original, unstage if same
                if result != current_value:
                    self.edit_changes["nic_model"] = result
                else:
                    self.edit_changes.pop("nic_model", None)

        elif field.name == "graphics":
            options = [
                ("spice", "SPICE - Remote desktop (recommended)"),
                ("vnc", "VNC - Basic remote viewer"),
                ("none", "None - Serial console only"),
            ]
            # Find current value index
            current_value = self.edit_vm.graphics_type or "none"
            selected_idx = next((i for i, (val, _) in enumerate(options) if val == current_value), 0)

            dialog = SelectDialog(
                self.term, self.theme,
                "Select Display Type",
                options,
                selected_index=selected_idx
            )
            result = dialog.show()
            if result:
                # Always update field value
                field.value = result.upper() if result != "none" else "None"
                # Stage if different from original, unstage if same
                if result != current_value:
                    self.edit_changes["graphics"] = result
                else:
                    self.edit_changes.pop("graphics", None)

        elif field.name == "gpu":
            self._edit_gpu_field(field)

        elif field.name == "usb":
            self._edit_usb_field(field)

        elif field.name == "audio":
            options = [
                ("ich9", "Intel ICH9 (Recommended)"),
                ("ich6", "Intel ICH6"),
                ("ac97", "AC97 (Legacy)"),
                ("none", "None"),
            ]
            # Find current value index
            current_value = self.edit_vm.audio_model or "none"
            selected_idx = next((i for i, (val, _) in enumerate(options) if val == current_value), 0)

            dialog = SelectDialog(
                self.term, self.theme,
                "Select Audio Device",
                options,
                selected_index=selected_idx
            )
            result = dialog.show()
            if result:
                # Always update field value
                field.value = result.upper() if result != "none" else "None"
                # Stage if different from original, unstage if same
                if result != current_value:
                    self.edit_changes["audio"] = result
                else:
                    self.edit_changes.pop("audio", None)

        elif field.name == "autostart":
            options = [
                ("yes", "Yes - Start on host boot"),
                ("no", "No"),
            ]
            # Find current value index
            current_value = "yes" if self.edit_vm.autostart else "no"
            selected_idx = 0 if current_value == "yes" else 1

            dialog = SelectDialog(
                self.term, self.theme,
                "Autostart on Boot",
                options,
                selected_index=selected_idx
            )
            result = dialog.show()
            if result:
                new_autostart = result == "yes"
                # Always update field value
                field.value = "Yes" if new_autostart else "No"
                # Stage if different from original, unstage if same
                if new_autostart != self.edit_vm.autostart:
                    self.edit_changes["autostart"] = new_autostart
                else:
                    self.edit_changes.pop("autostart", None)

        elif field.name == "boot_order":
            from vm_manager.ui.widgets.dialog import OrderableListDialog

            # Available boot devices (order matters - shows initial order)
            boot_options = [
                ("hd", "Hard Disk"),
                ("cdrom", "CD-ROM/DVD"),
                ("network", "Network (PXE)"),
            ]

            # Get current boot devices
            current_boot = self.edit_vm.boot_devices or ["hd"]

            # Reorder boot_options to match current boot order
            current_map = {val: label for val, label in boot_options}
            ordered_options = [(dev, current_map[dev]) for dev in current_boot if dev in current_map]
            # Add any options not in current boot order
            for val, label in boot_options:
                if val not in current_boot:
                    ordered_options.append((val, label))

            dialog = OrderableListDialog(
                self.term, self.theme,
                "Boot Order (use Shift+↑↓ to reorder)",
                ordered_options,
                selected=current_boot
            )
            result = dialog.show()
            if result is not None:
                # Ensure at least one boot device
                if not result:
                    result = ["hd"]

                # Always update field value
                field.value = ", ".join(result)

                # Stage if different from original, unstage if same
                if result != current_boot:
                    self.edit_changes["boot_order"] = result
                else:
                    self.edit_changes.pop("boot_order", None)

    def _edit_gpu_field(self, field: EditableField) -> None:
        """Edit GPU passthrough selection in inline mode."""
        from vm_manager.ui.widgets.dialog import MessageDialog, ToggleListDialog

        # DEBUG: Setup logging to file
        debug_log = open('/tmp/vm_manager_gpu_debug.log', 'a')

        # Refresh GPU list
        self.available_gpus = self.gpu_service.list_gpus()

        # Check IOMMU
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

        # Get GPU device usage across all VMs
        gpu_usage = self.libvirt.get_gpu_device_usage()

        # Build options list and IOMMU group mapping
        gpu_options_unsorted: list[tuple[str, str, bool, str]] = []  # (pci, label, disabled, sort_key)
        iommu_groups: dict[str, list[str]] = {}  # device -> all devices in its group
        disabled_reasons: dict[str, str] = {}  # device -> reason why disabled
        seen_pci_addrs = set()

        for gpu in self.available_gpus:
            pci_addr = gpu.pci_address
            seen_pci_addrs.add(pci_addr)

            group = self.gpu_service.get_iommu_group(pci_addr)

            if group and len(group.devices) > 1:
                # IOMMU group with multiple devices - add all of them
                device_types = [d.device_type for d in group.devices]
                type_summary = ", ".join(sorted(set(device_types)))

                # Store IOMMU group mapping for all devices
                for group_dev in group.devices:
                    iommu_groups[group_dev.pci_address] = group.pci_addresses

                # Add all devices in the group to the list
                for group_dev in group.devices:
                    group_pci_addr = group_dev.pci_address
                    seen_pci_addrs.add(group_pci_addr)

                    if group_dev.pci_address == pci_addr:
                        # Primary device (the GPU/VGA controller)
                        group_label = f"{gpu.display_name} (IOMMU: {type_summary})"
                    else:
                        # Companion device (e.g., audio, USB controller)
                        group_label = f"  └─ {group_dev.device_type}: {group_dev.vendor_name} {group_dev.device_name}"

                    disabled = False
                    disable_reason = None

                    # Check if device is used by another VM
                    if group_pci_addr in gpu_usage:
                        using_vm = gpu_usage[group_pci_addr]
                        if using_vm != self.edit_vm.name:
                            group_label = f"{group_label} [in use by {using_vm}]"
                            disabled = True
                            disable_reason = f"GPU is in use by {using_vm}"

                    # Check driver
                    if not disabled:
                        if group_dev.driver and group_dev.driver != "vfio-pci":
                            group_label = f"{group_label} [{group_dev.driver}]"
                            disabled = True
                            disable_reason = "GPU must use vfio-pci driver for passthrough"
                        else:
                            if group_dev.driver == "vfio-pci":
                                group_label = f"{group_label} [vfio-pci]"

                    if disable_reason:
                        disabled_reasons[group_pci_addr] = disable_reason

                    gpu_options_unsorted.append((group_pci_addr, group_label, disabled, group_pci_addr))
            else:
                # Single device, no group
                label = gpu.full_description
                iommu_groups[pci_addr] = [pci_addr]

                disabled = False
                disable_reason = None

                # Check if device is used by another VM
                if pci_addr in gpu_usage:
                    using_vm = gpu_usage[pci_addr]
                    if using_vm != self.edit_vm.name:
                        label = f"{label} [in use by {using_vm}]"
                        disabled = True
                        disable_reason = f"GPU is in use by {using_vm}"

                # Check driver
                if not disabled:
                    if gpu.driver and gpu.driver != "vfio-pci":
                        label = f"{label} [{gpu.driver}]"
                        disabled = True
                        disable_reason = "GPU must use vfio-pci driver for passthrough"
                    else:
                        if gpu.driver == "vfio-pci":
                            label = f"{label} [vfio-pci]"

                if disable_reason:
                    disabled_reasons[pci_addr] = disable_reason

                gpu_options_unsorted.append((pci_addr, label, disabled, pci_addr))

        # Sort by PCI address (00.0 before 00.1, etc.)
        gpu_options_unsorted.sort(key=lambda x: x[3])
        gpu_options = [(addr, label, disabled) for addr, label, disabled, _ in gpu_options_unsorted]

        # Add any configured GPUs that aren't currently detected (for conflict resolution)
        for pci_addr in self.edit_vm.gpu_devices:
            if pci_addr not in seen_pci_addrs:
                label = f"{pci_addr} [device not found]"
                gpu_options.append((pci_addr, label, True))  # Disabled but can be deselected
                iommu_groups[pci_addr] = [pci_addr]  # Single device

        print(f"[DEBUG] IOMMU groups mapping: {iommu_groups}", file=debug_log, flush=True)
        print(f"[DEBUG] GPU usage: {gpu_usage}", file=debug_log, flush=True)

        # Create steal callback
        def steal_gpu_callback(device_id: str, from_vm: str) -> bool:
            """Mark GPU for stealing from another VM (actual steal happens on save)."""
            # Mark this device and its IOMMU group for stealing
            group_to_steal = iommu_groups.get(device_id, [device_id])
            for dev in group_to_steal:
                self.edit_devices_to_steal[dev] = (from_vm, "gpu")
            print(f"[DEBUG] Marked GPU {device_id} group {group_to_steal} for stealing from {from_vm}", file=debug_log, flush=True)
            return True

        # Show dialog with current selections
        dialog = ToggleListDialog(
            self.term, self.theme,
            "Select GPUs for Passthrough",
            gpu_options,
            selected=self.selected_gpus,
            disabled_hint="GPU is not available for passthrough",
            iommu_groups=iommu_groups,
            device_owners=gpu_usage,
            on_steal_device=steal_gpu_callback
        )

        result = dialog.show()

        # DEBUG: Print what we got back
        print(f"\n[DEBUG] Dialog returned: {result}", file=debug_log, flush=True)
        print(f"[DEBUG] Result type: {type(result)}", file=debug_log, flush=True)

        # Handle cancellation
        if result is None:
            print(f"[DEBUG] Result is None, returning early", file=debug_log, flush=True)
            debug_log.close()
            return

        # Validate result is a list
        if not isinstance(result, list):
            print(f"[DEBUG] Result is not a list, returning early", file=debug_log, flush=True)
            debug_log.close()
            return

        print(f"[DEBUG] Processing {len(result)} GPU addresses", file=debug_log, flush=True)

        # Update the selected GPUs list directly (user controls selection)
        self.selected_gpus = result

        # Build display value for the field
        if self.selected_gpus:
            gpu_names = []
            for addr in self.selected_gpus:
                gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                if gpu:
                    gpu_names.append(gpu.display_name)
                else:
                    gpu_names.append(addr)
            new_display_value = ", ".join(gpu_names)
        else:
            new_display_value = "None"

        # Update field value (this updates the field in self.edit_fields)
        field.value = new_display_value
        print(f"[DEBUG] Updated field.value to: {new_display_value}", file=debug_log, flush=True)

        # Compare with original to determine if we should stage
        original_gpus = set(self.edit_vm.gpu_devices) if self.edit_vm.gpu_devices else set()
        current_gpus = set(self.selected_gpus)

        print(f"[DEBUG] Original GPUs: {original_gpus}", file=debug_log, flush=True)
        print(f"[DEBUG] Current GPUs: {current_gpus}", file=debug_log, flush=True)
        print(f"[DEBUG] Are they different? {current_gpus != original_gpus}", file=debug_log, flush=True)

        if current_gpus != original_gpus:
            # Changed from original - stage it
            self.edit_changes["gpu"] = self.selected_gpus.copy()
            print(f"[DEBUG] STAGED changes: {self.edit_changes}", file=debug_log, flush=True)
        else:
            # Same as original - unstage it
            self.edit_changes.pop("gpu", None)
            print(f"[DEBUG] UNSTAGED (same as original)", file=debug_log, flush=True)

        # Close debug log
        debug_log.close()

    def _edit_usb_field(self, field: EditableField) -> None:
        """Edit USB passthrough selection in inline mode."""
        from vm_manager.ui.widgets.dialog import MessageDialog, ToggleListDialog

        # Get available USB devices
        available_usb = self.usb_service.list_devices()

        if not available_usb:
            MessageDialog(
                self.term, self.theme,
                "No USB Devices",
                "No USB devices found for passthrough",
                "warning"
            ).show()
            return

        # Get USB device usage across all VMs
        usb_usage = self.libvirt.get_usb_device_usage()

        # Build options list with usage info
        usb_options: list[tuple[str, str, bool]] = []
        seen_usb_ids = set()

        for usb in available_usb:
            usb_id = usb.id_string
            seen_usb_ids.add(usb_id)
            label = usb.full_description

            # Check if device is used by another VM
            if usb_id in usb_usage:
                using_vm = usb_usage[usb_id]
                if using_vm != self.edit_vm.name:
                    # Used by a different VM - disable and show which VM
                    label = f"{label} [in use by {using_vm}]"
                    disabled = True
                else:
                    # Used by current VM - allow toggling
                    disabled = False
            else:
                disabled = False

            usb_options.append((usb_id, label, disabled))

        # Add any configured devices that aren't currently plugged in (for conflict resolution)
        for usb_id in self.edit_vm.usb_devices:
            if usb_id not in seen_usb_ids:
                label = f"{usb_id} [device not found]"
                usb_options.append((usb_id, label, True))  # Disabled but can be deselected

        # Get currently selected USB devices for this VM
        selected_usb = self.edit_vm.usb_devices.copy() if hasattr(self, 'selected_usb') is False else getattr(self, 'selected_usb', self.edit_vm.usb_devices.copy())
        if not hasattr(self, 'selected_usb'):
            self.selected_usb = selected_usb

        # Create steal callback
        def steal_usb_callback(device_id: str, from_vm: str) -> bool:
            """Mark USB device for stealing from another VM (actual steal happens on save)."""
            # Mark this device for stealing
            self.edit_devices_to_steal[device_id] = (from_vm, "usb")
            return True

        # Show dialog
        dialog = ToggleListDialog(
            self.term, self.theme,
            "Select USB Devices for Passthrough",
            usb_options,
            selected=self.selected_usb,
            disabled_hint="USB device is already in use by another VM",
            device_owners=usb_usage,
            on_steal_device=steal_usb_callback
        )

        result = dialog.show()

        # Handle cancellation
        if result is None:
            return

        # Update the selected USB list
        self.selected_usb = result

        # Build display value
        if self.selected_usb:
            usb_names = []
            for usb_id in self.selected_usb:
                usb = next((u for u in available_usb if u.id_string == usb_id), None)
                if usb:
                    usb_names.append(usb.display_name)
                else:
                    usb_names.append(usb_id)
            new_display_value = ", ".join(usb_names)
        else:
            new_display_value = "None"

        # Update field value
        field.value = new_display_value

        # Compare with original to determine if we should stage
        original_usb = set(self.edit_vm.usb_devices) if self.edit_vm.usb_devices else set()
        current_usb = set(self.selected_usb)

        if current_usb != original_usb:
            # Changed from original - stage it
            self.edit_changes["usb"] = self.selected_usb.copy()
        else:
            # Same as original - unstage it
            self.edit_changes.pop("usb", None)
