# Blacksburg Transit Tracker

A simple browser UI that shows live Blacksburg Transit buses on a map.

## Features

- Shows live bus markers using latitude and longitude from BT4U.
- Refreshes bus positions every 15 seconds.
- Animates marker movement between refreshes.
- Opens a popup when a bus is clicked.
- Uses marker colors for schedule status:
  - Green: on time
  - Red: late / not on time
  - Purple: ahead of schedule

## How to Run

Open PowerShell in this folder and run:

```powershell
python server.py
```

Then open this URL in your browser:

```text
http://localhost:8000
```

Press `Ctrl+C` in the terminal to stop the server.

## API Used

This project uses the BT4U classic web service:

```text
https://www.bt4uclassic.org/webservices/bt4u_webservice.asmx
```

The local Python server calls:

- `GetCurrentBusInfo`
- `GetCurrentRoutes`

The Python server converts the XML responses into JSON for the browser UI.

## Schedule Status Note

The starter version compares `LatestEvent` and `LatestRSAEvent` from the BT4U feed:

- More than 60 seconds late: red
- Within 60 seconds: green
- More than 60 seconds early: purple

If you later find a more official schedule-adherence field in the BT4U data, update `get_schedule_status()` in `server.py`.
