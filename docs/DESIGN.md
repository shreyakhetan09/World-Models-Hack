# Frontend aesthetic: calm futurism

This covers the app interface around the world-model video. It should feel like a kind, capable assistant. The future-tech feel comes from precision, not neon.

Implemented in `frontend/app/globals.css` (tokens), `layout.tsx` (fonts) and the components. Use the **token classes** (`bg-surface`, `text-ink`, `text-muted`, `bg-primary`, `bg-tint`, `text-sound`, `text-hazard`, `text-survivor`, `bg-frame`, `border-line`) instead of raw hex values.

## Look and feel
- A light, airy base with one deep accent. A light interface reads as helpful and safe, and it stands apart from dark "cyber" rescue dashboards.
- Soft geometry: 12–16 px radii on cards (`rounded-xl` / `rounded-2xl`), pill-shaped buttons and tags (`rounded-full`), thin 1 px lines.
- Futuristic through detail: concentric hairline rings, small precise mono numbers, generous whitespace. **No glows, no gradients, no glass blur.**

## Palette (accents are reserved by role)
| Role | Hex | Use |
|---|---|---|
| Canvas | `#F5F7F6` | Page background |
| Surface | `#FFFFFF` | Cards, with a `#E3E8E6` 1 px border (`line`) |
| Ink | `#122220` | Primary text |
| Muted | `#6B7A77` | Labels, secondary text |
| Primary | `#0F6B63` | Buttons, active states, brand (deep teal) |
| Tint | `#DDF0EB` | Selected rows, soft highlights |
| Sound | `#E8A33D` | Audio radar and heard sources **only** |
| Hazard | `#E05A47` | Hazards and safety overrides **only** |
| Survivor / exit | `#2FA66A` | Located, escaped **only** |
| Frame | `#0C1413` | The world video frame: the one dark element and the focal point |

**Projector mode** (the header "Projector" button sets `data-theme="dark"`): canvas `#0C1413`, surfaces `#131D1B`, same accents. Teal text gets a lighter step (`#5CC2B6`) so it stays readable on dark surfaces.

## Type
- UI and headings: **Satoshi** (Fontshare). Data such as bearings, latency and scores: **JetBrains Mono** (`font-mono`).
- Sentence case throughout, with weight and size carrying the hierarchy (no ALL CAPS, including captions sent by the backend).
- Wordmark: lowercase `rescuesim`, with a small teal ring as the dot of the i.

## Key components
- **Audio radar:** soft concentric rings and an amber dot per source. Dashed rings mean muffled. A coral ring marks a heard hazard; a hollow dot marks a suspected decoy. A gentle pulse plays once when a new sound arrives; no sweeping animation.
- **Imagination tiles:** three rounded cards in a row, each with small score pills. The chosen path gets a teal outline and a "Chosen" tag.
- **Safety override:** a soft coral banner that slides down, written in the robot's voice, e.g. "Pausing: I can hear gas ahead." (`friendlyOverride`).
- **Decision feed:** short cards with a mono timestamp, an action chip (Move, Turn, Hold, Back) and a one-line reason.
- **Voice guide orb** (survivor mode, P8, not built yet): a calm teal ring that breathes when the guide speaks (`@keyframes breathe`), with captions below.
- **Compare view** (P14, not built yet): the left panel is grayscale and muted; the right panel uses the full palette and sits slightly raised. A results strip underneath uses large mono numbers.
