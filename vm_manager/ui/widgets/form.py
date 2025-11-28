"""Form widgets for input fields and buttons."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.ui.theme import Theme


class FieldType(Enum):
    """Type of form field."""
    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    BUTTON = "button"


@dataclass
class FormField:
    """A form field definition."""
    name: str
    label: str
    field_type: FieldType = FieldType.TEXT
    value: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)  # For SELECT: (value, display)
    validator: Callable[[str], str | None] | None = None
    placeholder: str = ""
    cursor_pos: int = 0
    recommended: list[str] = field(default_factory=list)  # Values to show first in dialogs
    disabled: bool = False  # If True, field is greyed out and not editable

    def get_display_value(self) -> str:
        """Get value for display."""
        if self.field_type == FieldType.SELECT:
            for val, display in self.options:
                if val == self.value:
                    return display
            return self.value or self.placeholder
        return self.value or self.placeholder

    def get_sorted_options(self) -> list[tuple[str, str]]:
        """Get options sorted with recommended first."""
        if not self.recommended:
            return self.options

        recommended_opts = []
        other_opts = []
        for opt in self.options:
            if opt[0] in self.recommended:
                recommended_opts.append(opt)
            else:
                other_opts.append(opt)

        # Sort recommended by their order in the recommended list
        recommended_opts.sort(key=lambda x: self.recommended.index(x[0]) if x[0] in self.recommended else 999)
        return recommended_opts + other_opts


class Form:
    """Form with multiple editable fields and navigation buttons."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        fields: list[FormField],
        buttons: list[tuple[str, str]] | None = None,  # (id, label)
    ) -> None:
        self.term = term
        self.theme = theme
        self.fields = fields
        self.buttons = buttons or [("cancel", "Cancel"), ("next", "Next")]

        self.focused_index = 0
        self.in_button_row = False
        self.focused_button = 0
        self.error_message = ""

    @property
    def focused_field(self) -> FormField | None:
        """Get currently focused field."""
        if self.in_button_row or self.focused_index >= len(self.fields):
            return None
        return self.fields[self.focused_index]

    def get_values(self) -> dict[str, str]:
        """Get all field values as a dictionary."""
        return {f.name: f.value for f in self.fields}

    def set_value(self, name: str, value: str) -> None:
        """Set a field value by name."""
        for f in self.fields:
            if f.name == name:
                f.value = value
                f.cursor_pos = len(value)
                break

    def render(self, x: int, y: int, width: int) -> int:
        """Render the form. Returns number of lines used."""
        lines_used = 0

        # Render fields
        for i, field in enumerate(self.fields):
            is_focused = (not self.in_button_row) and (i == self.focused_index)
            lines_used += self._render_field(x, y + lines_used, width, field, is_focused)
            lines_used += 1  # spacing

        # Render buttons
        lines_used += 1  # extra spacing before buttons
        self._render_buttons(x, y + lines_used, width)
        lines_used += 1

        # Render error message
        if self.error_message:
            print(
                self.term.move_xy(x, y + lines_used + 1)
                + self.theme.error(self.error_message[:width]),
                end="",
            )
            lines_used += 2

        return lines_used

    def _render_field(
        self, x: int, y: int, width: int, field: FormField, is_focused: bool
    ) -> int:
        """Render a single field. Returns lines used."""
        # Label
        label = field.label
        if field.disabled:
            label = self.theme.dim(label)
        elif is_focused:
            label = self.theme.colored(label, "cyan")
        print(self.term.move_xy(x, y) + label, end="")

        # Value
        if field.field_type == FieldType.SELECT:
            display = field.get_display_value()
            if field.disabled:
                display = self.theme.dim(f" {display}")
            elif is_focused:
                display = self.term.reverse(f" {display} ")
            else:
                display = f" {display}"
            print(self.term.move_xy(x, y + 1) + display, end="")
        else:
            # Text/Number field with cursor
            value = field.value
            field_width = width - 2

            if field.disabled:
                # Disabled field - grey text
                if value:
                    display = self.theme.dim(value[:field_width].ljust(field_width))
                else:
                    display = self.theme.dim(field.placeholder[:field_width].ljust(field_width))
            elif is_focused:
                # Show cursor
                before = value[:field.cursor_pos]
                after = value[field.cursor_pos:]
                cursor = "█"
                display = before + cursor + after
                display = display[:field_width].ljust(field_width)
                display = self.term.reverse(display)
            else:
                if value:
                    display = value[:field_width].ljust(field_width)
                else:
                    display = self.theme.dim(field.placeholder[:field_width].ljust(field_width))

            print(self.term.move_xy(x, y + 1) + display, end="")

        return 2

    def _render_buttons(self, x: int, y: int, width: int) -> None:
        """Render the button row."""
        button_strs: list[str] = []

        for i, (btn_id, label) in enumerate(self.buttons):
            is_focused = self.in_button_row and (i == self.focused_button)
            if is_focused:
                btn = self.term.reverse(f" {label} ")
            else:
                btn = f"[{label}]"
            button_strs.append(btn)

        buttons_line = "  ".join(button_strs)
        print(self.term.move_xy(x, y) + buttons_line, end="")

    def handle_key(self, key: Keystroke) -> str | None:
        """Handle key input. Returns button id if pressed, None otherwise."""
        self.error_message = ""

        field = self.focused_field

        # Navigation between fields and buttons
        if key.name == "KEY_TAB":
            self._focus_next()
            return None
        elif key.name == "KEY_BTAB":  # Shift+Tab
            self._focus_previous()
            return None
        elif key.name == "KEY_DOWN":
            self._focus_next()
            return None
        elif key.name == "KEY_UP":
            self._focus_previous()
            return None

        # Button row handling
        if self.in_button_row:
            if key.name == "KEY_LEFT":
                self.focused_button = max(0, self.focused_button - 1)
            elif key.name == "KEY_RIGHT":
                self.focused_button = min(len(self.buttons) - 1, self.focused_button + 1)
            elif key.name == "KEY_ENTER":
                return self.buttons[self.focused_button][0]
            return None

        # Field editing
        if field is None:
            return None

        # Don't allow editing disabled fields
        if field.disabled:
            return None

        if field.field_type == FieldType.SELECT:
            # For select fields, Enter opens selector, space cycles
            if key.name == "KEY_ENTER" or key == " ":
                return f"select:{field.name}"
            elif key.name == "KEY_LEFT":
                self._cycle_select(field, -1)
            elif key.name == "KEY_RIGHT":
                self._cycle_select(field, 1)
        else:
            # Text/Number field editing
            if key.name == "KEY_ENTER":
                # Enter moves to next field
                self._focus_next()
            elif key.name == "KEY_LEFT":
                field.cursor_pos = max(0, field.cursor_pos - 1)
            elif key.name == "KEY_RIGHT":
                field.cursor_pos = min(len(field.value), field.cursor_pos + 1)
            elif key.name == "KEY_HOME":
                field.cursor_pos = 0
            elif key.name == "KEY_END":
                field.cursor_pos = len(field.value)
            elif key.name == "KEY_BACKSPACE":
                if field.cursor_pos > 0:
                    field.value = field.value[:field.cursor_pos - 1] + field.value[field.cursor_pos:]
                    field.cursor_pos -= 1
            elif key.name == "KEY_DELETE":
                if field.cursor_pos < len(field.value):
                    field.value = field.value[:field.cursor_pos] + field.value[field.cursor_pos + 1:]
            elif key and len(key) == 1 and key.isprintable():
                # Validate input for number fields
                if field.field_type == FieldType.NUMBER and not key.isdigit():
                    return None
                field.value = field.value[:field.cursor_pos] + key + field.value[field.cursor_pos:]
                field.cursor_pos += 1

        return None

    def _focus_next(self) -> None:
        """Move focus to next field or button, skipping disabled fields."""
        if self.in_button_row:
            # Already in button row, wrap to first enabled field
            self.in_button_row = False
            self.focused_index = 0
            # Skip disabled fields
            while self.focused_index < len(self.fields) and self.fields[self.focused_index].disabled:
                self.focused_index += 1
            if self.focused_index >= len(self.fields):
                self.in_button_row = True
                self.focused_button = len(self.buttons) - 1
        elif self.focused_index < len(self.fields) - 1:
            self.focused_index += 1
            # Skip disabled fields
            while self.focused_index < len(self.fields) and self.fields[self.focused_index].disabled:
                self.focused_index += 1
            if self.focused_index >= len(self.fields):
                self.in_button_row = True
                self.focused_button = len(self.buttons) - 1
        else:
            # Move to button row
            self.in_button_row = True
            self.focused_button = len(self.buttons) - 1  # Focus "Next" button

    def _focus_previous(self) -> None:
        """Move focus to previous field or button, skipping disabled fields."""
        if self.in_button_row:
            # Move back to last enabled field
            self.in_button_row = False
            self.focused_index = len(self.fields) - 1
            # Skip disabled fields
            while self.focused_index >= 0 and self.fields[self.focused_index].disabled:
                self.focused_index -= 1
            if self.focused_index < 0:
                self.in_button_row = True
                self.focused_button = 0
        elif self.focused_index > 0:
            self.focused_index -= 1
            # Skip disabled fields
            while self.focused_index >= 0 and self.fields[self.focused_index].disabled:
                self.focused_index -= 1
            if self.focused_index < 0:
                self.in_button_row = True
                self.focused_button = 0
        else:
            # Wrap to button row
            self.in_button_row = True
            self.focused_button = 0  # Focus "Cancel" button

    def _cycle_select(self, field: FormField, direction: int) -> None:
        """Cycle through select options."""
        if not field.options:
            return

        current_idx = -1
        for i, (val, _) in enumerate(field.options):
            if val == field.value:
                current_idx = i
                break

        new_idx = (current_idx + direction) % len(field.options)
        field.value = field.options[new_idx][0]

    def validate(self) -> bool:
        """Validate all fields. Returns True if valid."""
        for field in self.fields:
            if field.validator:
                error = field.validator(field.value)
                if error:
                    self.error_message = f"{field.label}: {error}"
                    return False
        return True
