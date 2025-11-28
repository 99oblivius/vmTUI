"""Edit VM wizard screen."""

from typing import Any

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.config import DEFAULT_NETWORK
from vm_manager.models import VM
from vm_manager.services import GPUService, LibvirtService, NetworkService, USBService
from vm_manager.services.system import SystemService, SystemResources
from vm_manager.ui.theme import Theme
from vm_manager.ui.widgets.form import FieldType, Form, FormField
from vm_manager.ui.widgets.search_select import SearchSelect


class EditWizard:
    """Wizard for editing an existing VM."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        libvirt: LibvirtService,
        vm: VM,
        gpu_service: GPUService | None = None,
        system_service: SystemService | None = None,
        usb_service: USBService | None = None,
        network_service: NetworkService | None = None,
    ) -> None:
        self.term = term
        self.theme = theme
        self.libvirt = libvirt
        self.vm = vm
        self.gpu_service = gpu_service or GPUService()
        self.system_service = system_service or SystemService()
        self.usb_service = usb_service or USBService()
        self.network_service = network_service or NetworkService()

        # Get system resources for limits
        self.resources: SystemResources = self.system_service.get_resources()

        # Track changes
        self.changes: dict[str, Any] = {}

        # Track GPU selections (start with current VM's GPUs)
        self.selected_gpus: list[str] = list(vm.gpu_devices) if vm.gpu_devices else []
        self.available_gpus = self.gpu_service.list_gpus()

        # Build forms
        self.forms: list[Form] = []
        self._build_forms()

    def _build_forms(self) -> None:
        """Build the edit forms with current VM values."""
        max_cpus = self.resources.cpu_count
        max_mem = self.resources.memory_mb
        max_disk = self.resources.disk_free_gb

        # Validators
        def validate_cpus(val: str) -> str | None:
            if not val or not val.isdigit():
                return "Must be a number"
            v = int(val)
            if v < 1 or v > max_cpus:
                return f"Must be 1-{max_cpus}"
            return None

        def validate_memory(val: str) -> str | None:
            if not val or not val.isdigit():
                return "Must be a number"
            v = int(val)
            if v < 256 or v > max_mem:
                return f"Must be 256-{max_mem}"
            return None

        # Step 0: Basic Info (name is disabled)
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="name",
                    label="VM Name:",
                    field_type=FieldType.TEXT,
                    value=self.vm.name,
                    disabled=True,  # Can't rename VMs
                ),
            ],
            buttons=[("cancel", "Cancel"), ("next", "Next")],
        ))

        # Step 1: Resources
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="vcpus",
                    label=f"CPUs (1-{max_cpus}):",
                    field_type=FieldType.NUMBER,
                    value=str(self.vm.vcpus),
                    validator=validate_cpus,
                ),
                FormField(
                    name="memory",
                    label=f"Memory MB (256-{max_mem}):",
                    field_type=FieldType.NUMBER,
                    value=str(self.vm.memory_mb),
                    validator=validate_memory,
                ),
                FormField(
                    name="disk",
                    label="Disk GB:",
                    field_type=FieldType.NUMBER,
                    value=str(sum(d.stat().st_size // (1024**3) for d in self.vm.disks if d.exists()) or "N/A"),
                    disabled=True,  # Can't resize disk easily
                ),
                FormField(
                    name="cpu_pinning",
                    label="CPU Pinning:",
                    field_type=FieldType.SELECT,
                    value="none",
                    placeholder="Press Enter to configure...",
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("next", "Next")],
        ))

        # Step 2: Network
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="network",
                    label="Network:",
                    field_type=FieldType.SELECT,
                    value=self.vm.networks[0] if self.vm.networks else DEFAULT_NETWORK,
                    placeholder="Press Enter to select...",
                ),
                FormField(
                    name="nic_model",
                    label="NIC Model:",
                    field_type=FieldType.SELECT,
                    value="virtio",
                    options=[
                        ("virtio", "VirtIO (Best performance)"),
                        ("e1000e", "Intel e1000e (Good compatibility)"),
                        ("e1000", "Intel e1000 (Legacy)"),
                        ("rtl8139", "Realtek RTL8139 (Wide compatibility)"),
                        ("vmxnet3", "VMware vmxnet3"),
                    ],
                    recommended=["virtio", "e1000e"],
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("next", "Next")],
        ))

        # Step 3: Display & GPU
        # Get GPU display text
        gpu_display = "None"
        if self.selected_gpus:
            gpu_names = []
            for addr in self.selected_gpus:
                gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                if gpu:
                    gpu_names.append(gpu.display_name)
                else:
                    gpu_names.append(addr)
            gpu_display = ", ".join(gpu_names) if gpu_names else f"{len(self.selected_gpus)} selected"

        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="gpu",
                    label="GPU Passthrough:",
                    field_type=FieldType.SELECT,
                    value=gpu_display,
                    placeholder="Press Enter to select GPUs...",
                ),
                FormField(
                    name="graphics",
                    label="Remote Access:",
                    field_type=FieldType.SELECT,
                    value=self.vm.graphics_type or "spice",
                    options=[
                        ("spice", "SPICE - Remote desktop (recommended)"),
                        ("vnc", "VNC - Basic remote viewer"),
                        ("none", "None - Serial console only"),
                    ],
                    recommended=["spice"],
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("next", "Next")],
        ))

        # Step 4: Audio
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="audio",
                    label="Audio Device:",
                    field_type=FieldType.SELECT,
                    value="ich9",
                    options=[
                        ("ich9", "Intel ICH9 (Recommended)"),
                        ("ich6", "Intel ICH6"),
                        ("ac97", "AC97 (Legacy)"),
                        ("none", "None"),
                    ],
                    recommended=["ich9"],
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("next", "Next")],
        ))

        # Step 5: Settings
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="autostart",
                    label="Autostart:",
                    field_type=FieldType.SELECT,
                    value="yes" if self.vm.autostart else "no",
                    options=[
                        ("yes", "Yes - Start on host boot"),
                        ("no", "No"),
                    ],
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("save", "Save")],
        ))

        # Load network options
        self._load_options()

    def _load_options(self) -> None:
        """Load available options for selects."""
        # Networks
        network_options: list[tuple[str, str]] = []
        for bridge in self.network_service.list_bridges():
            network_options.append((f"bridge:{bridge}", f"{bridge} (bridge)"))
        try:
            for net in self.libvirt.list_networks():
                network_options.append((f"network:{net}", f"{net} (libvirt)"))
        except Exception:
            pass
        if network_options:
            self.forms[2].fields[0].options = network_options

    def run(self) -> dict[str, Any] | None:
        """Run the wizard. Returns changes dict or None if cancelled."""
        self.step = 0

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
        """Render the current step."""
        print(self.term.home + self.term.clear, end="")

        # Header
        step_titles = [
            "Basic Information",
            "Resources",
            "Network",
            "Display & GPU",
            "Audio",
            "Settings",
        ]
        title = f" Edit VM - {step_titles[self.step]} ({self.step + 1}/{len(self.forms)}) "
        print(
            self.term.move_xy(0, 0)
            + self.term.black_on_cyan(title.center(self.term.width)),
            end="",
        )

        # Hint about restart
        if self.step in [1, 2, 3, 4]:  # Steps that require restart
            hint = self.theme.warning("Changes require VM restart to take effect")
            print(self.term.move_xy(2, 2) + hint, end="")
            y = 4
        else:
            y = 3

        # Form
        self.forms[self.step].render(2, y, self.term.width - 4)

        # Footer
        hints = "Tab/↓: Next  Shift+Tab/↑: Previous  Enter: Select/Confirm"
        print(
            self.term.move_xy(0, self.term.height - 1)
            + self.theme.dim(hints[:self.term.width]),
            end="",
            flush=True,
        )

    def _handle_key(self, key: Keystroke) -> str | None:
        """Handle key input."""
        form = self.forms[self.step]
        result = form.handle_key(key)

        if result is None:
            return None

        # Handle select field actions
        if result.startswith("select:"):
            field_name = result.split(":")[1]
            self._handle_select(field_name)
            return None

        # Handle buttons
        if result == "cancel":
            return "cancel"
        elif result == "prev":
            self.step = max(0, self.step - 1)
        elif result == "next":
            if form.validate():
                self.step = min(len(self.forms) - 1, self.step + 1)
        elif result == "save":
            if form.validate():
                return "save"

        return None

    def _handle_select(self, field_name: str) -> None:
        """Handle select field interaction."""
        if field_name == "network":
            options = self.forms[2].fields[0].options
            if options:
                dialog = SearchSelect(
                    self.term,
                    self.theme,
                    "Select Network",
                    options,
                )
                result = dialog.show()
                if result:
                    display_name = result.split(":", 1)[1]
                    self.forms[2].set_value("network", display_name)
                    self.changes["network"] = result
                    self.forms[2]._focus_next()

        elif field_name == "graphics":
            options = self.forms[3].fields[1].options
            dialog = SearchSelect(
                self.term,
                self.theme,
                "Select Display Type",
                options,
            )
            result = dialog.show()
            if result:
                self.forms[3].set_value("graphics", result)
                self.changes["graphics"] = result
                self.forms[3]._focus_next()

        elif field_name == "nic_model":
            options = self.forms[2].fields[1].options
            dialog = SearchSelect(
                self.term,
                self.theme,
                "Select NIC Model",
                options,
            )
            result = dialog.show()
            if result:
                self.forms[2].set_value("nic_model", result)
                self.changes["nic_model"] = result
                self.forms[2]._focus_next()

        elif field_name == "audio":
            options = self.forms[4].fields[0].options
            dialog = SearchSelect(
                self.term,
                self.theme,
                "Select Audio Device",
                options,
            )
            result = dialog.show()
            if result:
                self.forms[4].set_value("audio", result)
                self.changes["audio"] = result
                self.forms[4]._focus_next()

        elif field_name == "autostart":
            options = self.forms[5].fields[0].options
            dialog = SearchSelect(
                self.term,
                self.theme,
                "Autostart on Boot",
                options,
            )
            result = dialog.show()
            if result:
                self.forms[5].set_value("autostart", result)
                self.changes["autostart"] = result == "yes"
                self.forms[5]._focus_next()

        elif field_name == "cpu_pinning":
            max_cpus = self.resources.cpu_count
            options: list[tuple[str, str]] = [("none", "None - No CPU pinning")]
            if max_cpus >= 2:
                options.append(("0-1", "CPUs 0-1 (first 2 cores)"))
            if max_cpus >= 4:
                options.append(("0-3", "CPUs 0-3 (first 4 cores)"))
            if max_cpus >= 8:
                options.append(("0-7", "CPUs 0-7 (first 8 cores)"))

            dialog = SearchSelect(
                self.term,
                self.theme,
                "Select CPU Pinning",
                options,
            )
            result = dialog.show()
            if result:
                self.forms[1].set_value("cpu_pinning", result)
                self.changes["cpu_pinning"] = result if result != "none" else ""
                self.forms[1]._focus_next()

        elif field_name == "gpu":
            # Refresh GPU list
            self.available_gpus = self.gpu_service.list_gpus()

            if not self.gpu_service.check_iommu_enabled():
                if self.available_gpus:
                    from vm_manager.ui.widgets.dialog import MessageDialog
                    MessageDialog(
                        self.term,
                        self.theme,
                        "IOMMU Disabled",
                        "GPUs found but IOMMU is not enabled",
                        "warning",
                    ).show()
                return

            if not self.available_gpus:
                from vm_manager.ui.widgets.dialog import MessageDialog
                MessageDialog(
                    self.term,
                    self.theme,
                    "No GPUs",
                    "No GPUs found for passthrough",
                    "warning",
                ).show()
                return

            # Create multi-select style list
            gpu_options: list[tuple[str, str]] = []
            for gpu in self.available_gpus:
                # Mark if already selected
                selected = gpu.pci_address in self.selected_gpus
                prefix = "[X] " if selected else "[ ] "

                # Get IOMMU group info
                group = self.gpu_service.get_iommu_group(gpu.pci_address)
                if group and len(group.devices) > 1:
                    device_types = [d.device_type for d in group.devices]
                    type_summary = ", ".join(sorted(set(device_types)))
                    label = f"{prefix}{gpu.display_name} (IOMMU: {type_summary})"
                else:
                    label = f"{prefix}{gpu.full_description}"
                gpu_options.append((gpu.pci_address, label))

            dialog = SearchSelect(
                self.term,
                self.theme,
                "Toggle GPU (Enter to toggle, Esc when done)",
                gpu_options,
            )

            # Keep showing dialog until user presses Escape
            while True:
                result = dialog.show()
                if result is None:
                    break

                # Toggle selection - include entire IOMMU group
                group = self.gpu_service.get_iommu_group(result)
                group_addrs = group.pci_addresses if group else [result]

                if result in self.selected_gpus:
                    # Remove all devices in group
                    for addr in group_addrs:
                        if addr in self.selected_gpus:
                            self.selected_gpus.remove(addr)
                else:
                    # Add all devices in group
                    for addr in group_addrs:
                        if addr not in self.selected_gpus:
                            self.selected_gpus.append(addr)

                # Update display
                for i, (val, display) in enumerate(gpu_options):
                    selected = val in self.selected_gpus
                    prefix = "[X] " if selected else "[ ] "
                    gpu = next((g for g in self.available_gpus if g.pci_address == val), None)
                    if gpu:
                        group = self.gpu_service.get_iommu_group(gpu.pci_address)
                        if group and len(group.devices) > 1:
                            device_types = [d.device_type for d in group.devices]
                            type_summary = ", ".join(sorted(set(device_types)))
                            gpu_options[i] = (val, f"{prefix}{gpu.display_name} (IOMMU: {type_summary})")
                        else:
                            gpu_options[i] = (val, f"{prefix}{gpu.full_description}")
                dialog.all_options = gpu_options
                dialog.filtered_options = gpu_options.copy()
                # Reset search state for better UX
                dialog.search_query = ""
                dialog.selected_index = 0
                dialog.scroll_offset = 0

            # Update form display
            if self.selected_gpus:
                gpu_names = []
                for addr in self.selected_gpus:
                    gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                    if gpu:
                        gpu_names.append(gpu.display_name)
                    else:
                        gpu_names.append(addr)
                display = ", ".join(gpu_names)
            else:
                display = "None"
            self.forms[3].set_value("gpu", display)
            self.changes["gpu_devices"] = self.selected_gpus.copy()
            self.forms[3]._focus_next()

    def _get_changes(self) -> dict[str, Any]:
        """Get all changes from forms."""
        changes = self.changes.copy()

        # Get values from forms
        values = {}
        for form in self.forms:
            values.update(form.get_values())

        # Check what changed
        if int(values.get("vcpus", self.vm.vcpus)) != self.vm.vcpus:
            changes["vcpus"] = int(values["vcpus"])

        if int(values.get("memory", self.vm.memory_mb)) != self.vm.memory_mb:
            changes["memory"] = int(values["memory"])

        if "autostart" not in changes:
            new_autostart = values.get("autostart", "no") == "yes"
            if new_autostart != self.vm.autostart:
                changes["autostart"] = new_autostart

        return changes
