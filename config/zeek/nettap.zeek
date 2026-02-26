# NetTap Zeek configuration overrides

# Capture interface
redef Pcap::snaplen = 65535;

# Log rotation — batch writes every 30s to reduce SSD wear
redef Log::default_rotation_interval = 30sec;

# Enable JSON output for OpenSearch ingestion
@load policy/tuning/json-logs

# Load standard protocol analyzers
@load base/protocols/conn
@load base/protocols/dns
@load base/protocols/http
@load base/protocols/ssl
@load base/protocols/dhcp
@load base/protocols/smtp
@load base/files/extract-all-files

# File analysis
@load frameworks/files/hash-all-files
