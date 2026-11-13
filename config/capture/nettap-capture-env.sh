# ==========================================================================
# NetTap capture env loader
# Mounted at /usr/local/bin/nettap-capture-env.sh in zeek-live, suricata-live,
# arkime-live and pcap-capture; sourced first by each entrypoint wrapper.
# ==========================================================================
#
# The daemon writes /etc/nettap/capture.env when the capture mode changes
# (DHCP gateway, mirror, bridge). This loader exports PCAP_IFACE and
# PCAP_FILTER from it (plus CAPTURE_FILTER = PCAP_FILTER, which Suricata and
# Zeek read), so the containers pick up the new settings on restart. It also
# exports PCAP_ROTATE_MEGABYTES (netsniff's file size, set on the Settings page).
#
# The file is parsed line by line instead of sourced: sourcing would run any
# shell code in it as root inside every capture container. Only the
# whitelisted keys are read, and values that are not a valid interface name
# or a plain BPF expression are ignored (the compose env stays in effect).
#
# No file means no change. Always ends with status 0 (chained with &&).
#
# Then it waits until every PCAP_IFACE interface exists (NET-211 #9): before
# the setup wizard the compose default br0 doesn't exist yet, and in bridge
# mode br0 appears only at Go Live. Capture programs started on a missing
# interface give up (supervisord FATAL) and nothing restarts them.
#
# Override the paths with NETTAP_CAPTURE_ENV, NETTAP_SURICATA_ENV and
# NETTAP_SYS_CLASS_NET (used by tests).
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
            PCAP_ROTATE_MEGABYTES)
                # netsniff rotation size from the settings page: 10-10000 MiB
                case "$_nettap_val" in
                    '' | *[!0-9]* | ??????*)
                        echo "nettap-capture-env: ignoring invalid PCAP_ROTATE_MEGABYTES in $_nettap_env_file" >&2
                        ;;
                    *)
                        if [ "$_nettap_val" -ge 10 ] && [ "$_nettap_val" -le 10000 ]; then
                            export PCAP_ROTATE_MEGABYTES="$_nettap_val"
                        else
                            echo "nettap-capture-env: ignoring out-of-range PCAP_ROTATE_MEGABYTES in $_nettap_env_file" >&2
                        fi
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

# NET-211 #9: wait for the capture interfaces (comma-separated, as Malcolm allows). The trap makes
# docker stop/restart end the wait at once: the wrapper shell is PID 1, which ignores an untrapped TERM.
_nettap_sys="${NETTAP_SYS_CLASS_NET:-/sys/class/net}"
if [ -d "$_nettap_sys" ] && [ -n "${PCAP_IFACE:-}" ]; then
    trap 'exit 143' TERM INT
    _nettap_ifs="$IFS"
    IFS=,
    for _nettap_val in $PCAP_IFACE; do
        IFS="$_nettap_ifs"
        if [ ! -e "$_nettap_sys/$_nettap_val" ]; then
            echo "nettap-capture-env: waiting for capture interface $_nettap_val (set by the setup wizard, or Go Live for a bridge)" >&2
            while [ ! -e "$_nettap_sys/$_nettap_val" ]; do
                sleep 5 &
                wait $!
            done
        fi
    done
    IFS="$_nettap_ifs"
    trap - TERM INT
fi

# ET Pro (NET-191): the daemon writes SURICATA_ETPRO_CODE to /etc/nettap/suricata.env (root, 600) from
# Settings → Suricata rules. A valid code turns et/open into et/pro in SURICATA_UPDATE_ENABLE_SOURCES (set
# only in suricata-live). Same whitelist parsing as above; the code is never echoed.
_nettap_suricata_env="${NETTAP_SURICATA_ENV:-/etc/nettap/suricata.env}"
if [ -n "${SURICATA_UPDATE_ENABLE_SOURCES:-}" ] && [ -f "$_nettap_suricata_env" ] && [ -r "$_nettap_suricata_env" ]; then
    _nettap_code=""
    while IFS= read -r _nettap_line || [ -n "$_nettap_line" ]; do
        case "$_nettap_line" in
            SURICATA_ETPRO_CODE=*) _nettap_code="${_nettap_line#*=}" ;;
        esac
    done < "$_nettap_suricata_env"
    # Same rule as the daemon: ^[A-Za-z0-9]{16,64}$
    case "$_nettap_code" in
        '') ;;
        *[!A-Za-z0-9]*)
            echo "nettap-capture-env: ignoring an invalid SURICATA_ETPRO_CODE in $_nettap_suricata_env" >&2
            ;;
        *)
            if [ "${#_nettap_code}" -ge 16 ] && [ "${#_nettap_code}" -le 64 ]; then
                _nettap_sources=""
                _nettap_ifs="$IFS"
                IFS=,
                for _nettap_val in $SURICATA_UPDATE_ENABLE_SOURCES; do
                    [ "$_nettap_val" = "et/open" ] && _nettap_val="et/pro|secret-code=$_nettap_code"
                    _nettap_sources="${_nettap_sources:+$_nettap_sources,}$_nettap_val"
                done
                IFS="$_nettap_ifs"
                export SURICATA_UPDATE_ENABLE_SOURCES="$_nettap_sources"
            else
                echo "nettap-capture-env: ignoring an invalid SURICATA_ETPRO_CODE in $_nettap_suricata_env" >&2
            fi
            ;;
    esac
fi

unset _nettap_env_file _nettap_line _nettap_val _nettap_suricata_env _nettap_code _nettap_sources _nettap_ifs _nettap_sys
true
