<!--
  StartKpis.svelte: the first visit's KPI row (NET-188, Start.dc): how far back the saved
  packets go, the capture files, whether capture is on, and the packet reader. A figure whose
  request failed shows "—" and says so, never 0.
-->
<script lang="ts">
	import type { CapturesResponse } from '$lib/api/packets';
	import { captureState, type CaptureStatus } from '$lib/api/capture';
	import type { TSharkStatus } from '$lib/api/tshark';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import { formatBytes } from '$lib/api/logs';
	import { epochNs } from '$lib/utils/packet-query';
	import { clockTime, dayWords, plural, readerVersion, spanWords } from './packets-view';

	interface Props {
		captures: CapturesResponse | null;
		capture: CaptureStatus | null;
		/** Undefined while loading; null when the request failed. */
		reader: TSharkStatus | null | undefined;
		failed: { captures: boolean; capture: boolean; reader: boolean };
		nowMs: number;
	}

	let { captures, capture, reader, failed, nowMs }: Props = $props();

	const MIB = 1024 ** 2;

	const oldest = $derived(captures?.oldest_packet ?? null);
	const kept = $derived.by(() => {
		const ns = epochNs(oldest ?? '');
		return ns === null ? null : spanWords(nowMs / 1000 - Number(ns / 1_000_000_000n));
	});
	const keptSub = $derived(
		failed.captures && !captures
			? "Couldn't load the capture files."
			: captures?.unindexed
				? `Oldest packet in the indexed files · ${plural(captures.unindexed, 'file')} still being indexed`
				: captures && !oldest
					? 'No capture file has been indexed yet'
					: 'The oldest files go first when space runs low',
	);

	const newestRecent = $derived(captures?.files.find((f) => f.recent) ?? null);
	const capState = $derived(captureState(capture));
	const captureValue = $derived(failed.capture && !capture ? '—' : !capture ? '…' : capState === 'active' ? 'On' : capState === 'stopped' ? 'Off' : 'Unknown');
	const rotation = $derived(
		capture ? `A new file every ${formatBytes(capture.maxFileSizeMB * MIB)}${capture.rotateMinutes ? ` or ${capture.rotateMinutes} minutes` : ''}` : undefined,
	);

	const version = $derived(reader ? readerVersion(reader.version) : null);
	const ready = $derived(!!reader?.available && !!reader?.container_running);
	const most = $derived(captures ? Math.max(...captures.limits.rows) : null);
</script>

<KpiCard
	class="c-3"
	label="Packets kept"
	icon="changelog"
	value={captures ? (kept ?? '—') : failed.captures ? '—' : '…'}
	note={oldest ? `back to ${clockTime(oldest, false)} ${dayWords(oldest)}` : undefined}
	sub={keptSub}
/>
<KpiCard
	class="c-3"
	label="Capture files"
	icon="pcap"
	value={captures ? captures.count.toLocaleString('en-GB') : failed.captures ? '—' : '…'}
	note={captures ? `${formatBytes(captures.bytes_total)} on disk${captures.failed ? ` · ${captures.failed.toLocaleString('en-GB')} can't be read` : ''}` : undefined}
	sub={failed.captures && !captures ? "Couldn't load the capture files." : rotation}
/>
<KpiCard
	class="c-3"
	label="Capture"
	icon="live"
	value={captureValue}
	note={capState === 'active' && newestRecent ? `Writing now${newestRecent.first ? ` · file started ${clockTime(newestRecent.first, false)}` : ''}` : undefined}
	sub={failed.capture && !capture ? "Couldn't read the capture state." : 'Turn it on or off on PCAP Search'}
/>
<KpiCard
	class="c-3"
	label="Packet reader"
	icon="search"
	value={reader === undefined ? '…' : reader === null ? '—' : ready ? 'Ready' : 'Not running'}
	note={version ?? undefined}
	sub={reader === null ? "Couldn't read the packet reader's status." : most ? `Reads up to ${most.toLocaleString('en-GB')} packets per search` : undefined}
/>
