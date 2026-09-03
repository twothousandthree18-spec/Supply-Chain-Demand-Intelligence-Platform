# Design System

**Phase 0 — Visual identity. Applies to both the Power BI dashboard and the web application.**

The visual identity MUST match the existing professional portfolio family used by:
- **Retail Analytics & Customer Intelligence**
- **AI Job Market & Workforce Intelligence**

The layout/content may differ, but the design system must remain consistent. Do NOT invent a new palette.

## 1. Exact Color Palette (tokens)

| Token | Hex | Usage |
|---|---|---|
| `--color-obsidian` | `#090B0A` | Primary background, dark surfaces, text-on-light emphasis. |
| `--color-deep-jade` | `#123C35` | Secondary dark surface, header/footer bands, emphasized panels, charts. |
| `--color-electric-jade` | `#19E6B1` | Primary accent, key actions, positive/forecast highlights, interactive elements. |
| `--color-champagne` | `#D8C39B` | Secondary accent, callouts, warnings/neutral emphasis, section labels. |
| `--color-soft-white` | `#EDEFEA` | Primary text on dark, page background on light surfaces. |

**Rule:** These are the ONLY brand colors. Do not substitute an invented palette. (Semantic states like `success/``warning`/`danger` may be derived from these tokens conservatively and documented.)

## 2. Typography Strategy

- **Headings/Display:** a modern geometric/sans or clean serif for the professional data-analysis look; consistent letter-spacing and weight hierarchy.
- **Body/Data:** a highly readable sans-serif (system or loaded font) — crisp numerals for KPIs/tables.
- **Monospace** reserved for code/reproducibility notes.
- Typographic scale: fixed set of sizes (display / H1–H4 / body / caption / numeric) used consistently across Power BI and web.

## 3. Spacing Principles

- A base spacing unit drives all gaps and padding (e.g., 4px grid).
- Generous whitespace around data panels to reduce visual noise and emphasize the narrative.
- Consistent padding within cards/panels.

## 4. Card / Panel Principles

- Cards on Obsidian or Soft-White surfaces with Deep-Jade as secondary panel backgrounds.
- Electric-Jade used sparingly for the primary accent/CTAs and key metrics.
- Each card has a clear title, one main message, supporting subtitle, and a footer/source label.
- Data-provenance chips (Observed / Derived / Simulated) shown where relevant.

## 5. Chart Principles

- Consistent color mapping across the whole product (structure = Deep-Jade/Champagne, accent = Electric-Jade, emphasis = Electric-Jade highlights).
- Charts are communication-first: clear titles, direct labels, no chartjunk, consistent axis formatting.
- One message per chart; annotations for the key insight.
- Forecast confidence shown as bands; simulated values visually distinguished from observed.

## 6. Responsive Principles

- Mobile-first layout: single-column on small screens, multi-column panels on larger screens.
- Cards/kpi tiles reflow without loss of message.
- Tables scroll horizontally on narrow screens; charts maintain legibility.
- Consistent breakpoints and spacing across the web app.

## 7. Consistency Mandate

All future build phases (Power BI theme, web CSS variables, reports) MUST reference these tokens. Any new component reuses the system; nothing introduces an off-palette color.
