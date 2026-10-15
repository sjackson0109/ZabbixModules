# Explorer design system: tokens and components

Network Explorer and Wi-Fi Explorer share one stylesheet, `src/design/explorers.css`. It holds the design tokens
and the components both modules use. `scripts/sync_widget_assets.py` copies it into all seven modules
(`assets/css/explorers.css`), and each manifest loads it before the module's own sheet. Edit the source and run
the script; CI fails if a copy drifts.

Class prefixes:

| Prefix | Where | Use for |
|---|---|---|
| `zx-` | `src/design/explorers.css` | Tokens and components shared by both Explorers |
| `ne-` | `src/widget/widget.css`, `explorer.css` | Network Explorer only: port tiles, topology drawing, interface detail |
| `we-` | `frontend/wifiexplorer/assets/css/wifi.css` | Wi-Fi Explorer only: KPI tiles, floor plans, capacity chart, VLAN hops |

Before adding a class to a module sheet, check whether a `zx-` component already does the job. A new idea that
both modules could use goes in the shared sheet, with a section here.

## Tokens

All tokens are CSS custom properties on `:root`, with dark values under `html[color-scheme='dark']` (Zabbix's dark
and high-contrast dark themes). Never write a colour literal in a module sheet; if no token fits, add one here.

### Tones (text and lines)

Each tone passes WCAG AA (4.5:1) for normal text on Zabbix's light backgrounds (white, and the `#ebeef0` page
behind a module view) and dark ones (`#2b2b2b`, `#0e1012`). Check a new tone against `#ebeef0`, not only white.

| Token | Light | Dark | Means |
|---|---|---|---|
| `--zx-tone-ok` | `#26793c` | `#59db8f` | Up, complete, ready, pass |
| `--zx-tone-warning` | `#916000` | `#ffc859` | Review: partial, degraded, a warning finding |
| `--zx-tone-critical` | `#b04444` | `#ff8f7a` | Down, failed, lost, flagged |
| `--zx-tone-info` | `#1d6aab` | `#8fb1ff` | Information, tagged VLAN, STP root path |
| `--zx-tone-unknown` | `#5c6c7b` | `#a8b4bf` | No data, secondary text, legend labels |
| `--zx-accent` | `#236daa` | `#6fb2ec` | Selection, focus, current tab, links in the drawing |

### Fills (badges and areas)

Zabbix's own severity colours, identical in both themes. Text on a fill is always `--zx-on-fill` (`#1f2c33`).
Never use a fill as text colour on the page background: most fail contrast.

| Token | Value | Zabbix meaning |
|---|---|---|
| `--zx-fill-ok` | `#59db8f` | Resolved |
| `--zx-fill-info` | `#7499ff` | Information |
| `--zx-fill-warning` | `#ffc859` | Warning |
| `--zx-fill-average` | `#ffa059` | Average |
| `--zx-fill-high` | `#e97659` | High |
| `--zx-fill-disaster` | `#e45959` | Disaster |
| `--zx-fill-unknown` | `#97aab3` | Not classified |

A warning is always yellow, never red. Red (`--zx-fill-high`, `--zx-tone-critical`) is kept for down, failed and
critical.

### Surfaces and lines

| Token | Value | Use |
|---|---|---|
| `--zx-line` | `rgba(128,128,128,.35)` | Borders, table rules, gridlines |
| `--zx-line-strong` | `rgba(128,128,128,.6)` | Badge and chip outlines |
| `--zx-surface-tint` | `rgba(128,128,128,.08)` | A faint panel or selected sub-tab |
| `--zx-halo` | `#fff` / `#1e252b` | The halo behind SVG text, so lines never cross a label |

### Scales

| Scale | Tokens |
|---|---|
| Spacing | `--zx-space-1` 4 px, `-2` 8 px, `-3` 12 px, `-4` 16 px, `-5` 24 px |
| Text | `--zx-text-xs` 10 px (port tile detail only), `-sm` 11 px, `-md` 12 px (Zabbix body), `-lg` 14 px (headings), `-xl` 20 px (KPI values) |
| Radius | `--zx-radius` 2 px, as Zabbix 7 |
| Opacity | `--zx-opacity-dimmed` .3 (filtered out of a drawing), `-faded` .55 (unrelated), `-disabled` .75 (admin disabled) |

Hairlines (1 to 3 px) and SVG glyph sizes stay literal; they are geometry, not rhythm.

## Components

### Tone (`zx-tone-*`)

Colours a state as text. Bold for ok, warning, critical and info; italic and unbold for unknown. The words always
carry the meaning (`Failed`, `Not ready`), so the colour only backs them up.

In Wi-Fi Explorer, `$toned($text, $state)` in `wifiexplorer.view.php` maps every domain state to a tone; a new
state is one line in that map, never new CSS.

```php
$toned($pathStates[$result['status']], $result['status']);   // "Failed" in the critical tone
```

### Callout (`zx-callout`, `-info`, `-warning`, `zx-callout-title`)

A message that must not be read past: a privacy warning, an unreachable SNMP agent, the collection summary. A
4 px left edge in the tone, a faint background. Use `role="note"` when it is not inside a form.

```js
notice(root, 'sw-01: the SNMP agent is unreachable.', 'warning'); // runtime.js -> p.zx-callout.zx-callout-warning
```

Do: one callout per message, title first. Don't: a callout for routine help text; that is a note.

### Note (`zx-note`)

Secondary text that explains: a tab's opening sentence, a hint next to a control. Grey, normal weight.

### Muted (`zx-muted`)

A missing value. Table cells and detail lists show **Unknown** in muted text (grey, italic) so it never reads as
data. An em dash means "does not apply" (no building, no labels) and is not muted. In Wi-Fi views use
`$missing()` or `$unknown($value)`; in the runtime, `valueNode()` does it for every table cell and detail value.

### Badge (`zx-badge-*`)

What a value rests on. Variants: `observed` (solid outline), `inferred`, `estimated`, `interpolated` (dashed),
`configured`, `declared` (tinted), `not_collected` (faded), `partial` (warning outline). Network Explorer's link
tables use `observed` for links confirmed from both ends and `inferred` for anything else, matching the dashed line
drawn for an uncertain link.

Don't put free text in a badge; a note belongs in its own column.

### Tabs (`zx-tabs`, `zx-tab`, `zx-tabs-sub`)

View tabs are links with `aria-current="page"` inside a `role="navigation"` list with an `aria-label`. In-page tabs
(stack members) are buttons with `role="tab"` and `aria-selected` inside a `role="tablist"`. Both get a 2 px
accent underline and bold text when current; hover shows a grey underline.

`zx-tabs-sub` is a choice inside one view (Capacity's range): smaller, no rule beneath, the current one tinted.
It must always look lighter than the view tabs above it.

### Legend (`zx-legend`, `zx-legend-key`, `zx-swatch`)

A list (`ul`) of key and label pairs with an `aria-label`. A key is bold text, a line swatch (`zx-swatch` plus a
module variant such as `ne-swatch-dashed`), or a module's own mini element (`ne-legend-tile` is a small port tile
in the state's own style). The topology legend lists only what the current drawing shows.

### Filter bar (`zx-filter-bar`, `zx-filter-field`)

The page's scope form and any in-view form (Impact). Labels stack above their fields, as in Zabbix 7 filters;
the submit button aligns with the bottom of the fields. Keep the module class too (`ne-scope`, `we-scope`) where
scripts look the form up.

### Disclosure (`zx-disclosure`, `zx-disclosure-quiet`)

A `details` element. Plain `zx-disclosure` has a bold summary, for sections such as data quality or the interface
diagnostics. Add `zx-disclosure-quiet` for help ("About this view") and grouped lists inside a table cell: normal
weight, grey.

### Tables

Use Zabbix's own `list-table` (Wi-Fi views: `CTableInfo`; the runtime's `table()` adds the class). Missing values
in a cell follow Muted above. Don't draw a bespoke table style.

## Module components

These live in a module sheet because only one module has them. They use the shared tokens.

| Component | Module | Notes |
|---|---|---|
| Port tile (`ne-port`, `ne-state-*`, `ne-vlan-*`, `ne-stp-*`, `ne-lldp-*`) | Network Explorer | Every state pairs colour with border style or opacity and a text label. Port colours left at the widget form's defaults follow the theme; a chosen colour overrides. |
| Topology node and edge (`ne-node-*`, `ne-edge-*`) | Network Explorer | Selection is weight and dash as well as colour. Findings badge uses the Zabbix fills. |
| KPI tile (`we-tile`, `we-tile-warning`, `we-tile-critical`) | Wi-Fi Explorer | One accent rule on every tab: none when healthy, yellow edge for something to review, red edge only for APs or radios down. |
| Floor-plan marker (`we-marker-*`) | Wi-Fi Explorer | A link: focus shows a dashed accent ring. Fills are Zabbix fills. |
| Hop chip (`we-hop`, `-failed`, `-unknown`) | Wi-Fi Explorer | The failing hop is outlined in red. |

## Accessibility checklist

- Text colour comes from a tone token, never a fill.
- No state rests on colour alone: pair it with a word, a glyph, a dash or a weight.
- Every focusable element shows a visible focus ring (`:focus-visible`, accent colour).
- Lists of tabs and legends carry an `aria-label`; tabs carry `aria-current` or `aria-selected`.
- Check new colours in both themes; `html[color-scheme='dark']` switches the tokens.
