"""Fuzzy search select widget."""

from blessed import Terminal
from blessed.keyboard import Keystroke

from vm_manager.ui.theme import Theme


class SearchSelect:
    """Searchable select dialog with fuzzy matching."""

    def __init__(
        self,
        term: Terminal,
        theme: Theme,
        title: str,
        options: list[tuple[str, str]],  # (value, display)
        selected_value: str | None = None,  # Initial value to pre-select
    ) -> None:
        self.term = term
        self.theme = theme
        self.title = title
        self.all_options = options
        self.filtered_options = options.copy()

        self.search_query = ""
        self.selected_index = 0
        self.scroll_offset = 0

        # Pre-select the initial value if provided
        if selected_value:
            for i, (val, _) in enumerate(self.filtered_options):
                if val == selected_value:
                    self.selected_index = i
                    break

    def _fuzzy_score(self, query: str, text: str) -> int:
        """Calculate fuzzy match score. Higher is better, 0 means no match."""
        query = query.lower()
        text = text.lower()

        if not query:
            return 1

        # Exact match gets highest score
        if query == text:
            return 10000

        # Contains as substring - highest priority for partial matches
        if query in text:
            # Bonus for word boundary match
            idx = text.find(query)
            if idx == 0 or text[idx - 1] in " -_./":
                return 5000 + (1000 - idx)
            return 3000 + (1000 - idx)

        # Word prefix matching (each word in query matches start of words in text)
        query_words = query.split()
        text_words = text.replace("-", " ").replace("_", " ").replace(".", " ").split()

        if query_words:
            word_matches = 0
            for qw in query_words:
                for tw in text_words:
                    if tw.startswith(qw):
                        word_matches += 1
                        break
            if word_matches == len(query_words):
                return 2000 + word_matches * 100

        # Fuzzy character sequence matching with scoring
        # Only use this for short queries or when characters are close together
        score = 0
        qi = 0
        prev_match_idx = -2
        consecutive_bonus = 0
        total_gap = 0

        for i, char in enumerate(text):
            if qi < len(query) and char == query[qi]:
                # Track gap between matches
                if prev_match_idx >= 0:
                    total_gap += i - prev_match_idx - 1

                # Base score for match
                score += 10

                # Bonus for consecutive matches
                if i == prev_match_idx + 1:
                    consecutive_bonus += 15
                    score += consecutive_bonus
                else:
                    consecutive_bonus = 0

                # Bonus for word boundary
                if i == 0 or text[i - 1] in " -_./":
                    score += 30

                prev_match_idx = i
                qi += 1

        # All characters must match
        if qi == len(query):
            # Penalize matches that are spread too far apart
            avg_gap = total_gap / max(1, len(query) - 1) if len(query) > 1 else 0
            if avg_gap > 5:
                # Too spread out, heavily penalize
                score = score // 4
            elif avg_gap > 2:
                score = score // 2

            # Minimum score threshold for fuzzy matches
            if score < 30:
                return 0
            return score

        return 0

    def _filter_options(self) -> None:
        """Filter and sort options based on search query."""
        if not self.search_query:
            self.filtered_options = self.all_options.copy()
        else:
            # Score all options
            scored: list[tuple[int, str, str]] = []
            for val, display in self.all_options:
                # Take best score from display or value
                score = max(
                    self._fuzzy_score(self.search_query, display),
                    self._fuzzy_score(self.search_query, val)
                )
                if score > 0:
                    scored.append((score, val, display))

            # Sort by score descending
            scored.sort(key=lambda x: -x[0])
            self.filtered_options = [(val, display) for _, val, display in scored]

        # Reset selection
        self.selected_index = 0
        self.scroll_offset = 0

    def show(self) -> str | None:
        """Show the search select dialog. Returns selected value or None."""
        # Calculate dialog dimensions
        width = min(70, self.term.width - 4)
        height = min(20, self.term.height - 4)
        x = (self.term.width - width) // 2
        y = (self.term.height - height) // 2

        visible_count = height - 7  # Title, search box, separator, bottom border

        with self.term.cbreak():
            while True:
                self._render(x, y, width, height, visible_count)

                key: Keystroke = self.term.inkey()

                if key.name == "KEY_ESCAPE":
                    return None
                elif key.name == "KEY_ENTER" or key == " ":
                    if self.filtered_options:
                        return self.filtered_options[self.selected_index][0]
                    return None
                elif key.name == "KEY_UP" or key == "k":
                    if self.selected_index > 0:
                        self.selected_index -= 1
                        if self.selected_index < self.scroll_offset:
                            self.scroll_offset = self.selected_index
                elif key.name == "KEY_DOWN" or key == "j":
                    if self.selected_index < len(self.filtered_options) - 1:
                        self.selected_index += 1
                        if self.selected_index >= self.scroll_offset + visible_count:
                            self.scroll_offset = self.selected_index - visible_count + 1
                elif key.name == "KEY_PGUP":
                    self.selected_index = max(0, self.selected_index - visible_count)
                    self.scroll_offset = max(0, self.scroll_offset - visible_count)
                elif key.name == "KEY_PGDOWN":
                    self.selected_index = min(
                        len(self.filtered_options) - 1,
                        self.selected_index + visible_count
                    )
                    self.scroll_offset = min(
                        max(0, len(self.filtered_options) - visible_count),
                        self.scroll_offset + visible_count
                    )
                elif key.name == "KEY_BACKSPACE":
                    self.search_query = self.search_query[:-1]
                    self._filter_options()
                elif key and len(key) == 1 and key.isprintable():
                    self.search_query += key
                    self._filter_options()

    def _render(self, x: int, y: int, width: int, height: int, visible_count: int) -> None:
        """Render the dialog."""
        chars = self.theme.box_chars()

        # Top border with title
        title = f" {self.title} "
        title_pos = (width - len(title)) // 2
        top = chars["tl"] + chars["h"] * (title_pos - 1) + title + chars["h"] * (width - title_pos - len(title) - 1) + chars["tr"]
        print(self.term.move_xy(x, y) + top, end="")

        # Search box
        y_pos = y + 1
        search_label = "Search: "
        search_display = self.search_query + "█"
        search_line = chars["v"] + " " + search_label + search_display
        search_line = search_line[:width - 1].ljust(width - 1) + chars["v"]
        print(self.term.move_xy(x, y_pos) + search_line, end="")

        # Result count
        y_pos += 1
        count_text = f"{len(self.filtered_options)} matches"
        padding = width - 3 - len(count_text)
        count_line = chars["v"] + " " + self.theme.dim(count_text) + " " * padding + chars["v"]
        print(self.term.move_xy(x, y_pos) + count_line, end="")

        # Separator
        y_pos += 1
        sep = chars["vr"] + chars["h"] * (width - 2) + chars["vl"]
        print(self.term.move_xy(x, y_pos) + sep, end="")

        # Options
        y_pos += 1
        visible = self.filtered_options[self.scroll_offset:self.scroll_offset + visible_count]

        for i, (value, display) in enumerate(visible):
            actual_idx = self.scroll_offset + i
            is_selected = actual_idx == self.selected_index

            # Truncate display text
            text = display[:width - 4]
            padded_text = f" {text}".ljust(width - 2)

            if is_selected:
                line = chars["v"] + self.term.reverse(padded_text) + chars["v"]
            else:
                line = chars["v"] + padded_text + chars["v"]

            print(self.term.move_xy(x, y_pos + i) + line, end="")

        # Fill remaining lines
        for i in range(len(visible), visible_count):
            empty = chars["v"] + " " * (width - 2) + chars["v"]
            print(self.term.move_xy(x, y_pos + i) + empty, end="")

        # Scroll indicator
        if len(self.filtered_options) > visible_count:
            if self.scroll_offset > 0:
                print(self.term.move_xy(x + width - 2, y_pos) + "↑", end="")
            if self.scroll_offset + visible_count < len(self.filtered_options):
                print(self.term.move_xy(x + width - 2, y_pos + visible_count - 1) + "↓", end="")

        # Bottom border with hints
        y_pos += visible_count
        hints = "↑↓:select  Enter/Space:confirm  Esc:cancel"
        bottom = chars["bl"] + chars["h"] * (width - 2) + chars["br"]
        print(self.term.move_xy(x, y_pos) + bottom, end="")

        y_pos += 1
        print(
            self.term.move_xy(x, y_pos) + self.theme.dim(hints.center(width)),
            end="",
        )

        print("", end="", flush=True)

    def _highlight_match(self, text: str, query: str) -> str:
        """Highlight matching characters in text."""
        # For now, return as-is. Could add highlighting later.
        return text
