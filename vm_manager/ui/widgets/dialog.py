"""Dialog widgets for user interaction."""

from collections.abc import Callable

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.ui.theme import Theme


class Dialog:
    """Base dialog class."""

    def __init__(self, term: Terminal, theme: Theme, title: str) -> None:
        self.term = term
        self.theme = theme
        self.title = title

    def _draw_box(self, x: int, y: int, width: int, height: int) -> list[str]:
        """Draw a box at the given position."""
        chars = self.theme.box_chars()
        lines: list[str] = []

        # Top border
        top = chars["tl"] + chars["h"] * (width - 2) + chars["tr"]
        lines.append(self.term.move_xy(x, y) + top)

        # Title
        title_text = f" {self.title} "
        title_pos = (width - len(title_text)) // 2
        title_line = (
            chars["v"]
            + " " * (title_pos - 1)
            + self.theme.bold(title_text)
            + " " * (width - title_pos - len(title_text) - 1)
            + chars["v"]
        )
        lines.append(self.term.move_xy(x, y + 1) + title_line)

        # Separator
        sep = chars["vr"] + chars["h"] * (width - 2) + chars["vl"]
        lines.append(self.term.move_xy(x, y + 2) + sep)

        # Middle empty lines
        for i in range(3, height - 1):
            middle = chars["v"] + " " * (width - 2) + chars["v"]
            lines.append(self.term.move_xy(x, y + i) + middle)

        # Bottom border
        bottom = chars["bl"] + chars["h"] * (width - 2) + chars["br"]
        lines.append(self.term.move_xy(x, y + height - 1) + bottom)

        return lines

    def center_position(self, width: int, height: int) -> tuple[int, int]:
        """Calculate centered position for dialog."""
        x = (self.term.width - width) // 2
        y = (self.term.height - height) // 2
        return x, y


class MessageDialog(Dialog):
    """Simple message dialog."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        message: str,
        message_type: str = "info",
    ) -> None:
        super().__init__(term, theme, title)
        self.message = message
        self.message_type = message_type

    def show(self) -> None:
        """Display the message dialog."""
        width = max(40, len(self.message) + 6, len(self.title) + 6)
        height = 7
        x, y = self.center_position(width, height)

        # Draw box
        lines = self._draw_box(x, y, width, height)
        for line in lines:
            print(line, end="", flush=True)

        # Draw message
        msg_x = x + (width - len(self.message)) // 2
        if self.message_type == "error":
            styled_msg = self.theme.error(self.message)
        elif self.message_type == "success":
            styled_msg = self.theme.success(self.message)
        elif self.message_type == "warning":
            styled_msg = self.theme.warning(self.message)
        else:
            styled_msg = self.message

        print(self.term.move_xy(msg_x, y + 4) + styled_msg, end="", flush=True)

        # Draw hint
        hint = "Press any key to continue"
        hint_x = x + (width - len(hint)) // 2
        print(
            self.term.move_xy(hint_x, y + 5) + self.theme.dim(hint), end="", flush=True
        )

        # Wait for key
        with self.term.cbreak():
            self.term.inkey()


class ConfirmDialog(Dialog):
    """Confirmation dialog with Yes/No."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        message: str,
    ) -> None:
        super().__init__(term, theme, title)
        self.message = message

    def show(self) -> bool:
        """Display dialog and return True if confirmed."""
        # Split message into lines
        message_lines = self.message.split('\n')
        max_line_len = max(len(line) for line in message_lines)
        width = max(40, max_line_len + 6, len(self.title) + 6)
        height = 7 + len(message_lines) - 1  # Extra height for multi-line messages
        x, y = self.center_position(width, height)

        # Draw box
        lines = self._draw_box(x, y, width, height)
        for line in lines:
            print(line, end="", flush=True)

        # Draw message (multi-line support)
        for i, msg_line in enumerate(message_lines):
            msg_x = x + (width - len(msg_line)) // 2
            print(self.term.move_xy(msg_x, y + 4 + i) + msg_line, end="", flush=True)

        # Draw options (adjust position based on number of message lines)
        options = "[y]es  [n]o"
        opt_x = x + (width - len(options)) // 2
        opt_y = y + 4 + len(message_lines) + 1
        print(
            self.term.move_xy(opt_x, opt_y) + self.theme.info(options),
            end="",
            flush=True,
        )

        # Wait for input
        with self.term.cbreak():
            while True:
                key = self.term.inkey()
                if key.lower() == "y":
                    return True
                elif key.lower() == "n" or key.name == "KEY_ESCAPE":
                    return False


class InputDialog(Dialog):
    """Text input dialog."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        prompt: str,
        default: str = "",
        validator: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__(term, theme, title)
        self.prompt = prompt
        self.default = default
        self.validator = validator
        self.value = default
        self.cursor_pos = len(default)
        self.error_message = ""

    def show(self) -> str | None:
        """Display dialog and return entered value or None if cancelled."""
        width = max(50, len(self.prompt) + 10, len(self.title) + 6)
        height = 8
        x, y = self.center_position(width, height)

        with self.term.cbreak():
            while True:
                # Draw box
                lines = self._draw_box(x, y, width, height)
                for line in lines:
                    print(line, end="", flush=True)

                # Draw prompt
                print(
                    self.term.move_xy(x + 2, y + 3) + self.prompt, end="", flush=True
                )

                # Draw input field
                input_width = width - 4
                display_value = self.value[:input_width].ljust(input_width)
                print(
                    self.term.move_xy(x + 2, y + 4)
                    + self.term.reverse(display_value),
                    end="",
                    flush=True,
                )

                # Draw error or hint
                if self.error_message:
                    print(
                        self.term.move_xy(x + 2, y + 5)
                        + self.theme.error(self.error_message[: width - 4]),
                        end="",
                        flush=True,
                    )
                else:
                    hint = "Enter to confirm, Esc to cancel"
                    print(
                        self.term.move_xy(x + 2, y + 5) + self.theme.dim(hint),
                        end="",
                        flush=True,
                    )

                # Position cursor
                cursor_x = x + 2 + min(self.cursor_pos, input_width - 1)
                print(self.term.move_xy(cursor_x, y + 4), end="", flush=True)

                # Handle input
                key: Keystroke = self.term.inkey()

                if key.name == "KEY_ESCAPE":
                    return None
                elif key.name == "KEY_ENTER":
                    if self.validator:
                        error = self.validator(self.value)
                        if error:
                            self.error_message = error
                            continue
                    return self.value
                elif key.name == "KEY_BACKSPACE":
                    if self.cursor_pos > 0:
                        self.value = (
                            self.value[: self.cursor_pos - 1]
                            + self.value[self.cursor_pos :]
                        )
                        self.cursor_pos -= 1
                        self.error_message = ""
                elif key.name == "KEY_DELETE":
                    if self.cursor_pos < len(self.value):
                        self.value = (
                            self.value[: self.cursor_pos]
                            + self.value[self.cursor_pos + 1 :]
                        )
                        self.error_message = ""
                elif key.name == "KEY_LEFT":
                    self.cursor_pos = max(0, self.cursor_pos - 1)
                elif key.name == "KEY_RIGHT":
                    self.cursor_pos = min(len(self.value), self.cursor_pos + 1)
                elif key.name == "KEY_HOME":
                    self.cursor_pos = 0
                elif key.name == "KEY_END":
                    self.cursor_pos = len(self.value)
                elif key and len(key) == 1 and key.isprintable():
                    self.value = (
                        self.value[: self.cursor_pos]
                        + key
                        + self.value[self.cursor_pos :]
                    )
                    self.cursor_pos += 1
                    self.error_message = ""


class DeleteDialog(Dialog):
    """Deletion confirmation dialog with type-back security."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        vm_name: str,
        has_storage: bool = True,
    ) -> None:
        super().__init__(term, theme, "Delete VM")
        self.vm_name = vm_name
        self.has_storage = has_storage
        self.typed_name = ""
        self.delete_config = False
        self.delete_storage = False
        self.selected_option = 0  # 0=config, 1=storage, 2=input, 3=confirm

    def show(self) -> tuple[bool, bool] | None:
        """Display dialog and return (delete_config, delete_storage) or None if cancelled."""
        width = max(55, len(self.vm_name) + 30)
        height = 14
        x, y = self.center_position(width, height)

        with self.term.cbreak():
            while True:
                # Draw box
                lines = self._draw_box(x, y, width, height)
                for line in lines:
                    print(line, end="", flush=True)

                # Warning message
                warning = f"This will delete '{self.vm_name}'"
                print(
                    self.term.move_xy(x + 2, y + 3)
                    + self.theme.warning(warning),
                    end="",
                    flush=True,
                )

                # Options
                cfg_check = "[X]" if self.delete_config else "[ ]"
                cfg_style = self.theme.selected if self.selected_option == 0 else lambda s: s
                cfg_text = f"{cfg_check} Delete VM configuration"
                print(
                    self.term.move_xy(x + 2, y + 5)
                    + cfg_style(cfg_text.ljust(width - 4)),
                    end="",
                    flush=True,
                )

                stg_check = "[X]" if self.delete_storage else "[ ]"
                stg_style = self.theme.selected if self.selected_option == 1 else lambda s: s
                if self.has_storage:
                    stg_text = f"{stg_check} Delete storage (disk files)"
                else:
                    stg_text = f"{stg_check} Delete storage (no files found)"
                print(
                    self.term.move_xy(x + 2, y + 6)
                    + stg_style(stg_text.ljust(width - 4)),
                    end="",
                    flush=True,
                )

                # Type-back input
                prompt = f"Type '{self.vm_name}' to confirm:"
                print(
                    self.term.move_xy(x + 2, y + 8) + prompt,
                    end="",
                    flush=True,
                )

                input_width = width - 4
                input_style = self.term.reverse if self.selected_option == 2 else lambda s: s
                display_value = self.typed_name[:input_width].ljust(input_width)

                # Color based on match
                if self.typed_name == self.vm_name:
                    display_value = self.theme.success(display_value)
                elif self.typed_name and not self.vm_name.startswith(self.typed_name):
                    display_value = self.theme.error(display_value)
                else:
                    display_value = input_style(display_value)

                print(
                    self.term.move_xy(x + 2, y + 9) + display_value,
                    end="",
                    flush=True,
                )

                # Buttons
                can_confirm = self.typed_name == self.vm_name and (self.delete_config or self.delete_storage)
                confirm_style = self.theme.selected if self.selected_option == 3 else lambda s: s
                if can_confirm:
                    confirm_btn = confirm_style(" [Delete] ")
                else:
                    confirm_btn = self.theme.dim(" [Delete] ")

                cancel_btn = " [Cancel] "

                buttons = f"{confirm_btn}  {cancel_btn}"
                print(
                    self.term.move_xy(x + 2, y + 11) + buttons,
                    end="",
                    flush=True,
                )

                # Hint
                hint = "Tab: navigate  Space: toggle  Enter: confirm"
                print(
                    self.term.move_xy(x + 2, y + 12)
                    + self.theme.dim(hint[:width - 4]),
                    end="",
                    flush=True,
                )

                print("", end="", flush=True)

                # Handle input
                key: Keystroke = self.term.inkey()

                if key.name == "KEY_ESCAPE":
                    return None
                elif key.name == "KEY_TAB" or key.name == "KEY_DOWN":
                    self.selected_option = (self.selected_option + 1) % 4
                elif key.name == "KEY_UP":
                    self.selected_option = (self.selected_option - 1) % 4
                elif key == " ":
                    if self.selected_option == 0:
                        self.delete_config = not self.delete_config
                    elif self.selected_option == 1 and self.has_storage:
                        self.delete_storage = not self.delete_storage
                elif key.name == "KEY_ENTER":
                    if self.selected_option == 3 and can_confirm:
                        return (self.delete_config, self.delete_storage)
                    elif self.selected_option < 2:
                        # Toggle on enter too
                        if self.selected_option == 0:
                            self.delete_config = not self.delete_config
                        elif self.selected_option == 1 and self.has_storage:
                            self.delete_storage = not self.delete_storage
                elif self.selected_option == 2:
                    # Text input mode
                    if key.name == "KEY_BACKSPACE":
                        self.typed_name = self.typed_name[:-1]
                    elif key and len(key) == 1 and key.isprintable():
                        self.typed_name += key
                elif key and len(key) == 1 and key.isprintable():
                    # If typing anywhere, focus input and add char
                    self.selected_option = 2
                    self.typed_name += key


class SelectDialog(Dialog):
    """Selection dialog with list of options."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        options: list[tuple[str, str]],  # (value, display)
        selected_index: int = 0,
    ) -> None:
        super().__init__(term, theme, title)
        self.options = options
        self.selected_index = selected_index

    def show(self) -> str | None:
        """Display dialog and return selected value or None if cancelled."""
        max_label = max(len(opt[1]) for opt in self.options) if self.options else 10
        width = max(40, max_label + 6, len(self.title) + 6)
        height = min(len(self.options) + 5, 20)
        x, y = self.center_position(width, height)

        visible_count = height - 5
        scroll_offset = 0

        with self.term.cbreak():
            while True:
                # Adjust scroll
                if self.selected_index < scroll_offset:
                    scroll_offset = self.selected_index
                elif self.selected_index >= scroll_offset + visible_count:
                    scroll_offset = self.selected_index - visible_count + 1

                # Draw box
                lines = self._draw_box(x, y, width, height)
                for line in lines:
                    print(line, end="", flush=True)

                # Draw options
                visible_options = self.options[
                    scroll_offset : scroll_offset + visible_count
                ]
                for i, (value, label) in enumerate(visible_options):
                    actual_index = scroll_offset + i
                    prefix = ">" if actual_index == self.selected_index else " "
                    text = f"{prefix} {label}"[: width - 4].ljust(width - 4)

                    if actual_index == self.selected_index:
                        text = self.theme.selected(text)

                    print(
                        self.term.move_xy(x + 2, y + 3 + i) + text, end="", flush=True
                    )

                # Draw hint
                hint = "↑↓ select, Enter confirm, Esc cancel"
                hint_y = y + height - 2
                print(
                    self.term.move_xy(x + 2, hint_y)
                    + self.theme.dim(hint[: width - 4]),
                    end="",
                    flush=True,
                )

                # Handle input
                key = self.term.inkey()

                if key.name == "KEY_ESCAPE":
                    return None
                elif key.name == "KEY_ENTER":
                    if self.options:
                        return self.options[self.selected_index][0]
                    return None
                elif key.name == "KEY_UP" or key == "k":
                    self.selected_index = max(0, self.selected_index - 1)
                elif key.name == "KEY_DOWN" or key == "j":
                    self.selected_index = min(
                        len(self.options) - 1, self.selected_index + 1
                    )


class ToggleListDialog(Dialog):
    """Toggle list dialog for multi-select with checkboxes."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        options: list[tuple[str, str, bool]],  # (value, display, disabled)
        selected: list[str] | None = None,  # Initially selected values
        disabled_hint: str = "This item cannot be selected",
        iommu_groups: dict[str, list[str]] | None = None,  # device -> group devices
        device_owners: dict[str, str] | None = None,  # device -> VM name that owns it
        on_steal_device: Callable[[str, str], bool] | None = None,  # Callback to steal device from another VM
    ) -> None:
        super().__init__(term, theme, title)
        self.options = options
        self.selected_values: set[str] = set(selected) if selected else set()
        self.cursor_index = 0
        self.disabled_hint = disabled_hint
        self.show_hint = False
        self.hint_message = ""
        self.iommu_groups = iommu_groups or {}
        self.device_owners = device_owners or {}
        self.on_steal_device = on_steal_device

    def show(self) -> list[str] | None:
        """Display dialog and return list of selected values, or None if cancelled."""
        max_label = max(len(opt[1]) for opt in self.options) if self.options else 10
        width = max(50, max_label + 10, len(self.title) + 6)
        height = min(len(self.options) + 6, 23)  # Extra lines for hint
        x, y = self.center_position(width, height)

        visible_count = height - 6  # Account for title, borders, and hint
        scroll_offset = 0

        with self.term.cbreak():
            while True:
                # Adjust scroll
                if self.cursor_index < scroll_offset:
                    scroll_offset = self.cursor_index
                elif self.cursor_index >= scroll_offset + visible_count:
                    scroll_offset = self.cursor_index - visible_count + 1

                # Draw box
                lines = self._draw_box(x, y, width, height)
                for line in lines:
                    print(line, end="", flush=True)

                # Draw options with checkboxes
                visible_options = self.options[
                    scroll_offset : scroll_offset + visible_count
                ]
                for i, (value, label, disabled) in enumerate(visible_options):
                    actual_index = scroll_offset + i
                    is_selected = value in self.selected_values
                    is_cursor = actual_index == self.cursor_index

                    # Show cursor marker and checkbox
                    cursor_marker = ">" if is_cursor else " "
                    checkbox = "X" if is_selected else " "
                    text = f"{cursor_marker}[{checkbox}] {label}"[: width - 4].ljust(width - 4)

                    if disabled:
                        text = self.theme.dim(text)
                    elif is_cursor:
                        text = self.theme.selected(text)

                    print(
                        self.term.move_xy(x + 2, y + 3 + i) + text, end="", flush=True
                    )

                # Fill remaining visible lines
                for i in range(len(visible_options), visible_count):
                    empty = " " * (width - 4)
                    print(self.term.move_xy(x + 2, y + 3 + i) + empty, end="", flush=True)

                # Draw hint message or default hints
                hint_y = y + height - 2
                if self.show_hint:
                    print(
                        self.term.move_xy(x + 2, hint_y)
                        + self.theme.warning(self.hint_message[: width - 4].ljust(width - 4)),
                        end="",
                        flush=True,
                    )
                else:
                    print(
                        self.term.move_xy(x + 2, hint_y)
                        + " " * (width - 4),
                        end="",
                        flush=True,
                    )

                hint = "↑↓: navigate  Space: toggle  Enter: confirm  Esc: cancel"
                print(
                    self.term.move_xy(x + 2, y + height - 1)
                    + self.theme.dim(hint[: width - 4]),
                    end="",
                    flush=True,
                )

                # Handle input
                key = self.term.inkey()
                self.show_hint = False  # Clear hint on any key

                if key.name == "KEY_ESCAPE":
                    return None
                elif key.name == "KEY_ENTER":
                    return list(self.selected_values)
                elif key.name == "KEY_UP":
                    self.cursor_index = max(0, self.cursor_index - 1)
                elif key.name == "KEY_DOWN":
                    self.cursor_index = min(len(self.options) - 1, self.cursor_index + 1)
                elif key == " ":
                    # Space toggles checkbox (and entire IOMMU group)
                    if self.options:
                        value, label, disabled = self.options[self.cursor_index]

                        # Get all devices in this IOMMU group
                        group_devices = self.iommu_groups.get(value, [value])

                        # Check if currently selected
                        is_currently_selected = value in self.selected_values

                        if disabled and not is_currently_selected:
                            # Disabled and NOT selected - check if owned by another VM
                            if value in self.device_owners and self.on_steal_device:
                                # Device is owned by another VM - ask to steal it
                                owner_vm = self.device_owners[value]
                                from vm_manager.ui.widgets.dialog import ConfirmDialog

                                confirm = ConfirmDialog(
                                    self.term,
                                    self.theme,
                                    "Device In Use",
                                    f"Remove from '{owner_vm}' and assign here?"
                                )

                                if confirm.show():
                                    # User confirmed - steal the device
                                    if self.on_steal_device(value, owner_vm):
                                        # Successfully stolen - add to current selection
                                        for dev in group_devices:
                                            self.selected_values.add(dev)
                                    else:
                                        # Failed to steal - show hint
                                        self.show_hint = True
                                        self.hint_message = f"Failed to remove device from {owner_vm}"
                            else:
                                # Not owned by another VM (e.g., wrong driver) - just show hint
                                self.show_hint = True
                                self.hint_message = self.disabled_hint
                        elif disabled and is_currently_selected:
                            # Disabled but currently selected - allow deselection to fix conflicts
                            for dev in group_devices:
                                self.selected_values.discard(dev)
                        else:
                            # Not disabled - normal toggle behavior
                            if is_currently_selected:
                                # Remove entire group
                                for dev in group_devices:
                                    self.selected_values.discard(dev)
                            else:
                                # Add entire group
                                for dev in group_devices:
                                    self.selected_values.add(dev)


class OrderableListDialog(Dialog):
    """Dialog with reorderable list using Shift+Up/Down."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        options: list[tuple[str, str]],  # (value, label)
        selected: list[str] | None = None,
    ) -> None:
        super().__init__(term, theme, title)
        # Store options as list to maintain order
        self.options = list(options)
        self.selected_values = set(selected) if selected else set()
        self.cursor_index = 0

    def show(self) -> list[str] | None:
        """Display dialog and return ordered list of selected values, or None if cancelled."""
        width = 60
        height = min(20, len(self.options) + 8)  # +8 for borders and hints
        x, y = self.center_position(width, height)

        visible_count = height - 7  # Reserve 7 lines for borders + title + 2 hint lines

        with self.term.cbreak(), self.term.hidden_cursor():
            while True:
                # Auto-scroll to keep cursor visible
                scroll_offset = 0
                if self.cursor_index >= visible_count:
                    scroll_offset = self.cursor_index - visible_count + 1

                # Draw box
                lines = self._draw_box(x, y, width, height)
                for line in lines:
                    print(line, end="", flush=True)

                # Draw options with checkboxes
                visible_options = self.options[
                    scroll_offset : scroll_offset + visible_count
                ]
                for i, (value, label) in enumerate(visible_options):
                    actual_index = scroll_offset + i
                    is_selected = value in self.selected_values
                    is_cursor = actual_index == self.cursor_index

                    # Show cursor marker and checkbox
                    cursor_marker = ">" if is_cursor else " "
                    checkbox = "X" if is_selected else " "
                    text = f"{cursor_marker}[{checkbox}] {label}"[: width - 4].ljust(width - 4)

                    if is_cursor:
                        text = self.theme.selected(text)

                    print(
                        self.term.move_xy(x + 2, y + 3 + i) + text, end="", flush=True
                    )

                # Fill remaining visible lines
                for i in range(len(visible_options), visible_count):
                    empty = " " * (width - 4)
                    print(self.term.move_xy(x + 2, y + 3 + i) + empty, end="", flush=True)

                # Draw hints on two lines
                hint1 = "↑↓: navigate  Space: toggle  Enter: confirm"
                hint2 = "Shift+↑↓: reorder  Esc: cancel"
                hint1_y = y + height - 2
                hint2_y = y + height - 1
                print(
                    self.term.move_xy(x + 2, hint1_y)
                    + self.theme.dim(hint1[: width - 4].ljust(width - 4)),
                    end="",
                    flush=True,
                )
                print(
                    self.term.move_xy(x + 2, hint2_y)
                    + self.theme.dim(hint2[: width - 4].ljust(width - 4)),
                    end="",
                    flush=True,
                )

                # Handle input
                key = self.term.inkey()

                # Check for Shift+Arrow keys (various terminal escape sequences)
                is_shift_up = (
                    key.name == "KEY_SR" or
                    str(key) == "\x1b[1;2A" or
                    (key.is_sequence and "1;2A" in str(key))
                )
                is_shift_down = (
                    key.name == "KEY_SF" or
                    str(key) == "\x1b[1;2B" or
                    (key.is_sequence and "1;2B" in str(key))
                )

                if key.name == "KEY_ESCAPE":
                    return None
                elif is_shift_up:
                    # Shift+Up - Move item up in order
                    if self.cursor_index > 0:
                        self.options[self.cursor_index], self.options[self.cursor_index - 1] = (
                            self.options[self.cursor_index - 1],
                            self.options[self.cursor_index],
                        )
                        self.cursor_index -= 1
                elif is_shift_down:
                    # Shift+Down - Move item down in order
                    if self.cursor_index < len(self.options) - 1:
                        self.options[self.cursor_index], self.options[self.cursor_index + 1] = (
                            self.options[self.cursor_index + 1],
                            self.options[self.cursor_index],
                        )
                        self.cursor_index += 1
                elif key.name == "KEY_UP":
                    # Normal up navigation
                    self.cursor_index = max(0, self.cursor_index - 1)
                elif key.name == "KEY_DOWN":
                    # Normal down navigation
                    self.cursor_index = min(len(self.options) - 1, self.cursor_index + 1)
                elif key == " ":
                    # Space toggles selection
                    if self.options:
                        value, label = self.options[self.cursor_index]
                        if value in self.selected_values:
                            self.selected_values.discard(value)
                        else:
                            self.selected_values.add(value)
                elif key.name == "KEY_ENTER":
                    # Return selected items in current order
                    result = [value for value, label in self.options if value in self.selected_values]
                    return result if result else None


class ProgressDialog(Dialog):
    """Progress dialog with animated throbber."""

    THROBBER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, term: Terminal, theme: Theme, title: str, message: str) -> None:
        super().__init__(term, theme, title)
        self.message = message
        self.frame = 0

    def show_frame(self) -> None:
        """Show one frame of the progress dialog."""
        # Calculate width based on message length
        width = max(60, len(self.message) + 10)
        height = 9
        x, y = self.center_position(width, height)

        # Draw box
        lines = self._draw_box(x, y, width, height)
        for line in lines:
            print(line, end="", flush=True)

        # Draw message
        msg_y = y + 4
        print(
            self.term.move_xy(x + (width - len(self.message)) // 2, msg_y) + self.message,
            end="",
            flush=True,
        )

        # Draw throbber
        throbber = self.THROBBER_FRAMES[self.frame % len(self.THROBBER_FRAMES)]
        throbber_y = y + 6
        print(
            self.term.move_xy(x + width // 2 - 1, throbber_y)
            + self.theme.info(throbber + " "),
            end="",
            flush=True,
        )

        self.frame += 1
