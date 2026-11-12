# Nirvaah — UI component inventory & reference map

Companion to `DESIGN.md`. Part 1 records what the app actually renders today and
what is off-system. Part 2 maps every component to a concrete reference on
**Watermelon UI**, **shadcn/ui** and **assistant-ui** so the rebuild has a
source to copy from rather than an impression to chase.

Sources (all URLs verified reachable):

- Watermelon UI — https://ui.watermelon.sh (React + Tailwind v4, shadcn-CLI installable)
- shadcn/ui — https://ui.shadcn.com/docs/components
- assistant-ui — https://www.assistant-ui.com/docs/elements

---

## 1. Current inventory and defects

Styles are spread across four imported sheets — `styles.css`, `additions.css`,
`theme.css`, `life/life.css` (`main.jsx:4-7`) — so later files win with
`!important`. That cascade is the root cause of the inconsistency, not any
single component.

| Component | Where | Current values | Defect |
|---|---|---|---|
| App shell / sidebar | `theme.css:143` `.sidebar` | `border-radius: 0 !important`, `border-right: 1px`, transparent bg, `padding: 18px 10px 14px 6px` | Full-height square rail next to 16 px cards — the "tight rectangle" |
| Card / panel | `theme.css:469` `.card,.panel` and `additions.css:1704` | radius `--radius-lg` = **16 px**, then overridden to **16 px !important** + `--shadow-sm !important` | Two files setting the same radius, one with `!important`; shadow contradicts the flat system |
| Header nav tabs | `theme.css:289` `.header-nav-tab` | radius **8 px**, padding `6px 12px`, 13 px, weight 500 | Different radius, height and weight from every other tab row; count badge changes width → row reflows |
| Range tabs (1M/3M/6M/12M) | `theme.css:912` `.range-tab` | radius **6 px**, `font-mono 10px` | Third radius, mono micro-type, no track |
| Breakdown tabs | `theme.css:935` `.breakdown-tab` | radius **7 px**, 12 px | Fourth radius |
| Manage Tags tabs | `additions.css:1265` `.manage-tab-btn` | radius **7 px**, active `#1060e8` + weight **700**, hover `#0f172a`, base `#64748b` | Old blue SaaS skin still live; weight change reflows labels |
| Dropdown trigger | `additions.css:15` `.custom-select-trigger` | radius **10 px**, `1.5px` border | Fifth radius; 1.5 px border is off-grid |
| Dropdown menu | `additions.css:72` `.custom-select-menu` | min-width 100 %, max-width 300 px, max-height 260 px | No spec for padding/row height/shadow transition |
| Chart tooltip | `additions.css:387` `.chart-tooltip` | `background: #1a1d24`, radius 10 px | Hardcoded cool-black tooltip inside a warm theme (`theme.css:1560` sets a different one) |
| Dialog shell | `theme.css:766` | radius `--radius-xl` = **20 px**, padding 26 px | Sixth radius; not shared with card family |
| Type system | `theme.css:9-11`, `index.html:11` | `Inter Tight` body + `Instrument Serif` display + `JetBrains Mono` | Serif display face on a finance product; not the shadcn/assistant-ui lineage |

Radius values live in the app today: **0, 6, 7, 8, 10, 16, 20**. The contract in
`DESIGN.md` collapses them to `sm/md/xl/2xl/pill`.

---

## 2. Reference map

Legend: **WM** = Watermelon UI, **SH** = shadcn/ui, **AU** = assistant-ui.
"—" means no honest equivalent exists on that site; do not force one.

| # | Our component | WM reference | SH reference | AU reference |
|---|---|---|---|---|
| 1 | App shell + sidebar panel | [macos-sidebar](https://ui.watermelon.sh/animated-components/macos-sidebar) — inset `rounded-3xl` shell, content column beside it | [sidebar](https://ui.shadcn.com/docs/components/sidebar) — inset variant, `sidebar-*` tokens | [thread-list-sidebar](https://www.assistant-ui.com/elements/thread-list-sidebar) — shell that hosts a list beside content |
| 2 | Sidebar groups + nav items | [macos-sidebar](https://ui.watermelon.sh/animated-components/macos-sidebar) — active row = neutral fill + `rounded-md`, no accent bar | [sidebar](https://ui.shadcn.com/docs/components/sidebar) — menu button + `sidebar-accent` | [thread-list](https://www.assistant-ui.com/elements/thread-list) — grouped, searchable, active selection |
| 3 | Profile / avatar block | [macos-sidebar](https://ui.watermelon.sh/animated-components/macos-sidebar) footer area | [sidebar](https://ui.shadcn.com/docs/components/sidebar) — footer slot | [agent-card](https://www.assistant-ui.com/elements/agent-card) — identity block with secondary line |
| 4 | Top area — floating search + theme toggle (no bar) | [status-picker](https://ui.watermelon.sh/animated-components/status-picker) — pill-shaped control cluster | [command](https://ui.shadcn.com/docs/components/command) (search) + [button](https://ui.shadcn.com/docs/components/button) | [command-palette](https://www.assistant-ui.com/elements/command-palette) — one-keystroke access to everything |
| 5 | ~~Header nav tabs~~ — removed; the life pages live in the sidebar and the top area carries only search | — | — | — |
| 6 | Range tabs 1M/3M/6M/12M | [continuous-tabs](https://ui.watermelon.sh/animated-components/continuous-tabs) | [tabs](https://ui.shadcn.com/docs/components/tabs) styled as segmented | — |
| 7 | Breakdown tabs (trends/cashflow, category/payment) | [fluid-tabs](https://ui.watermelon.sh/animated-components/fluid-tabs) | [tabs](https://ui.shadcn.com/docs/components/tabs) | — |
| 8 | Card / panel | [card](https://ui.watermelon.sh/components/card) — hairline border, no shadow | [card](https://ui.shadcn.com/docs/components/card) | — |
| 9 | KPI block (net cashflow, income, expenses, savings) | [stats blocks](https://ui.watermelon.sh/blocks/stats) + [budget-card](https://ui.watermelon.sh/animated-components/budget-card) | [card](https://ui.shadcn.com/docs/components/card) | [number-ticker](https://www.assistant-ui.com/elements/number-ticker) — digits roll instead of snapping |
| 10 | Payment Channel Insights | [budget-card](https://ui.watermelon.sh/animated-components/budget-card) — label / value / hairline rows / single trailing metric | [card](https://ui.shadcn.com/docs/components/card) + [table](https://ui.shadcn.com/docs/components/table) | [spec-sheet](https://www.assistant-ui.com/elements/spec-sheet) — labelled key/value rows |
| 11 | Cash-flow chart + tooltip | [capitalio-dashboard](https://ui.watermelon.sh/dashboard/capitalio-dashboard) — finance chart composition | [chart](https://ui.shadcn.com/docs/components/chart) — `chart-1..5` tokens | [chart](https://www.assistant-ui.com/elements/chart) — points land as the series streams |
| 12 | Category breakdown / donut | [activities-card](https://ui.watermelon.sh/animated-components/activities-card) | [chart](https://ui.shadcn.com/docs/components/chart) | [heat-graph](https://www.assistant-ui.com/elements/heat-graph) / [activity-graph](https://www.assistant-ui.com/elements/activity-graph) for spend density |
| 13 | Budget progress rows | [budget-card](https://ui.watermelon.sh/animated-components/budget-card) — 2 px track, no gradient | [card](https://ui.shadcn.com/docs/components/card) | [quota-banner](https://www.assistant-ui.com/elements/quota-banner) — remaining/limit framing |
| 14 | Transactions table | [data-table](https://ui.watermelon.sh/components/data-table) + [inline-table-control](https://ui.watermelon.sh/animated-components/inline-table-control) | [table](https://ui.shadcn.com/docs/components/table) — 44 px rows, clipped card | [data-table](https://www.assistant-ui.com/elements/data-table) — compact, sortable, styled for dense data |
| 15 | Filters + date range | [filter-disclosure](https://ui.watermelon.sh/animated-components/filter-disclosure) | [popover](https://ui.shadcn.com/docs/components/popover) + [calendar](https://ui.shadcn.com/docs/components/calendar) | — |
| 16 | Dropdown / `CustomSelect` | [dropdown-disclosure](https://ui.watermelon.sh/animated-components/dropdown-disclosure) + [status-picker](https://ui.watermelon.sh/animated-components/status-picker) | [select](https://ui.shadcn.com/docs/components/select) + [dropdown-menu](https://ui.shadcn.com/docs/components/dropdown-menu) | [model-selector](https://www.assistant-ui.com/elements/model-selector) — grouped, searchable picker |
| 17 | Dialog / modal shell | [dialog](https://ui.watermelon.sh/animated-components/category/dialog) + [dialog-stack](https://ui.watermelon.sh/animated-components/dialog-stack) | [dialog](https://ui.shadcn.com/docs/components/dialog) | [elicitation-form](https://www.assistant-ui.com/elements/elicitation-form) |
| 18 | Manage Tags modal | [editable-chip](https://ui.watermelon.sh/animated-components/editable-chip) + [dialog](https://ui.watermelon.sh/animated-components/category/dialog) | [dialog](https://ui.shadcn.com/docs/components/dialog) + [tabs](https://ui.shadcn.com/docs/components/tabs) + [badge](https://ui.shadcn.com/docs/components/badge) | [settings-panel](https://www.assistant-ui.com/elements/settings-panel) — grouped editable lists |
| 19 | Add / edit transaction form | [range-selection-slider](https://ui.watermelon.sh/animated-components/range-selection-slider) for amount entry | [input](https://ui.shadcn.com/docs/components/input) + [select](https://ui.shadcn.com/docs/components/select) | [composer](https://www.assistant-ui.com/elements/composer) — unified single-line input with inline controls |
| 20 | Category drilldown modal | [inline-table-control](https://ui.watermelon.sh/animated-components/inline-table-control) | [table](https://ui.shadcn.com/docs/components/table) + [dialog](https://ui.shadcn.com/docs/components/dialog) | [tool-call](https://www.assistant-ui.com/elements/tool-call) — request/result behind a disclosure |
| 21 | Buttons (primary/secondary/ghost/destructive) | [button](https://ui.watermelon.sh/components/button) | [button](https://ui.shadcn.com/docs/components/button) | [tooltip-icon-button](https://www.assistant-ui.com/elements/tooltip-icon-button) |
| 22 | Chips / badges (no dots; vibrant payment pills) | [editable-chip](https://ui.watermelon.sh/animated-components/editable-chip) | [badge](https://ui.shadcn.com/docs/components/badge) | [memory-chips](https://www.assistant-ui.com/elements/memory-chips) / [follow-up-suggestions](https://www.assistant-ui.com/elements/follow-up-suggestions) |
| 23 | Empty / loading / error states | [card](https://ui.watermelon.sh/components/card) empty conventions | [skeleton](https://ui.shadcn.com/docs/components/skeleton) | [empty-state](https://www.assistant-ui.com/elements/empty-state), [loading-state](https://www.assistant-ui.com/elements/loading-state), [error-state](https://www.assistant-ui.com/elements/error-state) |
| 24 | Toast / busy bar | — | [button](https://ui.shadcn.com/docs/components/button) states | [agent-status](https://www.assistant-ui.com/elements/agent-status) — one pill that says what is happening |
| 25 | Notes list | [card](https://ui.watermelon.sh/components/card) list pattern | [card](https://ui.shadcn.com/docs/components/card) | [artifact-card](https://www.assistant-ui.com/elements/artifact-card) |
| 26 | Tasks checklist | — | [card](https://ui.shadcn.com/docs/components/card) | [todo-list](https://www.assistant-ui.com/elements/todo-list) — rewritten mid-run, progress at a glance |
| 27 | Journal timeline | [macos-sidebar](https://ui.watermelon.sh/animated-components/macos-sidebar) chronology header | — | [timeline](https://www.assistant-ui.com/elements/timeline) + [day-separator](https://www.assistant-ui.com/elements/day-separator) |
| 28 | Goals / investments / liabilities cards | [stats blocks](https://ui.watermelon.sh/blocks/stats) | [card](https://ui.shadcn.com/docs/components/card) | [recommendation-card](https://www.assistant-ui.com/elements/recommendation-card) / [schedule-card](https://www.assistant-ui.com/elements/schedule-card) |
| 29 | Global search field | [status-picker](https://ui.watermelon.sh/animated-components/status-picker) pill input | [command](https://ui.shadcn.com/docs/components/command) | [thread-search](https://www.assistant-ui.com/elements/thread-search) |
| 30 | Theme toggle (icon button) | [status-picker](https://ui.watermelon.sh/animated-components/status-picker) — pill icon cluster | [button](https://ui.shadcn.com/docs/components/button) ghost variant | [tooltip-icon-button](https://www.assistant-ui.com/elements/tooltip-icon-button) |

---

## 3. What to lift from each site

**Watermelon UI — shape and interaction.** The two patterns worth copying
verbatim in spirit:

- `macos-sidebar`: `rounded-3xl` outer shell, `p-2`/`rounded-2xl` item rows,
  active state as a neutral fill behind the row, content column with its own
  padding. That is the fix for the square rail.
- `continuous-tabs`: `rounded-full` track, `p-1`/`p-1.5`, hairline border,
  inset highlight plus a soft outer shadow, and a single animated indicator
  (`layoutId`) moving between items. That is the fix for the four different tab
  radii and the tab reflow.

**shadcn/ui — tokens and restraint.** Semantic pairs (`card`/`card-foreground`,
`sidebar`/`sidebar-accent`), one `--radius` base with `calc()`-derived scale,
cards with `border` but no shadow, `ring` focus on every control, and
`chart-1..5` as a fixed palette. Use its token naming so future components and
any shadcn/Watermelon snippet drop in without translation.

**assistant-ui — element completeness.** Not a visual style to copy but a
standard of finish: every surface has designed empty / loading / error states,
numbers animate via a ticker rather than snapping, status is one pill, timelines
carry day separators, and dense tables are treated as a first-class element.
Adopt its element checklist as the definition of "done" for each Nirvaah panel.

---

## 4. Order of work (after this spec)

1. ~~`tokens.css` — emit the `DESIGN.md` tokens as CSS custom properties, and
   delete the four competing `:root` blocks.~~ **Done** — `src/tokens.css`
   owns every token (light + dark) and aliases the legacy variable names onto
   them, so the existing sheets inherit the new palette, type and radii.
2. ~~Shell + sidebar + header (fixes the square rail and the tab anchors).~~
   **Done** — `src/design.css`.
3. ~~One `SegmentedTabs` component replacing `.range-tab`, `.breakdown-tab`,
   `.manage-tab-btn` and `.header-nav-tab`.~~ **Done** — the component lives in
   `App.jsx` and is used by the header nav, the cashflow range, the report view
   toggle, the breakdown toggle and Manage Tags.
4. ~~Card/KPI primitives, then Transactions table + filters.~~ **Done.**
5. ~~`ManageTagsModal` and the select/menu primitives.~~ **Done.**
6. ~~Charts and the Payment Channel Insights panel.~~ **Done** — chart series
   now read `--chart-1..5`; tooltips are L1 popovers.
7. **Next** — states (skeleton / empty / error) across the remaining pages,
   replacing the last hardcoded hexes in `additions.css` (372 of them), and
   finally deleting the superseded `:root` blocks and `style.css`.

Verification: `vite build` clean; checked in the running app at 1440×900 and
390×844, light and dark, with live data (754 transactions).
