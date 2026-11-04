# StatStrip

Inline rows of figures separated by hairlines: the stats strip and the capture pipeline.

**Use**
- `.stats`: four figures across a hero card at the top of a list screen (Sessions, Data, Destinations, Devices). Key in `type-meta` 600 `text-3`, value in `type-stat`. Two per row on phones.
- `.pipe`: the capture pipeline on Home, one item per stage (Capture, Zeek, Suricata, OpenSearch, Storage), each with an `ok` check and one line of status. Five across, three on tablets, two on phones.
- `.ident-meta` uses the same pattern for device facts (IP, MAC, Vendor, Hostname, First seen, Last seen), with machine values in mono.

**Consumer provides**: label and value pairs; for the pipeline, a healthy or failing state per stage.
