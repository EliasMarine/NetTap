# Digital Sentinel SIEM: Technical Design Documentation

This document provides the architectural and stylistic blueprint for the Digital Sentinel SIEM, specifically focusing on the **SOC Command Center (Dashboard)** and the **Incident Investigation** views.

## 1. Core Visual Language (The "Digital Sentinel" Theme)

The design system utilizes a high-contrast, "cyber-noir" aesthetic optimized for 24/7 SOC operations.

*   **Primary Background:** `#10131a` (Deep Charcoal/Black)
*   **Secondary Background (Cards/Panels):** `#161a23`
*   **Accent/Primary Color:** `#00D1FF` (Cyan Pulse)
*   **Critical Alert:** `#FF4B5C` (Soft Neon Red)
*   **High Alert:** `#FFB302` (Amber)
*   **Medium Alert:** `#4ADE80` (Emerald)
*   **Typography:** `Space Grotesk` (System font fallback: sans-serif).
*   **Border Radius:** `4px` (Rigid, professional feel).

---

## 2. Shared Global Components

### Top Navigation Bar (`TopNavBar`)
**Structure:** Logo (Left) | Search Bar (Center) | System Status & Profile (Right)
*   **Container:** `flex justify-between items-center w-full px-6 h-16 bg-[#10131a] border-b border-[#3c494e]/20 shadow-[0_0_15px_rgba(0,209,255,0.1)]`
*   **Logo Text:** `text-xl font-bold tracking-tighter text-[#00d1ff] uppercase font-['Space_Grotesk']`
*   **Search Input:** `bg-[#1c212b] border border-[#3c494e]/40 rounded px-4 py-2 text-sm text-[#bbc9cf] focus:outline-none focus:border-[#00d1ff]`

### Side Navigation Bar (`SideNavBar`)
**Structure:** Icon-based vertical rail with expandable labels.
*   **Container:** `fixed left-0 top-0 h-full w-20 bg-[#10131a] border-r border-[#3c494e]/20 flex flex-col items-center py-6`
*   **Active Tab:** `bg-[#32353c] text-[#00d1ff] border-l-4 border-[#00d1ff]`
*   **Icons:** Material Symbols Outlined, `text-2xl`.

---

## 3. Screen 1: SOC Command Center (Dashboard Overview)
**Reference:** {{DATA:SCREEN:SCREEN_2}}

### A. Metric Key Performance Indicators (KPIs)
*   **Card Wrapper:** `bg-[#161a23] border-b-2 border-[#00d1ff]/30 p-5 rounded-sm relative overflow-hidden`
*   **Metric Value:** `text-4xl font-bold text-white tracking-tight`
*   **Trend Indicator:** `text-xs font-medium ml-2 uppercase` (e.g., `text-[#4ade80]` for positive MTTR reduction).

### B. Real-Time Threat Intelligence (Table)
*   **Container:** `bg-[#161a23] p-6 rounded-sm border border-[#3c494e]/10`
*   **Row Hover:** `hover:bg-[#1c212b] transition-colors duration-150`
*   **Severity Badges:**
    *   *Critical:* `bg-[#FF4B5C]/20 text-[#FF4B5C] border border-[#FF4B5C]/40 px-2 py-0.5 rounded text-[10px] font-bold`
    *   *High:* `bg-[#FFB302]/20 text-[#FFB302] border border-[#FFB302]/40 ...`

### C. Geo-Spatial Threat Vector (Map)
*   **Overlay:** Dark-mode grayscale map with pulse animations on origin/destination nodes.
*   **Node Pulse:** `animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00d1ff] opacity-75`

---

## 4. Screen 2: Incident Investigation View
**Reference:** {{DATA:SCREEN:SCREEN_5}}

### A. Investigation Header
*   **Incident ID:** `text-3xl font-bold text-white font-['Space_Grotesk'] uppercase`
*   **Action Button (Assign):** `bg-[#00d1ff] hover:bg-[#00b8e6] text-[#10131a] font-bold py-2 px-6 rounded uppercase tracking-wider text-sm`

### B. Entity Relationship Graph
*   **Node Wrapper:** `bg-[#1c212b] border border-[#3c494e]/50 p-4 rounded flex flex-col items-center gap-2`
*   **Active Node:** `border-[#00d1ff] shadow-[0_0_15px_rgba(0,209,255,0.3)]`
*   **Connecting Lines:** `stroke-[#00d1ff]/20 stroke-[1px] stroke-dasharray-[4]`

### C. Evidence Locker (File List)
*   **Table Header:** `text-[#7c8b91] text-xs uppercase tracking-widest border-b border-[#3c494e]/20 pb-2`
*   **File Row:** `flex items-center justify-between py-3 border-b border-[#3c494e]/10 hover:bg-[#1c212b]/50`

---

## 5. CSS Utility Classes Summary (Tailwind)

| Category | Classes |
| :--- | :--- |
| **Borders** | `border-[#3c494e]/20` (Low opacity for subtle depth) |
| **Backgrounds** | `bg-[#10131a]` (App Frame), `bg-[#161a23]` (Panels) |
| **Glows** | `shadow-[0_0_15px_rgba(0,209,255,0.15)]` |
| **Animations** | `transition-all duration-300 ease-in-out` |
| **Typography** | `font-['Space_Grotesk']`, `tracking-tighter` (Logo), `tracking-widest` (Headers) |
