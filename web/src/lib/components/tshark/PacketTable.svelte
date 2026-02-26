<script lang="ts">
	/**
	 * PacketTable — scrollable table of captured packets.
	 *
	 * Props:
	 *   packets       – array of packet objects from TShark analysis
	 *   loading       – whether data is currently being fetched
	 *   onselect      – callback when a row is clicked
	 *   selectedIndex – index of the currently selected row (-1 for none)
	 */

	interface Props {
		packets: any[];
		loading?: boolean;
		onselect: (packet: any) => void;
		selectedIndex?: number;
	}

	let { packets, loading = false, onselect, selectedIndex = -1 }: Props = $props();

	// ---- Helpers to extract common columns from a TShark packet object ----
	function col(pkt: any, key: string): string {
		// TShark JSON output typically nests under _source.layers
		// We try a few common paths and fall back to direct access.
		if (pkt?._source?.layers) {
			const layers = pkt._source.layers;

			switch (key) {
				case 'no':
					return layers?.frame?.['frame.number'] ?? '';
				case 'time':
					return layers?.frame?.['frame.time_relative'] ?? layers?.frame?.['frame.time_epoch'] ?? '';
				case 'src':
					return layers?.ip?.['ip.src'] ?? layers?.ipv6?.['ipv6.src'] ?? layers?.eth?.['eth.src'] ?? '';
				case 'dst':
					return layers?.ip?.['ip.dst'] ?? layers?.ipv6?.['ipv6.dst'] ?? layers?.eth?.['eth.dst'] ?? '';
				case 'protocol':
					return layers?.frame?.['frame.protocols']?.split(':').pop() ?? '';
				case 'length':
					return layers?.frame?.['frame.len'] ?? '';
				case 'info':
					return layers?.['_ws.col.Info'] ?? layers?.frame?.['frame.protocols'] ?? '';
			}
		}

		// Flat key access as a fallback (simple JSON output)
		switch (key) {
			case 'no':
				return pkt?.['frame.number'] ?? pkt?.no ?? String(packets.indexOf(pkt) + 1);
			case 'time':
				return pkt?.['frame.time_relative'] ?? pkt?.time ?? '';
			case 'src':
				return pkt?.['ip.src'] ?? pkt?.src ?? '';
			case 'dst':
				return pkt?.['ip.dst'] ?? pkt?.dst ?? '';
			case 'protocol':
				return pkt?.protocol ?? pkt?.['frame.protocols']?.split(':').pop() ?? '';
			case 'length':
				return pkt?.['frame.len'] ?? pkt?.length ?? '';
			case 'info':
				return pkt?.info ?? pkt?.['_ws.col.Info'] ?? '';
		}

		return '';
	}

	function handleRowClick(pkt: any) {
		onselect(pkt);
	}

	function handleRowKeydown(e: KeyboardEvent, pkt: any) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			onselect(pkt);
		}
	}
</script>

<div class="packet-table-wrapper">
	{#if loading}
		<div class="table-overlay">
			<div class="spinner"></div>
			<span class="loading-text">Analyzing packets...</span>
		</div>
	{/if}

	<div class="table-scroll">
		<table class="packet-table">
			<thead>
				<tr>
					<th class="col-no">No.</th>
					<th class="col-time">Time</th>
					<th class="col-src">Source</th>
					<th class="col-dst">Destination</th>
					<th class="col-proto">Protocol</th>
					<th class="col-len">Length</th>
					<th class="col-info">Info</th>
				</tr>
			</thead>
			<tbody>
				{#if packets.length === 0 && !loading}
					<tr class="empty-row">
						<td colspan="7">
							<div class="empty-state">
								<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
									<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
									<polyline points="3.27 6.96 12 12.01 20.73 6.96" />
									<line x1="12" y1="22.08" x2="12" y2="12" />
								</svg>
								<span>No packets to display. Select a PCAP file and run analysis.</span>
							</div>
						</td>
					</tr>
				{:else}
					{#each packets as pkt, idx}
						<tr
							class="packet-row"
							class:selected={idx === selectedIndex}
							class:even={idx % 2 === 0}
							onclick={() => handleRowClick(pkt)}
							onkeydown={(e) => handleRowKeydown(e, pkt)}
							tabindex="0"
							aria-selected={idx === selectedIndex}
						>
							<td class="col-no mono">{col(pkt, 'no')}</td>
							<td class="col-time mono">{col(pkt, 'time')}</td>
							<td class="col-src mono">{col(pkt, 'src')}</td>
							<td class="col-dst mono">{col(pkt, 'dst')}</td>
							<td class="col-proto">
								<span class="badge badge-accent">{col(pkt, 'protocol')}</span>
							</td>
							<td class="col-len mono">{col(pkt, 'length')}</td>
							<td class="col-info">{col(pkt, 'info')}</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>
</div>

<style>
	.packet-table-wrapper {
		position: relative;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background-color: var(--bg-secondary);
		overflow: hidden;
	}

	.table-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-sm);
		background-color: rgba(13, 17, 23, 0.85);
		z-index: 10;
	}

	.spinner {
		width: 28px;
		height: 28px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.loading-text {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.table-scroll {
		overflow: auto;
		max-height: 480px;
	}

	.packet-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
		white-space: nowrap;
	}

	.packet-table thead {
		position: sticky;
		top: 0;
		z-index: 5;
	}

	.packet-table th {
		padding: var(--space-sm) var(--space-md);
		text-align: left;
		font-weight: 600;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-secondary);
		background-color: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-default);
		user-select: none;
	}

	.packet-table td {
		padding: var(--space-xs) var(--space-md);
		color: var(--text-primary);
		border-bottom: 1px solid var(--border-muted);
		max-width: 360px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	.packet-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.packet-row.even {
		background-color: rgba(22, 27, 34, 0.5);
	}

	.packet-row:hover {
		background-color: var(--accent-muted);
	}

	.packet-row.selected {
		background-color: var(--accent-muted);
		box-shadow: inset 3px 0 0 var(--accent);
	}

	.col-no { width: 60px; }
	.col-time { width: 100px; }
	.col-src { width: 150px; }
	.col-dst { width: 150px; }
	.col-proto { width: 90px; }
	.col-len { width: 70px; }
	.col-info { width: auto; }

	.empty-row td {
		border-bottom: none;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-2xl) var(--space-lg);
		color: var(--text-muted);
		font-size: var(--text-sm);
		text-align: center;
	}

	.empty-state svg {
		color: var(--text-muted);
		opacity: 0.5;
	}
</style>
