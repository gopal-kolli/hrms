---
name: SOLARA Atlas Employee Portal
description: A clear, restrained HR workspace for leave and Comp Off work.
colors:
  portal-teal: "#006b64"
  portal-teal-dark: "#00544f"
  portal-teal-soft: "#eaf4f2"
  portal-ink: "#172f35"
  portal-muted: "#547076"
  portal-line: "#c9deda"
  portal-white: "#ffffff"
  success-ink: "#086b4e"
  success-surface: "#ddf4eb"
  pending-ink: "#805b00"
  pending-surface: "#fff4d2"
  rejected-ink: "#9b3323"
  rejected-surface: "#fde7e2"
  error-surface: "#fff4f0"
typography:
  display:
    fontFamily: "InterVar, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2rem, 4vw, 2.8rem)"
    fontWeight: 780
    lineHeight: 1
    letterSpacing: "-0.035em"
  body:
    fontFamily: "InterVar, ui-sans-serif, system-ui, sans-serif"
  section-title:
    fontFamily: "InterVar, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 760
    letterSpacing: "-0.01em"
  label:
    fontFamily: "InterVar, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.78rem"
rounded:
  portal: "14px"
  control: "10px"
  tile: "12px"
  compact: "8px"
  status: "999px"
spacing:
  page-desktop: "30px 20px 108px"
  page-mobile: "16px 12px 24px"
  mobile-panel: "12px"
  panel: "20px"
  workspace: "22px"
  action-gap: "12px"
  section-gap: "20px"
components:
  button-primary:
    backgroundColor: "{colors.portal-teal}"
    textColor: "{colors.portal-white}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
    height: "46px"
  button-primary-hover:
    backgroundColor: "{colors.portal-teal-dark}"
  button-secondary:
    backgroundColor: "{colors.portal-white}"
    textColor: "{colors.portal-teal}"
    rounded: "{rounded.control}"
    height: "50px"
  button-home-mobile:
    backgroundColor: "{colors.portal-teal}"
    textColor: "{colors.portal-white}"
    rounded: "{rounded.control}"
    height: "48px"
  card:
    backgroundColor: "{colors.portal-white}"
    rounded: "{rounded.portal}"
    padding: "{spacing.panel}"
  status-approved:
    backgroundColor: "{colors.success-surface}"
    textColor: "{colors.success-ink}"
    rounded: "{rounded.status}"
  status-pending:
    backgroundColor: "{colors.pending-surface}"
    textColor: "{colors.pending-ink}"
    rounded: "{rounded.status}"
---

# Design System: SOLARA Atlas Employee Portal

## Overview

**Creative North Star: "The Modern HR Workspace"**

SOLARA Atlas is a calm operating surface built around the employee's available leave and next action. A deep teal header and actions establish the working context; a pale teal ground and white, lightly lifted panels keep data readable without decorative imagery.

The system uses its existing InterVar sans stack, strong dark-ink hierarchy, fine teal rules, and compact line icons. The approved green composition is direction and layout reference only. Previews use synthetic fixture data; implementation always renders live portal data and never copies fixture values or raster content.

**Key Characteristics:**
- Deep teal is reserved for portal chrome, primary action, active navigation, and purposeful links.
- White panels group real work; fine rules and modest ambient shadow separate them from the pale ground.
- Leave, earned Comp Off credit, request status, and manager responsibility stay explicit.
- No separate logo symbol, imagery, charts, gradients, or decorative illustration are part of this system.

## Colors

The portal palette is teal-led, quiet, and functional: ink and muted copy hold the reading hierarchy while status color is limited to status.

### Primary

- **Portal Teal** (`#006b64`): header, active tab, inline links, icons, focus-related controls, and primary actions.
- **Portal Teal Dark** (`#00544f`): primary-action hover and selected emphasis.
- **Pale Teal Ground** (`#eaf4f2`): page ground and Ionic content surface.

### Neutral

- **Portal Ink** (`#172f35`): headings and primary text.
- **Portal Muted** (`#547076`): secondary copy, metadata, and inactive navigation.
- **Fine Teal Rule** (`#c9deda`): dividers, tile strokes, and low-emphasis field borders.
- **Portal White** (`#ffffff`): panels, cards, and outlined actions.

### Status

- **Approved** (`#ddf4eb` / `#086b4e`): approved request chip and approval confirmation.
- **Pending** (`#fff4d2` / `#805b00`): open or pending request chip.
- **Rejected** (`#fde7e2` / `#9b3323`): rejected request chip and request errors. The broader alert surface is `#fff4f0` with `#f1cabe` rule.

### Named Rules

**The Teal Has a Job Rule.** Use `#006b64` for navigation, a primary action, or an intentional link; do not spread it across passive panel fill or routine body text.

## Typography

**Display Font:** InterVar, with `ui-sans-serif`, `system-ui`, and `sans-serif` fallbacks.

**Body Font:** InterVar, with `ui-sans-serif`, `system-ui`, and `sans-serif` fallbacks.

**Character:** A single clear sans family keeps operational information compact and legible. Weight and spacing, rather than a second display typeface, establish hierarchy.

### Hierarchy

- **Display** (780, `clamp(2rem, 4vw, 2.8rem)`, 1, `-0.035em`): page headings such as My leave.
- **Section title** (760, `1.05rem`, default line-height, `-0.01em`): panel and workspace headings.
- **Balance value** (780, `2rem` in the current workspace, 1, `-0.03em`): tabular-numeric leave quantities.
- **Body** (inherited family): ordinary portal text; metadata commonly uses `0.78rem`–`0.95rem` and muted ink.
- **Label/status** (760, `0.7rem` for chips): concise status labels; chips retain normal case.

### Named Rules

**The Numbers Read First Rule.** Use tabular numerals and the heavier balance-value treatment for leave amounts; keep allocation and date detail muted and smaller.

## Layout

The centered portal content and header have a `1120px` maximum width. Desktop page padding is `30px 20px 108px`; panels use 20px padding, and the leave workspace uses 22px. The main action pair is a two-column grid with a 12px gap. Request sections use two columns with a 20px gap; service links are two columns with a fine vertical rule.

At 640px and below, the brand bar reduces from 68px to 60px and home-page padding becomes `16px 12px 24px`. The leave workspace and mobile panels use 12px padding. Balance tiles remain a two-column grid but change to compact horizontal cells: a 28px pale-teal icon disc sits beside the leave name, 1.45rem balance, and allocation line. The paired home actions stay two columns at 48px minimum height with an 8px gap. The desktop request columns are replaced by one combined request summary sourced from the same leave and Comp Off APIs; its history and team links retain 44px targets. Services become a three-column core grid, while the remaining three routes sit behind the More services disclosure. The implementation is designed for the 390px mobile viewport and expands through the same `1120px` container at 1440px. Reusable primary buttons preserve a 46px minimum height.

Ionic's actual scroll-surface override is `.portal-ion-content { --background: var(--portal-teal-soft); }`; supporting native page shells use the same `--background` value.

## Elevation & Depth

Depth is soft and structural. White work surfaces use `0 10px 24px rgba(0, 77, 70, 0.08)` over the pale teal ground. Interior balance tiles rely on a fine border rather than another shadow. The primary action alone adds a smaller teal shadow (`0 8px 16px rgba(0, 107, 100, 0.18)`).

### Shadow Vocabulary

- **Portal panel** (`0 10px 24px rgba(0, 77, 70, 0.08)`): workspace, request, service, form, and list containers.
- **Primary action** (`0 8px 16px rgba(0, 107, 100, 0.18)`): filled leave action.

### Named Rules

**The Quiet Lift Rule.** Apply the ambient panel shadow once to a surface; nested content stays flat or uses a fine rule.

## Shapes

The principal panel radius is 14px. Primary controls, fields, and action buttons use 10px; balance tiles use 12px; compact hints use 8px. Status pills are fully rounded at 999px. Lines are 1px and use `#c9deda`; the form focus treatment shifts the stroke to teal and adds a 2px `#b9ddd8` outline with 1px offset. Keyboard focus generally uses a 3px `#0b8178` outline with 3px offset.

## Components

### Buttons

**Character:** Direct, full-height action controls that distinguish leave consumption from earned-credit requests.

- **Shape:** 10px radius; home action links are at least 50px high on desktop and 48px on mobile, and `.portal-primary-button` is at least 46px high.
- **Primary:** `#006b64` fill, white text, 10px 18px padding for the reusable primary button; its hover state is `#00544f`.
- **Secondary:** white fill, 1px teal border, and teal text.
- **Hover / Focus / Disabled:** home action hover rises 1px over a 0.16s ease transition; form fields expose the teal stroke and pale focus outline. Disabled primary actions use `#d3e4e1` and `#486660`. Reduced-motion mode removes relevant action and loading animation.

### Balance Tiles

**Character:** Real leave balances are contained, scannable, and numeric-first.

- **Style:** 1px `#c9deda` border, 12px radius, 18px padding on desktop. Mobile uses an 8px-radius, 9px 8px horizontal tile.
- **Content:** desktop uses a teal 24px line icon, ink leave-type name, 2rem tabular balance, and muted allocation detail. On mobile, a 28px pale-teal icon disc spans the compact horizontal cell beside the 0.72rem name, 1.45rem balance, and 0.64rem allocation detail; the allocation line remains visible.

### Cards / Containers

**Character:** White panels create a calm operational rhythm over the pale teal ground.

- **Corner style:** 14px.
- **Background:** white.
- **Shadow strategy:** use the portal-panel shadow; balance tiles inside the workspace remain unshadowed.
- **Internal padding:** 20px standard panel and 22px leave workspace on desktop; the dense mobile leave workspace and request/services panels use 12px.

### Inputs / Fields

**Style:** fields use a fine teal-rule border, 10px radius, and ink content. Focus switches to teal with the `#b9ddd8` outline; textareas use teal carets and `#586c70` placeholders.

### Request Status

**Style:** a 999px-radius chip with 4px 8px padding, 0.7rem / 760 label styling, and explicit approved, pending, or rejected color pairing. Do not communicate the state by color alone; each chip carries its status text.

### Mobile Request Summary

**Character:** one compact request panel for the latest leave and Comp Off records, without changing their data sources.

- **Rows:** 48px minimum height with a 28px teal line icon, 0.8rem title, 0.72rem metadata, and the existing text-bearing status chip.
- **History and manager links:** an inline, wrapping-safe link row with 44px minimum targets. Team requests is rendered only for an eligible manager.

### Service Grid and Disclosure

**Style:** on mobile, Attendance, Expenses, and Salary slips form the three-column core grid; each service is a 56px minimum tile with icon above label. The other three existing routes are hidden until the More services button expands them as 44px minimum horizontal rows. This is a presentation disclosure, not a new route set.

### Navigation

**Style:** persistent white Ionic tab bar with a 1px top rule, a 70px minimum desktop height and 60px mobile height, and five existing portal destinations. Inactive labels use muted ink; the current destination uses teal and weight 720. The bar carries safe-area-aware 7px/12px padding and stays within the 1120px content measure.

## Do's and Don'ts

### Do:

- **Do** use the implemented `#006b64`, `#eaf4f2`, white, and `#172f35` portal palette for home and Comp Off surfaces.
- **Do** preserve real employee data, real request status, feature gates, and existing service routes; label all preview fixtures as synthetic.
- **Do** retain the 640px dense mobile layout: horizontal balance cells with allocation lines, paired 48px home actions, 44px request links, and the core-services disclosure.
- **Do** use existing line icons and text brand treatment without adding a new logo symbol.

### Don't:

- **Don't** copy raster comp text, balances, dates, counts, avatars, or other preview fixtures into the implementation.
- **Don't** add decorative imagery, fake charts, gradients, or a new logo symbol.
- **Don't** use the stale default Ionic gray/blue theme for these portal surfaces when the implemented portal tokens provide the relevant surface.
