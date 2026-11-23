# Build Prompt 2 of 6: F1 Control Room UI Revamp

## Role and goal

You are a senior frontend engineer and designer rebuilding the F1 Control Room web app. The goal is a fast telemetry tool that makes an F1 fan, or a hiring manager, stop scrolling. It should have:

- a clickable track map that drives every chart;
- a telemetry lab;
- the Chaos Point preview;
- a stewards chat;
- one 3D showcase page.

Load these skills first (see `00_RESOURCES_AND_SKILLS.md`): `frontend-design` (aesthetic direction), `astryx` (components and templates), `webapp-testing` (Playwright checks), `theme-factory` (tokens).

**If a frontend already exists:** keep its routing and data layer, and migrate page by page. **If not:** create `frontend/` as a Next.js (App Router, TypeScript) app.

## Stack

| Concern | Choice | Notes |
|---|---|---|
| Framework | Next.js + React 19 + TypeScript | `output: "standalone"` for Docker |
| Components and layout | **Astryx** (`@astryxdesign/core`, CLI, a theme, `@stylexjs/stylex`) | Start every page from `astryx build "<page purpose>"`, then `astryx template`. It's in beta, so pin exact versions. Don't use Astryx charts (canary only). |
| Telemetry charts | **uPlot** | One plot per channel (speed, throttle, brake, gear, RPM, DRS), stacked, with a shared synced cursor and x-axis = distance |
| Other charts | **ECharts** | Stints and tyre strategy, standings, positions chart, chaos heat strip, calibration plot |
| Track map | **SVG + d3-zoom + d3-shape** | Mini-sector paths as separate `<path>` elements for hit-testing and hover |
| 3D | **react-three-fiber + drei** | Showcase page only. Lazy-load it. |
| Data | TanStack Query | A web worker parses columnar telemetry, so React never sits in the redraw path |
| AI states | **thinking-orbs** | `searching` while retrieving, `solving` while the agent reasons, `composing` while streaming |
| Motion | Framer Motion | Page transitions, panel reveals |

## Design direction

- **Dark-first.** Charcoal (`#15161A` range) and warm sand neutrals, with **F1 red only on primary actions and live states** (the two-plus-one palette rule).
- **Team colours** for driver series, from the API. Fall back to an accessible palette when two teammates share a colour: dash the second driver.
- **Type:** a condensed display face for headings, giving a timing-screen feel, and tabular numerals everywhere numbers align (`font-variant-numeric: tabular-nums`).
- **Data-ink first.** No chart junk. Gridlines at 8% opacity. Annotate corners (T1, T2…) along the distance axis.
- **Accessibility:** keyboard navigation of mini-sectors (arrow keys), visible focus, WCAG AA contrast, and `prefers-reduced-motion` respected (orbs and 3D pause).

## Pages

### 1. Race hub (`/races/[year]/[round]`)

- **Left (60%): track map.**
  - Mini-sectors coloured by the fastest driver among the selected ones, with corner numbers and DRS zones as dashed overlays.
  - Hover shows the segment's time per driver.
  - Clicking a segment selects that distance range and opens the Telemetry lab zoomed to it.
- **Right: Chaos meter.**
  - A big Chaos Index number with its p10–p90 band.
  - Per-target bars (SC/VSC/red, mechanical DNF, incident DNF, slow stop).
  - A lap-window heat strip below.
  - A "How is this calculated?" link to the model page.
- **Tabs below:** Results, Strategy (ECharts stint bars by compound), Positions (lap chart), Weather, Incidents timeline.
- **Data:** `track-map`, `mini-sectors`, `chaos/races/<y>/<r>/`, and the existing results, stints and weather endpoints.

### 2. Telemetry lab (`/races/[year]/[round]/telemetry`)

- Driver picker (2–4 drivers) and lap picker (fastest, or a specific lap).
- **Delta trace on top**, from the new `telemetry/delta` endpoint, then the stacked uPlot channels.
- A mini track map in the corner highlights the cursor's position on the track as you scrub.
- Brush on the distance axis, or click a mini-sector, to request `start_m`/`end_m` with `format=columnar` and `channels=...`, then zoom all plots.
- **Performance:** request columnar JSON, decode in a worker, use min/max per-pixel decimation for wide ranges, and keep everything at 60 fps while scrubbing.

### 3. Chaos (`/chaos`)

- **Upcoming race preview:**
  - Index, per-target probabilities with bands;
  - top factors (from feature attributions or a simple "vs circuit average" comparison);
  - lap-window risk strip.
- **Circuit history:** a small-multiples grid of every circuit's SC, DNF and red-flag rates, sortable.
- **Driver profile:** DNF tendencies and unlucky-stop tendency with wide intervals, labelled "tendency, not skill".
- **Model page:**
  - calibration plot;
  - Brier score and log-loss versus the baseline, by season;
  - a model card covering data, features, NVIDIA Kumo Tabular, limitations and changelog.

### 4. Ask the Stewards (`/stewards`)

- A chat with streaming answers over SSE and an orb state indicator.
- Citations show as chips: clicking one opens a side panel with the exact regulation article or decision page text highlighted.
- Starter prompts, for example "Was the 5-second penalty for X consistent with past decisions?" and "What does Article 33.4 say?"
- Shows "evidence not found" honestly when the answer isn't in the documents.

### 5. 3D replay (`/races/[year]/[round]/3d`)

- The track ribbon is extruded from the X/Y polyline with Z elevation from FastF1 positions. Kerbs are coloured by mini-sector.
- Cars are coloured spheres, interpolated from position data, with play, pause, 1–16× speed and scrub.
- An orbit camera, plus a "follow driver" camera.
- Lazy-loaded, with a static poster fallback on low-power devices.

### Shared components

- `TrackMap`
- `TelemetryStack`
- `DeltaTrace`
- `ChaosMeter`
- `HeatStrip`
- `CitationChip`
- `DriverPicker`
- `LapPicker`
- `OrbStatus`

Each gets a Storybook story if Storybook is set up, or an Astryx sandbox example.

## Docker

`frontend/Dockerfile`:
- multi-stage (`node:22-alpine` deps, then build, then `node server.js` from `.next/standalone`);
- arm64;
- non-root.

Compose service `frontend` sits behind nginx at `/`, with the API at `/api/`.

## Testing (webapp-testing skill)

Playwright flows:

1. Open a 2024 race hub, click mini-sector 7, and confirm the telemetry lab opens with `start_m`/`end_m` in the request.
2. Scrub the telemetry and confirm the track-map marker moves.
3. Ask the stewards a question and confirm streamed text plus at least one citation chip.
4. Load the chaos model page and confirm the calibration chart renders.

Record performance budgets with Lighthouse: race hub LCP under 2.5 s on 4G, and the telemetry lab interaction under 100 ms.

## Definition of done

- All five pages ship, responsive down to 375 px. The 3D page shows its poster on mobile.
- Playwright suite green in CI.
- README screenshots and a 20-second GIF of clicking a mini-sector and the telemetry zooming in.
