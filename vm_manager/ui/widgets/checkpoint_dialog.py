"""Checkpoint and snapshot management dialog."""

from collections.abc import Callable
from datetime import datetime

from blessed import Terminal

from vm_manager.models import VM
from vm_manager.ui.theme import Theme
from vm_manager.ui.widgets.dialog import ConfirmDialog, Dialog, InputDialog, ProgressDialog


class CheckpointDialog(Dialog):
    """Modal dialog for managing checkpoints and snapshots."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        vm: VM,
        checkpoints: list[tuple[str, str, bool]],  # (name, created, is_active)
        snapshots: list[tuple[str, str]],  # (name, created)
        on_create_checkpoint: Callable[[str, str], bool],  # (name, description) -> success
        on_switch_checkpoint: Callable[[str], bool],  # (name) -> success
        on_delete_checkpoint: Callable[[str], bool],  # (name) -> success
        on_separate_checkpoint: Callable[[str, str], bool],  # (checkpoint, new_vm_name) -> success
        on_create_snapshot: Callable[[str, str], bool],  # (name, description) -> success
        on_restore_snapshot: Callable[[str], bool],  # (name) -> success
        on_delete_snapshot: Callable[[str], bool],  # (name) -> success
        on_list_checkpoints: Callable[[], list[tuple[str, str, bool]]],  # () -> checkpoints
        on_list_snapshots: Callable[[], list[tuple[str, str]]],  # () -> snapshots
    ) -> None:
        super().__init__(term, theme, f"Checkpoints & Snapshots - {vm.name}")
        self.vm = vm
        self.checkpoints = checkpoints
        self.snapshots = snapshots
        self.on_create_checkpoint = on_create_checkpoint
        self.on_switch_checkpoint = on_switch_checkpoint
        self.on_delete_checkpoint = on_delete_checkpoint
        self.on_separate_checkpoint = on_separate_checkpoint
        self.on_create_snapshot = on_create_snapshot
        self.on_restore_snapshot = on_restore_snapshot
        self.on_delete_snapshot = on_delete_snapshot
        self.on_list_checkpoints = on_list_checkpoints
        self.on_list_snapshots = on_list_snapshots

        self.mode = "snapshot"  # "snapshot" or "checkpoint" - start with snapshots
        self.cursor_index = 0
        self.status_message = ""  # Status message to show at bottom
        self.status_type = "info"  # "info", "success", "error"

    def _set_status(self, message: str, status_type: str = "info") -> None:
        """Set status message."""
        self.status_message = message
        self.status_type = status_type

    def _refresh_lists(self) -> None:
        """Refresh checkpoint and snapshot lists and clear status."""
        self.checkpoints = self.on_list_checkpoints()
        self.snapshots = self.on_list_snapshots()
        # Clear status message on refresh
        self.status_message = ""
        # Reset cursor if out of bounds
        if self.mode == "checkpoint":
            self.cursor_index = min(self.cursor_index, max(0, len(self.checkpoints) - 1))
        else:
            self.cursor_index = min(self.cursor_index, max(0, len(self.snapshots) - 1))

    def show(self) -> bool:
        """Display dialog and return True if changes were made."""
        width = 80
        height = 24
        x, y = self.center_position(width, height)

        with self.term.cbreak(), self.term.hidden_cursor():
            while True:
                # Draw box
                lines = self._draw_box(x, y, width, height)
                for line in lines:
                    print(line, end="", flush=True)

                # Draw mode tabs (snapshots first, then checkpoints)
                snapshot_tab = "[ Quick Snapshots ]" if self.mode == "snapshot" else "  Quick Snapshots  "
                checkpoint_tab = "[ Checkpoints ]" if self.mode == "checkpoint" else "  Checkpoints  "

                tab_y = y + 2
                print(
                    self.term.move_xy(x + 4, tab_y)
                    + (self.theme.selected(snapshot_tab) if self.mode == "snapshot" else self.theme.dim(snapshot_tab)),
                    end="",
                    flush=True,
                )
                print(
                    self.term.move_xy(x + 26, tab_y)
                    + (self.theme.selected(checkpoint_tab) if self.mode == "checkpoint" else self.theme.dim(checkpoint_tab)),
                    end="",
                    flush=True,
                )

                # Draw separator
                separator_y = y + 3
                print(self.term.move_xy(x + 2, separator_y) + "─" * (width - 4), end="", flush=True)

                # Draw current mode content
                content_y = y + 4
                if self.mode == "snapshot":
                    self._draw_snapshots(x, content_y, width, height)
                else:
                    self._draw_checkpoints(x, content_y, width, height)

                # Draw status message above hints (if present)
                status_y = y + height - 3
                hint_y = y + height - 2

                if self.status_message:
                    # Show status message on separate line
                    if self.status_type == "success":
                        msg = self.theme.success(self.status_message)
                    elif self.status_type == "error":
                        msg = self.theme.error(self.status_message)
                    else:
                        msg = self.theme.info(self.status_message)
                    print(
                        self.term.move_xy(x + 2, status_y)
                        + msg[: width - 4].ljust(width - 4),
                        end="",
                        flush=True,
                    )
                else:
                    # Clear status line if no message
                    print(
                        self.term.move_xy(x + 2, status_y)
                        + " " * (width - 4),
                        end="",
                        flush=True,
                    )

                # Always show hints
                if self.mode == "snapshot":
                    hints = "Tab: Checkpoints  N: New  Enter: Restore  D: Delete  Esc: Close"
                else:
                    hints = "Tab: Snapshots  N: New  Enter: Switch  D: Delete  S: Separate  Esc: Close"

                print(
                    self.term.move_xy(x + 2, hint_y)
                    + self.theme.dim(hints[: width - 4]),
                    end="",
                    flush=True,
                )

                # Handle input with short timeout to allow status message updates
                key = self.term.inkey(timeout=0.1)

                if not key:
                    continue

                if key.name == "KEY_ESCAPE":
                    return False
                elif key.name == "KEY_TAB":
                    # Switch mode (toggle between snapshot and checkpoint)
                    self.mode = "checkpoint" if self.mode == "snapshot" else "snapshot"
                    self.cursor_index = 0
                    self.status_message = ""  # Clear status on page change
                elif key.name == "KEY_UP":
                    items = self.snapshots if self.mode == "snapshot" else self.checkpoints
                    self.cursor_index = max(0, self.cursor_index - 1)
                elif key.name == "KEY_DOWN":
                    items = self.snapshots if self.mode == "snapshot" else self.checkpoints
                    self.cursor_index = min(len(items) - 1, self.cursor_index + 1) if items else 0
                elif key.lower() == "n":
                    # Create new
                    if self.mode == "snapshot":
                        self._create_snapshot()
                    else:
                        self._create_checkpoint()
                elif key.name == "KEY_ENTER":
                    # Restore/Switch
                    if self.mode == "snapshot":
                        self._restore_snapshot()
                    else:
                        self._switch_checkpoint()
                elif key.lower() == "d":
                    # Delete
                    if self.mode == "snapshot":
                        self._delete_snapshot()
                    else:
                        self._delete_checkpoint()
                elif key.lower() == "s" and self.mode == "checkpoint":
                    # Separate checkpoint to new VM
                    if self._separate_checkpoint():
                        # Close dialog after successful separation
                        return True

    def _draw_checkpoints(self, x: int, y: int, width: int, height: int) -> None:
        """Draw checkpoint list."""
        visible_count = height - 10
        content_width = width - 4

        if not self.checkpoints:
            empty_msg = "No checkpoints yet. Press 'N' to create one."
            print(
                self.term.move_xy(x + (width - len(empty_msg)) // 2, y + 5)
                + self.theme.dim(empty_msg),
                end="",
                flush=True,
            )
            # Clear remaining lines
            for i in range(visible_count):
                print(self.term.move_xy(x + 2, y + i) + " " * content_width, end="", flush=True)
            return

        # Header
        header = "  Name".ljust(35) + "Created".ljust(25) + "Status"
        print(self.term.move_xy(x + 2, y) + self.theme.dim(header), end="", flush=True)

        # List checkpoints
        for i, (name, created, is_active) in enumerate(self.checkpoints[:visible_count]):
            # Build line components
            cursor = ">" if i == self.cursor_index else " "
            name_part = name[:33].ljust(33)
            created_part = created[:23].ljust(23)
            status_part = "[ACTIVE]" if is_active else ""

            # Assemble line without any styling
            line_text = f"{cursor} {name_part} {created_part} {status_part}"

            # Truncate to fit width (before applying any ANSI styling)
            line_text = line_text[:content_width].ljust(content_width)

            # Apply styling based on state
            if i == self.cursor_index:
                styled_line = self.theme.selected(line_text)
            elif is_active:
                styled_line = self.theme.success(line_text)
            else:
                styled_line = line_text

            print(self.term.move_xy(x + 2, y + 1 + i) + styled_line, end="", flush=True)

        # Clear any remaining lines below the list
        checkpoint_count = len(self.checkpoints[:visible_count])
        for i in range(checkpoint_count + 1, visible_count):
            print(self.term.move_xy(x + 2, y + 1 + i) + " " * content_width, end="", flush=True)

    def _draw_snapshots(self, x: int, y: int, width: int, height: int) -> None:
        """Draw snapshot list."""
        visible_count = height - 10
        content_width = width - 4

        if not self.snapshots:
            empty_msg = "No snapshots yet. Press 'N' to create one."
            print(
                self.term.move_xy(x + (width - len(empty_msg)) // 2, y + 5)
                + self.theme.dim(empty_msg),
                end="",
                flush=True,
            )
            # Clear remaining lines
            for i in range(visible_count):
                print(self.term.move_xy(x + 2, y + i) + " " * content_width, end="", flush=True)
            return

        # Header
        header = "  Name".ljust(40) + "Created"
        print(self.term.move_xy(x + 2, y) + self.theme.dim(header), end="", flush=True)

        # List snapshots
        for i, (name, created) in enumerate(self.snapshots[:visible_count]):
            # Build line components
            cursor = ">" if i == self.cursor_index else " "
            name_part = name[:38].ljust(38)

            # Assemble line without any styling
            line_text = f"{cursor} {name_part} {created}"

            # Truncate to fit width (before applying any ANSI styling)
            line_text = line_text[:content_width].ljust(content_width)

            # Apply styling if cursor is on this line
            if i == self.cursor_index:
                styled_line = self.theme.selected(line_text)
            else:
                styled_line = line_text

            print(self.term.move_xy(x + 2, y + 1 + i) + styled_line, end="", flush=True)

        # Clear any remaining lines below the list
        snapshot_count = len(self.snapshots[:visible_count])
        for i in range(snapshot_count + 1, visible_count):
            print(self.term.move_xy(x + 2, y + 1 + i) + " " * content_width, end="", flush=True)

    def _create_checkpoint(self) -> None:
        """Create a new checkpoint."""
        import threading
        import time

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"{self.vm.name}-checkpoint-{timestamp}"

        dialog = InputDialog(
            self.term,
            self.theme,
            "Create Checkpoint",
            f"Checkpoint name:",
            default=default_name,
            validator=lambda x: "Name required" if not x else None,
        )
        name = dialog.show()
        if not name:
            return

        desc_dialog = InputDialog(
            self.term, self.theme, "Create Checkpoint", "Description (optional):"
        )
        description = desc_dialog.show()
        if description is None:
            return

        # Show progress dialog while creating checkpoint
        progress = ProgressDialog(
            self.term, self.theme, "Creating Checkpoint", f"Copying disk for '{name}'..."
        )

        # Run checkpoint creation in background thread
        result = [False]  # Use list to allow modification from thread
        error = [None]

        def create_in_background():
            try:
                result[0] = self.on_create_checkpoint(name, description)
            except Exception as e:
                error[0] = str(e)

        thread = threading.Thread(target=create_in_background, daemon=True)
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
            self._set_status(f"Failed to create checkpoint: {error[0]}", "error")
        elif result[0]:
            # Refresh checkpoint list to show new checkpoint
            self._refresh_lists()
            self._set_status(f"Checkpoint '{name}' created", "success")

    def _switch_checkpoint(self) -> None:
        """Switch to selected checkpoint."""
        if not self.checkpoints or self.cursor_index >= len(self.checkpoints):
            return

        name, _, is_active = self.checkpoints[self.cursor_index]
        if is_active:
            self._set_status("This checkpoint is already active", "info")
            return

        confirm = ConfirmDialog(
            self.term,
            self.theme,
            "Switch Checkpoint",
            f"Switch to checkpoint '{name}'?\nRestart VM for changes to take effect.",
        )
        if confirm.show():
            if self.on_switch_checkpoint(name):
                self._refresh_lists()
                # Move cursor to the now-active checkpoint
                for i, (cp_name, _, cp_is_active) in enumerate(self.checkpoints):
                    if cp_name == name and cp_is_active:
                        self.cursor_index = i
                        break
                self._set_status(f"Switched to checkpoint '{name}'", "success")
            else:
                self._set_status(f"Failed to switch checkpoint", "error")

    def _delete_checkpoint(self) -> None:
        """Delete selected checkpoint."""
        if not self.checkpoints or self.cursor_index >= len(self.checkpoints):
            return

        name, _, is_active = self.checkpoints[self.cursor_index]
        if is_active:
            self._set_status("Cannot delete active checkpoint", "error")
            return

        confirm = ConfirmDialog(
            self.term, self.theme, "Delete Checkpoint", f"Delete checkpoint '{name}'?\nThis cannot be undone."
        )
        if not confirm.show():
            return

        import threading
        import time

        # Show progress dialog while deleting
        progress = ProgressDialog(
            self.term, self.theme, "Deleting Checkpoint", f"Removing checkpoint '{name}'..."
        )

        result = [False]
        error = [None]

        def delete_in_background():
            try:
                result[0] = self.on_delete_checkpoint(name)
            except Exception as e:
                error[0] = str(e)

        thread = threading.Thread(target=delete_in_background, daemon=True)
        thread.start()

        # Show progress dialog while thread runs
        with self.term.hidden_cursor():
            while thread.is_alive():
                progress.show_frame()
                # Drain input buffer
                while True:
                    key = self.term.inkey(timeout=0)
                    if not key:
                        break
                time.sleep(0.1)

        thread.join()

        if error[0]:
            self._set_status(f"Failed to delete checkpoint: {error[0]}", "error")
        elif result[0]:
            self._refresh_lists()
            self._set_status(f"Checkpoint '{name}' deleted", "success")
        else:
            self._set_status(f"Failed to delete checkpoint", "error")

    def _separate_checkpoint(self) -> bool:
        """Separate checkpoint into new VM.

        Returns True if separation was successful, False otherwise.
        """
        if not self.checkpoints or self.cursor_index >= len(self.checkpoints):
            return False

        checkpoint_name, _, _ = self.checkpoints[self.cursor_index]

        dialog = InputDialog(
            self.term,
            self.theme,
            "Separate to New VM",
            "New VM name:",
            default=f"{self.vm.name}-from-{checkpoint_name}",
            validator=lambda x: "Name required" if not x else None,
        )
        new_vm_name = dialog.show()
        if not new_vm_name:
            return False

        confirm = ConfirmDialog(
            self.term,
            self.theme,
            "Separate Checkpoint",
            f"Create new VM '{new_vm_name}' from checkpoint?\nCreates independent VM.",
        )
        if not confirm.show():
            return False

        # Perform the separation
        if self.on_separate_checkpoint(checkpoint_name, new_vm_name):
            self._refresh_lists()
            self._set_status(f"Created VM '{new_vm_name}' from checkpoint", "success")
            return True
        else:
            self._set_status(f"Failed to separate checkpoint", "error")
            return False

    def _create_snapshot(self) -> None:
        """Create a quick snapshot."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"snap-{timestamp}"

        dialog = InputDialog(
            self.term,
            self.theme,
            "Create Snapshot",
            "Snapshot name:",
            default=default_name,
            validator=lambda x: "Name required" if not x else None,
        )
        name = dialog.show()
        if not name:
            return

        desc_dialog = InputDialog(
            self.term, self.theme, "Create Snapshot", "Description (optional):"
        )
        description = desc_dialog.show()
        if description is None:
            return

        if self.on_create_snapshot(name, description):
            self._refresh_lists()
            self._set_status(f"Snapshot '{name}' created", "success")
        else:
            self._set_status(f"Failed to create snapshot", "error")

    def _restore_snapshot(self) -> None:
        """Restore selected snapshot."""
        if not self.snapshots or self.cursor_index >= len(self.snapshots):
            return

        name, _ = self.snapshots[self.cursor_index]

        confirm = ConfirmDialog(
            self.term,
            self.theme,
            "Restore Snapshot",
            f"Restore snapshot '{name}'?\nCurrent state will be lost.",
        )
        if confirm.show():
            if self.on_restore_snapshot(name):
                self._refresh_lists()
                self._set_status(f"Restored snapshot '{name}'", "success")
            else:
                self._set_status(f"Failed to restore snapshot", "error")

    def _delete_snapshot(self) -> None:
        """Delete selected snapshot."""
        if not self.snapshots or self.cursor_index >= len(self.snapshots):
            return

        name, _ = self.snapshots[self.cursor_index]

        confirm = ConfirmDialog(
            self.term, self.theme, "Delete Snapshot", f"Delete snapshot '{name}'?\nThis cannot be undone."
        )
        if confirm.show():
            if self.on_delete_snapshot(name):
                self._refresh_lists()
                self._set_status(f"Snapshot '{name}' deleted", "success")
            else:
                self._set_status(f"Failed to delete snapshot", "error")
