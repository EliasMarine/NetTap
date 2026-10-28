# Packet Analysis Redesign — Docked Layout with Pop-Out Floating Panels

**Date:** 2026-03-08
**Branch:** phase-4/webui-v2
**Status:** Approved

## Problem

The current packet analysis page uses a fixed `1fr 380px` CSS grid that splits the packet table and protocol tree side-by-side. This wastes vertical space, gives the protocol tree only 380px width (too narrow for long field values), and provides no way to resize or rearrange panels. There is also no hex dump view.

## Design

### Layout: Wireshark-Inspired 3-Pane with Draggable Dividers

```
┌─────────────────────────────────────────────────────┐
│ ← Back to Tools    Packet Analysis    ● TShark 4.x ↻│
├─────────────────────────────────────────────────────┤
│ Controls: PCAP path, format, max packets, filter     │  ← collapsible
├═══════════════════ divider H1 ══════════════════════╡
│ Packet Table (full width, ~40% height)               │
├═══════════════════ divider H2 ══════════════════════╡
│ Protocol Tree (60%)  │ divider V1 │ Hex Dump (40%)   │
└──────────────────────┴────────────┴──────────────────┘
```

### Panel Title Bars

Each of the 3 panels (Packet Table, Protocol Tree, Hex Dump) gets a slim title bar with action buttons:

| Icon | Action |
|------|--------|
| Maximize | Panel takes full results area, others collapse |
| Pop out | Panel becomes a floating, draggable, resizable overlay |
| Minimize | Panel collapses to just its title bar |

### Floating (Pop-Out) Behavior

- Panel detaches from grid, becomes absolute-positioned overlay
- Default float size: 600x400px, centered on viewport
- Draggable by title bar (pointer events)
- Resizable by dragging edges/corners
- Original grid slot shows "(popped out)" placeholder
- Click pop-out button again or close button to re-dock
- Z-index: last-clicked float goes on top

### Resizable Dividers

Three draggable dividers:
- **H1:** Between controls and packet table (controls collapse to ~40px)
- **H2:** Between packet table and bottom panels (default 40/60 split)
- **V1:** Between protocol tree and hex dump (default 60/40 split)

Implementation: `onpointerdown` → track drag → `onpointermove` → update CSS custom properties for split percentages → `onpointerup` → commit.

### Hex Dump Panel (New)

Classic hex editor format for the selected packet:
- Left column: byte offset (0000, 0010, 0020...)
- Middle: hex bytes, 16 per row, grouped in pairs
- Right: ASCII printable characters (`.` for non-printable)
- Highlights bytes for the protocol layer hovered in the Protocol Tree
- Data source: `frame_raw` field from TShark JSON (when available)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Focus packet table |
| `2` | Focus protocol tree |
| `3` | Focus hex dump |
| `Esc` | Dock all floating panels |
| `Up/Down` | Navigate packets in table |

## Component Architecture

```
AnalysisPanel.svelte (orchestrator — controls + layout manager)
  ├── Controls section (inline, collapsible)
  ├── PanelManager.svelte (manages layout splits, floating state)
  │     ├── DockPanel.svelte (wraps each panel with title bar + actions)
  │     │     ├── PacketTable.svelte (existing, minor prop changes)
  │     │     ├── ProtocolTree.svelte (existing, add hover callback)
  │     │     └── HexDump.svelte (new)
  │     └── ResizeDivider.svelte (horizontal/vertical drag handles)
  └── FloatingPanel.svelte (draggable overlay wrapper)
```

### New Files
- `web/src/lib/components/tshark/PanelManager.svelte`
- `web/src/lib/components/tshark/DockPanel.svelte`
- `web/src/lib/components/tshark/FloatingPanel.svelte`
- `web/src/lib/components/tshark/ResizeDivider.svelte`
- `web/src/lib/components/tshark/HexDump.svelte`

### Modified Files
- `web/src/lib/components/tshark/AnalysisPanel.svelte` — replace fixed grid with PanelManager
- `web/src/lib/components/tshark/ProtocolTree.svelte` — add `onhover` callback for hex highlighting
- `web/src/lib/components/tshark/PacketTable.svelte` — remove fixed max-height (PanelManager controls sizing)

## Design Decisions

- **No external library** — custom pointer-event drag logic (~200 lines total for resize + float). Keeps bundle small and avoids dependency risk.
- **Protocol tree gets 60% of bottom split** — user identified protocol detail as the primary panel.
- **Controls stay inline** (not a panel) — they're used briefly then collapsed. No need for drag/float.
- **Hex dump data** — requires TShark `-x` flag or `frame_raw` in JSON output. Will need a small daemon API change to pass `-x` when hex dump is visible.
