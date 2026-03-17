"""
NetTap PCAP Integrity Checker

Writes and verifies checksums for PCAP files to detect data corruption.
Uses xxh3 (xxhash) when available for speed, falls back to sha256.

Usage:
    from storage.pcap_integrity import PcapIntegrityChecker

    checker = PcapIntegrityChecker()
    checker.write_checksum("/data/pcap/capture.pcap")
    ok = checker.verify_pcap_integrity("/data/pcap/capture.pcap")
"""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger("nettap.storage.pcap_integrity")

# Try to import xxhash for faster checksums
try:
    import xxhash

    _HAS_XXHASH = True
except ImportError:
    _HAS_XXHASH = False

# Read files in 1MB chunks for memory efficiency
_CHUNK_SIZE = 1024 * 1024


class PcapIntegrityChecker:
    """Write and verify checksums for PCAP files.

    When xxhash is available, uses xxh3_128 for speed (up to 10x faster
    than SHA-256 on modern CPUs). Falls back to SHA-256 when xxhash is
    not installed.

    Checksum files are stored alongside the PCAP with a ``.xxh3`` or
    ``.sha256`` extension.
    """

    def __init__(self) -> None:
        self.algorithm = "xxh3" if _HAS_XXHASH else "sha256"
        logger.info("PCAP integrity checker using algorithm: %s", self.algorithm)

    @property
    def checksum_extension(self) -> str:
        """Return the file extension used for checksum files."""
        return f".{self.algorithm}"

    def _compute_checksum(self, pcap_path: str | Path) -> str:
        """Compute the checksum of a PCAP file.

        Args:
            pcap_path: Path to the PCAP file.

        Returns:
            Hex digest string of the checksum.

        Raises:
            FileNotFoundError: If the PCAP file does not exist.
            OSError: If the file cannot be read.
        """
        pcap_path = Path(pcap_path)

        if _HAS_XXHASH:
            hasher = xxhash.xxh3_128()
        else:
            hasher = hashlib.sha256()

        with open(pcap_path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)

        return hasher.hexdigest()

    def checksum_path_for(self, pcap_path: str | Path) -> Path:
        """Return the expected checksum file path for a given PCAP.

        Args:
            pcap_path: Path to the PCAP file.

        Returns:
            Path object for the checksum sidecar file.
        """
        pcap_path = Path(pcap_path)
        return pcap_path.parent / f"{pcap_path.name}{self.checksum_extension}"

    def write_checksum(self, pcap_path: str | Path) -> Path:
        """Compute and write a checksum file alongside the PCAP.

        The checksum file contains the hex digest followed by two spaces
        and the filename (matching the format of ``sha256sum`` / ``xxh128sum``).

        Args:
            pcap_path: Path to the PCAP file.

        Returns:
            Path to the written checksum file.

        Raises:
            FileNotFoundError: If the PCAP file does not exist.
            OSError: If the checksum file cannot be written.
        """
        pcap_path = Path(pcap_path)
        digest = self._compute_checksum(pcap_path)
        cksum_path = self.checksum_path_for(pcap_path)

        cksum_path.write_text(
            f"{digest}  {pcap_path.name}\n", encoding="utf-8"
        )

        logger.info(
            "Wrote %s checksum for %s: %s",
            self.algorithm,
            pcap_path.name,
            digest,
        )
        return cksum_path

    def verify_pcap_integrity(self, pcap_path: str | Path) -> bool:
        """Verify a PCAP file against its stored checksum.

        Args:
            pcap_path: Path to the PCAP file.

        Returns:
            True if the checksum matches, False if it does not match
            or if the checksum file is missing / unreadable.
        """
        pcap_path = Path(pcap_path)

        if not pcap_path.exists():
            logger.error("PCAP file not found: %s", pcap_path)
            return False

        cksum_path = self.checksum_path_for(pcap_path)

        if not cksum_path.exists():
            logger.warning(
                "No checksum file found for %s (expected %s)",
                pcap_path.name,
                cksum_path.name,
            )
            return False

        try:
            stored_line = cksum_path.read_text(encoding="utf-8").strip()
            # Format: "<hex_digest>  <filename>"
            stored_digest = stored_line.split("  ")[0].strip()
        except (OSError, IndexError) as exc:
            logger.error(
                "Cannot read checksum file %s: %s", cksum_path, exc
            )
            return False

        current_digest = self._compute_checksum(pcap_path)

        if current_digest == stored_digest:
            logger.debug(
                "PCAP integrity OK: %s (%s)", pcap_path.name, self.algorithm
            )
            return True
        else:
            logger.error(
                "PCAP INTEGRITY FAILURE: %s — expected %s, got %s",
                pcap_path.name,
                stored_digest,
                current_digest,
            )
            return False
