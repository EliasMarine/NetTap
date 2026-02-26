<script lang="ts">
	/**
	 * NetworkMap — Pure SVG topology-style network visualization.
	 *
	 * Displays devices as nodes and connections as edges using a simplified
	 * force-directed layout. Devices are positioned radially based on
	 * connection count, with the gateway/router at center.
	 *
	 * Props:
	 *   devices       — Array of MapDevice entries
	 *   connections   — Array of MapConnection entries
	 *   width         — SVG width in pixels (default 800)
	 *   height        — SVG height in pixels (default 600)
	 *   ondeviceclick — Callback fired when a device node is clicked
	 */

	interface MapDevice {
		ip: string;
		label: string;
		type: 'router' | 'server' | 'desktop' | 'mobile' | 'iot' | 'unknown';
		risk_level: 'low' | 'medium' | 'high' | 'critical';
		connection_count: number;
		total_bytes: number;
	}

	interface MapConnection {
		source_ip: string;
		target_ip: string;
		bytes: number;
		protocol: string;
	}

	interface Props {
		devices: MapDevice[];
		connections: MapConnection[];
		width?: number;
		height?: number;
		ondeviceclick?: (ip: string) => void;
	}

	let {
		devices = [],
		connections = [],
		width = 800,
		height = 600,
		ondeviceclick = (_ip: string) => {},
	}: Props = $props();

	// ---- Constants ----
	const NODE_RADIUS = 16;
	const LABEL_OFFSET = 28;
	const GRID_SPACING = 40;
	const SIM_ITERATIONS = 100;
	const REPULSION = 2000;
	const SPRING_K = 0.005;
	const SPRING_LENGTH = 120;
	const DAMPING = 0.85;
	const CENTER_GRAVITY = 0.01;

	// Risk-level colors
	const RISK_COLORS: Record<string, string> = {
		low: '#3fb950',
		medium: '#d29922',
		high: '#f85149',
		critical: '#da3633',
	};

	// Protocol colors for connection lines
	const PROTOCOL_COLORS: Record<string, string> = {
		TCP: '#58a6ff',
		tcp: '#58a6ff',
		UDP: '#bc8cff',
		udp: '#bc8cff',
		HTTP: '#3fb950',
		http: '#3fb950',
		HTTPS: '#3fb950',
		https: '#3fb950',
		DNS: '#d29922',
		dns: '#d29922',
	};
	const DEFAULT_PROTOCOL_COLOR = '#8b949e';

	// Device type labels for legend
	const DEVICE_TYPE_LABELS: Record<string, string> = {
		router: 'Router',
		server: 'Server',
		desktop: 'Desktop',
		mobile: 'Mobile',
		iot: 'IoT Device',
		unknown: 'Unknown',
	};

	// ---- State ----
	let hoveredDeviceIp = $state<string | null>(null);
	let hoveredConnectionIdx = $state<number | null>(null);
	let tooltipText = $state('');
	let tooltipX = $state(0);
	let tooltipY = $state(0);
	let showTooltip = $state(false);

	// ---- Positioned nodes from force layout ----
	interface PositionedDevice extends MapDevice {
		x: number;
		y: number;
	}

	// Force-directed layout simulation
	let positionedDevices = $derived.by(() => {
		if (devices.length === 0) return [];

		const cx = width / 2;
		const cy = height / 2;

		// Find max connection count for radial placement
		const maxConns = Math.max(1, ...devices.map((d) => d.connection_count));

		// Build adjacency set for spring forces
		const adjacency = new Set<string>();
		for (const conn of connections) {
			adjacency.add(`${conn.source_ip}|${conn.target_ip}`);
			adjacency.add(`${conn.target_ip}|${conn.source_ip}`);
		}

		// Initialize positions: radial distribution based on connection count
		// More connections = closer to center
		const simNodes: { ip: string; x: number; y: number; vx: number; vy: number }[] =
			devices.map((d, i) => {
				const ratio = 1 - d.connection_count / maxConns; // 0 = center, 1 = edge
				const maxRadius = Math.min(cx, cy) * 0.75;
				const r = ratio * maxRadius + 30;

				// Spread devices evenly around center using golden angle
				const goldenAngle = Math.PI * (3 - Math.sqrt(5));
				const angle = i * goldenAngle;

				return {
					ip: d.ip,
					x: cx + r * Math.cos(angle),
					y: cy + r * Math.sin(angle),
					vx: 0,
					vy: 0,
				};
			});

		// Create IP->index lookup
		const ipToIdx = new Map<string, number>();
		for (let i = 0; i < simNodes.length; i++) {
			ipToIdx.set(simNodes[i].ip, i);
		}

		// Run simulation
		for (let iter = 0; iter < SIM_ITERATIONS; iter++) {
			// Repulsion: all pairs push each other apart
			for (let i = 0; i < simNodes.length; i++) {
				for (let j = i + 1; j < simNodes.length; j++) {
					let dx = simNodes[j].x - simNodes[i].x;
					let dy = simNodes[j].y - simNodes[i].y;
					let dist = Math.sqrt(dx * dx + dy * dy) || 1;
					const force = REPULSION / (dist * dist);
					const fx = (dx / dist) * force;
					const fy = (dy / dist) * force;
					simNodes[i].vx -= fx;
					simNodes[i].vy -= fy;
					simNodes[j].vx += fx;
					simNodes[j].vy += fy;
				}
			}

			// Spring attraction along edges
			for (const conn of connections) {
				const si = ipToIdx.get(conn.source_ip);
				const ti = ipToIdx.get(conn.target_ip);
				if (si === undefined || ti === undefined) continue;

				let dx = simNodes[ti].x - simNodes[si].x;
				let dy = simNodes[ti].y - simNodes[si].y;
				let dist = Math.sqrt(dx * dx + dy * dy) || 1;
				const displacement = dist - SPRING_LENGTH;
				const force = SPRING_K * displacement;
				const fx = (dx / dist) * force;
				const fy = (dy / dist) * force;
				simNodes[si].vx += fx;
				simNodes[si].vy += fy;
				simNodes[ti].vx -= fx;
				simNodes[ti].vy -= fy;
			}

			// Center gravity
			for (const node of simNodes) {
				node.vx += (cx - node.x) * CENTER_GRAVITY;
				node.vy += (cy - node.y) * CENTER_GRAVITY;
			}

			// Apply velocities with damping and boundary constraints
			for (const node of simNodes) {
				node.vx *= DAMPING;
				node.vy *= DAMPING;
				node.x += node.vx;
				node.y += node.vy;

				// Keep nodes inside bounds with padding
				const pad = NODE_RADIUS + 4;
				node.x = Math.max(pad, Math.min(width - pad, node.x));
				node.y = Math.max(pad, Math.min(height - pad, node.y));
			}
		}

		// Map back to positioned devices
		return devices.map((d) => {
			const sn = simNodes[ipToIdx.get(d.ip)!];
			return { ...d, x: sn.x, y: sn.y } as PositionedDevice;
		});
	});

	// Device lookup by IP
	let deviceMap = $derived.by(() => {
		const map = new Map<string, PositionedDevice>();
		for (const d of positionedDevices) {
			map.set(d.ip, d);
		}
		return map;
	});

	// Connection line width: scale bytes to 1-4px stroke
	let maxBytes = $derived(Math.max(1, ...connections.map((c) => c.bytes)));

	function connectionWidth(bytes: number): number {
		return 1 + (bytes / maxBytes) * 3;
	}

	function protocolColor(protocol: string): string {
		return PROTOCOL_COLORS[protocol] || DEFAULT_PROTOCOL_COLOR;
	}

	// Check if a device is connected to the hovered device
	function isDeviceHighlighted(ip: string): boolean {
		if (hoveredDeviceIp === ip) return true;
		if (hoveredConnectionIdx !== null) {
			const conn = connections[hoveredConnectionIdx];
			if (conn) return conn.source_ip === ip || conn.target_ip === ip;
		}
		if (hoveredDeviceIp !== null) {
			for (const conn of connections) {
				if (
					(conn.source_ip === hoveredDeviceIp && conn.target_ip === ip) ||
					(conn.target_ip === hoveredDeviceIp && conn.source_ip === ip)
				) {
					return true;
				}
			}
		}
		return false;
	}

	// Check if a connection involves the hovered device
	function isConnectionHighlighted(idx: number): boolean {
		if (hoveredConnectionIdx === idx) return true;
		if (hoveredDeviceIp !== null) {
			const conn = connections[idx];
			return conn.source_ip === hoveredDeviceIp || conn.target_ip === hoveredDeviceIp;
		}
		return false;
	}

	// Grid pattern lines
	let gridLinesX = $derived.by(() => {
		const lines: number[] = [];
		for (let x = GRID_SPACING; x < width; x += GRID_SPACING) {
			lines.push(x);
		}
		return lines;
	});
	let gridLinesY = $derived.by(() => {
		const lines: number[] = [];
		for (let y = GRID_SPACING; y < height; y += GRID_SPACING) {
			lines.push(y);
		}
		return lines;
	});

	// Unique device types present for the legend
	let presentDeviceTypes = $derived.by(() => {
		const types = new Set<string>();
		for (const d of devices) types.add(d.type);
		return Array.from(types);
	});

	// Unique risk levels present for the legend
	let presentRiskLevels = $derived.by(() => {
		const levels = new Set<string>();
		for (const d of devices) levels.add(d.risk_level);
		// Sort in severity order
		const order = ['low', 'medium', 'high', 'critical'];
		return order.filter((l) => levels.has(l));
	});

	// Event handlers
	function updateTooltipFromEvent(event: MouseEvent) {
		const svgEl = (event.currentTarget as SVGElement).closest('svg');
		if (!svgEl) return;
		const rect = svgEl.getBoundingClientRect();
		tooltipX = event.clientX - rect.left;
		tooltipY = event.clientY - rect.top;
	}

	function handleDeviceHover(device: PositionedDevice, event: MouseEvent) {
		hoveredDeviceIp = device.ip;
		hoveredConnectionIdx = null;
		tooltipText = `${device.label} (${device.ip})`;
		updateTooltipFromEvent(event);
		showTooltip = true;
	}

	function handleConnectionHover(idx: number, event: MouseEvent) {
		hoveredConnectionIdx = idx;
		hoveredDeviceIp = null;
		const conn = connections[idx];
		if (conn) {
			const srcLabel = deviceMap.get(conn.source_ip)?.label ?? conn.source_ip;
			const tgtLabel = deviceMap.get(conn.target_ip)?.label ?? conn.target_ip;
			tooltipText = `${srcLabel} \u2192 ${tgtLabel}: ${conn.bytes.toLocaleString()} bytes (${conn.protocol})`;
		}
		updateTooltipFromEvent(event);
		showTooltip = true;
	}

	function handleMouseMove(event: MouseEvent) {
		updateTooltipFromEvent(event);
	}

	function handleMouseLeave() {
		hoveredDeviceIp = null;
		hoveredConnectionIdx = null;
		showTooltip = false;
	}

	function handleDeviceClick(device: PositionedDevice) {
		ondeviceclick(device.ip);
	}

	let hasData = $derived(devices.length > 0);
</script>

<div class="network-map" role="img" aria-label="Network topology map">
	{#if !hasData}
		<div class="chart-empty" style:width="{width}px" style:height="{height}px">
			<p>No devices detected</p>
		</div>
	{:else}
		<div class="map-container" style:position="relative">
			<svg {width} {height} viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
				<!-- Background grid -->
				<g class="grid-pattern" opacity="0.06">
					{#each gridLinesX as gx}
						<line x1={gx} y1={0} x2={gx} y2={height} stroke="var(--text-muted)" stroke-width="1" />
					{/each}
					{#each gridLinesY as gy}
						<line x1={0} y1={gy} x2={width} y2={gy} stroke="var(--text-muted)" stroke-width="1" />
					{/each}
				</g>

				<!-- Connection lines layer -->
				<g class="map-connections">
					{#each connections as conn, i}
						{@const src = deviceMap.get(conn.source_ip)}
						{@const tgt = deviceMap.get(conn.target_ip)}
						{#if src && tgt}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<line
								x1={src.x}
								y1={src.y}
								x2={tgt.x}
								y2={tgt.y}
								stroke={protocolColor(conn.protocol)}
								stroke-width={connectionWidth(conn.bytes)}
								opacity={hoveredDeviceIp !== null || hoveredConnectionIdx !== null
									? isConnectionHighlighted(i)
										? 0.8
										: 0.15
									: 0.4}
								class="connection-line"
								onmouseenter={(e) => handleConnectionHover(i, e)}
								onmousemove={handleMouseMove}
								onmouseleave={handleMouseLeave}
							/>
						{/if}
					{/each}
				</g>

				<!-- Device nodes layer -->
				<g class="map-devices">
					{#each positionedDevices as device}
						{@const dimmed =
							(hoveredDeviceIp !== null || hoveredConnectionIdx !== null) &&
							!isDeviceHighlighted(device.ip)}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<g
							class="device-node"
							class:dimmed
							transform="translate({device.x}, {device.y})"
							onmouseenter={(e) => handleDeviceHover(device, e)}
							onmousemove={handleMouseMove}
							onmouseleave={handleMouseLeave}
							onclick={() => handleDeviceClick(device)}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleDeviceClick(device); } }}
							role="button"
							tabindex="0"
							style="cursor: pointer;"
						>
							<!-- Risk-level border ring -->
							<circle
								r={NODE_RADIUS + 3}
								fill="none"
								stroke={RISK_COLORS[device.risk_level]}
								stroke-width="2"
								opacity="0.7"
							/>

							<!-- Device shape by type -->
							{#if device.type === 'router'}
								<!-- Hexagon -->
								<polygon
									points={hexagonPoints(NODE_RADIUS)}
									fill="var(--bg-tertiary)"
									stroke={RISK_COLORS[device.risk_level]}
									stroke-width="1.5"
								/>
								<!-- Network icon: small arrows -->
								<path
									d="M-5,-3 L0,-7 L5,-3 M-5,3 L0,7 L5,3 M-7,0 L7,0"
									fill="none"
									stroke="var(--text-secondary)"
									stroke-width="1.2"
									stroke-linecap="round"
								/>
							{:else if device.type === 'server'}
								<!-- Rounded rectangle -->
								<rect
									x={-NODE_RADIUS}
									y={-NODE_RADIUS}
									width={NODE_RADIUS * 2}
									height={NODE_RADIUS * 2}
									rx="4"
									ry="4"
									fill="var(--bg-tertiary)"
									stroke={RISK_COLORS[device.risk_level]}
									stroke-width="1.5"
								/>
								<!-- Stack lines -->
								<line
									x1={-8}
									y1={-5}
									x2={8}
									y2={-5}
									stroke="var(--text-secondary)"
									stroke-width="1.2"
								/>
								<line
									x1={-8}
									y1={0}
									x2={8}
									y2={0}
									stroke="var(--text-secondary)"
									stroke-width="1.2"
								/>
								<line
									x1={-8}
									y1={5}
									x2={8}
									y2={5}
									stroke="var(--text-secondary)"
									stroke-width="1.2"
								/>
							{:else if device.type === 'desktop'}
								<!-- Monitor shape -->
								<rect
									x={-NODE_RADIUS}
									y={-NODE_RADIUS + 2}
									width={NODE_RADIUS * 2}
									height={NODE_RADIUS * 1.5}
									rx="2"
									ry="2"
									fill="var(--bg-tertiary)"
									stroke={RISK_COLORS[device.risk_level]}
									stroke-width="1.5"
								/>
								<!-- Stand -->
								<line
									x1={0}
									y1={NODE_RADIUS * 0.5 + 2}
									x2={0}
									y2={NODE_RADIUS}
									stroke="var(--text-secondary)"
									stroke-width="1.5"
								/>
								<line
									x1={-6}
									y1={NODE_RADIUS}
									x2={6}
									y2={NODE_RADIUS}
									stroke="var(--text-secondary)"
									stroke-width="1.5"
									stroke-linecap="round"
								/>
							{:else if device.type === 'mobile'}
								<!-- Phone shape -->
								<rect
									x={-8}
									y={-NODE_RADIUS}
									width={16}
									height={NODE_RADIUS * 2}
									rx="4"
									ry="4"
									fill="var(--bg-tertiary)"
									stroke={RISK_COLORS[device.risk_level]}
									stroke-width="1.5"
								/>
								<!-- Home button circle -->
								<circle r="2" cx={0} cy={NODE_RADIUS - 5} fill="var(--text-secondary)" />
								<!-- Screen line -->
								<line
									x1={-5}
									y1={-NODE_RADIUS + 5}
									x2={5}
									y2={-NODE_RADIUS + 5}
									stroke="var(--text-secondary)"
									stroke-width="1"
								/>
							{:else if device.type === 'iot'}
								<!-- Circle with signal lines -->
								<circle
									r={NODE_RADIUS}
									fill="var(--bg-tertiary)"
									stroke={RISK_COLORS[device.risk_level]}
									stroke-width="1.5"
								/>
								<!-- Signal arcs -->
								<path
									d="M-4,-2 A6,6 0 0,1 -4,4"
									fill="none"
									stroke="var(--text-secondary)"
									stroke-width="1.2"
								/>
								<path
									d="M-7,-4 A10,10 0 0,1 -7,6"
									fill="none"
									stroke="var(--text-secondary)"
									stroke-width="1.2"
								/>
								<!-- Dot -->
								<circle r="2" cx={2} cy={1} fill="var(--text-secondary)" />
							{:else}
								<!-- Unknown: plain circle -->
								<circle
									r={NODE_RADIUS}
									fill="var(--bg-tertiary)"
									stroke={RISK_COLORS[device.risk_level]}
									stroke-width="1.5"
								/>
								<text
									x={0}
									y={1}
									text-anchor="middle"
									dominant-baseline="middle"
									fill="var(--text-muted)"
									font-size="14"
								>
									?
								</text>
							{/if}

							<!-- Device label -->
							<text
								x={0}
								y={LABEL_OFFSET}
								text-anchor="middle"
								class="device-label"
							>
								{device.label.length > 14 ? device.label.slice(0, 13) + '\u2026' : device.label}
							</text>
						</g>
					{/each}
				</g>
			</svg>

			<!-- Tooltip overlay -->
			{#if showTooltip}
				<div
					class="map-tooltip"
					style:left="{tooltipX}px"
					style:top="{tooltipY - 40}px"
				>
					{tooltipText}
				</div>
			{/if}
		</div>

		<!-- Legend -->
		<div class="map-legend">
			<div class="legend-section">
				<span class="legend-title">Device Types</span>
				<div class="legend-items">
					{#each presentDeviceTypes as dtype}
						<div class="legend-item">
							<svg width="16" height="16" viewBox="-10 -10 20 20">
								{#if dtype === 'router'}
									<polygon points={hexagonPoints(8)} fill="var(--bg-tertiary)" stroke="var(--text-secondary)" stroke-width="1" />
								{:else if dtype === 'server'}
									<rect x="-7" y="-7" width="14" height="14" rx="2" fill="var(--bg-tertiary)" stroke="var(--text-secondary)" stroke-width="1" />
								{:else if dtype === 'desktop'}
									<rect x="-7" y="-6" width="14" height="10" rx="1" fill="var(--bg-tertiary)" stroke="var(--text-secondary)" stroke-width="1" />
								{:else if dtype === 'mobile'}
									<rect x="-5" y="-8" width="10" height="16" rx="2" fill="var(--bg-tertiary)" stroke="var(--text-secondary)" stroke-width="1" />
								{:else if dtype === 'iot'}
									<circle r="7" fill="var(--bg-tertiary)" stroke="var(--text-secondary)" stroke-width="1" />
								{:else}
									<circle r="7" fill="var(--bg-tertiary)" stroke="var(--text-secondary)" stroke-width="1" />
								{/if}
							</svg>
							<span class="legend-label">{DEVICE_TYPE_LABELS[dtype] || dtype}</span>
						</div>
					{/each}
				</div>
			</div>

			<div class="legend-section">
				<span class="legend-title">Risk Level</span>
				<div class="legend-items">
					{#each presentRiskLevels as level}
						<div class="legend-item">
							<span class="legend-swatch" style:background-color={RISK_COLORS[level]}></span>
							<span class="legend-label">{level.charAt(0).toUpperCase() + level.slice(1)}</span>
						</div>
					{/each}
				</div>
			</div>

			<div class="legend-section">
				<span class="legend-title">Protocols</span>
				<div class="legend-items">
					{#each Object.entries(PROTOCOL_COLORS).filter(([k]) => k === k.toUpperCase()) as [proto, color]}
						<div class="legend-item">
							<span class="legend-line" style:background-color={color}></span>
							<span class="legend-label">{proto}</span>
						</div>
					{/each}
					<div class="legend-item">
						<span class="legend-line" style:background-color={DEFAULT_PROTOCOL_COLOR}></span>
						<span class="legend-label">Other</span>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>

<script lang="ts" module>
	/**
	 * Generate SVG polygon points string for a regular hexagon centered at origin.
	 */
	export function hexagonPoints(radius: number): string {
		const pts: string[] = [];
		for (let i = 0; i < 6; i++) {
			const angle = (Math.PI / 3) * i - Math.PI / 6;
			pts.push(`${(radius * Math.cos(angle)).toFixed(2)},${(radius * Math.sin(angle)).toFixed(2)}`);
		}
		return pts.join(' ');
	}
</script>

<style>
	.network-map {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-md);
	}

	.chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.map-container {
		position: relative;
		background-color: var(--bg-secondary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-muted);
		overflow: hidden;
	}

	svg {
		display: block;
	}

	.connection-line {
		cursor: pointer;
		transition: opacity 0.15s ease;
	}

	.device-node {
		transition: opacity 0.15s ease;
	}

	.device-node.dimmed {
		opacity: 0.3;
	}

	.device-label {
		fill: var(--text-secondary);
		font-size: 11px;
		font-family: var(--font-mono);
		pointer-events: none;
	}

	.map-tooltip {
		position: absolute;
		transform: translateX(-50%);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		padding: 4px 10px;
		pointer-events: none;
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--text-primary);
		white-space: nowrap;
		z-index: 10;
	}

	/* Legend */
	.map-legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-lg);
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-muted);
		border-radius: var(--radius-md);
		width: 100%;
	}

	.legend-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.legend-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.legend-items {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
	}

	.legend-item svg {
		flex-shrink: 0;
	}

	.legend-label {
		color: var(--text-secondary);
	}

	.legend-swatch {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.legend-line {
		width: 16px;
		height: 3px;
		border-radius: 1px;
		flex-shrink: 0;
	}
</style>
