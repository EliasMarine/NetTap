# Packet analysis fixtures (NET-188)

Synthetic captures with documentation addresses only (192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24, locally administered MACs). The fragment capture's destination MAC uses
the 00:50:56 prefix on purpose: its first bytes equal the reassembled TCP source port.

- `synthetic.pcap`: from `make_pcap.py`. SYN and SYN-ACK at the same microsecond, an ACK,
  a DNS reply with two answers, a packet cut to 96 of 1,514 bytes, and an HTTP request
  with a tab in its URI.
- `frag.pcap`: from `make_frag.py`. Two IPv4 fragments of one TCP segment.
- `*.out`: what NetTap's real job scripts (`services/packet_search.py`) printed on the G11
  (TShark 4.0.17, 2026-11-07) through the real supervisor:
  - `search_all`: SEARCH_JOB, filter `frame`, whole file.
  - `search_limit`: SEARCH_JOB, filter `tcp`, 3 rows.
  - `detail_1`, `detail_5`: DETAIL_JOB for frames 1 and 5; `detail_frag`: frame 2 of `frag.pcap`.
  - `download_125`: DOWNLOAD_JOB for frames 1, 2 and 5.
  - `fields_tls`: FIELDS_JOB for `tls.handshake.ext`, 21 rows (one past the list of 20).
