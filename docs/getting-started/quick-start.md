# Quick start

This page has moved into the [setup guide](setup-guide.md), which covers the same ground in order and stays in step with the installer.

The short version, if you've done this before:

1. Choose a mode: [DHCP gateway, mirror or inline bridge](setup-guide.md#2-choose-how-nettap-connects).
2. Install Ubuntu Server 24.04 or 22.04 with the username `nettap` ([section 3](setup-guide.md#3-install-ubuntu-server)).
3. `git clone https://github.com/EliasMarine/NetTap.git` into your home folder, then from `~/NetTap` run `sudo scripts/install/install.sh`. Add `--skip-bridge` for mirror and DHCP gateway modes. Inline bridge mode with a wired management port needs one extra step first ([section 5](setup-guide.md#5-run-the-installer)).
4. Open `https://nettap.local` and finish the wizard ([section 6](setup-guide.md#6-run-the-setup-wizard)), then [go live](setup-guide.md#7-go-live).
