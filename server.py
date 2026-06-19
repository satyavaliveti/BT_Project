from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
import json
import xml.etree.ElementTree as ET


API_BASE_URL = "https://www.bt4uclassic.org/webservices/bt4u_webservice.asmx"
PROJECT_DIR = Path(__file__).parent
PORT = 8000


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
    """
    BT's feed exposes LatestEvent and LatestRSAEvent. For this starter app,
    compare those timestamps as the schedule-adherence signal.
    """
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
                self.send_json(200, {"buses": buses})
                return

            if self.path == "/api/routes":
                routes = parse_routes(fetch_xml("GetCurrentRoutes"))
                self.send_json(200, {"routes": routes})
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
