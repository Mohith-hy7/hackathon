# BeeGuard

BeeGuard is a single-server demo for bee health, pesticide alerts, hive-to-crop matching, and honey traceability. The browser UI and API are served together, and the demo data persists in a local SQLite database.

## Run it

1. Install Node.js 22.5 or later (Node 24 is recommended).
2. In this folder, run:

   ```powershell
   npm start
   ```

3. Open http://127.0.0.1:5000 in a browser.

There are no third-party packages to install. The app uses Node's built-in HTTP server and SQLite driver.

## Included working flows

- Dashboard metrics loaded from SQLite
- Persisted pesticide alert protection action
- Server-calculated and saved hive/crop matches
- Honey batch verification
- Honey buyer search and price comparison
- Read and create honey listing API endpoints

## API quick reference

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server health check |
| GET | `/api/dashboard` | Live overview metrics |
| GET / POST | `/api/alerts` | Read or create pesticide alerts |
| POST | `/api/alerts/:id/protect` | Record a hive protection action |
| GET / POST | `/api/matches` | Read or calculate hive matches |
| GET / POST | `/api/honey` | Browse or add honey |
| GET | `/api/honey/batch/:batchId` | Verify a batch |
| GET | `/api/buyer/search?type=Wildflower&maxPrice=450` | Search affordable honey |

Demo batch IDs: `BG2026-001` and `BG2026-002`.

> This is a local hackathon/demo backend. Add login and authorization before allowing public deployment or using real producer data.
