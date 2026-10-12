# Tartarus design system

Tartarus uses the cyberpunk terminal look of the developer's red-team project (Momos), recoloured
**ice blue** for blue-team malware analysis. The reference stylesheet is
[tartarus-theme.css](tartarus-theme.css). Copy it into the frontend as `src/css/app.css`.

## Principles

1. **Black void, neon edges.** Surfaces are pure black (`#000`) or near-black. Structure comes
   from 2px translucent ice-blue borders, not from fills or drop shadows.
2. **Sharp corners everywhere.** `--radius: 0` on every component, including Quasar ones.
3. **Glow means focus.** A blue glow (`box-shadow` with the accent at 25–40% alpha) appears only on
   hover, focus or the active element. Never apply it to static content.
4. **Terminal voice.** Use monospace for labels, table headers, identifiers (PIDs, hashes,
   paths, IPs) and the `>` prompt in inputs. Use sans-serif for prose and values people read in
   sentences.
5. **Blue is the interface, warm is the threat.** Ice blue is reserved for UI chrome and
   interaction. Severity and errors always use the warm threat scale (red, orange, amber), so an
   alert is never mistaken for decoration.
6. **Colour is never the only signal.** Severity carries an icon and a label. Event categories
   carry an icon and a lane label.

## Tokens

All tokens are CSS custom properties on `:root` in `tartarus-theme.css`. Only dark mode is
supported, and there is no light theme.

### Surfaces

| Token | Value | Use |
|---|---|---|
| `--black` | `#000000` | Page background, inputs, tables |
| `--dark-bg` | `#0a0a0a` | Panels, cards, code blocks, chart surface |
| `--card-bg` | `#1a1a1a` | Dialogs, menus, tooltips, disabled inputs |

### Accent: ice blue

| Token | Value | Use | Contrast on black |
|---|---|---|---|
| `--blue-primary` | `#38bdf8` | Links, focus borders, active tab, header text, checked checkbox fill | 9.8:1 |
| `--blue-light` | `#7dd3fc` | Link hover, progress gradient end, chip text | 12.6:1 |
| `--blue-lighter` | `#bae6fd` | Code text | 14.9:1 |
| `--blue-hover` | `#0ea5e9` | Hover text on buttons, tabs and radios | 7.6:1 |
| `--blue-dark` | `#0369a1` | `--active-bg`: selected button or radio, with **white** text (5.9:1) | n/a |
| `--blue-darker` | `#0c4a6e` | `--disabled-bg`, scrollbar thumb | n/a |
| `--border-primary` / `-secondary` / `-subtle` | `#38bdf8` at 30% / 50% / 20% | Borders and separators | n/a |
| `--hover-bg` | `#38bdf8` at 10% | Hover fill | n/a |
| `--shadow-blue-{weak,subtle,medium,strong}` | 8 / 10 / 15 / 20px glow | Hover, focus and active glow | n/a |

**Text on filled ice blue must be black** (`--text-on-primary`). White on `#38bdf8` is only
2.1:1. This is the one place where the Momos rule "white on accent" flips.

### Text

| Token | Value | Use | Contrast on black |
|---|---|---|---|
| `--text-white` | `#ffffff` | Primary text | 21:1 |
| `--text-gray-light` | `#e5e5e5` | Quote and secondary prose | n/a |
| `--text-gray` | `#a3a3a3` | Secondary text, idle buttons | 8.3:1 |
| `--text-gray-dark` | `#888888` | Placeholders, timestamps | 5.9:1 |
| `--text-muted` | `#6b7280` | Fine print (≥14px) | 4.3:1 |
| `--text-gray-darker` | `#525252` | Disabled only (not readable text) | 2.7:1 |

### Severity and status (warm threat scale, never themed)

| Token | Value | Meaning | Icon (Material) |
|---|---|---|---|
| `--status-critical` | `#ef4444` | Critical detection, errors, failed analysis | `dangerous` |
| `--status-high` | `#f97316` | High severity, negated filter chips | `warning` |
| `--status-medium` | `#eab308` | Medium severity, warning toasts | `report` |
| `--status-low` | `#94a3b8` | Low severity | `info` |
| `--status-info` | `#a3a3a3` | Informational | `info_outline` |
| `--status-success` / `--status-active` | `#22c55e` | Service up, analysis done, success toast | `check_circle` |

The classes are `.severity-critical`, `.severity-high`, `.severity-medium`, `.severity-low` and
`.severity-informational`. Each sets both `color` and `border-color`.

Severity mapping: CAPE signature severity 1 → low, 2 → medium, 3 → high, ≥4 → critical. Sigma
`level` maps directly; Sigma `informational` → info.

### Event categories (timeline and graph lanes)

These colours identify event *categories*. Their fixed order matches the lane order and was
validated on `--dark-bg` (lightness band, chroma, adjacent-pair CVD ΔE ≥ 8, normal-vision
ΔE ≥ 15, contrast ≥ 3:1). Do not reorder them, and do not add a seventh hue. A new category
goes into the neutral `api`/"other" lane or gets its own facet.

| Lane | Token | Value | Icon |
|---|---|---|---|
| 1. Process | `--cat-process` | `#3987e5` | `terminal` |
| 2. File | `--cat-file` | `#d55181` | `description` |
| 3. Registry | `--cat-registry` | `#2ba82b` | `account_tree` |
| 4. Network | `--cat-network` | `#9085e9` | `lan` |
| 5. Memory | `--cat-memory` | `#199e70` | `memory` |
| 6. API (other) | `--cat-api` | `#8a8a8a` | `functions` |

Rules:
- The API lane is deliberately neutral gray. It is the high-volume background stream, and
  colouring it would drown the other lanes.
- Detections are **not** a category colour. They use the severity scale, drawn as markers above
  the lanes.
- Labels and values stay in text tokens. Never colour text with a category colour; the coloured
  mark beside the text carries the identity.
- Never put category colours in the same small area as severity colours, and pair every mark
  with its lane label.

### Typography

| Token | Value |
|---|---|
| `--font-mono` | `"Courier New", Courier, monospace` |
| `--font-sans` | `system-ui, -apple-system, sans-serif` |

| Role | Font | Size / weight |
|---|---|---|
| Page title | sans | 1.5rem / 600, `--text-white` |
| Section header (`.header-text`) | sans | 1.1rem / 600, `--blue-primary`, 20px left pad |
| Body | sans | 1rem / 400 |
| Settings rows (`.settings-text`) | sans | 16px / 400, line-height 1.2 |
| Field labels (`.floating-label`) | mono | 0.65rem / bold, letter-spacing 1px, `--blue-primary` |
| Table headers | mono | 0.75rem / bold, uppercase, letter-spacing 1px, `--blue-primary` |
| Identifiers (PID, hash, path, IP, API name) | mono | inherit |
| Code / raw event JSON | mono | 0.85rem, `--blue-lighter` on `--dark-bg` |

### Spacing, radius and motion

- Spacing: `--spacing-xs` 0.25rem, `-sm` 0.5rem, `-md` 1rem, `-lg` 1.5rem, `-xl` 2rem. Gaps:
  `.gap-low` 10px, `.gap-mid` 30px, `.gap-high` 60px.
- Radius: `--radius: 0`. No exceptions.
- Motion: `--transition-fast` 150ms for hover and focus, `-normal` 250ms for panels, `-slow`
  350ms for page-level transitions. Press feedback is `transform: scale(0.98)`. Invalid input
  shakes for 0.3s. Respect `prefers-reduced-motion` by disabling the shake, pulse and loader
  rotation.

## Components

Each item below is implemented in `tartarus-theme.css`. Quasar components are themed through
the overrides at the bottom of that file.

| Component | Look and behaviour |
|---|---|
| **Button** (`.button`, `q-btn flat square`) | Black background, gray text. On hover: 10% blue fill and `--blue-hover` text. When active (`.is-active`): `--blue-dark` fill with white text. Primary actions (Submit, Start) use `q-btn` outline in `--blue-primary`. Destructive actions use outline in `--status-critical` and always open a confirm dialog. |
| **Text input** (`.input-field`, `q-input outlined square dark`) | 2px `--border-primary` border, black background, blue caret. On focus: full `--blue-primary` border plus a subtle glow. On error: red border, red glow and a shake. When disabled: `--card-bg` background and dark gray border. |
| **Terminal input** (`.terminal-input-group`) | An input with a mono blue `>` prompt. Used for the **query bar** and the global search. |
| **Floating label** (`.input-wrapper` + `.floating-label`) | A tiny mono uppercase label inside the field's top-left corner, used in dense forms such as the Submit dialog and Settings. |
| **Segmented radio** (`.radio-group`) | Joined buttons with 2px borders that overlap by -2px. The checked one is filled `--blue-dark`. Used for the network route, view mode and timeline zoom. |
| **Checkbox** (`.checkbox-input`) | A 1rem square. When checked: `--blue-primary` fill with a **black** check. |
| **Progress** (`progress`, `q-linear-progress`) | 10px, 2px border, `--blue-primary` → `--blue-light` gradient. Indeterminate progress pulses. |
| **Loader** (`.loader`) | Two counter-rotating squares in white and blue. |
| **Live dot** (`.live-dot`) | A pulsing 8px blue square next to the "LIVE" label while an analysis runs. |
| **Card / panel** (`q-card`) | `--dark-bg` background, 2px `--border-primary` border, no shadow. |
| **Dialog** (`q-dialog`) | `--card-bg` background, 2px full `--blue-primary` border, `--shadow-modal`, backdrop at 80% black. |
| **Tooltip** (`q-tooltip`) | `--card-bg` background, 1px `--blue-primary` border, 0.8rem text. |
| **Menu** (`q-menu`) | `--card-bg` background, 1px `--border-secondary` border. |
| **Table** (`q-table` dark flat square, virtual-scroll) | Black background, mono uppercase blue headers, row hover in `--hover-bg`, selected row in `--blue-dark` at 35%. |
| **Tabs** (`q-tabs`) | Mono labels. The active tab is `--blue-primary` with a glowing indicator. |
| **Filter chip** (`q-chip.filter-chip`) | Mono text in `--blue-light` with a 1px border. A **negated** chip (`.is-negated`) uses `--status-high` with strike-through. |
| **Severity badge** | A `q-badge` outline in the severity colour, with icon and label (e.g. `⚠ HIGH`). |
| **Toast** (Quasar Notify, `.tt-toast`) | Bottom-right, 320px wide, black background, 2px border, blue glow on hover. Success uses a green border and glow; warning amber; error red. Mono text for codes. |
| **Code block** (`pre`, `.code-block`) | `--dark-bg` background, `--blue-lighter` text, 1px border. Used for raw event JSON and extracted configs. |
| **Scrollbars** | 8px (6px in `.scrollable-panel`), `--blue-darker` thumb on black, `--blue-dark` on hover. |

### Momos → Tartarus mapping

| Momos | Tartarus |
|---|---|
| `--red-primary` `#dc2626` | `--blue-primary` `#38bdf8` |
| `--red-light` / `--red-lighter` | `--blue-light` `#7dd3fc` / `--blue-lighter` `#bae6fd` |
| `--red-hover` `#b91c1c` | `--blue-hover` `#0ea5e9` |
| `--red-dark` / `--red-darker` | `--blue-dark` `#0369a1` / `--blue-darker` `#0c4a6e` |
| `--shadow-red-*` | `--shadow-blue-*` |
| `.bg-red`, `.text-red`, `.border-red`, `.shadow-red` | `.bg-blue`, `.text-blue`, `.border-blue`, `.shadow-blue` |
| Severity as shades of red | Warm threat scale (red, orange, amber, slate) |
| White check on red checkbox | **Black** check on ice blue |
| vue3-toastify theme | Quasar Notify `tt-*` types |
| md-editor-v3 theme | Dropped (notes are plain text). Its quote, code, dialog and tooltip styles were carried over to Quasar. |
| `.row`, `.column`, `.full-width`… | Dropped in favour of Quasar's classes with the same names |

## Quasar setup

`src/css/quasar.variables.scss`:

```scss
$primary   : #38bdf8;
$secondary : #0369a1;
$accent    : #7dd3fc;
$dark      : #0a0a0a;
$dark-page : #000000;
$positive  : #22c55e;
$negative  : #ef4444;
$info      : #38bdf8;
$warning   : #eab308;

$generic-border-radius : 0;
$button-border-radius  : 0;
```

`quasar.config`:
- `framework.config.dark: true` (dark only, no toggle).
- `framework.plugins: ['Notify', 'Dialog', 'Loading', 'LocalStorage']`.
- `extras: ['material-icons', 'material-icons-outlined']`.
- `css: ['app.css']`, where `app.css` is `tartarus-theme.css`.

`src/boot/notify.ts` registers the toast types:

```ts
import { Notify } from 'quasar'

const base = { position: 'bottom-right', timeout: 5000, progress: true, actions: [{ icon: 'close', color: 'grey', round: true, flat: true }] } as const
Notify.registerType('tt-info',    { ...base, icon: 'info',         classes: 'tt-toast tt-toast--info' })
Notify.registerType('tt-success', { ...base, icon: 'check_circle', classes: 'tt-toast tt-toast--success' })
Notify.registerType('tt-warning', { ...base, icon: 'report',       classes: 'tt-toast tt-toast--warning' })
Notify.registerType('tt-error',   { ...base, icon: 'dangerous',    classes: 'tt-toast tt-toast--error', timeout: 0 })
```

Error toasts stay until dismissed.

Component defaults: always pass `square`, `dark` and `flat` (or `outline`) to Quasar
components. Inputs use `outlined dense`.

## Data visualisation

### Process graph (Cytoscape.js)

| Element | Style |
|---|---|
| Process node | Rectangle, `--dark-bg` fill, 2px border in `--border-secondary`, mono label `name (pid)` in `--text-white`. |
| Node with detections | Border in the colour of its **highest** severity, plus a small severity badge. |
| Sample root node | Border in `--blue-primary` with `--shadow-blue-medium` glow and a `bug_report` icon. |
| Selected node | Border in `--blue-light` with `--shadow-blue-strong` glow. Other nodes dim to 40% opacity. |
| Spawn edge (parent → child) | 2px solid `--blue-dark`, arrowhead. |
| Injection edge | 2px dashed `--status-high`, arrowhead, label `inject`. |
| Network edge (to host/IP node) | 2px dotted `--cat-network`. Host nodes are small diamonds with mono IP or domain labels. |
| Layout | Top-down tree (dagre). Zoom and pan; double-click a node to open Process detail. |

### Timeline

- **Rows are category lanes**, in the fixed order above. Each lane has a left gutter with icon
  and label (e.g. `▣ FILE`).
- Each event is a ≥8px mark in its lane colour. Overlapping marks get a 2px `--dark-bg` ring.
  Dense ranges collapse into a count bar (aggregation), and zooming expands them.
- Detections sit on a separate top lane as triangles in severity colours, with an icon in the
  tooltip.
- Background: `--dark-bg`. The time axis uses mono labels in `--text-gray-dark`, and the grid
  lines are `--border-subtle`.
- Hover shows a tooltip with time, process, summary and key fields. Click selects the event and
  opens it in the detail drawer. Dragging on the axis brushes a time range and adds a
  `@timestamp` filter chip.
- An optional **process filter** limits all lanes to the selected processes. Process identity
  is shown in the tooltip and detail, not by colour.

### Small charts (dashboard)

For counts such as events per category or detections per severity, use horizontal bars with
direct labels and a legend whenever there are two or more series. Every chart also has a table
view. Stat tiles show a single number in `--text-white` with a mono label.

## Iconography

Material Icons (outlined by default, filled for active states), 24px in the navigation and 18px
inline. App icon / PWA icon: a stylised descending pit or gate in `--blue-primary` on black.
This is to be designed; see Open questions in [overview](../overview.md).

## Accessibility notes

- Every text token is ≥ 4.3:1 on black, except `--text-gray-darker`, which is for disabled
  states only.
- Focus is always visible: `--blue-light` 2px outline with 2px offset (`:focus-visible`).
- Every interactive element can be reached by keyboard. The query bar is focused with `/`.
- Severity and category are never shown by colour alone (icon and label).
- `prefers-reduced-motion`: no shake, pulse or rotation, and no smooth scroll.
