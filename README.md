# VM Manager

A TUI-based virtual machine manager for libvirt/KVM, designed as a terminal replacement for virt-manager.

## Features

- **Split-pane TUI** - VM list with live details panel
- **Keyboard-driven** - Vim-style navigation (j/k)
- **VM Creation Wizard** - 8-step guided process
- **GPU Passthrough** - Multi-GPU selection with IOMMU group detection
- **USB Passthrough** - Multi-select USB devices
- **Audio Support** - AC97, ICH6, ICH9 audio devices
- **Network Options** - Host bridges and libvirt networks with NIC model selection
- **Display Options** - SPICE, VNC, or headless with serial console
- **CPU Pinning** - Pin vCPUs to specific physical cores
- **OS Variant Browser** - Fuzzy search all OS variants
- **Snapshot Management** - Create, revert, and delete snapshots
- **Non-blocking Operations** - Start/stop VMs without freezing UI
- **Console View** - View serial console output in details pane
- **Safe Deletion** - Type-back confirmation with separate config/storage options

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
  ovmf

# Fedora/RHEL
sudo dnf install \
  qemu-kvm \
  libvirt \
  libvirt-client \
  bridge-utils \
  virt-install \
  virt-viewer \
  libosinfo \
  edk2-ovmf

# Arch
sudo pacman -S \
  qemu-full \
  libvirt \
  bridge-utils \
  virt-install \
  virt-viewer \
  libosinfo \
  edk2-ovmf
```

### Starting libvirt

```bash
# Enable and start libvirtd
sudo systemctl enable --now libvirtd

# Verify it's running
virsh list --all
```

### Python

- Python 3.13 or higher

## Installation

### Using pyenv (Recommended)

```bash
# Clone and enter directory
cd /root/vm-manager

# The pyenv environment is already configured
# Activate it:
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# Install dependencies
pip install -e .

# Run
vm-manager
```

### Building a Standalone Binary

```bash
# Install build dependencies
pip install -e ".[build]"

# Build with Nuitka
./build.sh

# Install system-wide
sudo cp dist/vm-manager /usr/local/bin/
```

### Development Setup

```bash
pip install -e ".[dev]"

# Type checking
mypy vm_manager

# Linting
ruff check vm_manager
```

## Usage

```bash
# Run the TUI
vm-manager
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `n` | Create new VM |
| `e` | Edit selected VM |
| `d` | Delete selected VM (with type-back confirmation) |
| `s` | Start VM (non-blocking) |
| `t` | Stop VM (graceful/force) |
| `c` | Open console (SPICE/VNC/serial) |
| `v` | Toggle console view (running VMs) |
| `p` | Manage snapshots |
| `/` | Search VMs |
| `r` | Refresh list |
| `?` | Show help |
| `q` | Quit |

### VM Creation Wizard Steps

1. **Basic Information** - VM name
2. **Resources** - CPUs, memory, disk, CPU pinning
3. **Operating System** - OS variant, ISO selection
4. **Network** - Bridge/network selection, NIC model
5. **Display & GPU** - SPICE/VNC/None, GPU passthrough
6. **Audio** - Audio device model
7. **USB Passthrough** - USB device selection
8. **Review & Create** - Confirm and create

## Configuration

VMs and disks are stored in `/var/lib/libvirt/images/vms/`:

```
/var/lib/libvirt/images/vms/
├── iso/      # ISO images
└── disks/    # VM disk images
```

Ensure proper permissions:

```bash
sudo mkdir -p /var/lib/libvirt/images/vms/{iso,disks}
sudo chown -R libvirt-qemu:libvirt-qemu /var/lib/libvirt/images/vms
```

## Networking

### Using Host Bridges (Recommended)

If you have your own bridge (e.g., `br0`), VM Manager will automatically detect it and show it in the network selection. This gives VMs direct network access.

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

- **VirtIO** - Best performance (requires guest drivers)
- **e1000e** - Good compatibility (works without drivers)
- **e1000** - Legacy Intel
- **rtl8139** - Wide compatibility for old OSes

## GPU Passthrough

For GPU passthrough to work:

1. Enable IOMMU in BIOS (Intel VT-d / AMD-Vi)
2. Add kernel parameters:
   ```
   # Intel
   intel_iommu=on

   # AMD
   amd_iommu=on
   ```
3. The VM Manager will detect available GPUs and their IOMMU groups
4. You can select multiple GPUs and combine with SPICE/VNC for remote access

## USB Passthrough

USB devices are passed through by vendor:product ID. The wizard shows a multi-select dialog where you can toggle devices with Enter.

Note: Some USB devices may need to be unbound from the host driver first.

## Display Options

- **SPICE** - Remote desktop with audio/USB redirection (recommended)
- **VNC** - Basic remote display
- **None** - Headless with serial console only

For SPICE/VNC, connect with:
```bash
# Using virt-viewer
virt-viewer --connect qemu:///system <vm-name>

# Or directly
spice://localhost:<port>
vnc://localhost:<port>
```

## License

MIT
