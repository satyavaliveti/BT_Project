from argparse import ArgumentParser
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from time import sleep
from urllib.parse import urlencode
from urllib.request import urlopen
import json
import xml.etree.ElementTree as ET


API_BASE_URL = "https://www.bt4uclassic.org/webservices/bt4u_webservice.asmx"
PROJECT_DIR = Path(__file__).parent
OUTPUT_FILE = PROJECT_DIR / "historical_bunching_stops.json"
DEFAULT_DAYS = 365
DEFAULT_GAP_SECONDS = 120
DEFAULT_NO_OF_TRIPS = 300


def fetch_xml(operation, params=None):
    query = f"?{urlencode(params)}" if params else ""
    url = f"{API_BASE_URL}/{operation}{query}"

    with urlopen(url, timeout=25) as response:
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


def parse_time(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_current_routes():
    root = ET.fromstring(fetch_xml("GetCurrentRoutes"))
    routes = []

    for route in root.findall("CurrentRoutes"):
        route_short_name = text_from(route, "RouteShortName")
        if route_short_name:
            routes.append(route_short_name)

    return sorted(set(routes))


def get_scheduled_stops(route_short_name, service_date):
    root = ET.fromstring(
        fetch_xml(
            "GetScheduledStopInfo",
            {
                "routeShortName": route_short_name,
                "serviceDate": service_date.isoformat(),
            },
        )
    )
    stops = {}

    for stop in root.findall("ScheduledStops"):
        stop_code = text_from(stop, "StopCode")
        if not stop_code:
            continue

        stops[stop_code] = {
            "stopName": text_from(stop, "StopName"),
            "latitude": number_from(stop, "Latitude"),
            "longitude": number_from(stop, "Longitude"),
        }

    return stops


def get_route_stop_times(route_short_name, service_date, no_of_trips):
    root = ET.fromstring(
        fetch_xml(
            "GetArrivalAndDepartureTimesForRoutes",
            {
                "routeShortNames": route_short_name,
                "noOfTrips": str(no_of_trips),
                "serviceDate": service_date.isoformat(),
            },
        )
    )
    stop_times = []

    for item in root.findall("DeparturesForRoute"):
        arrival_time = parse_time(text_from(item, "CalculatedArrivalTime"))
        stop_code = text_from(item, "StopCode")
        trip_id = text_from(item, "TripID")

        if arrival_time is None or not stop_code or not trip_id:
            continue

        stop_times.append(
            {
                "routeShortName": route_short_name,
                "serviceDate": service_date.isoformat(),
                "tripId": trip_id,
                "patternName": text_from(item, "PatternName"),
                "stopName": text_from(item, "StopName"),
                "stopCode": stop_code,
                "rank": text_from(item, "Rank"),
                "arrivalTime": arrival_time,
            }
        )

    return stop_times


def analyze_stop_bunching(stop_times, stops_by_code, gap_seconds):
    by_stop = defaultdict(list)

    for stop_time in stop_times:
        by_stop[stop_time["stopCode"]].append(stop_time)

    events = []

    for stop_code, arrivals in by_stop.items():
        arrivals.sort(key=lambda item: item["arrivalTime"])

        for previous, current in zip(arrivals, arrivals[1:]):
            if previous["tripId"] == current["tripId"]:
                continue

            gap = int((current["arrivalTime"] - previous["arrivalTime"]).total_seconds())

            if 0 <= gap <= gap_seconds:
                stop_details = stops_by_code.get(stop_code, {})
                events.append(
                    {
                        "routeShortNames": sorted(
                            {
                                previous["routeShortName"],
                                current["routeShortName"],
                            }
                        ),
                        "serviceDate": current["serviceDate"],
                        "stopCode": stop_code,
                        "stopName": stop_details.get("stopName") or current["stopName"],
                        "latitude": stop_details.get("latitude", 0),
                        "longitude": stop_details.get("longitude", 0),
                        "gapSeconds": gap,
                        "tripIds": [previous["tripId"], current["tripId"]],
                        "patternNames": [previous["patternName"], current["patternName"]],
                    }
                )

    return events


def aggregate_events(events, requested_days, available_service_days, gap_seconds):
    hotspots = {}

    for event in events:
        if event["latitude"] == 0 or event["longitude"] == 0:
            continue

        key = event["stopCode"]

        if key not in hotspots:
            hotspots[key] = {
                "id": key,
                "routeShortName": "Multi",
                "routes": set(),
                "stopCode": event["stopCode"],
                "stopName": event["stopName"],
                "latitude": event["latitude"],
                "longitude": event["longitude"],
                "eventCount": 0,
                "observedServiceDays": set(),
                "gapTotalSeconds": 0,
                "closestGapSeconds": event["gapSeconds"],
                "sampleTripIds": set(),
            }

        hotspot = hotspots[key]
        hotspot["eventCount"] += 1
        hotspot["observedServiceDays"].add(event["serviceDate"])
        hotspot["gapTotalSeconds"] += event["gapSeconds"]
        hotspot["closestGapSeconds"] = min(hotspot["closestGapSeconds"], event["gapSeconds"])
        hotspot["sampleTripIds"].update(event["tripIds"])
        hotspot["routes"].update(event["routeShortNames"])

    results = []

    for hotspot in hotspots.values():
        event_count = hotspot["eventCount"]
        observed_days = sorted(hotspot["observedServiceDays"])

        results.append(
            {
                "id": hotspot["id"],
                "routeShortName": (
                    sorted(hotspot["routes"])[0]
                    if len(hotspot["routes"]) == 1
                    else "Multi"
                ),
                "routes": sorted(hotspot["routes"]),
                "stopCode": hotspot["stopCode"],
                "stopName": hotspot["stopName"],
                "latitude": hotspot["latitude"],
                "longitude": hotspot["longitude"],
                "eventCount": event_count,
                "observedServiceDays": len(observed_days),
                "firstObservedDate": observed_days[0] if observed_days else None,
                "lastObservedDate": observed_days[-1] if observed_days else None,
                "averageGapSeconds": round(hotspot["gapTotalSeconds"] / event_count),
                "closestGapSeconds": hotspot["closestGapSeconds"],
                "sampleTripIds": sorted(hotspot["sampleTripIds"])[:6],
            }
        )

    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "requestedDays": requested_days,
        "availableServiceDays": available_service_days,
        "gapThresholdSeconds": gap_seconds,
        "hotspots": sorted(results, key=lambda item: item["eventCount"], reverse=True),
    }


def build_historical_bunching(days, gap_seconds, no_of_trips, pause_seconds):
    routes = get_current_routes()
    today = date.today()
    all_events = []
    available_days = set()

    print(f"Checking {len(routes)} routes across the last {days} days.")
    print("This uses only the dated BT records that the public API returns.")

    for day_offset in range(days):
        service_date = today - timedelta(days=day_offset)
        day_stop_times = []
        day_stops = {}

        for route_short_name in routes:
            try:
                stop_times = get_route_stop_times(route_short_name, service_date, no_of_trips)

                if not stop_times:
                    continue

                stops = get_scheduled_stops(route_short_name, service_date)
                day_stop_times.extend(stop_times)
                day_stops.update(stops)
                available_days.add(service_date.isoformat())
                print(
                    f"{service_date} {route_short_name}: "
                    f"{len(stop_times)} stop-times"
                )
                sleep(pause_seconds)
            except Exception as error:
                print(f"Skipped {service_date} {route_short_name}: {error}")

        if day_stop_times:
            events = analyze_stop_bunching(day_stop_times, day_stops, gap_seconds)
            all_events.extend(events)
            print(f"{service_date}: {len(events)} stop-wide close-arrival events")

    result = aggregate_events(all_events, days, len(available_days), gap_seconds)

    with OUTPUT_FILE.open("w", encoding="utf-8") as output_file:
        json.dump(result, output_file, indent=2)

    print(f"Wrote {len(result['hotspots'])} historical stop hotspots to {OUTPUT_FILE}")
    print(f"Available service days returned by BT API: {result['availableServiceDays']}")


def main():
    parser = ArgumentParser(description="Build stop-level BT bus bunching hotspots.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--gap-seconds", type=int, default=DEFAULT_GAP_SECONDS)
    parser.add_argument("--no-of-trips", type=int, default=DEFAULT_NO_OF_TRIPS)
    parser.add_argument("--pause-seconds", type=float, default=0.1)
    args = parser.parse_args()

    build_historical_bunching(
        days=args.days,
        gap_seconds=args.gap_seconds,
        no_of_trips=args.no_of_trips,
        pause_seconds=args.pause_seconds,
    )


if __name__ == "__main__":
    main()
