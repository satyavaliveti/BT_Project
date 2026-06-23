# Blacksburg Transit React UI

Modern React + MapLibre UI for live Blacksburg Transit buses.

## Before Running

Install Node.js from:

```text
https://nodejs.org/
```

Keep the Python backend running in the original project:

```powershell
cd "C:\Users\satya\OneDrive\Documents\Visual Studio 2022\blacksburg_transit_ui"
python server.py
```

## Run the React UI

Open a second PowerShell terminal:

```powershell
cd "C:\Users\satya\OneDrive\Documents\Visual Studio 2022\blacksburg-transit-react"
npm install
npm run dev
```

Then open:

```text
http://localhost:5173
```

The React app reads bus and route data from:

```text
http://localhost:8000/api/buses
http://localhost:8000/api/routes
```
