"""Entry point for VM Manager."""

import sys

from vm_manager.ui.app import App


def main() -> int:
    """Main entry point."""
    app = App()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
