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

The **Opinions** tab on Home and Explore searches the OpinionSearch backend. The **Example data** option contains separate, hand-authored discussions and visualisations. Search opens a selectable Positive / Negative / Neutral sentiment overview with original opinions below it, using the example page’s visual style. Unscored results stay separate. Sentiment is tone, not agreement; automatic discussion grouping and topic-specific stance analysis remain deferred.

## Page map

The core journey is **Home → Topic index → Discussion → Original contribution**. Submitting from Home now runs embedding and sentiment scoring and opens the saved contribution with its private receipt; the submitted text becomes publicly searchable.

| Route | Purpose |
| --- | --- |
| `/` | Describe an issue and preview topics. |
| `/topics` | Search backend opinions, or browse and sort illustrative discussions under Example data. |
| `/discussions/:id` | View positions, reasons and links to original contributions. Currently uses labelled examples. |
| `/contributions/:id` | Reopen a submitted input with its receipt, or read an illustrative source contribution. |
| `/privacy-policy`, `/terms-and-conditions` | Factual prototype privacy and scope information. |

Old `/topics/:id` links open that topic's group in the index. Session codes on home links are ignored and removed from the URL. Session rooms, voting, common-ground generation, recommendations, reports and their APIs have been retired from this frontend; old report links show the unavailable-page view.

## Connect the backend

Start this repository's backend with `docker compose up --build` from the repository root. Copy [.env.example](.env.example) to `.env.local` and set `OPINIONSEARCH_API_TARGET` to that OpinionSearch backend origin. With its default Docker port:

```dotenv
OPINIONSEARCH_API_TARGET=http://127.0.0.1:8000
```

Then run:

```sh
npm run dev
```

Vite forwards `/api` only when `OPINIONSEARCH_API_TARGET` is explicitly configured; there is no default backend target. This variable configures Vite's local proxy and is not exposed to browser code. Demo mode ignores it. Restart Vite after changing the target.

Search uses `GET /api/v1/opinions/?query=...`, reusing the backend's existing BGE-M3 search. Add opinions through Django admin or the backend's fixture loader to make them searchable; starting the containers does not seed opinions. The first model load may take longer than the client's timeout; retry after the backend finishes loading. [SEARCH_API.md](SEARCH_API.md) records this small read contract. After applying migrations to an existing database, run `docker compose run --rm web uv run python manage.py backfill_sentiment` to score opinions that predate the sentiment field. This leaves private contributions unchanged.

The issue form uses the two contribution endpoints in [API_CONTRACT.md](API_CONTRACT.md). It states that submitted text will be publicly searchable and sends `publication: "public"`. The backend stores the original `Contribution`, runs the existing BGE-M3 embedding and sentiment functions, and creates one linked `Opinion` for search. Submitting “i like coffee” therefore makes it retrievable by searching “coffee”. No topic, stance or author is invented. Earlier private submissions keep their original visibility.

The client boundary is [contributions.js](src/components/understanding/contributions.js). The form sends text, a submission key and visibility; the saved-text page retrieves the original with its receipt. Both models currently run synchronously, with a 120-second submission timeout for cold model loading. An inference failure preserves the source and returns an error; retrying the same request finishes indexing without duplicate records. There is no background poll, classification form, editing or withdrawal control. This folder does not start a Django server or the separate HiveMind backend.

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

Before a public deployment, establish the operator/contact, hosting and processors, storage and deletion policies, and final privacy/terms content. The current information pages describe the prototype, and the API contract records the implemented intake flow and its extension boundary.

Licence metadata has been preserved: this frontend declares `AGPL-3.0-or-later`, while OpinionSearch's root `LICENSE.txt` contains GPL v3. The copied HiveMind documentation also contains conflicting licence labels. Reconcile that provenance separately; the cleanup does not choose a new licence or remove origin attribution.
