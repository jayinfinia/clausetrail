# React frontend

`npm ci && npm run build` creates assets served by FastAPI. `npm run dev` runs Vite with API proxying; when using that path set APP_ORIGIN=http://localhost:5173 for backend origin checks and open the matching localhost URL. Build mode at localhost:8000 is the tested default.

Screens: demo sign-in, overview, register, review queue, imports/folder picker, spreadsheet mapping and conflicts, evidence review, amendments, deadlines, cited questions and processing settings. API authorization remains authoritative.
