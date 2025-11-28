"""Configuration and constants for VM Manager."""

from pathlib import Path

# Paths
VM_DIR: Path = Path("/var/lib/libvirt/images/vms")
ISO_DIR: Path = VM_DIR / "iso"
DISK_DIR: Path = VM_DIR / "disks"

# libvirt connection URI
LIBVIRT_URI: str = "qemu:///system"

# Default VM settings
DEFAULT_RAM_MB: int = 2048
DEFAULT_VCPUS: int = 2
DEFAULT_DISK_GB: int = 20
DEFAULT_OS_VARIANT: str = "generic"
DEFAULT_NETWORK: str = "default"

# UI settings
REFRESH_INTERVAL_MS: int = 2000
LIST_PAGE_SIZE: int = 20

# Color scheme
COLORS: dict[str, str] = {
    "running": "green",
    "shut_off": "red",
    "paused": "yellow",
    "crashed": "red",
    "pmsuspended": "cyan",
    "idle": "blue",
    "in_shutdown": "yellow",
    "blocked": "magenta",
    "nostate": "white",
    "header": "cyan",
    "selected": "white_on_blue",
    "error": "red",
    "success": "green",
    "warning": "yellow",
    "info": "cyan",
}

# Key bindings
KEYBINDINGS: dict[str, str] = {
    "quit": "q",
    "new": "n",
    "edit": "e",
    "delete": "d",
    "start": "s",
    "stop": "t",
    "console": "c",
    "snapshots": "p",
    "search": "/",
    "refresh": "r",
    "help": "?",
    "up": "k",
    "down": "j",
    "select": " ",
    "enter": "KEY_ENTER",
    "escape": "KEY_ESCAPE",
}
