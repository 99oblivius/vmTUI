# VM Manager

A terminal-based virtual machine manager for libvirt/KVM, designed as a keyboard-driven replacement for virt-manager.

## Features

- **Split-pane TUI** - VM list with live details panel showing CPU, memory, disk, network info
- **Keyboard-driven** - Vim-style navigation (j/k) with full keyboard control
- **VM Creation Wizard** - 8-step guided process with validation and smart defaults
- **Inline Editing** - Edit VM configuration directly in the details pane
- **GPU Passthrough** - Multi-GPU selection with IOMMU group detection and driver validation
- **USB Passthrough** - Multi-select USB devices by vendor:product ID
- **Audio Support** - AC97, ICH6, ICH9 audio device emulation
- **Network Options** - Host bridges and libvirt networks with multiple NIC models
- **Display Options** - SPICE, VNC, or headless with serial console
- **CPU Pinning** - Pin vCPUs to specific physical cores for performance
- **OS Variant Browser** - Fuzzy search across all libosinfo OS variants
- **Snapshot Management** - Create, revert, and delete VM snapshots
- **Non-blocking Operations** - Start/stop VMs without freezing the UI
- **Console View** - View serial console output in the details pane
- **Safe Deletion** - Type-back confirmation with separate config/storage deletion options

## Requirements

### System Dependencies

```bash
# Debian/Ubuntu
sudo apt install \
  qemu-kvm \
  libvirt-daemon-system \
  libvirt-clients \
  bridge-utils \
  virtinst \
  virt-viewer \
  libosinfo-bin \
  ovmf \
  python3-libvirt

# Fedora/RHEL
sudo dnf install \
  qemu-kvm \
  libvirt \
  libvirt-client \
  bridge-utils \
  virt-install \
  virt-viewer \
  libosinfo \
  edk2-ovmf \
  python3-libvirt

# Arch
sudo pacman -S \
  qemu-full \
  libvirt \
  bridge-utils \
  virt-install \
  virt-viewer \
  libosinfo \
  edk2-ovmf \
  python-libvirt
```

### libvirt Setup

```bash
# Enable and start libvirtd
sudo systemctl enable --now libvirtd

# Add your user to the libvirt group (logout/login required)
sudo usermod -aG libvirt $USER

# Verify it's running
virsh list --all
```

### Python

- Python 3.10 or higher (3.13+ recommended for best performance)

## Installation

### Option 1: Using pip with venv (Recommended)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/vm-manager.git
cd vm-manager

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install .

# Run
vm-manager
```

### Option 2: Using pipx

[pipx](https://pipx.pypa.io/) installs Python applications in isolated environments.

```bash
# Install pipx if you don't have it
sudo apt install pipx  # Debian/Ubuntu
sudo dnf install pipx  # Fedora
sudo pacman -S python-pipx  # Arch

pipx ensurepath

# Install vm-manager
pipx install git+https://github.com/YOUR_USERNAME/vm-manager.git

# Run
vm-manager
```

### Option 3: Building a Standalone Binary

Build a single executable that bundles Python:

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/vm-manager.git
cd vm-manager

# Create venv and install with build dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[build]"

# Build with Nuitka (takes several minutes)
./build.sh

# Install system-wide
sudo cp dist/vm-manager /usr/local/bin/

# Run from anywhere
vm-manager
```

### Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/vm-manager.git
cd vm-manager
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Type checking
mypy vm_manager

# Linting
ruff check vm_manager
```

## Usage

```bash
vm-manager
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `n` | Create new VM |
| `e` | Edit selected VM (inline) |
| `d` | Delete selected VM (with type-back confirmation) |
| `s` | Start VM (non-blocking) |
| `t` | Stop VM (graceful/force) |
| `c` | Open console (SPICE/VNC/serial) |
| `v` | Toggle console view in details pane (running VMs) |
| `p` | Manage snapshots |
| `/` | Search VMs |
| `r` | Refresh list |
| `?` | Show help |
| `q` | Quit |

### VM Creation Wizard Steps

1. **Basic Information** - VM name (validates uniqueness)
2. **Resources** - CPUs, memory (MB), disk (GB), CPU pinning
3. **Operating System** - OS variant (fuzzy search), ISO file selection
4. **Network** - Bridge/network selection, NIC model
5. **Display & GPU** - SPICE/VNC/None, multi-GPU passthrough selection
6. **Audio** - Audio device model (ICH9/ICH6/AC97/None)
7. **USB Passthrough** - Multi-select USB device passthrough
8. **Review & Create** - Summary and confirmation

## Configuration

VMs and disks are stored in `/var/lib/libvirt/images/vms/`:

```
/var/lib/libvirt/images/vms/
├── iso/      # ISO images for installation
└── disks/    # VM disk images (qcow2)
```

Create the directories and set permissions:

```bash
sudo mkdir -p /var/lib/libvirt/images/vms/{iso,disks}
sudo chown -R libvirt-qemu:libvirt-qemu /var/lib/libvirt/images/vms
```

## Networking

### Using Host Bridges (Recommended)

If you have your own bridge (e.g., `br0`), VM Manager will automatically detect it and show it in the network selection. This gives VMs direct network access on your LAN.

```bash
# Example: Create a bridge with NetworkManager
nmcli con add type bridge ifname br0
nmcli con add type bridge-slave ifname eth0 master br0
nmcli con up br0
```

### Using libvirt Networks

You can also use libvirt's NAT networks:

```bash
# Start default network
sudo virsh net-start default
sudo virsh net-autostart default
```

### NIC Models

| Model | Description |
|-------|-------------|
| **VirtIO** | Best performance (requires guest drivers) |
| **e1000e** | Good compatibility, works without drivers |
| **e1000** | Legacy Intel, broad support |
| **rtl8139** | Wide compatibility for older OSes |
| **vmxnet3** | VMware paravirtual NIC |

## GPU Passthrough

For GPU passthrough to work:

1. **Enable IOMMU** in BIOS (Intel VT-d / AMD-Vi)

2. **Add kernel parameters** to `/etc/default/grub`:
   ```
   # Intel
   GRUB_CMDLINE_LINUX_DEFAULT="... intel_iommu=on"

   # AMD
   GRUB_CMDLINE_LINUX_DEFAULT="... amd_iommu=on"
   ```
   Then run `sudo update-grub` and reboot.

3. **Bind GPU to vfio-pci driver** - GPUs must use vfio-pci to be selectable for passthrough

4. **Select GPUs in wizard** - VM Manager detects available GPUs and their IOMMU groups. The entire IOMMU group is passed through together.

5. **Combine with remote display** - You can select GPU passthrough and still enable SPICE/VNC for remote access during setup.

## USB Passthrough

USB devices are passed through by vendor:product ID. The wizard shows a multi-select dialog where you can toggle devices with Space.

Note: Some USB devices may need to be unbound from the host driver first.

## Display Options

| Option | Description |
|--------|-------------|
| **SPICE** | Remote desktop with audio/USB redirection (recommended) |
| **VNC** | Basic remote display, widely compatible |
| **None** | Headless mode with serial console only |

Connect to VMs with:
```bash
# Using virt-viewer (recommended)
virt-viewer --connect qemu:///system <vm-name>

# Or directly via protocol
spicy spice://localhost:<port>
vncviewer localhost:<port>
```

## Technical Details

### Architecture

```
vm_manager/
├── models/          # Data models (VM, VMConfig, Snapshot, Hardware)
├── services/        # Backend services
│   ├── libvirt_service.py  # Core libvirt operations
│   ├── gpu.py              # GPU detection, IOMMU groups
│   ├── usb.py              # USB device enumeration
│   ├── network.py          # Bridge/network detection
│   ├── osinfo.py           # OS variant database
│   └── system.py           # System resource detection
├── ui/
│   ├── app.py       # Main application controller
│   ├── theme.py     # Terminal theming
│   ├── screens/     # Main screen, create wizard
│   └── widgets/     # Reusable UI components
└── utils/           # Formatting utilities
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `blessed` | Terminal UI framework |
| `libvirt-python` | libvirt API bindings |

External tools used:
- `osinfo-query` - OS variant database lookups
- `virt-install` - VM creation

### Default VM Configuration

| Setting | Default |
|---------|---------|
| vCPUs | 2 |
| Memory | 2048 MB |
| Disk | 20 GB |
| Graphics | SPICE |
| Audio | ICH9 |
| NIC | VirtIO |
| OS Variant | generic |

## Troubleshooting

### "Permission denied" connecting to libvirt

Add your user to the libvirt group:
```bash
sudo usermod -aG libvirt $USER
```
Then logout and login again.

### No VMs showing but they exist

Ensure libvirtd is running:
```bash
sudo systemctl status libvirtd
```

### Python version too old

Requires Python 3.10+ (3.13+ recommended). Check your version with `python3 --version`.

- Ubuntu 22.04+, Fedora 36+, Debian 12+ include Python 3.10+
- For Python 3.13, use [pyenv](https://github.com/pyenv/pyenv) or your distro's backports

## License

MIT
