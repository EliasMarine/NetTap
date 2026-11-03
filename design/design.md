# Design System Document

## 1. Overview & Creative North Star: "The Digital Sentinel"

This design system is engineered for high-stakes environments where precision meets rapid intuition. Moving away from the cluttered "dashboard-as-a-spreadsheet" trope, our Creative North Star is **The Digital Sentinel**. This philosophy treats data as a living tactical landscape rather than a static report.

We break the "template" look by leveraging a **Luminous Depth** strategy. Instead of flat cards on a flat background, the interface uses a hierarchy of darkness and light to pull the user's eye toward critical threats. We utilize intentional asymmetry in data visualization and overlapping glass-morphism panels to create a sense of sophisticated, multi-layered intelligence. The goal is to make the analyst feel they are peering into a high-powered lens, not just a web browser.

---

## 2. Colors

The palette is anchored in deep, atmospheric neutrals to minimize eye strain during 24/7 SOC operations, accented by high-energy tactical signals.

### Core Palette
* **Background (`#10131a`):** The "Infinite Void"—a deep, charcoal-navy that serves as the canvas.
* **Primary / Cyber Blue (`#a4e6ff` / `#00d1ff`):** Used for active intelligence, focus states, and primary actions. It represents "The Beam" that cuts through the noise.
* **Secondary / Emerald Green (`#66dd8b`):** Represents "Stasis" or healthy system flow.
* **Tertiary / Crimson & Amber (`#ffb4ab` & `#ffaaa4`):** Specifically reserved for "Anomalies" and "Breaches."

### Surface Hierarchy & Nesting
To create an elite editorial feel, we abandon the "grid-of-boxes" look in favor of **Tonal Nesting**:
* **The "No-Line" Rule:** Do not use 1px solid borders to define major sections. Sectioning is achieved by shifting from `surface` to `surface-container-low` or `surface-container-lowest`.
* **Layering:** High-priority modules (like active alerts) should utilize `surface-container-highest` (`#32353c`) to physically "lift" toward the user.
* **The "Glass & Gradient" Rule:** Use `surface-tint` (`#4cd6ff`) at 5-10% opacity with a `backdrop-blur` of 12px for floating command bars or modals. Apply a subtle linear gradient (from `primary` to `primary-container`) on hero metrics to give them a "holographic" quality.

---

## 3. Typography

The typography strategy is a dual-engine system: **Humanist Editorial** for context and **Hard-Monospace** for technical certainty.

* **Display & Headlines (Space Grotesk):** This typeface provides a futuristic, slightly wide-tracked feel. Its geometric nature feels engineered. Use `display-lg` for critical system-wide status counts.
* **Body & Titles (Inter):** A neutral, highly legible Swiss-style face for reading logs and descriptions.
* **The "Technical Precision" Rule:** All data values, IP addresses, and timestamps must use a monospaced variant or a high-tracking `label-md` style. This ensures that numbers align perfectly in vertical columns, allowing for rapid scanning of anomalies in data sets.
* **Hierarchy:** Use high-contrast sizing (e.g., `headline-lg` next to a `label-sm`) to create an "Editorial" layout that emphasizes what matters most.

---

## 4. Elevation & Depth

We eschew traditional drop shadows for **Ambient Tonal Layering**.

* **The Layering Principle:** Depth is communicated by stacking. A `surface-container-low` section sits on the `surface` background. A `surface-container-highest` card sits inside that. This creates "soft" containment without visual clutter.
* **Ambient Shadows:** For "floating" elements like context menus, use a 32px blur with the shadow color set to a 15% opacity version of `primary-fixed-dim`. This mimics the "glow" of a high-tech screen.
* **The "Ghost Border":** Where containment is vital for accessibility, use the `outline-variant` (`#3c494e`) at 20% opacity. It should feel like a suggestion of a boundary, not a hard cage.
* **Glow Effects:** Critical alerts (`error_container`) should possess a subtle outer glow using the `error` color at low opacity to simulate an emergency beacon.

---

## 5. Components

### Buttons
* **Primary:** Solid `primary-container` with `on-primary-container` text. Use `rounded-sm` (0.125rem) to maintain a "hard-tech" edge.
* **Ghost:** `outline` color with no fill; transitions to a subtle `primary` glow on hover.

### Cards & Lists
* **Prohibition of Dividers:** Do not use lines to separate list items. Use the **Spacing Scale** (specifically `spacing-2` or `spacing-3`) to create white space or alternating backgrounds using `surface-container-low` and `surface-container-lowest`.
* **Card Styling:** Cards should have a `rounded-md` (0.375rem) corner and utilize the `surface-container` background. High-priority cards get a top-edge "accent line" of 2px in the alert color (`error` or `secondary`).

### Technical Inputs
* **Text Fields:** Use `surface-container-highest` for the input bed. The focus state shouldn't just change the border color; it should increase the background brightness slightly to indicate activity.

### Additional Components: "The Pulse"
* **Status Micro-Glows:** Instead of static dots, use a breathing animation (4s cycle) on "Healthy" or "Warning" indicators to show the system is actively monitoring.

---

## 6. Do's and Don'ts

### Do:
* **Do** use asymmetrical layouts. Let a large metric column sit next to a dense, small-text log column to create visual interest.
* **Do** use monospaced fonts for all quantitative data.
* **Do** use the `spacing-10` and `spacing-16` values to allow the interface to "breathe"—sophistication is found in the gaps.

### Don't:
* **Don't** use 100% white. Use `on-surface-variant` (`#bbc9cf`) for secondary text to maintain the dark-room optimization.
* **Don't** use standard "drop shadows." If it doesn't look like light is emitting from the screen, it's too traditional.
* **Don't** use generic icons. Use thin-stroke, technical iconography that matches the `outline` weight.
