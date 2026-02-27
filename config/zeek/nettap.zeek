# NetTap Zeek configuration overrides

# Capture interface
redef Pcap::snaplen = 65535;

# Log rotation — batch writes every 30s to reduce SSD wear
redef Log::default_rotation_interval = 30sec;

# Enable JSON output for OpenSearch ingestion
@load policy/tuning/json-logs

# ---------------------------------------------------------------------------
# Compression settings
# ---------------------------------------------------------------------------
# Zeek natively supports gzip compression for log output, but NetTap uses
# zstd for superior compression ratios (~8:1 for JSON logs vs ~4:1 for gzip)
# and lower CPU overhead.
#
# Since Zeek does not have built-in zstd support, we disable gzip here and
# let the log rotation pipeline (Malcolm's filebeat + logstash) handle zstd
# compression of rotated logs before they are shipped to OpenSearch.
#
# The rotation pipeline flow:
#   1. Zeek writes uncompressed JSON logs to disk
#   2. Logs rotate every 30s (see rotation_interval above)
#   3. filebeat picks up rotated logs and forwards to logstash
#   4. logstash pipeline applies zstd compression for archival/shipping
#   5. OpenSearch indexes the structured data
#
# This approach trades a small amount of temporary disk usage for better
# compression ratios and reduced CPU load on the capture path.
# ---------------------------------------------------------------------------
redef LogAscii::gzip_level = 0;  # Disable gzip (using zstd in pipeline instead)
redef LogAscii::enable_utf_8 = T;

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
