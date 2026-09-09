# OpinionSearch frontend

This folder contains the website and the [contribution API contract](API_CONTRACT.md) for the backend team. It does not implement a backend or an analysis pipeline.

It is self-contained within OpinionSearch and does not import, run or read files from the separate HiveMind repository. The website currently retains the chosen **HiveMind** display name and logo; its package and browser-storage identity are **OpinionSearch**.

## Try the frontend without a backend

From this folder, with Node.js 20+ and npm installed:

```sh
npm ci
npm run dev:demo
```

Open `http://localhost:5174`. This project uses a fixed development port and stops if it is occupied, rather than silently moving to another port. The input and saved-text page explicitly say **Demo**. Submitted text is stored only in the current browser tab's session storage. It does not reach a server or join the example discussions. This mode demonstrates the interaction; it is not durable storage or a security implementation.

The topic index's **Example data** option contains separate, hand-authored discussions. The public index is empty while its backend contract is deferred.

## Page map

The core journey is **Home → Topic index → Discussion → Original contribution**. Submitting from Home opens a private contribution receipt.

| Route | Purpose |
| --- | --- |
| `/` | Describe an issue and preview topics. |
| `/topics` | Browse broad topics and sort the discussions within them. |
| `/discussions/:id` | View positions, reasons and links to original contributions. Currently uses labelled examples. |
| `/contributions/:id` | Read a private saved input or an illustrative source contribution. |
| `/privacy-policy`, `/terms-and-conditions` | Factual prototype privacy and scope information. |

Old `/topics/:id` links open that topic's group in the index. Session codes on home links are ignored and removed from the URL. Session rooms, voting, common-ground generation, recommendations, reports and their APIs have been retired from this frontend; old report links show the unavailable-page view.

## Connect the backend

Copy [.env.example](.env.example) to `.env.local` and set `OPINIONSEARCH_API_TARGET` to the intended OpinionSearch backend origin. For example, if that backend runs on port 8001:

```dotenv
OPINIONSEARCH_API_TARGET=http://127.0.0.1:8001
```

Then run:

```sh
npm run dev
```

In this mode, the frontend calls the two endpoints in [API_CONTRACT.md](API_CONTRACT.md). Vite forwards `/api` only when `OPINIONSEARCH_API_TARGET` is explicitly configured; there is no default backend target. This variable configures Vite's local proxy and is not exposed to browser code. Demo mode ignores it. Restart Vite after changing the target.

Before the backend is configured and those endpoints exist, sending displays an error and preserves the input. It never silently falls back to demo storage. This folder does not start a Django server or the separate HiveMind backend.

The client boundary is [contributions.js](src/components/understanding/contributions.js). The form sends text and a submission key; the saved-text page retrieves the original contribution with its receipt. There is no processing poll, classification form, editing or publication control in this intake-only flow.

## Build

```sh
npm run build
npm run preview
```

Production builds always use the real API. The local contribution demo is enabled only by the development server's `demo` mode. The deployment host must serve `dist` and return its `index.html` for frontend page routes, while routing `/api` to the backend.

`npm run preview` serves the build at `http://localhost:4174` and uses the same explicitly configured local API target. This setting does not configure production hosting; the deployed `/api` must belong to OpinionSearch.

Browser receipts, their history fallback and local demo records use OpinionSearch-specific names. The frontend does not read or migrate the separate HiveMind application's stored records.

Runtime logos and icons are in `public/`. The full-size logo and editable social image are retained as source assets in [design/brand](design/brand), outside the deployed asset directory.

## Provenance and deployment details

This frontend was copied from HiveMind, which builds on the original Murmi software from Carbon Copy Association. This records the software's origin; it does not identify the operator of this OpinionSearch prototype.

Before a public deployment, establish the operator/contact, hosting and processors, storage and deletion policies, and final privacy/terms content. The current information pages describe the prototype, and the API contract specifies future backend requirements.

Licence metadata has been preserved: this frontend declares `AGPL-3.0-or-later`, while OpinionSearch's root `LICENSE.txt` contains GPL v3. The copied HiveMind documentation also contains conflicting licence labels. Reconcile that provenance separately; the cleanup does not choose a new licence or remove origin attribution.
