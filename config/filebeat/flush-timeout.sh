#!/bin/bash
# NET-243: Filebeat 8.13+ holds a partial batch until 1,600 events are queued or
# queue.mem.flush.timeout (10 s by default) passes. A home network never fills one, so every
# Suricata alert waited up to 10 s before Logstash saw it (G11, 2,000 alerts: median 5.2 s,
# p90 11.3 s, max 14.4 s). 2 s keeps batching (each bulk request fsyncs the index translog)
# and leaves alerts well inside the 10 s goal.
# The image's own config is patched at every start, so a Malcolm update keeps its own inputs.
# A failed patch is logged and Filebeat starts with its defaults: slower alerts, never no data.
CONFIG=/usr/share/filebeat-logs/filebeat-logs.yml

if yq -i '.queue.mem.flush.timeout = "2s"' "$CONFIG"; then
	echo "nettap: Filebeat queue flush timeout set to 2s (NET-243)" >&2
else
	echo "nettap: couldn't set Filebeat's queue flush timeout in $CONFIG; alerts can take up to 10 s longer to index (NET-243)" >&2
fi
exec "$@"
