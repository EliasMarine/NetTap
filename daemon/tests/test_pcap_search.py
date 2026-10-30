"""
Tests for the PcapSearchService.

Covers: BPF filter validation, file listing, preview extraction,
search, and download.
"""


import pytest

from services.pcap_search import PcapSearchService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pcap_dir(tmp_path):
    """Create a temp PCAP directory with sample files."""
    pcap1 = tmp_path / "capture_001.pcap"
    pcap1.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 100)  # pcap magic + data

    pcap2 = tmp_path / "capture_002.pcapng"
    pcap2.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 200)  # pcapng magic + data

    # Non-pcap file (should be ignored)
    txt = tmp_path / "readme.txt"
    txt.write_text("not a pcap")

    # Subdirectory with a pcap
    subdir = tmp_path / "2026-03"
    subdir.mkdir()
    pcap3 = subdir / "sub_capture.pcap"
    pcap3.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 50)

    return tmp_path


@pytest.fixture
def service(pcap_dir):
    """Return a PcapSearchService with temp PCAP directory."""
    return PcapSearchService(pcap_dir=str(pcap_dir))


# ---------------------------------------------------------------------------
# BPF filter validation
# ---------------------------------------------------------------------------


class TestBpfValidation:
    def test_valid_filter(self, service):
        """Standard BPF filters should be valid."""
        assert service.validate_bpf_filter("tcp port 80")[0] is True
        assert service.validate_bpf_filter("host 192.168.1.1")[0] is True
        assert service.validate_bpf_filter("udp and port 53")[0] is True

    def test_empty_filter(self, service):
        """Empty filter should be invalid."""
        valid, err = service.validate_bpf_filter("")
        assert valid is False
        assert "Empty" in err

    def test_none_filter(self, service):
        """None filter should be invalid."""
        valid, err = service.validate_bpf_filter(None)
        assert valid is False

    def test_forbidden_characters(self, service):
        """Filters with shell injection chars should be rejected."""
        valid, err = service.validate_bpf_filter("tcp; rm -rf /")
        assert valid is False
        assert "forbidden" in err.lower()

        valid, err = service.validate_bpf_filter("host 1.1.1.1 | grep")
        assert valid is False

        valid, err = service.validate_bpf_filter("tcp `whoami`")
        assert valid is False

    def test_too_long_filter(self, service):
        """Excessively long filters should be rejected."""
        valid, err = service.validate_bpf_filter("a" * 1001)
        assert valid is False
        assert "too long" in err.lower()


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------


class TestGetAvailablePcaps:
    def test_lists_pcap_files(self, service, pcap_dir):
        """Should find all PCAP files recursively."""
        files = service.get_available_pcaps()
        assert len(files) == 3

        names = {f["name"] for f in files}
        assert "capture_001.pcap" in names
        assert "capture_002.pcapng" in names
        assert "sub_capture.pcap" in names

    def test_excludes_non_pcap(self, service):
        """Should not include non-PCAP files."""
        files = service.get_available_pcaps()
        names = {f["name"] for f in files}
        assert "readme.txt" not in names

    def test_includes_metadata(self, service):
        """Each file entry should have required metadata."""
        files = service.get_available_pcaps()
        for f in files:
            assert "file" in f
            assert "name" in f
            assert "size_bytes" in f
            assert "modified" in f
            assert f["size_bytes"] > 0

    def test_nonexistent_directory(self, tmp_path):
        """Should return empty list for nonexistent directory."""
        svc = PcapSearchService(pcap_dir=str(tmp_path / "nonexistent"))
        assert svc.get_available_pcaps() == []

    def test_sorted_by_modification_time(self, service):
        """Files should be sorted by modification time, newest first."""
        files = service.get_available_pcaps()
        times = [f["modified"] for f in files]
        assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Search (mocked tshark)
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_invalid_filter_raises(self, service):
        """Should raise ValueError for invalid BPF filter."""
        with pytest.raises(ValueError, match="Invalid BPF filter"):
            await service.search("")

    @pytest.mark.asyncio
    async def test_no_pcaps_returns_empty(self, tmp_path):
        """Should return empty when no PCAP files exist."""
        svc = PcapSearchService(pcap_dir=str(tmp_path / "empty"))
        result = await svc.search("tcp port 80")
        assert result == []


# ---------------------------------------------------------------------------
# Preview (mocked tshark)
# ---------------------------------------------------------------------------


class TestPreview:
    @pytest.mark.asyncio
    async def test_file_outside_pcap_dir_rejected(self, service):
        """Should reject files outside the PCAP directory."""
        with pytest.raises(ValueError, match="within the configured"):
            await service.preview("/etc/passwd")

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, service, pcap_dir):
        """Should raise FileNotFoundError for missing files."""
        fake_path = str(pcap_dir / "nonexistent.pcap")
        with pytest.raises(FileNotFoundError):
            await service.preview(fake_path)

    @pytest.mark.asyncio
    async def test_invalid_bpf_filter_rejected(self, service, pcap_dir):
        """Should reject invalid BPF filter in preview."""
        pcap_file = str(pcap_dir / "capture_001.pcap")
        with pytest.raises(ValueError, match="Invalid BPF filter"):
            await service.preview(pcap_file, bpf_filter="tcp; evil")


# ---------------------------------------------------------------------------
# Download (mocked tshark + mergecap)
# ---------------------------------------------------------------------------


class TestDownload:
    @pytest.mark.asyncio
    async def test_invalid_filter_raises(self, service):
        """Should raise ValueError for invalid BPF filter."""
        with pytest.raises(ValueError, match="Invalid BPF filter"):
            await service.download_filtered("")

    @pytest.mark.asyncio
    async def test_no_pcaps_returns_none(self, tmp_path):
        """Should return None when no PCAP files exist."""
        svc = PcapSearchService(pcap_dir=str(tmp_path / "empty"))
        result = await svc.download_filtered("tcp port 80")
        assert result is None
