import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";


const API_BASE_URL = "http://localhost:8000";
const REFRESH_MS = 15000;
const BLACKSBURG_CENTER = [-80.4139, 37.2296];

const STATUS_LABELS = {
  all: "All",
  "on-time": "On Time",
  late: "Late",
  ahead: "Ahead",
  unknown: "Unknown",
};

const STATUS_COLORS = {
  "on-time": "#16a34a",
  late: "#dc2626",
  ahead: "#7c3aed",
  unknown: "#64748b",
};


function statusClass(status) {
  return status || "unknown";
}


function formatTime(value) {
  if (!value) {
    return "Unknown";
  }

  return new Date(value).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}


function statusCriteria(status) {
  const criteria = {
    "on-time": {
      title: "On Time Criteria",
      description: "A bus is marked on time when its latest actual event is within 60 seconds before or after the calculated schedule event.",
      formula: "schedule delta is between -60 and +60 seconds",
    },
    late: {
      title: "Late Criteria",
      description: "A bus is marked late when its latest actual event is more than 60 seconds after the calculated schedule event.",
      formula: "actual time - scheduled time > 60 seconds",
    },
    ahead: {
      title: "Ahead Criteria",
      description: "A bus is marked ahead when its latest actual event is more than 60 seconds before the calculated schedule event.",
      formula: "actual time - scheduled time < -60 seconds",
    },
  };

  return criteria[status] || null;
}


function historicalMarkerStyle(hotspot) {
  const eventCount = hotspot.eventCount || 1;
  const strength = Math.min(eventCount / 8, 1);
  const haloAlpha = 0.18 + strength * 0.42;
  const fillAlpha = 0.42 + strength * 0.5;
  const red = Math.round(185 + strength * 70);

  return {
    haloAlpha,
    fillAlpha,
    red,
  };
}


function createBusMarkerElement(bus, isSelected) {
  const wrapper = document.createElement("button");
  wrapper.className = `bus-marker ${statusClass(bus.status)} ${isSelected ? "selected" : ""}`;
  wrapper.type = "button";
  wrapper.title = `Bus ${bus.id} on ${bus.routeShortName}`;
  wrapper.style.setProperty("--direction", `${bus.direction || 0}deg`);
  wrapper.innerHTML = `<span>${bus.routeShortName || "?"}</span>`;
  return wrapper;
}


function createHotspotMarkerElement(hotspot) {
  const wrapper = document.createElement("button");
  wrapper.className = "bunching-marker";
  wrapper.type = "button";
  wrapper.title = `${hotspot.routeShortName} bunching hotspot`;
  wrapper.innerHTML = `
    <span>${hotspot.eventCount}</span>
    <small>${hotspot.routeShortName}</small>
  `;
  return wrapper;
}


function createHistoricalStopMarkerElement(hotspot) {
  const wrapper = document.createElement("button");
  const markerStyle = historicalMarkerStyle(hotspot);

  wrapper.className = "historical-stop-marker";
  wrapper.type = "button";
  wrapper.title = `${hotspot.stopName} historical bunching stop`;
  wrapper.style.setProperty("--halo-alpha", markerStyle.haloAlpha);
  wrapper.style.setProperty("--fill-alpha", markerStyle.fillAlpha);
  wrapper.style.setProperty("--red-strength", markerStyle.red);
  wrapper.innerHTML = `
    <span>${hotspot.eventCount}</span>
    <small>${hotspot.routeShortName}</small>
  `;
  return wrapper;
}


function App() {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRefs = useRef(new Map());
  const hotspotRefs = useRef(new Map());
  const historicalStopRefs = useRef(new Map());

  const [buses, setBuses] = useState([]);
  const [bunchingHotspots, setBunchingHotspots] = useState([]);
  const [historicalStopHotspots, setHistoricalStopHotspots] = useState([]);
  const [historicalCoverage, setHistoricalCoverage] = useState(null);
  const [routes, setRoutes] = useState({});
  const [selectedBusId, setSelectedBusId] = useState(null);
  const [selectedRoute, setSelectedRoute] = useState("all");
  const [selectedStatus, setSelectedStatus] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const [isPaused, setIsPaused] = useState(false);
  const [showBunching, setShowBunching] = useState(true);
  const [showHistoricalBunching, setShowHistoricalBunching] = useState(true);
  const [isPanelOpen, setIsPanelOpen] = useState(true);
  const [error, setError] = useState("");

  const routeColor = (routeShortName) => routes[routeShortName]?.color || "#334155";
  const routeName = (routeShortName, fallback) => routes[routeShortName]?.name || fallback || "Unknown route";

  const selectedBus = useMemo(
    () => buses.find((bus) => bus.id === selectedBusId) || null,
    [buses, selectedBusId],
  );

  const activeRoutes = useMemo(
    () => [...new Set(buses.map((bus) => bus.routeShortName))].filter(Boolean).sort(),
    [buses],
  );

  const visibleHotspots = useMemo(() => {
    if (!showBunching) {
      return [];
    }

    return bunchingHotspots.filter((hotspot) => (
      selectedRoute === "all" || hotspot.routeShortName === selectedRoute
    ));
  }, [bunchingHotspots, selectedRoute, showBunching]);

  const visibleHistoricalStopHotspots = useMemo(() => {
    if (!showHistoricalBunching) {
      return [];
    }

    return historicalStopHotspots.filter((hotspot) => (
      selectedRoute === "all" || hotspot.routes?.includes(selectedRoute)
    ));
  }, [historicalStopHotspots, selectedRoute, showHistoricalBunching]);

  const stats = useMemo(() => ({
    all: buses.length,
    "on-time": buses.filter((bus) => bus.status === "on-time").length,
    late: buses.filter((bus) => bus.status === "late").length,
    ahead: buses.filter((bus) => bus.status === "ahead").length,
  }), [buses]);

  const filteredBuses = useMemo(() => {
    const search = searchText.trim().toLowerCase();

    return buses.filter((bus) => {
      const routeMatches = selectedRoute === "all" || bus.routeShortName === selectedRoute;
      const statusMatches = selectedStatus === "all" || bus.status === selectedStatus;
      const searchMatches = [
        bus.id,
        bus.routeShortName,
        bus.patternName,
        bus.lastStopName,
        routeName(bus.routeShortName, bus.patternName),
      ]
        .join(" ")
        .toLowerCase()
        .includes(search);

      return routeMatches && statusMatches && searchMatches;
    });
  }, [buses, routes, searchText, selectedRoute, selectedStatus]);

  useEffect(() => {
    if (mapRef.current || !mapContainerRef.current) {
      return;
    }

    mapRef.current = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
          },
        ],
      },
      center: BLACKSBURG_CENTER,
      zoom: 13,
    });

    mapRef.current.addControl(new maplibregl.NavigationControl(), "bottom-right");

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    async function loadRoutes() {
      const response = await fetch(`${API_BASE_URL}/api/routes`);
      if (!response.ok) {
        throw new Error("Could not load routes.");
      }

      const data = await response.json();
      setRoutes(data.routes);
    }

    loadRoutes().catch((nextError) => setError(nextError.message));
  }, []);

  useEffect(() => {
    async function loadHistoricalBunching() {
      const response = await fetch(`${API_BASE_URL}/api/historical-bunching`);
      if (!response.ok) {
        throw new Error("Could not load historical bunching.");
      }

      const data = await response.json();
      setHistoricalStopHotspots(data.hotspots || []);
      setHistoricalCoverage({
        generatedAt: data.generatedAt,
        requestedDays: data.requestedDays,
        availableServiceDays: data.availableServiceDays,
        gapThresholdSeconds: data.gapThresholdSeconds,
        message: data.message,
      });
    }

    loadHistoricalBunching().catch((nextError) => setError(nextError.message));
  }, []);

  async function refreshBuses() {
    try {
      const busesResponse = await fetch(`${API_BASE_URL}/api/buses`);
      if (!busesResponse.ok) {
        throw new Error("Could not load buses.");
      }

      const busesData = await busesResponse.json();
      const bunchingResponse = await fetch(`${API_BASE_URL}/api/bunching`);

      if (!bunchingResponse.ok) {
        throw new Error("Could not load bunching hotspots.");
      }

      const bunchingData = await bunchingResponse.json();

      setBuses(busesData.buses);
      setBunchingHotspots(bunchingData.hotspots);
      setLastRefreshed(new Date());
      setError("");
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  useEffect(() => {
    refreshBuses();
  }, []);

  useEffect(() => {
    if (isPaused) {
      return undefined;
    }

    const timer = window.setInterval(refreshBuses, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [isPaused]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }

    const visibleIds = new Set(filteredBuses.map((bus) => bus.id));

    for (const bus of filteredBuses) {
      const isSelected = bus.id === selectedBusId;
      const position = [bus.longitude, bus.latitude];
      const current = markerRefs.current.get(bus.id);

      if (current) {
        current.marker.setLngLat(position);
        current.element.className = `bus-marker ${statusClass(bus.status)} ${isSelected ? "selected" : ""}`;
        current.element.title = `Bus ${bus.id} on ${bus.routeShortName}`;
        current.element.style.setProperty("--direction", `${bus.direction || 0}deg`);
        current.element.innerHTML = `<span>${bus.routeShortName || "?"}</span>`;
        current.marker.setPopup(new maplibregl.Popup({ offset: 24 }).setHTML(popupHtml(bus)));
      } else {
        const element = createBusMarkerElement(bus, isSelected);
        element.addEventListener("click", () => selectBus(bus.id, true));

        const marker = new maplibregl.Marker({ element, rotationAlignment: "map" })
          .setLngLat(position)
          .setPopup(new maplibregl.Popup({ offset: 24 }).setHTML(popupHtml(bus)))
          .addTo(mapRef.current);

        markerRefs.current.set(bus.id, { marker, element });
      }
    }

    for (const [busId, markerData] of markerRefs.current.entries()) {
      if (!visibleIds.has(busId)) {
        markerData.marker.remove();
        markerRefs.current.delete(busId);
      }
    }
  }, [filteredBuses, selectedBusId, routes]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }

    const visibleIds = new Set(visibleHotspots.map((hotspot) => hotspot.id));

    for (const hotspot of visibleHotspots) {
      const position = [hotspot.longitude, hotspot.latitude];
      const current = hotspotRefs.current.get(hotspot.id);

      if (current) {
        const markerStyle = historicalMarkerStyle(hotspot);

        current.marker.setLngLat(position);
        current.element.style.setProperty("--halo-alpha", markerStyle.haloAlpha);
        current.element.style.setProperty("--fill-alpha", markerStyle.fillAlpha);
        current.element.style.setProperty("--red-strength", markerStyle.red);
        current.element.innerHTML = `
          <span>${hotspot.eventCount}</span>
          <small>${hotspot.routeShortName}</small>
        `;
        current.marker.setPopup(new maplibregl.Popup({ offset: 28 }).setHTML(hotspotPopupHtml(hotspot)));
      } else {
        const element = createHotspotMarkerElement(hotspot);
        const marker = new maplibregl.Marker({ element })
          .setLngLat(position)
          .setPopup(new maplibregl.Popup({ offset: 28 }).setHTML(hotspotPopupHtml(hotspot)))
          .addTo(mapRef.current);

        hotspotRefs.current.set(hotspot.id, { marker, element });
      }
    }

    for (const [hotspotId, markerData] of hotspotRefs.current.entries()) {
      if (!visibleIds.has(hotspotId)) {
        markerData.marker.remove();
        hotspotRefs.current.delete(hotspotId);
      }
    }
  }, [visibleHotspots]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }

    const visibleIds = new Set(visibleHistoricalStopHotspots.map((hotspot) => hotspot.id));

    for (const hotspot of visibleHistoricalStopHotspots) {
      const position = [hotspot.longitude, hotspot.latitude];
      const current = historicalStopRefs.current.get(hotspot.id);

      if (current) {
        current.marker.setLngLat(position);
        current.element.innerHTML = `
          <span>${hotspot.eventCount}</span>
          <small>${hotspot.routeShortName}</small>
        `;
        current.marker.setPopup(
          new maplibregl.Popup({ offset: 30 }).setHTML(historicalStopPopupHtml(hotspot)),
        );
      } else {
        const element = createHistoricalStopMarkerElement(hotspot);
        const marker = new maplibregl.Marker({ element })
          .setLngLat(position)
          .setPopup(new maplibregl.Popup({ offset: 30 }).setHTML(historicalStopPopupHtml(hotspot)))
          .addTo(mapRef.current);

        historicalStopRefs.current.set(hotspot.id, { marker, element });
      }
    }

    for (const [hotspotId, markerData] of historicalStopRefs.current.entries()) {
      if (!visibleIds.has(hotspotId)) {
        markerData.marker.remove();
        historicalStopRefs.current.delete(hotspotId);
      }
    }
  }, [visibleHistoricalStopHotspots]);

  function popupHtml(bus) {
    return `
      <strong>Bus ${bus.id} - ${bus.statusLabel}</strong>
      <div class="popup-grid">
        <span>Route</span><b>${bus.routeShortName} - ${routeName(bus.routeShortName, bus.patternName)}</b>
        <span>Last stop</span><b>${bus.lastStopName || "Unknown"}</b>
        <span>Speed</span><b>${bus.speed} mph</b>
        <span>Capacity</span><b>${bus.capacityPercent}%</b>
        <span>Updated</span><b>${formatTime(bus.latestEvent)}</b>
      </div>
    `;
  }

  function hotspotPopupHtml(hotspot) {
    return `
      <strong>${hotspot.routeShortName} bunching hotspot</strong>
      <div class="popup-grid">
        <span>Events</span><b>${hotspot.eventCount}</b>
        <span>Buses seen</span><b>${hotspot.busIds.join(", ")}</b>
        <span>Avg distance</span><b>${hotspot.averageDistanceMeters} m</b>
        <span>Last seen</span><b>${formatTime(hotspot.lastSeen)}</b>
      </div>
    `;
  }

  function historicalStopPopupHtml(hotspot) {
    return `
      <strong>${hotspot.stopName}</strong>
      <div class="popup-grid">
        <span>Routes</span><b>${hotspot.routes?.join(", ") || hotspot.routeShortName}</b>
        <span>Stop code</span><b>${hotspot.stopCode}</b>
        <span>Close arrivals</span><b>${hotspot.eventCount}</b>
        <span>Observed days</span><b>${hotspot.observedServiceDays}</b>
        <span>Avg gap</span><b>${hotspot.averageGapSeconds} sec</b>
        <span>Closest gap</span><b>${hotspot.closestGapSeconds} sec</b>
        <span>Criteria</span><b>2 buses at this stop within ${historicalCoverage?.gapThresholdSeconds || 120} sec</b>
      </div>
    `;
  }

  function selectBus(busId, panToBus) {
    const bus = buses.find((item) => item.id === busId);
    setSelectedBusId(busId);

    if (bus && panToBus && mapRef.current) {
      mapRef.current.flyTo({
        center: [bus.longitude, bus.latitude],
        zoom: Math.max(mapRef.current.getZoom(), 15),
        speed: 1.1,
      });
    }

    markerRefs.current.get(busId)?.marker.togglePopup();
  }

  function fitVisibleBuses() {
    if (!mapRef.current || filteredBuses.length === 0) {
      return;
    }

    const bounds = new maplibregl.LngLatBounds();
    filteredBuses.forEach((bus) => bounds.extend([bus.longitude, bus.latitude]));
    mapRef.current.fitBounds(bounds, { padding: 80, maxZoom: 15 });
  }

  function resetFilters() {
    setSelectedRoute("all");
    setSelectedStatus("all");
    setSearchText("");
    setSelectedBusId(null);
  }

  function toggleStatusFilter(status) {
    if (status === "all") {
      setSelectedStatus("all");
      return;
    }

    setSelectedStatus((currentStatus) => (
      currentStatus === status ? "all" : status
    ));
  }

  const activeStatusCriteria = statusCriteria(selectedStatus);

  return (
    <div className="app">
      <div ref={mapContainerRef} className="map" />

      {!isPanelOpen && (
        <button className="floating-button" onClick={() => setIsPanelOpen(true)}>
          Show controls
        </button>
      )}

      {isPanelOpen && (
        <aside className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Live Dashboard</p>
              <h1>Blacksburg Transit</h1>
              <p className="muted">Track live buses, filter routes, and inspect schedule status.</p>
            </div>
            <button className="icon-button" onClick={() => setIsPanelOpen(false)}>x</button>
          </div>

          <div className="legend">
            {Object.entries(STATUS_COLORS).slice(0, 3).map(([key, color]) => (
              <span key={key}>
                <i style={{ background: color }} />
                {STATUS_LABELS[key]}
              </span>
            ))}
            <span>
              <i style={{ background: "#f97316" }} />
              Live bunching
            </span>
            <span>
              <i style={{ background: "#ef4444" }} />
              Historical stop
            </span>
          </div>

          <div className="toolbar">
            <input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder="Search bus, route, stop"
            />
            <button className="primary" onClick={refreshBuses}>Refresh</button>
            <button className={isPaused ? "active" : ""} onClick={() => setIsPaused(!isPaused)}>
              {isPaused ? "Resume" : "Pause"}
            </button>
          </div>

          <button
            className={`bunching-toggle ${showBunching ? "active" : ""}`}
            onClick={() => setShowBunching(!showBunching)}
          >
            {showBunching ? "Hide" : "Show"} live bunching hotspots
            <span>{visibleHotspots.length}</span>
          </button>

          <button
            className={`bunching-toggle ${showHistoricalBunching ? "active" : ""}`}
            onClick={() => setShowHistoricalBunching(!showHistoricalBunching)}
          >
            {showHistoricalBunching ? "Hide" : "Show"} historical stop hotspots
            <span>{visibleHistoricalStopHotspots.length}</span>
          </button>

          {showHistoricalBunching && (
            <div className="criteria-card">
              <strong>Bus bunching criteria</strong>
              <p>
                Historical stop hotspots are counted when two different bus trips
                are calculated to arrive at the same stop within
                {" "}
                <b>{historicalCoverage?.gapThresholdSeconds || 120} seconds</b>.
                More close-arrival events make the red halo brighter and less translucent.
              </p>
              <p>
                Live bunching is counted separately when two active buses on the
                same route are within about <b>250 meters</b>.
              </p>
            </div>
          )}

          <div className="stats">
            {Object.entries(stats).map(([key, count]) => (
              <button
                key={key}
                className={selectedStatus === key ? "active" : ""}
                onClick={() => toggleStatusFilter(key)}
              >
                <strong>{count}</strong>
                <span>{STATUS_LABELS[key]}</span>
              </button>
            ))}
          </div>

          {activeStatusCriteria && (
            <div className="criteria-card status-criteria-card">
              <strong>{activeStatusCriteria.title}</strong>
              <p>{activeStatusCriteria.description}</p>
              <p>
                Formula:
                {" "}
                <b>{activeStatusCriteria.formula}</b>.
              </p>
            </div>
          )}

          <div className="section-row">
            <strong>Routes</strong>
            <button onClick={resetFilters}>Reset</button>
          </div>

          <div className="chips">
            <button className={selectedRoute === "all" ? "active" : ""} onClick={() => setSelectedRoute("all")}>
              All routes
            </button>
            {activeRoutes.map((routeShortName) => (
              <button
                key={routeShortName}
                className={selectedRoute === routeShortName ? "active" : ""}
                onClick={() => setSelectedRoute(routeShortName)}
              >
                <i style={{ background: routeColor(routeShortName) }} />
                {routeShortName}
              </button>
            ))}
          </div>

          <div className="section-row">
            <strong>Buses</strong>
            <button onClick={fitVisibleBuses}>Fit map</button>
          </div>

          <div className="bus-list">
            {filteredBuses.length === 0 && <p className="muted">No buses match your filters.</p>}
            {filteredBuses.map((bus) => (
              <button
                key={bus.id}
                className={`bus-card ${bus.id === selectedBusId ? "active" : ""}`}
                onClick={() => selectBus(bus.id, true)}
              >
                <span className="route-badge" style={{ background: routeColor(bus.routeShortName) }}>
                  {bus.routeShortName || "?"}
                </span>
                <span>
                  <strong>Bus {bus.id}</strong>
                  <small>{routeName(bus.routeShortName, bus.patternName)}</small>
                  <small>{bus.lastStopName || "Unknown stop"}</small>
                </span>
                <em className={statusClass(bus.status)}>{STATUS_LABELS[bus.status] || "Unknown"}</em>
              </button>
            ))}
          </div>

          <p className="status-line">
            {error || `Showing ${filteredBuses.length} of ${buses.length} buses.`}
            {` Live hotspots: ${visibleHotspots.length}. Historical stops: ${visibleHistoricalStopHotspots.length}.`}
            {lastRefreshed && ` Last refreshed at ${formatTime(lastRefreshed.toISOString())}.`}
            {historicalCoverage?.message && ` ${historicalCoverage.message}`}
            {historicalCoverage?.generatedAt && ` Historical cache covers ${historicalCoverage.availableServiceDays} of ${historicalCoverage.requestedDays} requested days.`}
          </p>
        </aside>
      )}

      {selectedBus && (
        <section className="details">
          <button className="icon-button" onClick={() => setSelectedBusId(null)}>x</button>
          <p className="eyebrow">Selected Bus</p>
          <h2>Bus {selectedBus.id} - {selectedBus.statusLabel}</h2>
          <dl>
            <dt>Route</dt>
            <dd>{selectedBus.routeShortName} - {routeName(selectedBus.routeShortName, selectedBus.patternName)}</dd>
            <dt>Last stop</dt>
            <dd>{selectedBus.lastStopName || "Unknown"}</dd>
            <dt>At stop</dt>
            <dd>{selectedBus.isBusAtStop ? "Yes" : "No"}</dd>
            <dt>Speed</dt>
            <dd>{selectedBus.speed} mph</dd>
            <dt>Capacity</dt>
            <dd>{selectedBus.capacityPercent}%</dd>
            <dt>Direction</dt>
            <dd>{selectedBus.direction} degrees</dd>
            <dt>Updated</dt>
            <dd>{formatTime(selectedBus.latestEvent)}</dd>
          </dl>
        </section>
      )}
    </div>
  );
}


export default App;
