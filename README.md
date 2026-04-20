# Knowledge Assist (Frontend)

This app lives under the monorepo folder `frontend/`. From the repository root you can run `npm run dev` (see root `package.json`).

React + Vite SPA for **sales intelligence**: review AI-extracted Q&A per opportunity, with theming, login, and optional API-backed questions.

## Quick start

```bash
npm install
npm run dev
```

- Dev server: Vite default (typically `http://localhost:5173`).
- Production: `npm run build`, preview: `npm run preview`.

**Demo login:** `admin@relanto.ai` / `password` (see `src/services/authService.js`).

### Environment

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE` | Base URL for the questions API (default in code: `http://localhost:8000`). Used by `src/services/questionsService.js`. |

Example `.env` / `.env.local`:

```env
VITE_API_BASE=https://api.example.com
```

### Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |

### Stack

React 18 · Vite 5 · CSS variables (`src/index.css`) · inline component styles · no React Router (state-driven navigation)

---

## Purpose

The app is a **sales intelligence** workspace for reviewing AI-extracted answers to structured qualification questions (Q&A) per opportunity. Users sign in, browse opportunities on a landing dashboard, and open a detailed **Q&A review** flow with sources, editing, feedback, notes, and optional **conflict resolution** when multiple AI answers exist.

**Market Intelligence** is a module tab that currently shows a placeholder (“under development”) screen.

---

## Tech stack (detail)

| Layer | Choice |
|--------|--------|
| UI | React 18 (function components, hooks) |
| Build | Vite 5 |
| Styling | Inline styles + CSS custom properties in `src/index.css` (no CSS-in-JS library) |
| Fonts | Plus Jakarta Sans (Google Fonts, loaded from `Login.jsx`, `var(--font)`) |
| State | Local React state in `App.jsx`, `QAPage.jsx`, and leaf components |

Navigation is **state-driven** (`page`, `activeOpp`, `activeModule` in `App.jsx`), not URL-based routing.

---

## Project structure

```
src/
  App.jsx              # Auth gate, theme, module tabs, landing vs Q&A routing
  main.jsx             # React root mount
  index.css            # Global theme variables, body background
  data.js              # Opportunities, static Q&A sections (allSections), builders
  components/
    Login.jsx          # Sign in / sign up, branding panel
    Topbar.jsx         # Logo, module switcher, theme toggle, profile menu
    Landing.jsx        # Sales overview + opportunity table
    QAPage.jsx         # Opportunity Q&A: sections nav + QuestionCard list
    QuestionCard.jsx   # Per-question review form (tabs, conflict modal)
    DealSummary.jsx    # Deal summary panel (not wired in nav currently)
    Badge.jsx          # Status / type pills
  services/
    authService.js     # Dummy auth + localStorage-backed sign-up
    questionsService.js # GET /questions → section structure transformer
public/
  relanto-logo.png     # Brand asset
docs/
  dor-payload-ui-gap-notes.md  # Extraction payload vs UI coverage
```

---

## Application flow

### Unauthenticated

- Renders `LoginWithTheme` (`Login.jsx`).
- Sign-up is limited to emails on the org domain (`relanto.ai` in `authService.js`); new users persist in `localStorage` under `ka_auth_users_v1`.

### Authenticated

- **Topbar:** Knowledge Assist label, Relanto logo, module tabs, **Blue / Relanto** theme toggle, profile menu (logout).
- **Sales Intelligence**
  - **Landing** (`Landing.jsx`): stats, filters, table; row click opens Q&A for that opportunity id.
  - **Q&A** (`QAPage.jsx`): reads `allSections[oppId]` from `data.js`; section sidebar; `QuestionCard` per question.
- **Market Intelligence:** placeholder only.

### Theme

- `document.documentElement` gets `data-theme`: `blue` or `relanto`.
- Saved in `localStorage` as `ka-theme`.
- Tokens are defined in `index.css` for both themes (including dark Relanto topbar variables and `--tint` RGB for `rgba(var(--tint), …)` in components).

---

## Data model

### Opportunities (`opps` in `data.js`)

Powers the landing table: `id`, `name`, `stage`, `badge`, coverage (`ai`, `human`, `max`), etc.

### `allSections`

Map: **opportunity id** → **array of section objects**.

Each section has `id`, `title`, `icon`, `color`, `bg`, and `signals`. Entries with `type: 'ai'` include `qs` (questions). Optional deal-summary fields: `isSummary`, `narrative`, `risks`, `strengths` (full deal summary UI may be disabled in `QAPage`).

### Question object (`QuestionCard`)

| Field | Description |
|--------|-------------|
| `id` | e.g. `QID-001` from `buildDorQuestion` |
| `text` | Question copy |
| `answer` | Default AI answer |
| `conf` | Numeric confidence (data only; not shown on card header/footer) |
| `status` | `pending` \| `accepted` \| `overridden` |
| `override` | Saved override when applicable |
| `srcs` | `[{ name, color, type }]` — `type` → icons: `zoom`, `gdrive`, `slack`, `ai`, `none` |
| `conflicts` | Optional ≥2 of `{ answer, conf, srcType }` for the conflict modal |
| `subsection`, … | NovaPulse-style grouping in the nav |

Internal maps in `data.js` still use **`DOR-xxx`** keys for payloads; **`QID-xxx`** is what the UI shows.

### Stub opportunities

Ids not in the main `allSections` object get **`stubSections(id)`** at the end of `data.js` — minimal summary + one generic question.

---

## Key components

- **`QuestionCard.jsx`** — Header (question, sources, conflict badge, status). Tabs: Review, Edit, Feedback, Info. Conflict modal. Footer: accept / undo. Lifted state via props.
- **`QAPage.jsx`** — `initQAState`, handlers, section list, `QuestionCard` grid.
- **`Landing.jsx`** — Filters, tiles, table (Opportunity, Stage, Q Coverage, chevron).
- **`Topbar.jsx`** — Imports `MODULES` from `App.jsx`; Relanto theme + logo.

---

## Services

- **`authService.js`** — `signInWithEmailPassword`, `signUpWithEmailPassword`, `ORG_DOMAIN`. No real server.
- **`questionsService.js`** — `fetchQuestions()` → `GET ${VITE_API_BASE}/questions` expecting `{ questions: [...] }`. `buildSectionsFromQuestions` groups by section/subsection and normalizes ids (`qid-` / `dor-` → `QID-`). `loadQuestionsAsSections` = fetch + build (optional future wiring per opportunity).

---

## Styling conventions

Use **`var(--*)`** from `index.css` for themeable colors. Prefer `rgba(var(--tint), …)` over hardcoded blue RGBA where updated.

---

## Extending the app

1. **New opportunity with full Q&A:** add `allSections['OID/…']` in `data.js` (or merge API-built sections later).
2. **API-driven questions:** use `loadQuestionsAsSections` and attach the result to an opportunity key (not fully wired in `App.jsx` today).
3. **Deal Summary:** re-import `DealSummary.jsx` in `QAPage.jsx` and restore nav if needed.

---

## Product name & branding

- Title: **Knowledge Assist** (`index.html`, Topbar).
- Relanto logo (`public/relanto-logo.png`) and **Blue / Relanto** theme toggle.

---

## Additional notes

- **[DOR payload vs UI gaps](docs/dor-payload-ui-gap-notes.md)** — extraction payload fields compared to what the UI shows.

When you add routing, global state, or real API auth, update this README to match.
