# ==========================================================================
# NetTap capture env loader
# Mounted at /usr/local/bin/nettap-capture-env.sh in zeek-live, suricata-live,
# arkime-live and pcap-capture; sourced first by each entrypoint wrapper.
# ==========================================================================
#
# The daemon writes /etc/nettap/capture.env when the capture mode changes
# (DHCP gateway, mirror, bridge). This loader exports PCAP_IFACE and
# PCAP_FILTER from it (plus CAPTURE_FILTER = PCAP_FILTER, which Suricata and
# Zeek read), so the containers pick up the new settings on restart.
#
# The file is parsed line by line instead of sourced: sourcing would run any
# shell code in it as root inside every capture container. Only the two
# whitelisted keys are read, and values that are not a valid interface name
# or a plain BPF expression are ignored (the compose env stays in effect).
#
# No file means no change. Always ends with status 0 (chained with &&).
#
# Override the path with NETTAP_CAPTURE_ENV (used by tests).
# POSIX sh compatible.

_nettap_env_file="${NETTAP_CAPTURE_ENV:-/etc/nettap/capture.env}"

if [ -f "$_nettap_env_file" ] && [ -r "$_nettap_env_file" ]; then
    while IFS= read -r _nettap_line || [ -n "$_nettap_line" ]; do
        case "$_nettap_line" in
            *=*) ;;
            *) continue ;;
        esac
        _nettap_val="${_nettap_line#*=}"
        case "${_nettap_line%%=*}" in
            PCAP_IFACE)
                # Same rule as the daemon: ^[A-Za-z0-9._-]{1,15}$
                # (16 '?' = 16 or more characters, too long).
                case "$_nettap_val" in
                    '' | *[!A-Za-z0-9._-]* | ????????????????*)
                        echo "nettap-capture-env: ignoring invalid PCAP_IFACE in $_nettap_env_file" >&2
                        ;;
                    *)
                        export PCAP_IFACE="$_nettap_val"
                        ;;
                esac
                ;;
            PCAP_FILTER)
                # Empty is valid (no filter). The daemon only writes
                # "net <subnet> or udp port 67 or udp port 68".
                case "$_nettap_val" in
                    *[!A-Za-z0-9\ ./:]*)
                        echo "nettap-capture-env: ignoring invalid PCAP_FILTER in $_nettap_env_file" >&2
                        ;;
                    *)
                        export PCAP_FILTER="$_nettap_val"
                        export CAPTURE_FILTER="$_nettap_val"
                        ;;
                esac
                ;;
        esac
    done < "$_nettap_env_file"
fi

unset _nettap_env_file _nettap_line _nettap_val
true
