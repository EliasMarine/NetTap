<script lang="ts">
	import PacketTable from './PacketTable.svelte';
	import ProtocolTree from './ProtocolTree.svelte';
	import HexDump from './HexDump.svelte';
	import DockPanel from './DockPanel.svelte';
	import FloatingPanel from './FloatingPanel.svelte';
	import ResizeDivider from './ResizeDivider.svelte';

	type PanelMode = 'docked' | 'minimized' | 'maximized' | 'floating';

	interface Props {
		packets: any[];
		loading: boolean;
		selectedPacket: any | null;
		selectedPacketIndex: number;
		rawHex?: string | null;
		onPacketSelect: (packet: any) => void;
	}

	let {
		packets,
		loading,
		selectedPacket,
		selectedPacketIndex,
		rawHex = null,
		onPacketSelect,
	}: Props = $props();

	// Layout state
	let topSplitPercent = $state(40);
	let bottomSplitPercent = $state(60);

	// Panel modes
	let tablePanelMode = $state<PanelMode>('docked');
	let treePanelMode = $state<PanelMode>('docked');
	let hexPanelMode = $state<PanelMode>('docked');

	// Floating positions
	let floatingPositions = $state<Record<string, { x: number; y: number }>>({
		table: { x: 50, y: 50 },
		tree: { x: 100, y: 100 },
		hex: { x: 150, y: 150 },
	});

	let topZIndex = $state(50);

	function handlePanelAction(panelId: string, action: 'minimize' | 'maximize' | 'popout') {
		const getMode = (id: string) => {
			if (id === 'table') return tablePanelMode;
			if (id === 'tree') return treePanelMode;
			return hexPanelMode;
		};

		const setMode = (id: string, mode: PanelMode) => {
			if (id === 'table') tablePanelMode = mode;
			else if (id === 'tree') treePanelMode = mode;
			else hexPanelMode = mode;
		};

		const current = getMode(panelId);

		switch (action) {
			case 'minimize':
				setMode(panelId, current === 'minimized' ? 'docked' : 'minimized');
				break;
			case 'maximize':
				setMode(panelId, current === 'maximized' ? 'docked' : 'maximized');
				break;
			case 'popout':
				setMode(panelId, 'floating');
				break;
		}
	}

	function handleDock(panelId: string) {
		if (panelId === 'table') tablePanelMode = 'docked';
		else if (panelId === 'tree') treePanelMode = 'docked';
		else hexPanelMode = 'docked';
	}

	function handleFloatingFocus(panelId: string) {
		topZIndex++;
	}

	function handleHorizontalDrag(delta: number) {
		const container = document.querySelector('.panel-manager');
		if (!container) return;
		const totalHeight = container.clientHeight;
		const percentDelta = (delta / totalHeight) * 100;
		topSplitPercent = Math.max(15, Math.min(85, topSplitPercent + percentDelta));
	}

	function handleVerticalDrag(delta: number) {
		const container = document.querySelector('.bottom-panels');
		if (!container) return;
		const totalWidth = container.clientWidth;
		const percentDelta = (delta / totalWidth) * 100;
		bottomSplitPercent = Math.max(20, Math.min(80, bottomSplitPercent + percentDelta));
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
		switch (e.key) {
			case 'Escape':
				tablePanelMode = 'docked';
				treePanelMode = 'docked';
				hexPanelMode = 'docked';
				break;
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="panel-manager">
	{#if tablePanelMode !== 'floating'}
		<div class="top-panel" style="height: {tablePanelMode === 'maximized' ? '100' : tablePanelMode === 'minimized' ? 'auto' : topSplitPercent}%;">
			<DockPanel title="Packet Table" panelId="table" mode={tablePanelMode} onaction={handlePanelAction}>
				<PacketTable
					{packets}
					{loading}
					onselect={onPacketSelect}
					selectedIndex={selectedPacketIndex}
				/>
			</DockPanel>
		</div>
	{/if}

	{#if tablePanelMode === 'docked' && (treePanelMode === 'docked' || hexPanelMode === 'docked')}
		<ResizeDivider direction="horizontal" ondrag={handleHorizontalDrag} />
	{/if}

	{#if treePanelMode !== 'floating' || hexPanelMode !== 'floating'}
		<div class="bottom-panels" style="flex: 1; min-height: 0;">
			{#if treePanelMode !== 'floating'}
				<div class="bottom-left" style="width: {treePanelMode === 'maximized' ? '100' : treePanelMode === 'minimized' ? 'auto' : bottomSplitPercent}%;">
					<DockPanel title="Protocol Tree" panelId="tree" mode={treePanelMode} onaction={handlePanelAction}>
						<ProtocolTree packet={selectedPacket} />
					</DockPanel>
				</div>
			{/if}

			{#if treePanelMode === 'docked' && hexPanelMode === 'docked'}
				<ResizeDivider direction="vertical" ondrag={handleVerticalDrag} />
			{/if}

			{#if hexPanelMode !== 'floating'}
				<div class="bottom-right" style="flex: 1; min-width: 0;">
					<DockPanel title="Hex Dump" panelId="hex" mode={hexPanelMode} onaction={handlePanelAction}>
						<HexDump {rawHex} />
					</DockPanel>
				</div>
			{/if}
		</div>
	{/if}

	{#if tablePanelMode === 'floating'}
		<FloatingPanel
			title="Packet Table"
			panelId="table"
			bind:x={floatingPositions.table.x}
			bind:y={floatingPositions.table.y}
			width={800}
			height={300}
			onclose={handleDock}
			onfocus={handleFloatingFocus}
		>
			<PacketTable {packets} {loading} onselect={onPacketSelect} selectedIndex={selectedPacketIndex} />
		</FloatingPanel>
	{/if}

	{#if treePanelMode === 'floating'}
		<FloatingPanel
			title="Protocol Tree"
			panelId="tree"
			bind:x={floatingPositions.tree.x}
			bind:y={floatingPositions.tree.y}
			width={600}
			height={400}
			onclose={handleDock}
			onfocus={handleFloatingFocus}
		>
			<ProtocolTree packet={selectedPacket} />
		</FloatingPanel>
	{/if}

	{#if hexPanelMode === 'floating'}
		<FloatingPanel
			title="Hex Dump"
			panelId="hex"
			bind:x={floatingPositions.hex.x}
			bind:y={floatingPositions.hex.y}
			width={600}
			height={400}
			onclose={handleDock}
			onfocus={handleFloatingFocus}
		>
			<HexDump {rawHex} />
		</FloatingPanel>
	{/if}
</div>

<style>
	.panel-manager {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 500px;
		position: relative;
	}

	.top-panel {
		min-height: 0;
		overflow: hidden;
	}

	.bottom-panels {
		display: flex;
		min-height: 0;
	}

	.bottom-left {
		min-width: 0;
		overflow: hidden;
	}

	.bottom-right {
		overflow: hidden;
	}
</style>
