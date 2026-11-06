"""Raw ssl/x509 documents behind the calls a certificate pass makes (NET-154).

Answers create_pit / delete_pit, a session page sorted by _shard_doc and paged with
search_after (also the after-expiry recount's chain and time filters), and the x509 details
aggregation. `tamper(kind, reply)` can break a reply.
"""

from datetime import datetime, timezone

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
CHAIN = "zeek.ssl.cert_chain_fps"
FROM, TO = "2026-11-05T00:00:00Z", "2026-11-05T12:00:00Z"
PUBLIC = "93.184.216.34"


def when(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def ssl(
    chain,
    sni="a.com",
    server=PUBLIC,
    port=443,
    client="192.168.1.10",
    status="ok",
    t="2026-11-05T10:00:00.000Z",
):
    return {
        "chain": chain,
        "sni": sni,
        "server": server,
        "port": port,
        "client": client,
        "status": status,
        "t": t,
    }


def x509(
    fp,
    t="2026-11-05T09:00:00.000Z",
    org="Let's Encrypt",
    not_after="2027-01-01T00:00:00",
    **extra,
):
    return {
        "fp": fp,
        "t": t,
        "x509": {
            "certificate_subject": {"CN": [f"{fp}.example"]},
            "certificate_issuer": {"CN": ["R3"], "O": [org]},
            "certificate_subject_full": f"CN={fp}.example",
            "certificate_issuer_full": f"CN=R3,O={org}",
            "certificate_not_valid_after": not_after,
            **extra,
        },
    }


class RawOpenSearch:
    """Raw documents in, OpenSearch-shaped replies out, with optional reply tampering."""

    def __init__(self, sessions, certs, tamper=None):
        self.sessions = sessions
        self.certs = certs
        self.tamper = tamper or (lambda kind, reply: reply)
        self.open_pits: set[str] = set()
        self.closed: list[str] = []
        self.pit_params: dict = {}
        self.bodies: list[dict] = []
        self.timeouts: list[float] = []

    def create_pit(self, index, **params):
        self.pit_params = params
        pit = f"pit-{len(self.open_pits) + len(self.closed)}"
        self.open_pits.add(pit)
        return self.tamper("pit", {"pit_id": pit, "_shards": {"total": 1, "failed": 0}})

    def delete_pit(self, body):
        for pit in body["pit_id"]:
            self.open_pits.discard(pit)
            self.closed.append(pit)

    def search(self, body, request_timeout=None):
        assert body["pit"]["id"] in self.open_pits, (
            "every search runs on the open snapshot"
        )
        self.bodies.append(body)
        self.timeouts.append(request_timeout)
        if "aggs" in body:
            return self.tamper("details", self._details(body))
        return self.tamper("sessions", self._sessions(body))

    def _sessions(self, body):
        excluded = {
            ip
            for c in body["query"]["bool"].get("must_not", [])
            for ip in c["terms"]["source.ip"]
        }
        filters = body["query"]["bool"]["filter"]
        # The after-expiry recount adds: the chain holds fp anywhere, and time after not_after
        in_chain = next(
            (c["term"][CHAIN] for c in filters if CHAIN in c.get("term", {})), None
        )
        after = next(
            (
                when(c["range"]["@timestamp"]["gt"])
                for c in filters
                if "gt" in c.get("range", {}).get("@timestamp", {})
            ),
            None,
        )
        docs = [
            (i, d)
            for i, d in enumerate(self.sessions)
            if d["chain"]
            and d["client"] not in excluded
            and (in_chain is None or in_chain in d["chain"])
            and (after is None or when(d["t"]) > after)
        ]
        after = body.get("search_after", [-1])[0]
        page = [(i, d) for i, d in docs if i > after][: body["size"]]
        hits = [
            {
                "_source": {"zeek": {"ssl": {"cert_chain_fps": d["chain"]}}},
                "fields": {
                    k: [v]
                    for k, v in (
                        ("zeek.ssl.server_name", d["sni"]),
                        ("destination.ip", d["server"]),
                        ("destination.port", d["port"]),
                        ("source.ip", d["client"]),
                        ("zeek.ssl.validation_status", d["status"]),
                        ("zeek.ssl.ssl_version", "TLSv12"),
                        ("@timestamp", d["t"]),
                    )
                    if v is not None
                },
                "sort": [i],
            }
            for i, d in page
        ]
        return {
            "pit_id": body["pit"]["id"],
            "timed_out": False,
            "_shards": {"failed": 0},
            "hits": {"hits": hits},
        }

    def _details(self, body):
        wanted = next(
            c["terms"]["zeek.x509.fingerprint"]
            for c in body["query"]["bool"]["filter"]
            if "terms" in c
        )
        buckets = []
        for fp in sorted(set(wanted)):
            records = sorted(
                (c for c in self.certs if c["fp"] == fp),
                key=lambda c: c["t"],
                reverse=True,
            )
            if records:
                hit = {"_source": {"zeek": {"x509": records[0]["x509"]}}}
                buckets.append(
                    {
                        "key": fp,
                        "doc_count": len(records),
                        "latest": {"hits": {"hits": [hit]}},
                    }
                )
        return {
            "timed_out": False,
            "_shards": {"failed": 0},
            "aggregations": {"fps": {"sum_other_doc_count": 0, "buckets": buckets}},
        }
