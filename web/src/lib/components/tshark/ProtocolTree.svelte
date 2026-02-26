<script lang="ts">
	/**
	 * ProtocolTree — expandable tree view for a selected packet's protocol layers.
	 *
	 * Props:
	 *   packet – the selected packet object (or null when nothing is selected)
	 */

	interface Props {
		packet: any | null;
	}

	let { packet }: Props = $props();

	// ---- Determine protocol layers from the packet data ----
	interface LayerEntry {
		name: string;
		fields: Array<{ key: string; value: string }>;
	}

	let layers = $derived<LayerEntry[]>(extractLayers(packet));

	// Track which layers are expanded (default: all expanded)
	let expandedLayers = $state<Set<string>>(new Set());

	// When a new packet is selected, expand all layers by default
	$effect(() => {
		if (packet) {
			expandedLayers = new Set(layers.map((l) => l.name));
		}
	});

	function extractLayers(pkt: any): LayerEntry[] {
		if (!pkt) return [];

		// TShark JSON with _source.layers structure
		const src = pkt?._source?.layers ?? pkt;
		if (!src || typeof src !== 'object') return [];

		const results: LayerEntry[] = [];

		for (const [layerName, layerData] of Object.entries(src)) {
			// Skip internal metadata keys
			if (layerName.startsWith('_ws.') || layerName === '_index' || layerName === '_type' || layerName === '_score') continue;

			const fields: Array<{ key: string; value: string }> = [];

			if (layerData && typeof layerData === 'object' && !Array.isArray(layerData)) {
				for (const [fieldKey, fieldVal] of Object.entries(layerData as Record<string, unknown>)) {
					// Flatten nested objects into dot-separated keys
					if (fieldVal && typeof fieldVal === 'object' && !Array.isArray(fieldVal)) {
						for (const [subKey, subVal] of Object.entries(fieldVal as Record<string, unknown>)) {
							fields.push({ key: subKey, value: formatValue(subVal) });
						}
					} else {
						fields.push({ key: fieldKey, value: formatValue(fieldVal) });
					}
				}
			} else {
				fields.push({ key: layerName, value: formatValue(layerData) });
			}

			if (fields.length > 0) {
				results.push({ name: layerName, fields });
			}
		}

		return results;
	}

	function formatValue(val: unknown): string {
		if (val === null || val === undefined) return '';
		if (typeof val === 'string') return val;
		if (typeof val === 'number' || typeof val === 'boolean') return String(val);
		if (Array.isArray(val)) return val.map(formatValue).join(', ');
		return JSON.stringify(val);
	}

	function toggleLayer(name: string) {
		const next = new Set(expandedLayers);
		if (next.has(name)) {
			next.delete(name);
		} else {
			next.add(name);
		}
		expandedLayers = next;
	}

	function handleLayerKeydown(e: KeyboardEvent, name: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			toggleLayer(name);
		}
	}

	function layerDisplayName(name: string): string {
		// Pretty-print common protocol names
		const map: Record<string, string> = {
			frame: 'Frame',
			eth: 'Ethernet',
			ip: 'Internet Protocol (IPv4)',
			ipv6: 'Internet Protocol (IPv6)',
			tcp: 'Transmission Control Protocol',
			udp: 'User Datagram Protocol',
			http: 'Hypertext Transfer Protocol',
			tls: 'Transport Layer Security',
			dns: 'Domain Name System',
			arp: 'Address Resolution Protocol',
			icmp: 'Internet Control Message Protocol',
			dhcp: 'Dynamic Host Configuration Protocol',
			ssh: 'Secure Shell Protocol',
			smtp: 'Simple Mail Transfer Protocol',
		};
		return map[name.toLowerCase()] ?? name;
	}
</script>

<div class="protocol-tree">
	{#if !packet}
		<div class="empty-state">
			<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
				<polyline points="4 7 4 4 20 4 20 7" />
				<line x1="9" y1="20" x2="15" y2="20" />
				<line x1="12" y1="4" x2="12" y2="20" />
			</svg>
			<span>Select a packet to view protocol details</span>
		</div>
	{:else if layers.length === 0}
		<div class="empty-state">
			<span>No protocol layers found for this packet</span>
		</div>
	{:else}
		{#each layers as layer}
			<div class="layer">
				<button
					class="layer-header"
					class:expanded={expandedLayers.has(layer.name)}
					onclick={() => toggleLayer(layer.name)}
					onkeydown={(e) => handleLayerKeydown(e, layer.name)}
					aria-expanded={expandedLayers.has(layer.name)}
				>
					<svg
						class="chevron"
						class:rotated={expandedLayers.has(layer.name)}
						viewBox="0 0 16 16"
						width="14"
						height="14"
						fill="currentColor"
					>
						<path d="M6.22 3.22a.75.75 0 011.06 0l4.25 4.25a.75.75 0 010 1.06l-4.25 4.25a.75.75 0 01-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 010-1.06z" />
					</svg>
					<span class="layer-name">{layerDisplayName(layer.name)}</span>
					<span class="layer-badge">{layer.name}</span>
				</button>

				{#if expandedLayers.has(layer.name)}
					<div class="layer-fields">
						{#each layer.fields as field}
							<div class="field-row">
								<span class="field-key">{field.key}</span>
								<span class="field-value">{field.value}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	{/if}
</div>

<style>
	.protocol-tree {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background-color: var(--bg-secondary);
		overflow-y: auto;
		max-height: 480px;
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
		opacity: 0.5;
	}

	.layer {
		border-bottom: 1px solid var(--border-muted);
	}

	.layer:last-child {
		border-bottom: none;
	}

	.layer-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		width: 100%;
		padding: var(--space-sm) var(--space-md);
		background: none;
		border: none;
		cursor: pointer;
		color: var(--text-primary);
		font-size: var(--text-sm);
		font-weight: 600;
		text-align: left;
		transition: background-color var(--transition-fast);
	}

	.layer-header:hover {
		background-color: var(--bg-tertiary);
	}

	.layer-header.expanded {
		background-color: rgba(33, 38, 45, 0.5);
	}

	.chevron {
		flex-shrink: 0;
		color: var(--text-muted);
		transition: transform var(--transition-fast);
	}

	.chevron.rotated {
		transform: rotate(90deg);
	}

	.layer-name {
		flex: 1;
	}

	.layer-badge {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 400;
		color: var(--text-muted);
		background-color: var(--bg-tertiary);
		padding: 1px 6px;
		border-radius: var(--radius-sm);
	}

	.layer-fields {
		padding: 0 var(--space-md) var(--space-sm);
		padding-left: calc(var(--space-md) + 14px + var(--space-sm));
	}

	.field-row {
		display: flex;
		gap: var(--space-md);
		padding: 2px 0;
		font-size: var(--text-xs);
		border-bottom: 1px solid var(--border-muted);
	}

	.field-row:last-child {
		border-bottom: none;
	}

	.field-key {
		flex-shrink: 0;
		width: 220px;
		font-family: var(--font-mono);
		color: var(--text-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.field-value {
		flex: 1;
		font-family: var(--font-mono);
		color: var(--text-primary);
		word-break: break-all;
	}
</style>
