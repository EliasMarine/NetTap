# First-Run Setup Wizard

When you first access the NetTap dashboard, a guided setup wizard walks you through initial configuration. The wizard has five steps.

---

## Step 1: Welcome

The welcome screen runs a hardware compatibility check to verify your system meets requirements before proceeding:

- **Two or more network interfaces** --- confirms at least 2 physical NICs are present
- **Docker is running** --- verifies the Docker daemon is active
- **Sufficient disk space (100GB+)** --- checks available storage

Once all checks pass (indicated by green checkmarks), click **Next** to continue.

!!! tip
    If a check fails, the wizard shows what went wrong. You can fix the issue and re-run the check without restarting the wizard.

---

## Step 2: Network Interfaces

This step lets you select which NICs to use for the WAN and LAN sides of the transparent bridge.

The wizard displays all detected physical interfaces with:

- Interface name (e.g., `enp1s0`, `enp2s0`)
- MAC address
- Link state (up/down)
- Speed (e.g., 2500Mb/s)
- Driver (e.g., `igc` for Intel i226-V)
- Interface type (Ethernet, wireless, virtual)

### Selecting WAN and LAN

1. Choose your **WAN interface** --- this connects to your ISP modem
2. Choose your **LAN interface** --- this connects to your router

The wizard prevents you from selecting the same interface for both.

### NIC LED Identification

If you are unsure which physical port corresponds to which interface name, use the **Identify** button next to each NIC. This triggers the LED on that port to blink for 15 seconds, so you can physically verify which port is which.

!!! note "LED blink support"
    LED identification uses the `ethtool --identify` command. This works with most Intel NICs (i225-V, i226-V, I350) but may not be supported on all hardware.

---

## Step 3: Bridge Configuration

After selecting your NICs, the wizard shows a preview of the bridge configuration that will be applied:

- Bridge name: `br0`
- WAN interface assignment
- LAN interface assignment
- STP disabled (transparent inline tap)
- Forward delay set to 0
- Promiscuous mode enabled on both interfaces

Click **Create Bridge** to apply the configuration. The wizard creates the bridge, tunes NIC offloading settings, disables bridge netfilter (to avoid iptables overhead), and validates the result.

!!! warning "Brief network interruption"
    Creating the bridge causes a brief (1--3 second) interruption in traffic between your modem and router. Devices may experience a momentary connection drop while the bridge initializes.

---

## Step 4: Storage Configuration

Configure data retention policies:

| Setting | Default | Description |
|---|---|---|
| Hot tier retention | 90 days | How long to keep Zeek metadata logs |
| Warm tier retention | 180 days | How long to keep Suricata alert data |
| Cold tier retention | 30 days | How long to keep raw PCAP captures |
| Disk threshold | 80% | Start pruning old data when disk usage exceeds this |

These defaults work well for most home networks with 1 TB of storage. Adjust based on your storage capacity and retention needs.

---

## Step 5: Account Setup

Create the initial administrator account for the NetTap dashboard.

After completing this step, the wizard saves your configuration and redirects you to the main dashboard.

---

## After the Wizard

Once the wizard completes:

1. **Data collection begins immediately.** Zeek and Suricata start analyzing traffic on the bridge interface.
2. **Give it 5--10 minutes** for initial data to populate the dashboard. OpenSearch needs time to index the first logs.
3. **The dashboard auto-refreshes** every 30 seconds by default.

If you need to reconfigure later, most settings are available in the **Settings** page (`/settings`) or by editing the `.env` file directly and restarting services.

---

## Skipping the Wizard

If you prefer to configure everything via the command line and `.env` file (see [Installation](installation.md)), you can skip the wizard by completing the full installation process with `install.sh` before accessing the web UI. The wizard only appears when the system detects that initial setup has not been completed.
