# BuildPlan AI — Frontend (React + Vite)

## Setup

```
cd app/frontend
npm install
npm run dev
```

This starts a dev server (usually at http://localhost:5173). Open that URL in your browser.

Make sure the Flask backend is running separately on http://localhost:5000:

```
cd app/backend
python app.py
```

## Production build

```
npm run build
```

Outputs static files to `dist/`. You can serve `dist/` with any static file server, or point Flask at it.
