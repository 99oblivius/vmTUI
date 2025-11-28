"""Main application class."""

import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.config import DISK_DIR, ISO_DIR, VM_DIR
from vm_manager.services import GPUService, LibvirtService, OSInfoService
from vm_manager.ui.screens.create import CreateWizard
from vm_manager.ui.screens.main import MainScreen
from vm_manager.ui.theme import Theme
from vm_manager.ui.widgets.checkpoint_dialog import CheckpointDialog
from vm_manager.ui.widgets.dialog import ConfirmDialog, DeleteDialog, InputDialog, MessageDialog, SelectDialog


class BackgroundTask:
    """A task that runs in the background."""

    def __init__(
        self,
        func: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ):
        self.func = func
        self.on_success = on_success
        self.on_error = on_error
        self.result: Any = None
        self.error: Exception | None = None
        self.done = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the task in a background thread."""
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        """Run the task."""
        try:
            self.result = self.func()
        except Exception as e:
            self.error = e
        finally:
            self.done = True

    def check(self) -> bool:
        """Check if task is done and call callbacks. Returns True if done."""
        if self.done:
            if self.error and self.on_error:
                self.on_error(self.error)
            elif self.on_success:
                self.on_success(self.result)
            return True
        return False


class App:
    """Main VM Manager application."""

    def __init__(self) -> None:
        self.term = Terminal()
        self.theme = Theme(self.term)
        self.libvirt = LibvirtService()
        self.gpu_service = GPUService()
        self.osinfo_service = OSInfoService()
        self.main_screen: MainScreen | None = None
        self.running = False
        self.background_tasks: list[BackgroundTask] = []

    def run(self) -> int:
        """Run the application. Returns exit code."""
        # Set up signal handlers
        def handle_signal(signum: int, frame: Any) -> None:
            self.running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            # Check for libosinfo and show hint if not available
            hint = self.osinfo_service.get_install_hint()
            if hint:
                print("Note:", file=sys.stderr)
                print(hint, file=sys.stderr)
                print("", file=sys.stderr)

            # Ensure directories exist
            self._ensure_directories()

            # Connect to libvirt
            print("Connecting to libvirt...", end="", flush=True)
            self.libvirt.connect()
            print(" OK", flush=True)

            # Create main screen
            print("Loading VMs...", end="", flush=True)
            self.main_screen = MainScreen(
                self.term, self.theme, self.libvirt
            )
            self.main_screen.refresh_vms()
            print(f" {len(self.main_screen.vms)} found", flush=True)

            # Run main loop
            self.running = True
            print("Starting UI...", flush=True)
            return self._main_loop()

        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        finally:
            self.running = False
            self.libvirt.disconnect()

    def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        for directory in [VM_DIR, ISO_DIR, DISK_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

    def _main_loop(self) -> int:
        """Main application loop."""
        assert self.main_screen is not None

        with self.term.fullscreen(), self.term.cbreak(), self.term.hidden_cursor():
            needs_redraw = True
            last_width = self.term.width
            last_height = self.term.height

            while self.running:
                # Check for terminal resize
                if self.term.width != last_width or self.term.height != last_height:
                    last_width = self.term.width
                    last_height = self.term.height
                    needs_redraw = True

                # Check background tasks
                tasks_completed = self._check_background_tasks()
                if tasks_completed:
                    needs_redraw = True

                # Render main screen only when needed
                if needs_redraw:
                    self.main_screen.render()
                    needs_redraw = False

                # Wait for input with shorter timeout to check tasks more often
                key: Keystroke = self.term.inkey(timeout=0.5)

                if key:
                    action = self.main_screen.handle_key(
                        str(key) if len(key) == 1 else key.name or ""
                    )
                    self._handle_action(action)
                    needs_redraw = True

        return 0

    def _check_background_tasks(self) -> bool:
        """Check and process completed background tasks. Returns True if any completed."""
        completed = []
        for task in self.background_tasks:
            if task.check():
                completed.append(task)

        for task in completed:
            self.background_tasks.remove(task)

        # Refresh VMs if any tasks completed
        if completed and self.main_screen:
            self.main_screen.refresh_vms()

        return len(completed) > 0

    def _handle_action(self, action: str | None) -> None:
        """Handle action from main screen."""
        assert self.main_screen is not None

        if action is None:
            return

        if action == "quit":
            self.running = False
        elif action == "refresh":
            self.main_screen.refresh_vms()
            self.main_screen.set_status("Refreshed", "success")
        elif action == "new":
            self._create_vm()
        elif action == "delete":
            self._delete_vm()
        elif action == "start":
            self._start_vm()
        elif action == "stop":
            self._stop_vm()
        elif action == "save_edit":
            self._save_inline_edit()
        elif action == "console":
            self._open_console()
        elif action == "snapshots":
            self._manage_snapshots()
        elif action == "help":
            self._show_help()

    def _create_vm(self) -> None:
        """Show VM creation wizard."""
        assert self.main_screen is not None

        wizard = CreateWizard(
            self.term,
            self.theme,
            self.libvirt,
            self.gpu_service,
            self.osinfo_service,
        )

        config = wizard.run()
        if config:
            try:
                self.libvirt.create_vm(config)
                self.main_screen.refresh_vms()

                # Start if requested
                if config.autostart:
                    try:
                        self.libvirt.start_vm(config.name)
                        self.main_screen.refresh_vms()
                        self.main_screen.set_status(
                            f"VM '{config.name}' created and started", "success"
                        )
                    except Exception as e:
                        self.main_screen.set_status(
                            f"VM created but failed to start: {e}", "warning"
                        )
                else:
                    self.main_screen.set_status(
                        f"VM '{config.name}' created successfully", "success"
                    )

            except Exception as e:
                self.main_screen.set_status(f"Failed to create VM: {e}", "error")

    def _delete_vm(self) -> None:
        """Delete the selected VM."""
        assert self.main_screen is not None

        vm = self.main_screen.vm_list.selected_item
        if not vm:
            return

        # Check if storage exists
        has_storage = len(vm.disks) > 0 and any(d.exists() for d in vm.disks)

        # Show delete dialog with type-back confirmation
        dialog = DeleteDialog(
            self.term,
            self.theme,
            vm.name,
            has_storage=has_storage,
        )

        result = dialog.show()
        if result:
            delete_config, delete_storage = result

            # Show progress dialog for deletion
            import threading
            import time
            from vm_manager.ui.widgets.dialog import ProgressDialog

            # Determine what we're deleting for the progress message
            if delete_config and delete_storage:
                progress_msg = f"Deleting VM '{vm.name}' and storage..."
            elif delete_config:
                progress_msg = f"Deleting VM '{vm.name}' config..."
            elif delete_storage:
                progress_msg = f"Deleting storage for '{vm.name}'..."
            else:
                return  # Nothing to delete

            progress = ProgressDialog(
                self.term, self.theme, "Deleting VM", progress_msg
            )

            result_status = [None]
            error = [None]

            def delete_in_background():
                try:
                    if delete_config and delete_storage:
                        self.libvirt.delete_vm(vm.name, remove_storage=True)
                        result_status[0] = f"VM '{vm.name}' and storage deleted"
                    elif delete_config:
                        self.libvirt.delete_vm(vm.name, remove_storage=False)
                        result_status[0] = f"VM '{vm.name}' config deleted (storage kept)"
                    elif delete_storage:
                        self.libvirt.delete_storage(vm.name)
                        result_status[0] = f"Storage for '{vm.name}' deleted"
                except Exception as e:
                    error[0] = str(e)

            thread = threading.Thread(target=delete_in_background, daemon=True)
            thread.start()

            # Show progress dialog while thread runs
            with self.term.hidden_cursor():
                while thread.is_alive():
                    progress.show_frame()
                    # Drain input buffer to prevent key buffering
                    while True:
                        key = self.term.inkey(timeout=0)
                        if not key:
                            break
                    time.sleep(0.1)

            thread.join()

            if error[0]:
                self.main_screen.set_status(f"Failed to delete: {error[0]}", "error")
            elif result_status[0]:
                self.main_screen.set_status(result_status[0], "success")

            self.main_screen.refresh_vms()

    def _start_vm(self) -> None:
        """Start the selected VM."""
        assert self.main_screen is not None

        vm = self.main_screen.vm_list.selected_item
        if not vm or not vm.can_start:
            return

        # Confirm start
        dialog = ConfirmDialog(
            self.term,
            self.theme,
            "Start VM",
            f"Start VM '{vm.name}'?",
        )
        if not dialog.show():
            return

        vm_name = vm.name

        # Show starting status
        self.main_screen.set_status(f"Starting '{vm_name}'...", "info")

        def do_start() -> str:
            # Use subprocess instead of libvirt API for thread safety
            result = subprocess.run(
                ["virsh", "start", vm_name],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise Exception(result.stderr.strip() or "Failed to start VM")
            return vm_name

        def on_success(name: str) -> None:
            if self.main_screen:
                self.main_screen.set_status(f"VM '{name}' started", "success")

        def on_error(e: Exception) -> None:
            if self.main_screen:
                self.main_screen.set_status(f"Failed to start: {e}", "error")

        task = BackgroundTask(do_start, on_success, on_error)
        task.start()
        self.background_tasks.append(task)

    def _stop_vm(self) -> None:
        """Stop the selected VM."""
        assert self.main_screen is not None

        vm = self.main_screen.vm_list.selected_item
        if not vm or not vm.can_stop:
            return

        # Ask how to stop
        dialog = SelectDialog(
            self.term,
            self.theme,
            "Stop VM",
            [
                ("graceful", "Graceful Shutdown (recommended)"),
                ("force", "Force Stop (immediate)"),
                ("reset", "Reset (restart)"),
                ("cancel", "Cancel"),
            ],
            selected_index=0
        )

        result = dialog.show()
        if not result or result == "cancel":
            return

        vm_name = vm.name

        # Handle reset/restart
        if result == "reset":
            self.main_screen.set_status(f"Resetting '{vm_name}'...", "info")

            def do_reset() -> str:
                # Use subprocess instead of libvirt API for thread safety
                cmd = ["virsh", "reset", vm_name]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(result.stderr.strip() or "Failed to reset VM")
                return vm_name

            def on_reset_success(name: str) -> None:
                if self.main_screen:
                    self.main_screen.set_status(f"VM '{name}' reset", "success")

            def on_reset_error(e: Exception) -> None:
                if self.main_screen:
                    self.main_screen.set_status(f"Failed to reset: {e}", "error")

            task = BackgroundTask(do_reset, on_reset_success, on_reset_error)
            task.start()
            self.background_tasks.append(task)
            return

        # Handle stop
        graceful = result == "graceful"

        # Show stopping status
        action_msg = "Shutting down" if graceful else "Force stopping"
        self.main_screen.set_status(f"{action_msg} '{vm_name}'...", "info")

        def do_stop() -> tuple[str, bool]:
            # Use subprocess instead of libvirt API for thread safety
            cmd = ["virsh", "destroy" if not graceful else "shutdown", vm_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(result.stderr.strip() or "Failed to stop VM")
            return (vm_name, graceful)

        def on_success(result: tuple[str, bool]) -> None:
            name, was_graceful = result
            if self.main_screen:
                action = "shutdown signal sent" if was_graceful else "force stopped"
                self.main_screen.set_status(f"VM '{name}' {action}", "success")

        def on_error(e: Exception) -> None:
            if self.main_screen:
                self.main_screen.set_status(f"Failed to stop: {e}", "error")

        task = BackgroundTask(do_stop, on_success, on_error)
        task.start()
        self.background_tasks.append(task)

    def _save_inline_edit(self) -> None:
        """Save changes from inline edit mode."""
        assert self.main_screen is not None

        # Get VM before exiting edit mode
        vm = self.main_screen.edit_vm
        if not vm:
            return

        # Get changes from main screen's edit mode
        changes = self.main_screen.exit_edit_mode(save=True)
        if not changes:
            self.main_screen.set_status("No changes to save", "info")
            return

        try:
            applied = []

            # First, steal devices from other VMs if needed
            if "_devices_to_steal" in changes:
                devices_to_steal = changes.pop("_devices_to_steal")
                for device_id, (from_vm, device_type) in devices_to_steal.items():
                    try:
                        # Get the other VM
                        other_vm = next((v for v in self.libvirt.list_vms() if v.name == from_vm), None)
                        if other_vm:
                            if device_type == "gpu":
                                # Remove GPU from other VM
                                new_gpu_list = [gpu for gpu in other_vm.gpu_devices if gpu != device_id]
                                self.libvirt.set_gpu_passthrough(from_vm, new_gpu_list)
                            elif device_type == "usb":
                                # Remove USB from other VM
                                new_usb_list = [usb for usb in other_vm.usb_devices if usb != device_id]
                                self.libvirt.set_usb_passthrough(from_vm, new_usb_list)
                    except Exception as e:
                        # Log but continue - don't fail entire save
                        pass

            # Apply each change
            if "vcpus" in changes:
                self.libvirt.set_vcpus(vm.name, changes["vcpus"])
                applied.append(f"vCPUs={changes['vcpus']}")

            if "memory" in changes:
                self.libvirt.set_memory(vm.name, changes["memory"])
                applied.append(f"Memory={changes['memory']}MB")

            if "autostart" in changes:
                self.libvirt.set_autostart(vm.name, changes["autostart"])
                status = "on" if changes["autostart"] else "off"
                applied.append(f"Autostart={status}")

            if "graphics" in changes:
                self.libvirt.set_graphics(vm.name, changes["graphics"])
                applied.append(f"Graphics={changes['graphics']}")

            if "network" in changes:
                network = changes["network"]
                nic_model = changes.get("nic_model", "virtio")
                self.libvirt.set_network(vm.name, network, nic_model)
                applied.append(f"Network={network.split(':')[-1]}")

            if "audio" in changes:
                self.libvirt.set_audio(vm.name, changes["audio"])
                applied.append(f"Audio={changes['audio']}")

            if "gpu" in changes:
                self.libvirt.set_gpu_passthrough(vm.name, changes["gpu"])
                if changes["gpu"]:
                    applied.append(f"GPUs={len(changes['gpu'])}")
                else:
                    applied.append("GPUs=none")

            if "usb" in changes:
                self.libvirt.set_usb_passthrough(vm.name, changes["usb"])
                if changes["usb"]:
                    applied.append(f"USB={len(changes['usb'])}")
                else:
                    applied.append("USB=none")

            if "boot_order" in changes:
                self.libvirt.set_boot_order(vm.name, changes["boot_order"])
                applied.append(f"Boot={','.join(changes['boot_order'])}")

            if "iso" in changes:
                iso_path = changes["iso"]
                if iso_path is None:
                    self.libvirt.eject_iso(vm.name)
                    applied.append("ISO=ejected")
                else:
                    self.libvirt.attach_iso(vm.name, iso_path)
                    applied.append(f"ISO={iso_path.name}")

            self.main_screen.refresh_vms()

            if applied:
                msg = ", ".join(applied)
                if len(applied) > 1:
                    self.main_screen.set_status(
                        f"Updated: {msg} (restart required)", "success"
                    )
                else:
                    self.main_screen.set_status(
                        f"{msg} (restart required)", "success"
                    )
            else:
                self.main_screen.set_status("No changes made", "info")

        except Exception as e:
            self.main_screen.set_status(f"Failed: {e}", "error")

    def _open_console(self) -> None:
        """Open console for selected VM."""
        assert self.main_screen is not None

        vm = self.main_screen.vm_list.selected_item
        if not vm or not vm.is_running:
            return

        # Exit fullscreen to run external command
        print(self.term.exit_fullscreen, end="", flush=True)
        print(self.term.normal_cursor, end="", flush=True)

        try:
            if vm.graphics_type in ("spice", "vnc") and vm.graphics_port:
                # Use virt-viewer for graphical consoles
                print(f"Opening {vm.graphics_type.upper()} console for {vm.name}...")
                print(f"Connection: {vm.graphics_type}://localhost:{vm.graphics_port}")
                subprocess.run(["virt-viewer", "--connect", "qemu:///system", vm.name])
            elif vm.gpu_devices:
                # GPU passthrough - no virtual console
                print(f"VM {vm.name} uses GPU passthrough.")
                print("Connect via the passed-through GPU's display output.")
                input("Press Enter to continue...")
            else:
                # Headless - use serial console
                print(f"Connecting to serial console for {vm.name}...")
                print("Press Ctrl+] to exit.")
                subprocess.run(["virsh", "console", vm.name])
        except FileNotFoundError as e:
            if "virt-viewer" in str(e):
                print("virt-viewer not found. Install it with:")
                print("  apt install virt-viewer  # Debian/Ubuntu")
                print("  dnf install virt-viewer  # Fedora/RHEL")
            else:
                print(f"Command not found: {e}")
            input("Press Enter to continue...")
        finally:
            # Re-enter fullscreen mode for TUI
            print(self.term.enter_fullscreen, end="", flush=True)
            print(self.term.hidden_cursor, end="", flush=True)

    def _manage_snapshots(self) -> None:
        """Open checkpoint/snapshot management for selected VM."""
        assert self.main_screen is not None

        vm = self.main_screen.vm_list.selected_item
        if not vm:
            return

        # Get checkpoints and snapshots
        checkpoints = self.libvirt.list_checkpoints(vm.name)
        try:
            snapshots_data = self.libvirt.list_snapshots(vm.name)
            snapshots = [(s.name, s.created_at.strftime("%Y-%m-%d %H:%M:%S")) for s in snapshots_data]
        except Exception:
            # VM may not support snapshots or have issues
            snapshots = []

        # Show dialog
        dialog = CheckpointDialog(
            self.term,
            self.theme,
            vm,
            checkpoints,
            snapshots,
            on_create_checkpoint=lambda name, desc: self.libvirt.create_checkpoint(vm.name, name, desc),
            on_switch_checkpoint=lambda name: self.libvirt.switch_checkpoint(vm.name, name),
            on_delete_checkpoint=lambda name: self.libvirt.delete_checkpoint(vm.name, name),
            on_separate_checkpoint=lambda checkpoint, new_vm: self.libvirt.separate_checkpoint_to_vm(
                checkpoint, new_vm, vm.name
            ),
            on_create_snapshot=self._wrap_snapshot_create(vm.name),
            on_restore_snapshot=lambda name: self.libvirt.restore_snapshot(vm.name, name),
            on_delete_snapshot=self._wrap_snapshot_delete(vm.name),
            on_list_checkpoints=lambda: self.libvirt.list_checkpoints(vm.name),
            on_list_snapshots=self._wrap_list_snapshots(vm.name),
        )
        dialog.show()
        # Refresh VM list after dialog closes (to show any newly separated VMs)
        self.main_screen.refresh_vms()

    def _wrap_snapshot_create(self, vm_name: str):
        """Wrap create_snapshot to return bool."""
        def wrapper(name: str, desc: str) -> bool:
            try:
                self.libvirt.create_snapshot(vm_name, name, desc)
                return True
            except Exception:
                return False
        return wrapper

    def _wrap_snapshot_delete(self, vm_name: str):
        """Wrap delete_snapshot to return bool."""
        def wrapper(name: str) -> bool:
            try:
                self.libvirt.delete_snapshot(vm_name, name)
                return True
            except Exception:
                return False
        return wrapper

    def _wrap_list_snapshots(self, vm_name: str):
        """Wrap list_snapshots to suppress errors and return empty list on failure."""
        def wrapper() -> list[tuple[str, str]]:
            try:
                snapshots = self.libvirt.list_snapshots(vm_name)
                return [(s.name, s.created_at.strftime("%Y-%m-%d %H:%M:%S")) for s in snapshots]
            except Exception:
                return []
        return wrapper

    def _show_help(self) -> None:
        """Show help dialog."""
        help_text = """VM Manager - Keyboard Shortcuts

Navigation:
  j/↓     Move down
  k/↑     Move up
  PgUp/Dn Page up/down
  Enter   Select/confirm

VM Actions:
  n       Create new VM
  e       Edit selected VM
  d       Delete selected VM
  s       Start VM
  t       Stop VM
  c       Open console
  p       Checkpoints & Snapshots
  b       Change boot order

General:
  /       Search VMs
  r       Refresh list
  ?       Show this help
  q       Quit

Press any key to close."""

        dialog = MessageDialog(
            self.term,
            self.theme,
            "Help",
            help_text,
        )
        # Custom rendering for multiline help
        width = 50
        lines = help_text.split("\n")
        height = len(lines) + 4
        x, y = dialog.center_position(width, height)

        # Draw box
        chars = self.theme.box_chars()
        print(self.term.move_xy(x, y) + chars["tl"] + chars["h"] * (width - 2) + chars["tr"], end="")

        for i, line in enumerate(lines):
            print(
                self.term.move_xy(x, y + 1 + i)
                + chars["v"]
                + line[: width - 2].ljust(width - 2)
                + chars["v"],
                end="",
            )

        print(
            self.term.move_xy(x, y + height - 1)
            + chars["bl"] + chars["h"] * (width - 2) + chars["br"],
            end="",
            flush=True,
        )

        with self.term.cbreak():
            self.term.inkey()
