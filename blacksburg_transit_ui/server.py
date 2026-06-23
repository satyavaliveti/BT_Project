from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
import json
import math
import xml.etree.ElementTree as ET


API_BASE_URL = "https://www.bt4uclassic.org/webservices/bt4u_webservice.asmx"
PROJECT_DIR = Path(__file__).parent
PORT = 8000
BUNCHING_HISTORY_FILE = PROJECT_DIR / "bus_bunching_history.jsonl"
HISTORICAL_BUNCHING_FILE = PROJECT_DIR / "historical_bunching_stops.json"
BUNCHING_DISTANCE_METERS = 250
BUNCHING_GRID_SIZE = 0.002
BUNCHING_MIN_EVENTS = 1


def fetch_xml(operation):
    url = f"{API_BASE_URL}/{operation}"
    with urlopen(url, timeout=15) as response:
        return response.read()


def text_from(element, name, default=""):
    child = element.find(name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def number_from(element, name, default=0.0):
    try:
        return float(text_from(element, name))
    except ValueError:
        return default


def parse_api_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_schedule_status(latest_event, latest_rsa_event):
    actual = parse_api_time(latest_event)
    scheduled = parse_api_time(latest_rsa_event)

    if actual is None or scheduled is None:
        return "unknown", "Unknown schedule status", 0

    seconds = int((actual - scheduled).total_seconds())

    if seconds > 60:
        return "late", f"{seconds // 60} min late", seconds
    if seconds < -60:
        return "ahead", f"{abs(seconds) // 60} min ahead", seconds
    return "on-time", "On time", seconds


def parse_buses(xml_bytes):
    root = ET.fromstring(xml_bytes)
    buses = []

    for item in root.findall("LatestInfoTable"):
        latitude = number_from(item, "Latitude")
        longitude = number_from(item, "Longitude")

        if latitude == 0 or longitude == 0:
            continue

        latest_event = text_from(item, "LatestEvent")
        latest_rsa_event = text_from(item, "LatestRSAEvent")
        status, status_label, schedule_delta_seconds = get_schedule_status(
            latest_event,
            latest_rsa_event,
        )

        buses.append(
            {
                "id": text_from(item, "AgencyVehicleName"),
                "routeShortName": text_from(item, "RouteShortName"),
                "patternName": text_from(item, "PatternName"),
                "tripStartTime": text_from(item, "TripStartTime"),
                "lastStopName": text_from(item, "LastStopName"),
                "stopCode": text_from(item, "StopCode"),
                "isBusAtStop": text_from(item, "IsBusAtStop") == "Y",
                "latitude": latitude,
                "longitude": longitude,
                "direction": number_from(item, "Direction"),
                "speed": number_from(item, "Speed"),
                "passengerCount": int(number_from(item, "TotalCount")),
                "capacityPercent": int(number_from(item, "PercentOfCapacity")),
                "latestEvent": latest_event,
                "latestScheduleEvent": latest_rsa_event,
                "scheduleDeltaSeconds": schedule_delta_seconds,
                "status": status,
                "statusLabel": status_label,
            }
        )

    return buses


def parse_routes(xml_bytes):
    root = ET.fromstring(xml_bytes)
    routes = {}

    for item in root.findall("CurrentRoutes"):
        short_name = text_from(item, "RouteShortName")
        if not short_name:
            continue

        routes[short_name] = {
            "name": text_from(item, "RouteName"),
            "shortName": short_name,
            "color": f"#{text_from(item, 'RouteColor', '555555')}",
            "textColor": f"#{text_from(item, 'RouteTextColor', 'FFFFFF')}",
            "realTimeInfoAvailable": text_from(item, "RealTimeInfoAvail") == "true",
        }

    return routes


def distance_meters(first_bus, second_bus):
    earth_radius_meters = 6371000
    first_lat = math.radians(first_bus["latitude"])
    second_lat = math.radians(second_bus["latitude"])
    delta_lat = math.radians(second_bus["latitude"] - first_bus["latitude"])
    delta_lng = math.radians(second_bus["longitude"] - first_bus["longitude"])

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_meters * c


def grid_key(latitude, longitude):
    return (
        round(latitude / BUNCHING_GRID_SIZE) * BUNCHING_GRID_SIZE,
        round(longitude / BUNCHING_GRID_SIZE) * BUNCHING_GRID_SIZE,
    )


def find_bunching_events(buses):
    events = []
    checked_pairs = set()

    for first in buses:
        for second in buses:
            if first["id"] == second["id"]:
                continue
            if first["routeShortName"] != second["routeShortName"]:
                continue

            pair_key = tuple(sorted([first["id"], second["id"]]))
            if pair_key in checked_pairs:
                continue

            checked_pairs.add(pair_key)
            distance = distance_meters(first, second)

            if distance > BUNCHING_DISTANCE_METERS:
                continue

            latitude = (first["latitude"] + second["latitude"]) / 2
            longitude = (first["longitude"] + second["longitude"]) / 2
            grid_latitude, grid_longitude = grid_key(latitude, longitude)

            events.append(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "routeShortName": first["routeShortName"],
                    "busIds": list(pair_key),
                    "latitude": latitude,
                    "longitude": longitude,
                    "gridLatitude": grid_latitude,
                    "gridLongitude": grid_longitude,
                    "distanceMeters": round(distance, 1),
                    "lastStops": [first["lastStopName"], second["lastStopName"]],
                }
            )

    return events


def record_bunching_events(buses):
    events = find_bunching_events(buses)

    if not events:
        return []

    with BUNCHING_HISTORY_FILE.open("a", encoding="utf-8") as history_file:
        for event in events:
            history_file.write(json.dumps(event) + "\n")

    return events


def read_bunching_events():
    if not BUNCHING_HISTORY_FILE.exists():
        return []

    events = []

    with BUNCHING_HISTORY_FILE.open("r", encoding="utf-8") as history_file:
        for line in history_file:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return events


def get_bunching_hotspots():
    hotspots = {}

    for event in read_bunching_events():
        key = (
            event["routeShortName"],
            event["gridLatitude"],
            event["gridLongitude"],
        )

        if key not in hotspots:
            hotspots[key] = {
                "id": f"{event['routeShortName']}-{event['gridLatitude']}-{event['gridLongitude']}",
                "routeShortName": event["routeShortName"],
                "latitudeTotal": 0,
                "longitudeTotal": 0,
                "eventCount": 0,
                "busIds": set(),
                "lastSeen": event["timestamp"],
                "averageDistanceMeters": 0,
                "distanceTotal": 0,
            }

        hotspot = hotspots[key]
        hotspot["latitudeTotal"] += event["latitude"]
        hotspot["longitudeTotal"] += event["longitude"]
        hotspot["eventCount"] += 1
        hotspot["distanceTotal"] += event["distanceMeters"]
        hotspot["lastSeen"] = max(hotspot["lastSeen"], event["timestamp"])
        hotspot["busIds"].update(event["busIds"])

    results = []

    for hotspot in hotspots.values():
        if hotspot["eventCount"] < BUNCHING_MIN_EVENTS:
            continue

        results.append(
            {
                "id": hotspot["id"],
                "routeShortName": hotspot["routeShortName"],
                "latitude": hotspot["latitudeTotal"] / hotspot["eventCount"],
                "longitude": hotspot["longitudeTotal"] / hotspot["eventCount"],
                "eventCount": hotspot["eventCount"],
                "busIds": sorted(hotspot["busIds"]),
                "lastSeen": hotspot["lastSeen"],
                "averageDistanceMeters": round(
                    hotspot["distanceTotal"] / hotspot["eventCount"],
                    1,
                ),
            }
        )

    return sorted(results, key=lambda item: item["eventCount"], reverse=True)


def get_historical_stop_bunching():
    if not HISTORICAL_BUNCHING_FILE.exists():
        return {
            "generatedAt": None,
            "requestedDays": 365,
            "availableServiceDays": 0,
            "hotspots": [],
            "message": (
                "No historical stop bunching cache exists yet. Run "
                "build_historical_bunching.py to collect the BT serviceDate data "
                "that the public API makes available."
            ),
        }

    with HISTORICAL_BUNCHING_FILE.open("r", encoding="utf-8") as data_file:
        return json.load(data_file)


class TransitHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def send_json(self, status_code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        try:
            if self.path == "/api/buses":
                buses = parse_buses(fetch_xml("GetCurrentBusInfo"))
                record_bunching_events(buses)
                self.send_json(200, {"buses": buses})
                return

            if self.path == "/api/routes":
                routes = parse_routes(fetch_xml("GetCurrentRoutes"))
                self.send_json(200, {"routes": routes})
                return

            if self.path == "/api/bunching":
                hotspots = get_bunching_hotspots()
                self.send_json(
                    200,
                    {
                        "hotspots": hotspots,
                        "distanceMeters": BUNCHING_DISTANCE_METERS,
                        "minimumEvents": BUNCHING_MIN_EVENTS,
                    },
                )
                return

            if self.path == "/api/historical-bunching":
                self.send_json(200, get_historical_stop_bunching())
                return

            super().do_GET()
        except (URLError, TimeoutError, ET.ParseError) as error:
            self.send_json(502, {"error": f"Could not load transit data: {error}"})


def main():
    server = ThreadingHTTPServer(("localhost", PORT), TransitHandler)
    print(f"Blacksburg Transit UI running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop the server.")
    server.serve_forever()


if __name__ == "__main__":
    main()
