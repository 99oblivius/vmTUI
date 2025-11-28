"""Theme and styling for the TUI."""

from blessed import Terminal

from vm_manager.config import COLORS
from vm_manager.models import VMState


class Theme:
    """Theme manager for consistent styling."""

    def __init__(self, term: Terminal) -> None:
        self.term = term

    def state_color(self, state: VMState) -> str:
        """Get colored state text."""
        color_key = state.color_key
        color_name = COLORS.get(color_key, "white")
        color_func = getattr(self.term, color_name, self.term.white)
        return str(color_func(state.display_name))

    def colored(self, text: str, color: str) -> str:
        """Apply color to text."""
        color_func = getattr(self.term, color, self.term.white)
        return str(color_func(text))

    def header(self, text: str) -> str:
        """Style header text."""
        return str(self.term.bold_cyan(text))

    def selected(self, text: str) -> str:
        """Style selected item."""
        return str(self.term.black_on_white(text))

    def error(self, text: str) -> str:
        """Style error text."""
        return str(self.term.bold_red(text))

    def success(self, text: str) -> str:
        """Style success text."""
        return str(self.term.bold_green(text))

    def warning(self, text: str) -> str:
        """Style warning text."""
        return str(self.term.bold_yellow(text))

    def info(self, text: str) -> str:
        """Style info text."""
        return str(self.term.cyan(text))

    def dim(self, text: str) -> str:
        """Style dimmed text."""
        try:
            return str(self.term.dim(text))
        except (TypeError, AttributeError):
            pass
        # Fallback to darker color if dim not supported
        try:
            return str(self.term.bright_black(text))
        except (TypeError, AttributeError):
            return text

    def bold(self, text: str) -> str:
        """Style bold text."""
        return str(self.term.bold(text))

    def key_hint(self, key: str, action: str) -> str:
        """Format key binding hint."""
        return f"{self.term.bold_yellow(f'[{key}]')}{action}"

    def box_chars(self) -> dict[str, str]:
        """Get box drawing characters."""
        return {
            "tl": "┌",
            "tr": "┐",
            "bl": "└",
            "br": "┘",
            "h": "─",
            "v": "│",
            "vr": "├",
            "vl": "┤",
            "hd": "┬",
            "hu": "┴",
            "cross": "┼",
        }
