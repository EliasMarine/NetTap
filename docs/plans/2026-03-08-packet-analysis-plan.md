# Packet Analysis Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the fixed 2-panel packet analysis layout with a Wireshark-inspired 3-pane layout featuring resizable dividers, panel minimize/maximize/pop-out, and a new hex dump view.

**Architecture:** A `PanelManager` orchestrator manages layout state (split percentages, panel modes). Each panel is wrapped in a `DockPanel` with a title bar and action buttons. `ResizeDivider` handles drag-to-resize. `FloatingPanel` wraps popped-out panels as draggable overlays. A new `HexDump` component renders raw packet bytes.

**Tech Stack:** Svelte 5 (runes: `$state`, `$derived`, `$effect`, `$props`), TypeScript, Vitest + @testing-library/svelte, Python aiohttp (daemon API)

**Design Doc:** `docs/plans/2026-03-08-packet-analysis-redesign.md`

---

## Task 1: ResizeDivider Component

**Files:**
- Create: `web/src/lib/components/tshark/ResizeDivider.svelte`
- Test: `web/src/lib/components/tshark/ResizeDivider.test.ts`

**Step 1: Write the test**

Create `web/src/lib/components/tshark/ResizeDivider.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ResizeDivider from './ResizeDivider.svelte';

describe('ResizeDivider', () => {
	it('renders a horizontal divider by default', () => {
		const { container } = render(ResizeDivider, {
			props: { direction: 'horizontal', ondrag: vi.fn() },
		});
		const el = container.querySelector('.resize-divider');
		expect(el).not.toBeNull();
		expect(el?.classList.contains('horizontal')).toBe(true);
	});

	it('renders a vertical divider', () => {
		const { container } = render(ResizeDivider, {
			props: { direction: 'vertical', ondrag: vi.fn() },
		});
		const el = container.querySelector('.resize-divider');
		expect(el?.classList.contains('vertical')).toBe(true);
	});

	it('calls ondrag during pointer move after pointerdown', async () => {
		const ondrag = vi.fn();
		const { container } = render(ResizeDivider, {
			props: { direction: 'horizontal', ondrag },
		});
		const el = container.querySelector('.resize-divider')!;

		await fireEvent.pointerDown(el, { clientX: 100, clientY: 200, pointerId: 1 });
		// Simulate a move on document
		await fireEvent.pointerMove(document, { clientX: 100, clientY: 250, pointerId: 1 });
		await fireEvent.pointerUp(document, { pointerId: 1 });

		expect(ondrag).toHaveBeenCalled();
	});
});
```

**Step 2: Run test to verify it fails**

```bash
cd web && npx vitest run src/lib/components/tshark/ResizeDivider.test.ts
```

Expected: FAIL — `ResizeDivider.svelte` does not exist.

**Step 3: Implement ResizeDivider**

Create `web/src/lib/components/tshark/ResizeDivider.svelte`:

```svelte
<script lang="ts">
	interface Props {
		direction: 'horizontal' | 'vertical';
		ondrag?: (delta: number) => void;
	}

	let { direction, ondrag }: Props = $props();

	let dragging = $state(false);
	let startPos = 0;

	function handlePointerDown(e: PointerEvent) {
		e.preventDefault();
		dragging = true;
		startPos = direction === 'horizontal' ? e.clientY : e.clientX;
		(e.target as HTMLElement).setPointerCapture(e.pointerId);

		const onMove = (ev: PointerEvent) => {
			if (!dragging) return;
			const current = direction === 'horizontal' ? ev.clientY : ev.clientX;
			const delta = current - startPos;
			startPos = current;
			ondrag?.(delta);
		};

		const onUp = () => {
			dragging = false;
			document.removeEventListener('pointermove', onMove);
			document.removeEventListener('pointerup', onUp);
		};

		document.addEventListener('pointermove', onMove);
		document.addEventListener('pointerup', onUp);
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="resize-divider {direction}"
	class:active={dragging}
	onpointerdown={handlePointerDown}
	role="separator"
	aria-orientation={direction}
></div>

<style>
	.resize-divider {
		flex-shrink: 0;
		background: var(--border-default);
		transition: background-color var(--transition-fast);
		touch-action: none;
		z-index: 2;
	}

	.resize-divider:hover,
	.resize-divider.active {
		background: var(--accent);
	}

	.horizontal {
		height: 4px;
		cursor: row-resize;
		width: 100%;
	}

	.vertical {
		width: 4px;
		cursor: col-resize;
		height: 100%;
	}
</style>
```

**Step 4: Run test to verify it passes**

```bash
cd web && npx vitest run src/lib/components/tshark/ResizeDivider.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/components/tshark/ResizeDivider.svelte web/src/lib/components/tshark/ResizeDivider.test.ts
git commit -m "feat(tshark): add ResizeDivider component for draggable panel splits"
```

---

## Task 2: DockPanel Component

**Files:**
- Create: `web/src/lib/components/tshark/DockPanel.svelte`
- Test: `web/src/lib/components/tshark/DockPanel.test.ts`

**Step 1: Write the test**

Create `web/src/lib/components/tshark/DockPanel.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DockPanel from './DockPanel.svelte';

describe('DockPanel', () => {
	it('renders the title', () => {
		render(DockPanel, { props: { title: 'Packet Table', panelId: 'table' } });
		expect(screen.getByText('Packet Table')).toBeInTheDocument();
	});

	it('shows minimize, maximize, and popout buttons', () => {
		const { container } = render(DockPanel, {
			props: { title: 'Proto Tree', panelId: 'tree' },
		});
		expect(container.querySelector('[title="Minimize"]')).not.toBeNull();
		expect(container.querySelector('[title="Maximize"]')).not.toBeNull();
		expect(container.querySelector('[title="Pop out"]')).not.toBeNull();
	});

	it('emits onaction when minimize is clicked', async () => {
		const onaction = vi.fn();
		const { container } = render(DockPanel, {
			props: { title: 'Test', panelId: 'test', onaction },
		});
		const btn = container.querySelector('[title="Minimize"]')!;
		await fireEvent.click(btn);
		expect(onaction).toHaveBeenCalledWith('test', 'minimize');
	});

	it('hides content when mode is minimized', () => {
		const { container } = render(DockPanel, {
			props: { title: 'Test', panelId: 'test', mode: 'minimized' },
		});
		const content = container.querySelector('.dock-panel-content');
		expect(content).toBeNull();
	});
});
```

**Step 2: Run test to verify it fails**

```bash
cd web && npx vitest run src/lib/components/tshark/DockPanel.test.ts
```

Expected: FAIL — `DockPanel.svelte` does not exist.

**Step 3: Implement DockPanel**

Create `web/src/lib/components/tshark/DockPanel.svelte`:

```svelte
<script lang="ts">
	import type { Snippet } from 'svelte';

	type PanelMode = 'docked' | 'minimized' | 'maximized' | 'floating';

	interface Props {
		title: string;
		panelId: string;
		mode?: PanelMode;
		onaction?: (panelId: string, action: 'minimize' | 'maximize' | 'popout') => void;
		children?: Snippet;
	}

	let { title, panelId, mode = 'docked', onaction, children }: Props = $props();
</script>

<div class="dock-panel" class:minimized={mode === 'minimized'} class:maximized={mode === 'maximized'}>
	<div class="dock-panel-header">
		<span class="dock-panel-title">{title}</span>
		<div class="dock-panel-actions">
			<button
				class="panel-action-btn"
				title="Minimize"
				onclick={() => onaction?.(panelId, 'minimize')}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M2 7.75h12a.75.75 0 010 1.5H2a.75.75 0 010-1.5z" />
				</svg>
			</button>
			<button
				class="panel-action-btn"
				title="Maximize"
				onclick={() => onaction?.(panelId, 'maximize')}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M3.5 3.5v9h9v-9h-9zM2 3a1 1 0 011-1h10a1 1 0 011 1v10a1 1 0 01-1 1H3a1 1 0 01-1-1V3z" />
				</svg>
			</button>
			<button
				class="panel-action-btn"
				title="Pop out"
				onclick={() => onaction?.(panelId, 'popout')}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M10 1h5v5h-1.5V3.56L8.78 8.28a.75.75 0 01-1.06-1.06L12.44 2.5H10V1zM3.5 3.5H7V2H3a1 1 0 00-1 1v10a1 1 0 001 1h10a1 1 0 001-1V9h-1.5v4.5h-9v-10z" />
				</svg>
			</button>
		</div>
	</div>
	{#if mode !== 'minimized'}
		<div class="dock-panel-content">
			{#if children}
				{@render children()}
			{/if}
		</div>
	{/if}
</div>

<style>
	.dock-panel {
		display: flex;
		flex-direction: column;
		min-height: 0;
		height: 100%;
		overflow: hidden;
	}

	.dock-panel.minimized {
		height: auto;
		flex: 0 0 auto;
	}

	.dock-panel.maximized {
		position: absolute;
		inset: 0;
		z-index: 20;
		background: var(--bg-primary);
	}

	.dock-panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 4px 8px;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-default);
		flex-shrink: 0;
		user-select: none;
	}

	.dock-panel-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.dock-panel-actions {
		display: flex;
		gap: 2px;
	}

	.panel-action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		padding: 0;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.panel-action-btn:hover {
		background: var(--bg-secondary);
		color: var(--text-primary);
	}

	.dock-panel-content {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}
</style>
```

**Step 4: Run test to verify it passes**

```bash
cd web && npx vitest run src/lib/components/tshark/DockPanel.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/components/tshark/DockPanel.svelte web/src/lib/components/tshark/DockPanel.test.ts
git commit -m "feat(tshark): add DockPanel wrapper with minimize/maximize/popout actions"
```

---

## Task 3: FloatingPanel Component

**Files:**
- Create: `web/src/lib/components/tshark/FloatingPanel.svelte`
- Test: `web/src/lib/components/tshark/FloatingPanel.test.ts`

**Step 1: Write the test**

Create `web/src/lib/components/tshark/FloatingPanel.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import FloatingPanel from './FloatingPanel.svelte';

describe('FloatingPanel', () => {
	it('renders with title and close button', () => {
		render(FloatingPanel, {
			props: { title: 'Protocol Tree', panelId: 'tree', onclose: vi.fn() },
		});
		expect(screen.getByText('Protocol Tree')).toBeInTheDocument();
		expect(screen.getByTitle('Dock panel')).not.toBeNull();
	});

	it('calls onclose when close button is clicked', async () => {
		const onclose = vi.fn();
		render(FloatingPanel, {
			props: { title: 'Test', panelId: 'test', onclose },
		});
		await fireEvent.click(screen.getByTitle('Dock panel'));
		expect(onclose).toHaveBeenCalledWith('test');
	});

	it('positions at provided coordinates', () => {
		const { container } = render(FloatingPanel, {
			props: { title: 'Test', panelId: 'test', x: 100, y: 50, width: 600, height: 400, onclose: vi.fn() },
		});
		const el = container.querySelector('.floating-panel') as HTMLElement;
		expect(el.style.left).toBe('100px');
		expect(el.style.top).toBe('50px');
	});
});
```

**Step 2: Run test to verify it fails**

```bash
cd web && npx vitest run src/lib/components/tshark/FloatingPanel.test.ts
```

Expected: FAIL

**Step 3: Implement FloatingPanel**

Create `web/src/lib/components/tshark/FloatingPanel.svelte`:

```svelte
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		panelId: string;
		x?: number;
		y?: number;
		width?: number;
		height?: number;
		onclose?: (panelId: string) => void;
		onfocus?: (panelId: string) => void;
		children?: Snippet;
	}

	let {
		title,
		panelId,
		x = $bindable(100),
		y = $bindable(100),
		width = 600,
		height = 400,
		onclose,
		onfocus,
		children,
	}: Props = $props();

	let dragging = $state(false);
	let dragOffsetX = 0;
	let dragOffsetY = 0;

	function handleHeaderPointerDown(e: PointerEvent) {
		if ((e.target as HTMLElement).closest('button')) return;
		e.preventDefault();
		dragging = true;
		dragOffsetX = e.clientX - x;
		dragOffsetY = e.clientY - y;

		const onMove = (ev: PointerEvent) => {
			if (!dragging) return;
			x = Math.max(0, ev.clientX - dragOffsetX);
			y = Math.max(0, ev.clientY - dragOffsetY);
		};

		const onUp = () => {
			dragging = false;
			document.removeEventListener('pointermove', onMove);
			document.removeEventListener('pointerup', onUp);
		};

		document.addEventListener('pointermove', onMove);
		document.addEventListener('pointerup', onUp);
	}

	function handlePanelClick() {
		onfocus?.(panelId);
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
	class="floating-panel"
	style="left: {x}px; top: {y}px; width: {width}px; height: {height}px;"
	onclick={handlePanelClick}
>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="floating-header" onpointerdown={handleHeaderPointerDown}>
		<span class="floating-title">{title}</span>
		<button class="floating-close" title="Dock panel" onclick={() => onclose?.(panelId)}>
			<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
				<path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.75.75 0 111.06 1.06L9.06 8l3.22 3.22a.75.75 0 11-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 01-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 010-1.06z" />
			</svg>
		</button>
	</div>
	<div class="floating-content">
		{#if children}
			{@render children()}
		{/if}
	</div>
</div>

<style>
	.floating-panel {
		position: absolute;
		display: flex;
		flex-direction: column;
		background: var(--bg-primary);
		border: 1px solid var(--accent);
		border-radius: var(--radius-md);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
		z-index: 50;
		overflow: hidden;
	}

	.floating-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 10px;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-default);
		cursor: grab;
		user-select: none;
		touch-action: none;
	}

	.floating-header:active {
		cursor: grabbing;
	}

	.floating-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.floating-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		padding: 0;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		cursor: pointer;
	}

	.floating-close:hover {
		background: var(--bg-secondary);
		color: var(--text-primary);
	}

	.floating-content {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}
</style>
```

**Step 4: Run test to verify it passes**

```bash
cd web && npx vitest run src/lib/components/tshark/FloatingPanel.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/components/tshark/FloatingPanel.svelte web/src/lib/components/tshark/FloatingPanel.test.ts
git commit -m "feat(tshark): add FloatingPanel draggable overlay for popped-out panels"
```

---

## Task 4: HexDump Component

**Files:**
- Create: `web/src/lib/components/tshark/HexDump.svelte`
- Test: `web/src/lib/components/tshark/HexDump.test.ts`

**Step 1: Write the test**

Create `web/src/lib/components/tshark/HexDump.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HexDump from './HexDump.svelte';

describe('HexDump', () => {
	it('shows empty state when no data is provided', () => {
		render(HexDump, { props: {} });
		expect(screen.getByText(/select a packet/i)).toBeInTheDocument();
	});

	it('renders hex bytes and ASCII for provided data', () => {
		// "Hello" = 48 65 6c 6c 6f
		const data = '48656c6c6f';
		const { container } = render(HexDump, { props: { rawHex: data } });

		// Should show offset 0000
		expect(container.textContent).toContain('0000');
		// Should show hex bytes
		expect(container.textContent).toContain('48');
		expect(container.textContent).toContain('65');
		// Should show ASCII
		expect(container.textContent).toContain('Hello');
	});

	it('shows dots for non-printable ASCII', () => {
		// 0x01 0x02 0x41 (A)
		const data = '010241';
		const { container } = render(HexDump, { props: { rawHex: data } });
		expect(container.textContent).toContain('..A');
	});
});
```

**Step 2: Run test to verify it fails**

```bash
cd web && npx vitest run src/lib/components/tshark/HexDump.test.ts
```

Expected: FAIL

**Step 3: Implement HexDump**

Create `web/src/lib/components/tshark/HexDump.svelte`:

```svelte
<script lang="ts">
	interface Props {
		rawHex?: string | null;
		highlightStart?: number;
		highlightEnd?: number;
	}

	let { rawHex = null, highlightStart = -1, highlightEnd = -1 }: Props = $props();

	interface HexRow {
		offset: string;
		hexPairs: string[];
		ascii: string;
	}

	let rows = $derived<HexRow[]>(parseHex(rawHex));

	function parseHex(hex: string | null | undefined): HexRow[] {
		if (!hex) return [];

		const clean = hex.replace(/\s/g, '');
		const bytes: number[] = [];
		for (let i = 0; i < clean.length; i += 2) {
			bytes.push(parseInt(clean.substring(i, i + 2), 16));
		}

		const result: HexRow[] = [];
		for (let i = 0; i < bytes.length; i += 16) {
			const chunk = bytes.slice(i, i + 16);
			const offset = i.toString(16).padStart(4, '0');
			const hexPairs = chunk.map((b) => b.toString(16).padStart(2, '0'));
			const ascii = chunk
				.map((b) => (b >= 0x20 && b <= 0x7e ? String.fromCharCode(b) : '.'))
				.join('');
			result.push({ offset, hexPairs, ascii });
		}
		return result;
	}
</script>

<div class="hex-dump">
	{#if rows.length === 0}
		<div class="empty-state">
			<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
				<rect x="2" y="3" width="20" height="18" rx="2" />
				<line x1="8" y1="7" x2="16" y2="7" />
				<line x1="8" y1="11" x2="16" y2="11" />
				<line x1="8" y1="15" x2="12" y2="15" />
			</svg>
			<span>Select a packet to view hex dump</span>
		</div>
	{:else}
		<div class="hex-content">
			{#each rows as row, rowIdx}
				<div class="hex-row">
					<span class="hex-offset">{row.offset}</span>
					<span class="hex-bytes">
						{#each row.hexPairs as pair, pairIdx}
							{@const byteOffset = rowIdx * 16 + pairIdx}
							<span
								class="hex-byte"
								class:highlighted={byteOffset >= highlightStart && byteOffset < highlightEnd}
							>{pair}</span>
							{#if pairIdx === 7}<span class="hex-gap"></span>{/if}
						{/each}
					</span>
					<span class="hex-ascii">{row.ascii}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.hex-dump {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-secondary);
		height: 100%;
		overflow-y: auto;
		font-family: var(--font-mono);
		font-size: 12px;
		line-height: 1.6;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-2xl) var(--space-lg);
		color: var(--text-muted);
		font-size: var(--text-sm);
		font-family: var(--font-sans, sans-serif);
		text-align: center;
	}

	.empty-state svg {
		opacity: 0.5;
	}

	.hex-content {
		padding: var(--space-sm) var(--space-md);
	}

	.hex-row {
		display: flex;
		gap: var(--space-md);
		white-space: pre;
	}

	.hex-offset {
		color: var(--text-muted);
		flex-shrink: 0;
		width: 4ch;
	}

	.hex-bytes {
		flex-shrink: 0;
		display: flex;
		gap: 4px;
	}

	.hex-gap {
		width: 4px;
	}

	.hex-byte {
		color: var(--text-primary);
	}

	.hex-byte.highlighted {
		background: var(--accent-muted);
		color: var(--accent);
		border-radius: 2px;
	}

	.hex-ascii {
		color: var(--text-secondary);
		flex-shrink: 0;
	}
</style>
```

**Step 4: Run test to verify it passes**

```bash
cd web && npx vitest run src/lib/components/tshark/HexDump.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/components/tshark/HexDump.svelte web/src/lib/components/tshark/HexDump.test.ts
git commit -m "feat(tshark): add HexDump component for raw packet byte display"
```

---

## Task 5: PanelManager Component

**Files:**
- Create: `web/src/lib/components/tshark/PanelManager.svelte`
- Test: `web/src/lib/components/tshark/PanelManager.test.ts`

**Step 1: Write the test**

Create `web/src/lib/components/tshark/PanelManager.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import PanelManager from './PanelManager.svelte';

// Sample packet data
const samplePackets = [
	{
		'frame.number': '1',
		'ip.src': '192.168.1.10',
		'ip.dst': '8.8.8.8',
		protocol: 'DNS',
		'frame.len': '74',
		info: 'Standard query A google.com',
	},
];

describe('PanelManager', () => {
	it('renders all three panel title bars', () => {
		render(PanelManager, {
			props: {
				packets: samplePackets,
				loading: false,
				selectedPacket: null,
				selectedPacketIndex: -1,
				onPacketSelect: vi.fn(),
			},
		});

		expect(screen.getByText('Packet Table')).toBeInTheDocument();
		expect(screen.getByText('Protocol Tree')).toBeInTheDocument();
		expect(screen.getByText('Hex Dump')).toBeInTheDocument();
	});

	it('renders PacketTable with packets data', () => {
		const { container } = render(PanelManager, {
			props: {
				packets: samplePackets,
				loading: false,
				selectedPacket: null,
				selectedPacketIndex: -1,
				onPacketSelect: vi.fn(),
			},
		});

		// PacketTable should render source IP
		expect(screen.getByText('192.168.1.10')).toBeInTheDocument();
	});

	it('shows protocol tree empty state when no packet selected', () => {
		render(PanelManager, {
			props: {
				packets: samplePackets,
				loading: false,
				selectedPacket: null,
				selectedPacketIndex: -1,
				onPacketSelect: vi.fn(),
			},
		});

		expect(screen.getByText(/select a packet to view protocol/i)).toBeInTheDocument();
	});
});
```

**Step 2: Run test to verify it fails**

```bash
cd web && npx vitest run src/lib/components/tshark/PanelManager.test.ts
```

Expected: FAIL

**Step 3: Implement PanelManager**

Create `web/src/lib/components/tshark/PanelManager.svelte`:

```svelte
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
	let topSplitPercent = $state(40); // packet table height %
	let bottomSplitPercent = $state(60); // protocol tree width %

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
		// Managed via style binding on each floating panel
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
	<!-- Top: Packet Table -->
	{#if tablePanelMode !== 'floating'}
		<div class="top-panel" style="height: {tablePanelMode === 'maximized' ? '100' : tablePanelMode === 'minimized' ? 'auto' : topSplitPercent}%;">
			<DockPanel title="Packet Table" panelId="table" mode={tablePanelMode} onaction={handlePanelAction}>
				<PacketTable
					{packets}
					{loading}
					onselect={onPacketSelect}
					{selectedPacketIndex}
				/>
			</DockPanel>
		</div>
	{/if}

	<!-- Horizontal divider -->
	{#if tablePanelMode === 'docked' && (treePanelMode === 'docked' || hexPanelMode === 'docked')}
		<ResizeDivider direction="horizontal" ondrag={handleHorizontalDrag} />
	{/if}

	<!-- Bottom: Protocol Tree + Hex Dump side by side -->
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

	<!-- Floating panels -->
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
			<PacketTable {packets} {loading} onselect={onPacketSelect} {selectedPacketIndex} />
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
```

**Step 4: Run test to verify it passes**

```bash
cd web && npx vitest run src/lib/components/tshark/PanelManager.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/components/tshark/PanelManager.svelte web/src/lib/components/tshark/PanelManager.test.ts
git commit -m "feat(tshark): add PanelManager layout orchestrator with 3-pane split"
```

---

## Task 6: Integrate PanelManager into AnalysisPanel

**Files:**
- Modify: `web/src/lib/components/tshark/AnalysisPanel.svelte`

**Step 1: Update AnalysisPanel imports and template**

In `web/src/lib/components/tshark/AnalysisPanel.svelte`:

1. Replace imports — remove `PacketTable` and `ProtocolTree` imports, add `PanelManager`:

```typescript
// REMOVE these two imports:
// import PacketTable from './PacketTable.svelte';
// import ProtocolTree from './ProtocolTree.svelte';

// ADD:
import PanelManager from './PanelManager.svelte';
```

2. Replace the results layout section (lines 379-392) with:

```svelte
	<!-- 3-pane results layout -->
	<div class="results-layout">
		<PanelManager
			packets={result?.packets ?? []}
			{loading}
			selectedPacket={selectedPacket}
			{selectedPacketIndex}
			onPacketSelect={handlePacketSelect}
		/>
	</div>
```

3. Replace the `.results-layout` CSS (lines 518-523) with:

```css
	.results-layout {
		flex: 1;
		min-height: 500px;
		position: relative;
	}
```

4. Remove these CSS rules that are no longer needed:
   - `.results-table-section` (line 525-527)
   - `.results-detail-section` (line 529-531)
   - The `@media (max-width: 1024px)` rule that sets `grid-template-columns: 1fr` (lines 652-656)

**Step 2: Run all tests**

```bash
cd web && npx vitest run
```

Expected: ALL PASS (existing PacketTable tests still pass since PacketTable is unchanged)

**Step 3: Commit**

```bash
git add web/src/lib/components/tshark/AnalysisPanel.svelte
git commit -m "refactor(tshark): replace fixed 2-panel grid with PanelManager 3-pane layout"
```

---

## Task 7: Update PacketTable — Remove Fixed max-height

**Files:**
- Modify: `web/src/lib/components/tshark/PacketTable.svelte:182-183`

**Step 1: Update the CSS**

In `web/src/lib/components/tshark/PacketTable.svelte`, change `.table-scroll` (line 182):

```css
	.table-scroll {
		overflow: auto;
		/* max-height removed — PanelManager controls sizing */
		height: 100%;
	}
```

**Step 2: Run PacketTable tests**

```bash
cd web && npx vitest run src/lib/components/tshark/PacketTable.test.ts
```

Expected: PASS

**Step 3: Commit**

```bash
git add web/src/lib/components/tshark/PacketTable.svelte
git commit -m "refactor(tshark): remove fixed max-height from PacketTable (PanelManager controls sizing)"
```

---

## Task 8: Update ProtocolTree — Remove Fixed max-height

**Files:**
- Modify: `web/src/lib/components/tshark/ProtocolTree.svelte:172-178`

**Step 1: Update the CSS**

In `web/src/lib/components/tshark/ProtocolTree.svelte`, change `.protocol-tree` (line 172):

```css
	.protocol-tree {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background-color: var(--bg-secondary);
		overflow-y: auto;
		/* max-height removed — PanelManager controls sizing */
		height: 100%;
	}
```

**Step 2: Run all tests**

```bash
cd web && npx vitest run
```

Expected: PASS

**Step 3: Commit**

```bash
git add web/src/lib/components/tshark/ProtocolTree.svelte
git commit -m "refactor(tshark): remove fixed max-height from ProtocolTree (PanelManager controls sizing)"
```

---

## Task 9: Run Full Test Suite + Svelte Check

**Step 1: Run all Vitest tests**

```bash
cd web && npx vitest run
```

Expected: ALL PASS

**Step 2: Run svelte-check**

```bash
cd web && npx svelte-check
```

Expected: No errors (warnings OK)

**Step 3: Commit any fixes if needed**

If any TypeScript or Svelte errors are found, fix them and commit:

```bash
git add -A
git commit -m "fix(tshark): resolve type/lint issues from panel redesign"
```

---

## Task 10: Daemon API — Add Hex Dump Support (Optional Enhancement)

> **Note:** This task adds `-x` flag support to the TShark daemon API for raw hex data. The hex dump panel works without this (shows empty state), so this can be deferred.

**Files:**
- Modify: `daemon/services/tshark_service.py:44-50` (TSharkRequest dataclass)
- Modify: `daemon/services/tshark_service.py:172-198` (`_build_tshark_command`)
- Modify: `daemon/api/tshark.py:29-37` (handle_tshark_analyze)
- Modify: `web/src/lib/api/tshark.ts:11-17` (TSharkAnalyzeRequest)

**Step 1: Add `include_hex` to TSharkRequest**

In `daemon/services/tshark_service.py`, update the `TSharkRequest` dataclass (line ~48):

```python
@dataclass
class TSharkRequest:
    pcap_path: str
    display_filter: str = ""
    max_packets: int = DEFAULT_MAX_PACKETS
    output_format: str = "json"
    fields: list[str] = field(default_factory=list)
    include_hex: bool = False
```

**Step 2: Add `-x` flag to command builder**

In `_build_tshark_command` (line ~192, before the return):

```python
        # Hex dump flag
        if request.include_hex:
            cmd.append("-x")
```

**Step 3: Pass `include_hex` from API handler**

In `daemon/api/tshark.py`, update `handle_tshark_analyze` (line ~33):

```python
        req = TSharkRequest(
            pcap_path=body.get("pcap_path", ""),
            display_filter=body.get("display_filter", ""),
            max_packets=int(body.get("max_packets", 100)),
            output_format=body.get("output_format", "json"),
            fields=body.get("fields", []),
            include_hex=bool(body.get("include_hex", False)),
        )
```

**Step 4: Update TypeScript API type**

In `web/src/lib/api/tshark.ts`, update `TSharkAnalyzeRequest`:

```typescript
export interface TSharkAnalyzeRequest {
	pcap_path: string;
	display_filter?: string;
	max_packets?: number;
	output_format?: 'json' | 'text';
	fields?: string[];
	include_hex?: boolean;
}
```

**Step 5: Run daemon tests**

```bash
cd daemon && python -m pytest -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add daemon/services/tshark_service.py daemon/api/tshark.py web/src/lib/api/tshark.ts
git commit -m "feat(tshark): add include_hex flag for hex dump data via -x"
```

---

## Summary of All New/Modified Files

| Action | File |
|--------|------|
| Create | `web/src/lib/components/tshark/ResizeDivider.svelte` |
| Create | `web/src/lib/components/tshark/ResizeDivider.test.ts` |
| Create | `web/src/lib/components/tshark/DockPanel.svelte` |
| Create | `web/src/lib/components/tshark/DockPanel.test.ts` |
| Create | `web/src/lib/components/tshark/FloatingPanel.svelte` |
| Create | `web/src/lib/components/tshark/FloatingPanel.test.ts` |
| Create | `web/src/lib/components/tshark/HexDump.svelte` |
| Create | `web/src/lib/components/tshark/HexDump.test.ts` |
| Create | `web/src/lib/components/tshark/PanelManager.svelte` |
| Create | `web/src/lib/components/tshark/PanelManager.test.ts` |
| Modify | `web/src/lib/components/tshark/AnalysisPanel.svelte` |
| Modify | `web/src/lib/components/tshark/PacketTable.svelte` |
| Modify | `web/src/lib/components/tshark/ProtocolTree.svelte` |
| Modify | `daemon/services/tshark_service.py` |
| Modify | `daemon/api/tshark.py` |
| Modify | `web/src/lib/api/tshark.ts` |
