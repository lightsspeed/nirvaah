---
version: alpha
name: Nirvaah Ledger
description: >-
  A warm-neutral, flat, token-driven finance UI. Ink for action, one clay
  accent for brand moments, hairline borders instead of shadows, one radius
  contract for every surface, and tabular numerals for all money.
colors:
  background: "#F6F4EF"
  foreground: "#1C1B19"
  card: "#FFFDFA"
  card-foreground: "#1C1B19"
  popover: "#FFFDFA"
  popover-foreground: "#1C1B19"
  primary: "#1C1B19"
  primary-foreground: "#FAF8F4"
  secondary: "#EFEBE2"
  secondary-foreground: "#1C1B19"
  muted: "#EFEBE2"
  muted-foreground: "#6B645A"
  accent: "#F1EBE0"
  accent-foreground: "#1C1B19"
  brand: "#B4552F"
  brand-foreground: "#FFF8F4"
  brand-soft: "#F8E7DF"
  brand-soft-foreground: "#8F3F22"
  destructive: "#A63A2A"
  destructive-foreground: "#FFF8F6"
  destructive-soft: "#FBEAE4"
  destructive-soft-foreground: "#A63A2A"
  success: "#3F7D4E"
  success-soft: "#E8F1E6"
  success-soft-foreground: "#2F6339"
  warning: "#8A6414"
  warning-soft: "#F8EFD8"
  warning-soft-foreground: "#6E4F10"
  border: "#E3DDD2"
  border-subtle: "#EFE9DF"
  input: "#E3DDD2"
  ring: "#B4552F"
  sidebar: "#F1EDE4"
  sidebar-foreground: "#1C1B19"
  sidebar-accent: "#FFFDFA"
  sidebar-accent-foreground: "#1C1B19"
  sidebar-border: "#E3DDD2"
  chart-1: "#B4552F"
  chart-2: "#6E8B6A"
  chart-3: "#C79A3E"
  chart-4: "#5A7089"
  chart-5: "#8A5A72"
  chart-6: "#2F7F8F"
  chart-7: "#6A5AA8"
  chart-8: "#A06A3F"
  chart-9: "#7C8A3A"
  chart-10: "#A4444D"
typography:
  display:
    fontFamily: Geist
    fontSize: 52px
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: "-0.02em"
  h1:
    fontFamily: Geist
    fontSize: 36px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  h2:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  h3:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0em"
  body:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "0em"
  body-strong:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: 500
    lineHeight: 1.55
    letterSpacing: "0em"
  small:
    fontFamily: Geist
    fontSize: 14.5px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0em"
  caption:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0em"
  overline:
    fontFamily: Geist
    fontSize: 12.5px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.08em"
  num-display:
    fontFamily: Geist Mono
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.025em"
  num-hero:
    fontFamily: Geist Mono
    fontSize: 46px
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  num-kpi:
    fontFamily: Geist Mono
    fontSize: 36px
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.025em"
  num-body:
    fontFamily: Geist Mono
    fontSize: 17px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "0em"
rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 10px
  xl: 14px
  "2xl": 18px
  "3xl": 24px
  pill: 999px
spacing:
  "1": 4px
  "2": 8px
  "3": 12px
  "4": 16px
  "5": 20px
  "6": 24px
  "8": 32px
  "10": 40px
  "12": 48px
components:
  sidebar:
    backgroundColor: "{colors.sidebar}"
    textColor: "{colors.sidebar-foreground}"
    rounded: "{rounded.2xl}"
  sidebar-item:
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  sidebar-item-active:
    backgroundColor: "{colors.sidebar-accent}"
    textColor: "{colors.sidebar-accent-foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  sidebar-section-label:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.overline}"
  search:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.pill}"
    padding: 18px
    height: 44px
  payment-pill:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.pill}"
    padding: 10px
    height: 26px
  segmented-control:
    backgroundColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: 4px
    height: 44px
  segmented-item:
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.pill}"
    padding: 8px
    height: 34px
  segmented-item-active:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.pill}"
    padding: 8px
    height: 34px
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    rounded: "{rounded.xl}"
    padding: 20px
  card-header:
    textColor: "{colors.card-foreground}"
    typography: "{typography.h3}"
  kpi-label:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.overline}"
  kpi-value:
    textColor: "{colors.foreground}"
    typography: "{typography.num-hero}"
  kpi-value-secondary:
    textColor: "{colors.foreground}"
    typography: "{typography.num-kpi}"
  delta-badge:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success-soft-foreground}"
    rounded: "{rounded.pill}"
    padding: 4px
  chip:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    rounded: "{rounded.pill}"
    padding: 6px
  chip-brand:
    backgroundColor: "{colors.brand-soft}"
    textColor: "{colors.brand-soft-foreground}"
    rounded: "{rounded.pill}"
    padding: 6px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  button-primary-hover:
    backgroundColor: "{colors.brand}"
    textColor: "{colors.brand-foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  button-secondary:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  button-ghost:
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.md}"
    padding: 8px
    height: 40px
  button-destructive:
    backgroundColor: "{colors.destructive-soft}"
    textColor: "{colors.destructive-soft-foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  select-trigger:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: 10px
    height: 40px
  select-menu:
    backgroundColor: "{colors.popover}"
    textColor: "{colors.popover-foreground}"
    rounded: "{rounded.xl}"
    padding: 4px
  select-item:
    textColor: "{colors.popover-foreground}"
    rounded: "{rounded.sm}"
    padding: 8px
    height: 36px
  dialog:
    backgroundColor: "{colors.popover}"
    textColor: "{colors.popover-foreground}"
    rounded: "{rounded.2xl}"
    padding: 24px
  dialog-title:
    textColor: "{colors.popover-foreground}"
    typography: "{typography.h2}"
  table-container:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.xl}"
  table-header:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.overline}"
    height: 44px
  table-row:
    textColor: "{colors.foreground}"
    height: 52px
  table-amount:
    textColor: "{colors.foreground}"
    typography: "{typography.num-body}"
  toast:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.lg}"
    padding: 12px
  toast-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.destructive-foreground}"
    rounded: "{rounded.lg}"
    padding: 12px
  divider:
    backgroundColor: "{colors.border}"
    height: 1px
  divider-subtle:
    backgroundColor: "{colors.border-subtle}"
    height: 1px
  sidebar-divider:
    backgroundColor: "{colors.sidebar-border}"
    height: 1px
  list-row-hover:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.sm}"
    height: 44px
  badge-success:
    backgroundColor: "{colors.success}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.pill}"
    padding: 4px
  badge-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning-soft-foreground}"
    rounded: "{rounded.pill}"
    padding: 4px
  chart-series-1:
    backgroundColor: "{colors.chart-1}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-2:
    backgroundColor: "{colors.chart-2}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-3:
    backgroundColor: "{colors.chart-3}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-4:
    backgroundColor: "{colors.chart-4}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-5:
    backgroundColor: "{colors.chart-5}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-6:
    backgroundColor: "{colors.chart-6}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-7:
    backgroundColor: "{colors.chart-7}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-8:
    backgroundColor: "{colors.chart-8}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-9:
    backgroundColor: "{colors.chart-9}"
    rounded: "{rounded.xs}"
    height: 4px
  chart-series-10:
    backgroundColor: "{colors.chart-10}"
    rounded: "{rounded.xs}"
    height: 4px
---

## Overview

**Nirvaah Ledger** is a warm-neutral financial workspace. Flat surfaces, hairline
borders, one clay accent, and numbers that always line up. It borrows the
discipline of three systems rather than the veneer of any one of them:

- **shadcn/ui** — semantic token *pairs* (`surface` + `surface-foreground`), a
  single `--radius` base with a derived scale, cards that carry no shadow,
  visible focus rings on every interactive element.
- **Watermelon UI** — pill segmented tabs with a sliding indicator, an inset
  floating sidebar shell instead of a full-height square rail, hairline-bordered
  cards, and chips/status pickers for compact state.
- **assistant-ui** — element-level completeness: every surface ships its
  default, hover, focus, loading, empty and error states; data-table, chart,
  number-ticker, activity heat-graph and spec-sheet are first-class patterns,
  not one-off screens.

Seven rules, in priority order:

1. **One radius contract.** A surface gets the radius its role dictates — never
   an arbitrary px value. See *Shapes*.
2. **Two typefaces, no more.** Geist for language, Geist Mono for money. No
   serif display face.
3. **Semantic tokens only.** No raw hex in components. If a value is missing,
   add a token here first.
4. **Flat by default.** Borders separate surfaces; shadows belong to things
   that float (menus, dialogs, toasts).
5. **States are part of the component.** Default / hover / focus-visible /
   active / disabled / loading / empty / error — all designed, not inherited
   from the browser.
6. **Motion explains state change.** 120–200 ms, ease-out, and the indicator
   moves — nothing bounces for decoration.
7. **Money is tabular and right-aligned.** Always `font-variant-numeric:
   tabular-nums` in Geist Mono.

## Colors

The palette is a warm paper neutral with a single clay accent. Ink is the
high-emphasis action colour; clay is reserved for brand moments (active
indicator, positive emphasis in charts, the one primary CTA that must read as
"Nirvaah", not as "a button").

- **background `#F6F4EF` / foreground `#1C1B19`** — 15.7:1. The page shell.
- **card `#FFFDFA`** — the elevated surface for every panel, table and dialog
  content block. Cards are separated by `border`, not shadow.
- **primary `#1C1B19`** — ink. Primary buttons, active indicators, toasts.
  Hover shifts to brand clay so the action confirms itself.
- **brand `#B4552F`** — clay. 4.67:1 against brand-foreground. Use for the
  brand mark, the segmented-control indicator under `:focus`, chart series 1,
  and single-number emphasis. Never as a large background wash.
- **muted `#EFEBE2` / muted-foreground `#6B645A`** — 5.75:1 on card. Section
  labels, secondary text, segmented-control tracks.
- **success / destructive / warning** — only for money direction and alerts,
  and only in the `*-soft` pair form (tinted background + dark text). Never a
  saturated fill behind normal-size text.
- **chart-1 … chart-10** — fixed categorical order (clay, sage, ochre, slate,
  plum, teal, indigo, bronze, olive, rose). Charts take the next colour in
  order; never pick by mood. Pies draw segments with a 2px `card` gap.

Dark mode overrides the same token names (background `#141312`, card `#1B1A18`,
border `#2B2926`, foreground `#F2EEE7`, muted-foreground `#A9A29A`, brand
`#E0795A`). Components never branch on theme.

## Typography

One family for language, one for numbers.

- **Geist** (400/500/600) — everything textual. Headings use `-0.02em`
  tracking; body stays at `0`.
- **Money shows the paise it was given.** A record of ₹706.82 renders as
  `₹706.82`; a whole amount renders as `₹35,000` with no trailing zeros. Rounding
  to the rupee hid real values, so the formatter switches between a 0-decimal and
  a 2-decimal instance based on the value itself.
- **Geist Mono** (400/500/600) — amounts, percentages, deltas, table figures,
  chart axes and any numeric label. Always `tabular-nums` so columns align and
  digits don't shift while values animate.
- **Overline** — 11 px / 600 / `0.08em` uppercase. Section labels in the sidebar,
  table headers, KPI labels. This replaces 10 px mono micro-caps.
- Scale: `display 52` for the one number on a page, `h1 36` page titles,
  `h2 24` panel/dialog titles, `h3 20` card headers, `body 16` default, `small
  14.5` dense rows, `caption 13` helper text, `overline 12.5` labels. Nothing
  below 12.5 px — if a label needs to be smaller than that, cut words instead.
- Maximum three weights in view. Never use weight change alone to signal active
  state inside a control (it reflows the label) — move the indicator instead.

**Category colour is computed, never assigned.** The hue is hashed from the
category name onto a 14-anchor wheel (`CAT_HUES`, 10°–320°), so a category the
user invents is coloured the moment it exists — in transactions, budgets,
reports, notes, tasks and journal alike. Shade comes from CSS
(`hsl(var(--cat-h) 58% 93%)` on light, `hsl(var(--cat-h) 32% 19%)` on dark), so
one name has one identity in both themes. Known life-page names keep their
curated tints; anything new falls through to the same hash.

**Do not** use `Instrument Serif`, `Inter Tight`, `Plus Jakarta Sans` or any
serif display face. That mix is what makes the current build read as two
products stitched together.

## Layout

- **Shell** — a 12 px gutter around the viewport, then an inset sidebar panel
  (264 px) and the content column, separated by a 12 px gap. The sidebar is a
  rounded panel *inside* the shell, not a full-height square rail.
- **Top area** — no bar: a 44 px search field floats, centred, over the content column at the top of the content column, background
  `background` with a 1 px `border-subtle` bottom edge. Because it is sticky,
  nav tabs and badges must have fixed slot widths: an active state or a count
  changing must never move neighbouring tabs.
- **Shell is fixed height** — the document never scrolls. `shell` is
  `100dvh / overflow:hidden`, split into sidebar + a column of
  `header / content / footer`. Only the content row scrolls
  (`overflow-y:auto`), so the wordmark line sits at the bottom of the app on
  every page and never travels with the list. The footer is a caption, not a
  bar: transparent, no rule, no shadow.
- **Floating panels are clamped, not clipped.** The date-range panel is
  portalled to `body`, anchored to its trigger's rect and shifted so it always
  sits inside the viewport (12 px min gutter), flipping above when the space
  below is short.
- **Sticky table heads are opaque** (`--card`, inset hairline) and sit above the
  rows, so scrolling never runs text through the column labels.
- **Content** — max-width 1280 px, page padding 32 px desktop / 24 px tablet /
  16 px mobile. Sections are separated by 24 px; cards inside a grid by 16 px.
- **Grid** — everything is a multiple of 4 px. KPI rows are 3 or 4 equal
  columns at ≥1280 px, 2 at ≥768 px, 1 below.
- **Breakpoints** — 640 / 768 / 1024 / 1280. The sidebar collapses to a sheet
  below 1024 px; tables scroll horizontally inside their card rather than
  reflowing into stacked labels.
- **Touch targets** — 44 px minimum on mobile; icon buttons 32 px desktop with
  a 44 px hit area on touch.

## Elevation & Depth

Exactly three levels. Nothing else casts a shadow.

| Level | Use | Value |
|---|---|---|
| L0 — flat | cards, panels, tables, KPI blocks, sidebar, header | no shadow, 1 px `border` |
| L1 — float | dropdown menus, popovers, tooltips, toasts | `0 8px 24px -12px rgb(28 27 25 / 0.18)` |
| L2 — modal | dialogs, command palette, mobile sidebar sheet | `0 24px 60px -20px rgb(28 27 25 / 0.24)` |

At rest, surfaces are borderless — `--card-edge` is `transparent`. Interaction is
revealed, not drawn: on hover a hairline appears (`--hover-edge`,
`rgb(28 27 25 / 0.10)`; white at 12 % in dark) over 140 ms, and rows take a
3.5 % `--hover-wash`. Nothing moves, nothing lifts.

Focus is not elevation: use `outline: 2px solid var(--ring); outline-offset: 2px`
(or a `0 0 0 2px background, 0 0 0 4px ring` ring) on every focusable control.

## Shapes

This table is the contract. Any element not listed needs a new row here before
it ships.

| Element | Radius | Token |
|---|---|---|
| App shell panel / sidebar | 18 px | `2xl` |
| Dialog / modal / command palette | 18 px | `2xl` |
| Card / panel / table container / KPI block | 14 px | `xl` |
| Popover / dropdown menu / chart tooltip | 14 px | `xl` |
| Primary & secondary buttons, inputs, selects, search field | 8 px | `md` |
| Sidebar nav item, table action button | 8 px | `md` |
| Menu item, list row hover, small control | 6 px | `sm` |
| Segmented-control track, segmented item, chip, badge, avatar, status pill | full | `pill` |
| Inline code / category dot | 4 px / full | `xs` / `pill` |

Two hard consequences, because they are the current failure:

- The sidebar and the transactions card must share the same family of corners.
  A `border-radius: 0` rail next to a 16 px card is a defect, not a style.
- There is no such thing as a 7 px or a 10 px radius in this system. Tabs are
  either `pill` (segmented) or `md` (nav links). Pick one per component and
  reuse the token.

## Dashboard layout

A 12-column grid with explicit placement, so DOM order can never shuffle it:

| Row | Cards |
|---|---|
| 1 | Net balance (cols 1–6) · Total income (7–9) · Total expense (10–12) |
| 2 | Goals (1–4) · Cashflow trend (5–8) · Recent activity (9–12) |
| 3 | Budget overview (1–4) · Financial position (5–8) · Report promo (9–12) |

Rows 2 and 3 are three equal cards; rows are 18 px apart and cards in a row
share one height. Below 1024 px every card is full width; below 640 px the grid
is one column.

**Every table speaks the tasks-row language.** No zebra, no vertical rules, no
header fill: an overline header on a hairline, then 56 px rows separated by
1 px `border-subtle`, last row open. Money cells are mono, tabular and
right-aligned; actions sit at the far right. The row is the unit of design, not
the card.

**Transactions is an app-shell page.** Above 1024 px the shell is
`100dvh / overflow: hidden`, the page itself never scrolls, and the table is the
only scroller: the panel is a flex column, the toolbar stays put, and the table
body scrolls under a sticky `thead`. Below that breakpoint the page scrolls
normally — an inner scroller fights the browser on a phone.

## Components

**Sidebar** — on desktop the rail is *not a surface*: it sits directly on
`background` with no fill, border or shadow, 248 px wide, 12 px gutter, sticky.
Brand block at the top (30 px clay tile, 17/600 wordmark, `overline` sub-label),
grouped nav with `overline` section labels, profile pinned at the bottom behind
a hairline divider. Nav items are 40 px, radius `md`, icon 16 px + 10 px gap;
active = `card` fill + `foreground` text, no left accent bar, no weight jump.
Below 1024 px it becomes a sheet: `card` surface, `0 18px 18px 0` corners, L2
shadow, 45 % ink scrim, 240 ms slide. It closes on scrim tap, Escape or nav tap
and the page scroll locks while open.

**Top area** — there is no chrome bar. A single 44 px search field (`pill`
radius, `card` surface, hairline border, L1 shadow) floats centred over the
content column, with the theme toggle as a matching 44 px round button beside
it. No background band, no bottom border: the field itself is the only visible
element. The hamburger sits to its left below 1024 px.

**Charts carry a view switch, not a second chart.** One panel, one range
control: Income & Expense Trends (area, two series) · Monthly Cashflow (bars,
two series) · Expense Trend (bars, single series with value labels and the
period total in the legend). The legend always describes the view that is on
screen.

**Payment channel insights is a five-card row** — primary spend channel, top
inflow channel, channel utilization, average ticket size, and net flow by
channel (name + diverging bar + signed value, sorted by absolute net). Five
equal cards at ≥1360 px, three (net card full width) at 900–1360, two, then one.

**A category, opened, becomes a project.** Selecting a category chip swaps the
overview for a project panel: the category name as the page title with
`n of m done`, a progress bar and a quiet `Delete project` (destructive, so it
asks first), a single-line quick add (`Add a task and press Enter` plus `Add`),
then one toolbar holding the filter tabs — All · Active · Done · Overdue ·
Next 7 days, each with a count — and the order control (Manual · Due date ·
Priority). Rows are the task row minus the category pill, which is redundant
inside its own project; separators are hairlines and the actions stay on hover.

**Journal borrows the task row exactly.** Date marker, title, then a meta line of
category pill · date · note indicator · tag · amount · relative time, a mood pill
on the right and hover actions last. Separators are hairlines, group heads are
overline + count. Consistency here is literal: it reuses the same classes.

**Global search** — that one field searches the whole workspace. Typing opens a
grouped panel (Pages · Transactions · Notes · Tasks · Journal) on `popover`,
`xl` radius, L2 shadow; each row is 46 px with a 28 px icon tile, a 15/500
title, a `category · context` subtitle, and a right-aligned mono meta
(`₹amount · date`). Keyboard: ↑↓ moves, ↵ opens, Esc closes. Choosing a
transaction filters that page to it; choosing a note, task or entry opens its
page.

**Dropdown menus are anchored to the viewport, not to their parent.** The menu
is `position: fixed` at the trigger's rect (width locked to the trigger, side
flipped when short on room, `max-height` from the available space). The menu is portalled to `document.body` so no
transformed or clipped ancestor can offset it, and it opens fully inside a
scrolling modal or a clipped cell. Every menu is exactly as wide as the control that opened it, and
never taller than 300 px — 36 px rows, 6 px padding, so it shows about eight
options and then scrolls. Height is clamped to the space that actually exists
(96–300 px) and the menu opens towards the roomier side, so a select in an
editor at the bottom of the page opens upward instead of running off-screen. The selected row is a tone (`secondary`), never a hue. Geometry
travels in custom properties (`--menu-left/-top/-w/-maxh`) so legacy
`.align-right` / `.drop-up` helpers cannot pin a menu to the viewport edge.

**Segmented controls** (1M/3M/6M/12M range, trends/cashflow, category/payment,
expense/income/payment inside Manage Tags) — one component, one set of
measurements: 44 px track, 34 px items, 12 px horizontal item padding, 16/500
label. Buttons, inputs and selects are 40 px; icon buttons 32 px; pills 30 px., `pill` radius everywhere, sliding indicator. Never re-style a tab row
locally; if a row needs different content, it still uses this control.

**Cards & KPI blocks** — `xl` radius, 1 px `border`, `card` background, 20 px
padding, no shadow. Header row: `h3` title (16/600), optional ghost icon action
(32 px) pushed right, then 16 px before content. KPI block: `overline` label,
`num-display` value (Geist Mono, tabular), optional `pill` delta badge, optional
sparkline at 1.5 px stroke using `chart-1`.

**Payment Channel Insights / Net Cashflow** — these are KPI + list blocks, not
mini-dashboards. Use the same card shell, `overline` labels, mono values,
hairline row dividers (`border-subtle`) at 40 px, and a single trailing
percentage per row. No gradient fills, no coloured left rails, no nested cards.

**Dropdowns / selects** — trigger 40 px, radius `md`, `card` background,
1 px `input` border, 13/500 label, chevron 14 px `muted-foreground`, hover
`accent`. Menu: `popover` background, radius `xl`, 4 px padding, L1 shadow,
max-height 280 px with internal scroll; items 36 px, radius `sm`, 10 px padding (menu 200 px min-width, 6 px inset),
hover/active `accent`, selected item shows a 14 px check plus `500` weight.
Open animation 120 ms fade + 2 px rise. Keyboard behaviour (arrows, Home/End,
typeahead, Esc) stays as already implemented in `CustomSelect`.

**Dialogs** (Manage Tags, Category drilldown, Edit transaction, Add transaction)
— radius `2xl`, `popover` background, L2 shadow, 24 px padding, max-width 560 px
(640 for tables), title `h2`, description `small` in `muted-foreground`, footer
right-aligned with ghost + primary buttons. Inside Manage Tags: the
expense/income/payment switch is the segmented control above the content,
categories are `pill` chips in `secondary` with a 14 px remove affordance, and
the add row is a 36 px input + `md` primary button on one line. **No `#1060e8`
blue anywhere** — that leftover accent is the clearest tell that this modal did
not belong to the system.

**Transactions table** — one `xl` card containing header + rows, `overflow:
hidden` so the corners clip cleanly. Header 44 px with `overline` labels;
rows 52 px, dividers `border-subtle`, hover `accent`; amount column right
aligned in Geist Mono `num-body`; category as a `pill` chip; method as plain
`caption` text. Pagination and filters sit *outside* the card, 16 px above it,
as `md` controls. No per-row rounded corners.

**Chips & badges** — `pill` only, 26 px tall, 10 px horizontal padding,
12.5/500. **No swatch dots, ever** — the pill carries the colour:

- *Category pill* — neutral `secondary` surface, **warm** hue in the text
  colour only (clay, ochre, plum, bronze, olive, rose). No fill, no dot.
- *Payment pill* — identical shape, **cool** hue in the text (blue, teal,
  indigo, cyan, violet). The warm/cool split is what tells a category from a
  channel at a glance; both stay inside the chip, so the table never competes
  with the amounts. Hue is hashed from the name, so a method added later still
  gets its own colour.
- *Semantic badges* — the `*-soft` pairs only.

**Charts** — five-colour categorical order, 1.5–2 px strokes, 11 px Geist Mono
axis labels in `muted-foreground`, horizontal gridlines only in
`border-subtle`. Tooltip is an L1 popover: `xl` radius, 10 px padding, label in
`overline`, values in `num-body`. Donut segments keep a 2 px `card`-coloured gap
between them.

**States** — every list and panel ships: skeleton (3 shimmer rows, `muted`),
empty (icon 20 px `muted-foreground`, one `h3` line, one sentence, one
`button-secondary`), error (inline banner, `destructive-soft` background,
`small` text, retry as `button-ghost`). Toasts appear bottom-right, `primary`
background, `lg` radius, 12 px padding, auto-dismiss 4 s.

## Do's and Don'ts

**Do**

- Reach for a token from this file before writing any value.
- Reuse the segmented control, card, dialog and select implementations rather
  than styling a new variant on the spot.
- Keep money in Geist Mono with `tabular-nums`, right-aligned in tables.
- Design the focus-visible and empty states in the same pass as the default.
- Prefer hierarchy (size, weight, spacing) over decoration.

**Don't**

- Mix radius values within one visual family (0 sidebar vs 16 card vs 7 tab).
- Ship a second type system: no `Instrument Serif`, no `Inter Tight`, no
  `Plus Jakarta Sans`, no per-component font sizes below 12.5 px.
- Hardcode hex values in component CSS (`#1060e8`, `#1a1d24`, `#64748b` are
  currently live in this codebase and must go).
- Put shadows on flat cards, gradients on KPI surfaces, or accent rails on
  list rows.
- Change font weight to indicate the active tab — it reflows the row.
- Let a count badge or a label change move neighbouring tabs; give tabs fixed
  slots.
- Add a component without a row in *Shapes* and an entry in *Components*.
