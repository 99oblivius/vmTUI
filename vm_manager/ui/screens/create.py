"""VM creation wizard screen."""

from pathlib import Path

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.config import (
    DEFAULT_DISK_GB,
    DEFAULT_NETWORK,
    DEFAULT_OS_VARIANT,
    DEFAULT_RAM_MB,
    DEFAULT_VCPUS,
    ISO_DIR,
)
from vm_manager.models import GPUDevice, USBDevice, VMConfig
from vm_manager.services import GPUService, LibvirtService, NetworkService, OSInfoService, SystemService, USBService
from vm_manager.services.system import SystemResources
from vm_manager.ui.theme import Theme
from vm_manager.ui.widgets.form import FieldType, Form, FormField
from vm_manager.ui.widgets.search_select import SearchSelect


class CreateWizard:
    """Step-by-step VM creation wizard."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        libvirt: LibvirtService,
        gpu_service: GPUService,
        osinfo_service: OSInfoService,
        system_service: SystemService | None = None,
        usb_service: USBService | None = None,
        network_service: NetworkService | None = None,
    ) -> None:
        self.term = term
        self.theme = theme
        self.libvirt = libvirt
        self.gpu_service = gpu_service
        self.osinfo_service = osinfo_service
        self.system_service = system_service or SystemService()
        self.usb_service = usb_service or USBService()
        self.network_service = network_service or NetworkService()

        # Get system resources
        self.resources: SystemResources = self.system_service.get_resources()

        # Wizard state
        self.step = 0
        self.total_steps = 8

        # Configuration being built
        self.config = VMConfig(
            name="",
            vcpus=DEFAULT_VCPUS,
            memory_mb=DEFAULT_RAM_MB,
            disk_size_gb=DEFAULT_DISK_GB,
            os_variant=DEFAULT_OS_VARIANT,
            network=DEFAULT_NETWORK,
            graphics="spice",
            audio_model="ich9",
        )

        # Step data
        self.available_networks: list[str] = []
        self.available_gpus: list[GPUDevice] = []
        self.available_usb: list[USBDevice] = []
        self.iso_files: list[Path] = []

        # Forms for each step
        self.forms: list[Form] = []
        self._init_forms()

    def _init_forms(self) -> None:
        """Initialize forms for each step."""
        # Step 0: Basic info
        def validate_name(x: str) -> str | None:
            if not x:
                return "Name is required"
            # Check if VM name already exists
            try:
                existing_vms = self.libvirt.list_vms()
                if any(vm.name == x for vm in existing_vms):
                    return f"VM '{x}' already exists"
            except Exception:
                pass  # If we can't check, allow it (will fail later with better error)
            return None

        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="name",
                    label="VM Name:",
                    field_type=FieldType.TEXT,
                    placeholder="e.g., my-vm",
                    validator=validate_name,
                ),
            ],
            buttons=[("cancel", "Cancel"), ("next", "Next")],
        ))

        # Step 1: Resources
        max_cpus = self.resources.cpu_count
        max_mem = self.resources.memory_mb
        max_disk = self.resources.disk_free_gb

        def validate_cpus(x: str) -> str | None:
            if not x:
                return "Required"
            try:
                val = int(x)
                if val < 1:
                    return "Must be at least 1"
                if val > max_cpus:
                    return f"Max available: {max_cpus}"
            except ValueError:
                return "Invalid number"
            return None

        def validate_memory(x: str) -> str | None:
            if not x:
                return "Required"
            try:
                val = int(x)
                if val < 256:
                    return "Must be at least 256"
                if val > max_mem:
                    return f"Max available: {max_mem}"
            except ValueError:
                return "Invalid number"
            return None

        def validate_disk(x: str) -> str | None:
            if not x:
                return "Required"
            try:
                val = int(x)
                if val < 1:
                    return "Must be at least 1"
                if val > max_disk:
                    return f"Max available: {max_disk}"
            except ValueError:
                return "Invalid number"
            return None

        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="vcpus",
                    label=f"CPUs (1-{max_cpus}):",
                    field_type=FieldType.NUMBER,
                    value=str(DEFAULT_VCPUS),
                    validator=validate_cpus,
                ),
                FormField(
                    name="memory",
                    label=f"Memory MB (256-{max_mem}):",
                    field_type=FieldType.NUMBER,
                    value=str(DEFAULT_RAM_MB),
                    validator=validate_memory,
                ),
                FormField(
                    name="disk",
                    label=f"Disk GB (1-{max_disk}):",
                    field_type=FieldType.NUMBER,
                    value=str(DEFAULT_DISK_GB),
                    validator=validate_disk,
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

        # Step 2: OS & Media
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="os_variant",
                    label="OS Variant:",
                    field_type=FieldType.SELECT,
                    value=DEFAULT_OS_VARIANT,
                    placeholder="Press Enter to search...",
                ),
                FormField(
                    name="iso_path",
                    label="ISO File:",
                    field_type=FieldType.SELECT,
                    placeholder="Press Enter to browse...",
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("next", "Next")],
        ))

        # Step 3: Network
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="network",
                    label="Network:",
                    field_type=FieldType.SELECT,
                    value=DEFAULT_NETWORK,
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

        # Step 4: Display & GPU (combined for clarity)
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="gpu",
                    label="GPU Passthrough:",
                    field_type=FieldType.SELECT,
                    value="none",
                    placeholder="Press Enter to select GPUs...",
                ),
                FormField(
                    name="graphics",
                    label="Remote Access:",
                    field_type=FieldType.SELECT,
                    value="spice",
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

        # Step 5: Audio
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

        # Step 6: USB Passthrough
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="usb",
                    label="USB Devices:",
                    field_type=FieldType.SELECT,
                    value="none",
                    placeholder="Press Enter to select devices...",
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("next", "Next")],
        ))

        # Step 7: Review
        self.forms.append(Form(
            self.term,
            self.theme,
            fields=[
                FormField(
                    name="autostart",
                    label="Start after creation:",
                    field_type=FieldType.SELECT,
                    value="no",
                    options=[("no", "No"), ("yes", "Yes")],
                ),
            ],
            buttons=[("cancel", "Cancel"), ("prev", "Previous"), ("create", "Create")],
        ))

    def run(self) -> VMConfig | None:
        """Run the wizard. Returns config or None if cancelled."""
        # Load available options
        self._load_options()

        with self.term.cbreak(), self.term.hidden_cursor():
            while True:
                self._render()

                key: Keystroke = self.term.inkey(timeout=0.1)
                if not key:
                    continue

                result = self._handle_key(key)
                if result == "cancel":
                    return None
                elif result == "complete":
                    return self.config

    def _load_options(self) -> None:
        """Load available options for selects."""
        # Networks - include both bridges and libvirt networks
        network_options: list[tuple[str, str]] = []

        # Add host bridges first
        for bridge in self.network_service.list_bridges():
            network_options.append((f"bridge:{bridge}", f"{bridge} (bridge)"))

        # Add libvirt networks
        try:
            for net in self.libvirt.list_networks():
                network_options.append((f"network:{net}", f"{net} (libvirt)"))
        except Exception:
            pass

        # Set default to first bridge if available, otherwise first network
        if network_options:
            self.forms[3].fields[0].options = network_options
            default = network_options[0][0]
            if default.startswith("bridge:"):
                self.config.network_type = "bridge"
                self.config.network = default[7:]
            else:
                self.config.network_type = "network"
                self.config.network = default[8:]
            self.forms[3].set_value("network", network_options[0][1].split(" ")[0])

        # GPUs
        self.available_gpus = self.gpu_service.list_gpus()
        gpu_options: list[tuple[str, str]] = [("none", "None")]
        if self.gpu_service.check_iommu_enabled():
            for gpu in self.available_gpus:
                gpu_options.append((gpu.pci_address, gpu.full_description))
        self.forms[4].fields[0].options = gpu_options

        # ISO files
        if ISO_DIR.exists():
            self.iso_files = sorted(ISO_DIR.glob("*.iso"))

    def _render(self) -> None:
        """Render the current wizard step."""
        print(self.term.home + self.term.clear, end="")

        # Header
        step_titles = [
            "Basic Information",
            "Resources",
            "Operating System",
            "Network",
            "Display & GPU",
            "Audio",
            "USB Passthrough",
            "Review & Create",
        ]
        title = f" Create VM - {step_titles[self.step]} ({self.step + 1}/{self.total_steps}) "
        print(
            self.term.move_xy(0, 0)
            + self.term.black_on_cyan(title.center(self.term.width)),
            end="",
        )

        # Form content
        y = 3
        form = self.forms[self.step]

        if self.step == 7:
            # Review step - show summary
            y = self._render_review(y)
            # Render just the buttons
            form.render(2, y + 2, self.term.width - 4)
        else:
            form.render(2, y, self.term.width - 4)

        # Footer hint
        hint = "Tab/↑↓: navigate  ←→: edit/select  Enter: confirm"
        print(
            self.term.move_xy(0, self.term.height - 1)
            + self.theme.dim(hint.center(self.term.width)),
            end="",
        )

        print("", end="", flush=True)

    def _render_review(self, y: int) -> int:
        """Render review summary. Returns y position after."""
        # Display names
        graphics_names = {
            "spice": "SPICE",
            "vnc": "VNC",
            "none": "None (Headless)",
        }

        cpu_info = str(self.config.vcpus)
        if self.config.cpu_pinning:
            cpu_info += f" (pinned: {self.config.cpu_pinning})"

        values = [
            ("Name:", self.config.name),
            ("CPUs:", cpu_info),
            ("Memory:", f"{self.config.memory_mb} MB"),
            ("Disk:", f"{self.config.disk_size_gb} GB"),
            ("OS Variant:", self.config.os_variant),
            ("Network:", f"{self.config.network} ({self.config.network_type}, {self.config.nic_model})"),
            ("ISO:", self.config.iso_path.name if self.config.iso_path else "None"),
            ("Display:", graphics_names.get(self.config.graphics, "Unknown")),
        ]

        if self.config.gpu_devices:
            # Show GPU names
            gpu_names = []
            for addr in self.config.gpu_devices:
                gpu = self.gpu_service.get_gpu_by_address(addr)
                if gpu:
                    gpu_names.append(gpu.display_name)
            if gpu_names:
                gpu_text = ", ".join(gpu_names)
            else:
                gpu_text = f"{len(self.config.gpu_devices)} device(s)"
            if self.config.graphics != "none":
                gpu_text += f" + {self.config.graphics.upper()}"
            values.append(("GPU:", gpu_text))
        else:
            values.append(("GPU:", "None"))

        # Audio
        audio_names = {
            "none": "None",
            "ac97": "AC97",
            "ich6": "Intel ICH6",
            "ich9": "Intel ICH9",
        }
        values.append(("Audio:", audio_names.get(self.config.audio_model, "None")))

        # USB
        if self.config.usb_devices:
            values.append(("USB:", f"{len(self.config.usb_devices)} device(s)"))
        else:
            values.append(("USB:", "None"))

        for label, value in values:
            print(self.term.move_xy(2, y) + f"{label:15} {value}", end="")
            y += 1

        return y

    def _handle_key(self, key: Keystroke) -> str | None:
        """Handle key input. Returns 'cancel', 'complete', or None."""
        form = self.forms[self.step]
        result = form.handle_key(key)

        if result is None:
            return None

        # Handle select field actions
        if result.startswith("select:"):
            field_name = result.split(":")[1]
            self._handle_select(field_name)
            return None

        # Handle button presses
        if result == "cancel":
            return "cancel"
        elif result == "prev":
            self._save_step_values()
            self.step = max(0, self.step - 1)
            self._load_step_values()
        elif result == "next":
            if form.validate():
                self._save_step_values()
                self.step += 1
                self._load_step_values()
        elif result == "create":
            if form.validate():
                self._save_step_values()
                return "complete"

        return None

    def _show_field_dialog(
        self,
        form_idx: int,
        field_name: str,
        title: str,
        options: list[tuple[str, str]] | None = None,
        auto_next: bool = True,
    ) -> str | None:
        """Show a SearchSelect dialog for a form field. Returns selected value."""
        form = self.forms[form_idx]
        field = next((f for f in form.fields if f.name == field_name), None)
        if not field:
            return None

        # Use provided options or get from field
        if options is None:
            options = field.get_sorted_options()

        if not options:
            from vm_manager.ui.widgets.dialog import MessageDialog
            MessageDialog(
                self.term,
                self.theme,
                "No Options",
                f"No options available for {field_name}",
                "warning",
            ).show()
            return None

        dialog = SearchSelect(
            self.term,
            self.theme,
            title,
            options,
        )
        result = dialog.show()
        if result:
            form.set_value(field_name, result)
            # Auto advance to next field
            if auto_next:
                form._focus_next()
        return result

    def _handle_select(self, field_name: str) -> None:
        """Handle select field activation."""
        if field_name == "os_variant":
            # Show fuzzy search dialog for OS variants
            variants = self.osinfo_service.list_variants()
            options = [(v.short_id, f"{v.short_id} - {v.name}") for v in variants]
            self._show_field_dialog(2, "os_variant", "Select OS Variant", options)

        elif field_name == "network":
            # Build network options from both libvirt networks and host bridges
            options: list[tuple[str, str]] = []

            # Add host bridges first (usually preferred for direct network access)
            for bridge in self.network_service.list_bridges():
                info = self.network_service.get_bridge_info(bridge)
                ip_info = f" - {info.get('ip', 'no IP')}" if info.get('ip') else ""
                options.append((f"bridge:{bridge}", f"{bridge} (host bridge{ip_info})"))

            # Add libvirt networks
            try:
                for net in self.libvirt.list_networks():
                    options.append((f"network:{net}", f"{net} (libvirt network)"))
            except Exception:
                pass

            if not options:
                from vm_manager.ui.widgets.dialog import MessageDialog
                MessageDialog(
                    self.term,
                    self.theme,
                    "No Networks",
                    "No networks or bridges found",
                    "warning",
                ).show()
                return

            dialog = SearchSelect(
                self.term,
                self.theme,
                "Select Network",
                options,
            )
            result = dialog.show()
            if result:
                # Parse result to get type and name
                if result.startswith("bridge:"):
                    self.config.network_type = "bridge"
                    self.config.network = result[7:]  # Remove "bridge:" prefix
                else:
                    self.config.network_type = "network"
                    self.config.network = result[8:]  # Remove "network:" prefix

                # Update display
                display_name = result.split(":", 1)[1]
                self.forms[3].set_value("network", display_name)
                self.forms[3]._focus_next()

        elif field_name == "nic_model":
            # Show NIC model options dialog
            self._show_field_dialog(3, "nic_model", "Select NIC Model")

        elif field_name == "graphics":
            # Show graphics options dialog
            self._show_field_dialog(4, "graphics", "Select Display Type")

        elif field_name == "audio":
            # Show audio options dialog
            self._show_field_dialog(5, "audio", "Select Audio Device")

        elif field_name == "cpu_pinning":
            # Show CPU pinning options
            max_cpus = self.resources.cpu_count
            options: list[tuple[str, str]] = [("none", "None - No CPU pinning")]

            # Add common pinning patterns
            if max_cpus >= 2:
                options.append(("0-1", "CPUs 0-1 (first 2 cores)"))
            if max_cpus >= 4:
                options.append(("0-3", "CPUs 0-3 (first 4 cores)"))
            if max_cpus >= 8:
                options.append(("0-7", "CPUs 0-7 (first 8 cores)"))
            if max_cpus >= 4:
                # Even cores for NUMA-like behavior
                even = ",".join(str(i) for i in range(0, min(max_cpus, 8), 2))
                options.append((even, f"CPUs {even} (even cores)"))

            # Custom option
            options.append(("custom", "Custom (enter manually)"))

            dialog = SearchSelect(
                self.term,
                self.theme,
                "Select CPU Pinning",
                options,
            )
            result = dialog.show()

            if result == "custom":
                # Show input dialog for custom pinning
                from vm_manager.ui.widgets.dialog import InputDialog
                input_dialog = InputDialog(
                    self.term,
                    self.theme,
                    "Custom CPU Pinning",
                    f"Enter CPU list (e.g., 0-3 or 0,2,4,6) [0-{max_cpus-1}]:",
                    "",
                )
                custom_value = input_dialog.show()
                if custom_value:
                    self.config.cpu_pinning = custom_value
                    self.forms[1].set_value("cpu_pinning", custom_value)
                    self.forms[1]._focus_next()
            elif result and result != "none":
                self.config.cpu_pinning = result
                self.forms[1].set_value("cpu_pinning", result)
                self.forms[1]._focus_next()
            elif result == "none":
                self.config.cpu_pinning = ""
                self.forms[1].set_value("cpu_pinning", "none")
                self.forms[1]._focus_next()

        elif field_name == "gpu":
            # Refresh GPU list - Multi-select like USB
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

            # Create options list with disabled flag for non-vfio GPUs
            from vm_manager.ui.widgets.dialog import ToggleListDialog

            gpu_options: list[tuple[str, str, bool]] = []
            for gpu in self.available_gpus:
                # Get IOMMU group info
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
                self.term,
                self.theme,
                "Select GPUs for Passthrough",
                gpu_options,
                selected=self.config.gpu_devices,
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

            self.config.gpu_devices = new_selected

            # Update form display with GPU names
            if self.config.gpu_devices:
                # Get names of selected GPUs (only actual GPUs, not audio devices etc)
                gpu_names = []
                for addr in self.config.gpu_devices:
                    gpu = next((g for g in self.available_gpus if g.pci_address == addr), None)
                    if gpu:
                        gpu_names.append(gpu.display_name)
                if gpu_names:
                    display_text = ", ".join(gpu_names)
                else:
                    display_text = f"{len(self.config.gpu_devices)} device(s)"
                self.forms[4].set_value("gpu", display_text)
            else:
                self.forms[4].set_value("gpu", "none")
            # Auto advance after multi-select
            self.forms[4]._focus_next()

        elif field_name == "iso_path":
            # Refresh ISO file list
            if ISO_DIR.exists():
                self.iso_files = sorted(ISO_DIR.glob("*.iso"))
            else:
                self.iso_files = []

            # Show ISO file selector
            if self.iso_files:
                options = [(str(f), f.name) for f in self.iso_files]
                dialog = SearchSelect(
                    self.term,
                    self.theme,
                    "Select ISO File",
                    options,
                )
                result = dialog.show()
                if result:
                    self.forms[2].fields[1].value = Path(result).name
                    self.config.iso_path = Path(result)
                    self.forms[2]._focus_next()
            else:
                # Show message that no ISOs were found
                from vm_manager.ui.widgets.dialog import MessageDialog
                MessageDialog(
                    self.term,
                    self.theme,
                    "No ISO Files",
                    f"No .iso files found in {ISO_DIR}",
                    "warning",
                ).show()

        elif field_name == "usb":
            # Refresh USB device list
            self.available_usb = self.usb_service.list_devices()

            if self.available_usb:
                # Create multi-select style list
                options: list[tuple[str, str]] = []
                for usb in self.available_usb:
                    # Mark if already selected
                    selected = usb.id_string in self.config.usb_devices
                    prefix = "[X] " if selected else "[ ] "
                    options.append((usb.id_string, f"{prefix}{usb.full_description}"))

                dialog = SearchSelect(
                    self.term,
                    self.theme,
                    "Toggle USB Device (Enter to toggle, Esc when done)",
                    options,
                )

                # Keep showing dialog until user presses Escape
                while True:
                    result = dialog.show()
                    if result is None:
                        break

                    # Toggle selection
                    if result in self.config.usb_devices:
                        self.config.usb_devices.remove(result)
                    else:
                        self.config.usb_devices.append(result)

                    # Update display
                    for i, (val, display) in enumerate(options):
                        selected = val in self.config.usb_devices
                        prefix = "[X] " if selected else "[ ] "
                        usb = next((u for u in self.available_usb if u.id_string == val), None)
                        if usb:
                            options[i] = (val, f"{prefix}{usb.full_description}")
                    dialog.all_options = options
                    dialog.filtered_options = options.copy()

                # Update form display
                if self.config.usb_devices:
                    self.forms[6].set_value("usb", f"{len(self.config.usb_devices)} selected")
                else:
                    self.forms[6].set_value("usb", "none")
                # Auto advance after multi-select
                self.forms[6]._focus_next()
            else:
                from vm_manager.ui.widgets.dialog import MessageDialog
                MessageDialog(
                    self.term,
                    self.theme,
                    "No USB Devices",
                    "No USB devices found for passthrough",
                    "warning",
                ).show()

        elif field_name == "autostart":
            # Show autostart options dialog
            self._show_field_dialog(7, "autostart", "Start After Creation")

    def _save_step_values(self) -> None:
        """Save current form values to config."""
        values = self.forms[self.step].get_values()

        if self.step == 0:
            self.config.name = values.get("name", "")
        elif self.step == 1:
            self.config.vcpus = int(values.get("vcpus", str(DEFAULT_VCPUS)) or str(DEFAULT_VCPUS))
            self.config.memory_mb = int(values.get("memory", str(DEFAULT_RAM_MB)) or str(DEFAULT_RAM_MB))
            self.config.disk_size_gb = int(values.get("disk", str(DEFAULT_DISK_GB)) or str(DEFAULT_DISK_GB))
            # cpu_pinning is set directly in _handle_select
        elif self.step == 2:
            self.config.os_variant = values.get("os_variant", DEFAULT_OS_VARIANT)
            # iso_path is set directly in _handle_select
        elif self.step == 3:
            # Network is set directly in _handle_select
            self.config.nic_model = values.get("nic_model", "virtio")
        elif self.step == 4:
            # GPU devices are set directly in _handle_select with multi-select
            self.config.graphics = values.get("graphics", "spice")
        elif self.step == 5:
            self.config.audio_model = values.get("audio", "ich9")
        elif self.step == 6:
            # USB devices are set directly in _handle_select
            pass
        elif self.step == 7:
            self.config.autostart = values.get("autostart", "no") == "yes"

    def _load_step_values(self) -> None:
        """Load config values into current form."""
        if self.step == 0:
            self.forms[0].set_value("name", self.config.name)
        elif self.step == 1:
            self.forms[1].set_value("vcpus", str(self.config.vcpus))
            self.forms[1].set_value("memory", str(self.config.memory_mb))
            self.forms[1].set_value("disk", str(self.config.disk_size_gb))
            if self.config.cpu_pinning:
                self.forms[1].set_value("cpu_pinning", self.config.cpu_pinning)
            else:
                self.forms[1].set_value("cpu_pinning", "none")
        elif self.step == 2:
            self.forms[2].set_value("os_variant", self.config.os_variant)
            if self.config.iso_path:
                self.forms[2].fields[1].value = self.config.iso_path.name
        elif self.step == 3:
            self.forms[3].set_value("network", self.config.network)
            self.forms[3].set_value("nic_model", self.config.nic_model)
        elif self.step == 4:
            # Combined Display & GPU step
            if self.config.gpu_devices:
                # Get names of selected GPUs
                gpu_names = []
                for addr in self.config.gpu_devices:
                    gpu = self.gpu_service.get_gpu_by_address(addr)
                    if gpu:
                        gpu_names.append(gpu.display_name)
                if gpu_names:
                    display_text = ", ".join(gpu_names)
                else:
                    display_text = f"{len(self.config.gpu_devices)} device(s)"
                self.forms[4].set_value("gpu", display_text)
            else:
                self.forms[4].set_value("gpu", "none")
            self.forms[4].set_value("graphics", self.config.graphics)
        elif self.step == 5:
            self.forms[5].set_value("audio", self.config.audio_model)
        elif self.step == 6:
            if self.config.usb_devices:
                self.forms[6].set_value("usb", f"{len(self.config.usb_devices)} selected")
            else:
                self.forms[6].set_value("usb", "none")
        elif self.step == 7:
            self.forms[7].set_value("autostart", "yes" if self.config.autostart else "no")
