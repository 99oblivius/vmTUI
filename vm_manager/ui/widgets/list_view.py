"""List view widget for displaying selectable items."""

from collections.abc import Callable
from typing import Generic, TypeVar

from blessed import Terminal

from vm_manager.ui.theme import Theme

T = TypeVar("T")


class ListView(Generic[T]):
    """Scrollable list view with selection."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        items: list[T],
        format_func: Callable[[T], str],
        height: int = 10,
    ) -> None:
        self.term = term
        self.theme = theme
        self.items = items
        self.format_func = format_func
        self.height = height
        self.selected_index = 0
        self.scroll_offset = 0

    def set_items(self, items: list[T]) -> None:
        """Update the items list."""
        self.items = items
        # Adjust selection if needed
        if self.selected_index >= len(items):
            self.selected_index = max(0, len(items) - 1)
        self._adjust_scroll()

    @property
    def selected_item(self) -> T | None:
        """Get the currently selected item."""
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None

    def move_up(self) -> None:
        """Move selection up."""
        if self.selected_index > 0:
            self.selected_index -= 1
            self._adjust_scroll()

    def move_down(self) -> None:
        """Move selection down."""
        if self.selected_index < len(self.items) - 1:
            self.selected_index += 1
            self._adjust_scroll()

    def page_up(self) -> None:
        """Move selection up by a page."""
        self.selected_index = max(0, self.selected_index - self.height)
        self._adjust_scroll()

    def page_down(self) -> None:
        """Move selection down by a page."""
        self.selected_index = min(
            len(self.items) - 1, self.selected_index + self.height
        )
        self._adjust_scroll()

    def home(self) -> None:
        """Move to first item."""
        self.selected_index = 0
        self._adjust_scroll()

    def end(self) -> None:
        """Move to last item."""
        self.selected_index = max(0, len(self.items) - 1)
        self._adjust_scroll()

    def _adjust_scroll(self) -> None:
        """Adjust scroll offset to keep selection visible."""
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.height:
            self.scroll_offset = self.selected_index - self.height + 1

    def render(self, x: int, y: int, width: int) -> list[str]:
        """Render the list view and return lines."""
        lines: list[str] = []

        if not self.items:
            lines.append(self.term.move_xy(x, y) + self.theme.dim("(no items)"))
            return lines

        visible_items = self.items[self.scroll_offset : self.scroll_offset + self.height]

        for i, item in enumerate(visible_items):
            actual_index = self.scroll_offset + i
            text = self.format_func(item)

            # Add left padding, truncate and pad to width accounting for ANSI codes
            # Target: 1 space padding + (width - 2) content + 1 space before border
            target_width = width - 1
            visible_len = self.term.length(text)

            if visible_len <= target_width:
                # Pad to exact width
                padding_needed = target_width - visible_len
                text = " " + text + " " * padding_needed
            else:
                # Truncate considering ANSI codes
                ratio = target_width / visible_len
                truncate_pos = int(len(text) * ratio)

                # Adjust to get exact visible width
                truncated = text[:truncate_pos]
                while self.term.length(truncated) > target_width and truncate_pos > 0:
                    truncate_pos -= 1
                    truncated = text[:truncate_pos]

                # Pad to exact width
                visible_len = self.term.length(truncated)
                padding_needed = target_width - visible_len
                text = " " + truncated + " " * padding_needed

            if actual_index == self.selected_index:
                text = self.theme.selected(text)

            lines.append(self.term.move_xy(x, y + i) + text)

        # Fill remaining height with empty lines
        for i in range(len(visible_items), self.height):
            lines.append(self.term.move_xy(x, y + i) + " " * width)

        return lines

    def handle_key(self, key: str) -> bool:
        """Handle key input. Returns True if handled."""
        if key in ("k", "KEY_UP"):
            self.move_up()
            return True
        elif key in ("j", "KEY_DOWN"):
            self.move_down()
            return True
        elif key == "KEY_PGUP":
            self.page_up()
            return True
        elif key == "KEY_PGDOWN":
            self.page_down()
            return True
        elif key == "KEY_HOME":
            self.home()
            return True
        elif key == "KEY_END":
            self.end()
            return True
        return False
