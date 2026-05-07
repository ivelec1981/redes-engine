// =============================================================================
// Redes Engine — Web Console (frontend minimalista)
// =============================================================================

const API = "/api/v1";
let currentNetworkId = null;
let map = null;

// =============================================================================
// Inicialización del mapa
// =============================================================================
function initMap() {
    map = new maplibregl.Map({
        container: "map",
        style: {
            version: 8,
            sources: {
                "osm": {
                    type: "raster",
                    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                    tileSize: 256,
                    attribution: "© OpenStreetMap contributors"
                }
            },
            layers: [{ id: "osm", type: "raster", source: "osm" }]
        },
        center: [-78.5, -1.5],   // Ecuador
        zoom: 6,
    });
    map.addControl(new maplibregl.NavigationControl());
    map.on("load", () => { log("✓ Mapa listo"); });
}

// =============================================================================
// Logging y métricas
// =============================================================================
function log(msg) {
    const el = document.getElementById("log");
    const ts = new Date().toLocaleTimeString();
    el.textContent = `[${ts}] ${msg}\n` + el.textContent;
}

function setMetric(id, value, format = "raw") {
    const el = document.getElementById(id);
    if (el) {
        if (format === "fixed1") el.textContent = Number(value).toFixed(1);
        else if (format === "fixed2") el.textContent = Number(value).toFixed(2);
        else el.textContent = value;
    }
}

// =============================================================================
// Health check
// =============================================================================
async function checkHealth() {
    try {
        const res = await fetch(`${API}/health`);
        const data = await res.json();
        const status = document.getElementById("health-status");
        const opendss = data.opendss_available ? "✅ OpenDSS" : "⚠ Sin OpenDSS";
        status.textContent = `v${data.version} · ${opendss} · ${data.networks_count} redes`;
    } catch (e) {
        document.getElementById("health-status").textContent = "API no disponible";
    }
}

// =============================================================================
// CRUD de redes
// =============================================================================
async function refreshNetworks() {
    const select = document.getElementById("network-select");
    try {
        const res = await fetch(`${API}/networks`);
        const networks = await res.json();
        select.innerHTML = '<option value="">— seleccionar —</option>';
        for (const n of networks) {
            const opt = document.createElement("option");
            opt.value = n.id;
            opt.textContent = `${n.name} (${n.n_buses} buses)`;
            select.appendChild(opt);
        }
        if (currentNetworkId) {
            select.value = currentNetworkId;
        }
        log(`✓ ${networks.length} redes disponibles`);
    } catch (e) {
        log(`❌ Error listando redes: ${e}`);
    }
}

async function loadDemoNetwork() {
    log("⚙ Cargando red demo (urbanización Pastaza)...");
    try {
        // Pedimos al backend que la cargue
        const res = await fetch(`${API}/demo/load`, { method: "POST" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        currentNetworkId = data.id;
        log(`✓ Red demo cargada: ${data.name} (id=${data.id})`);
        await refreshNetworks();
        document.getElementById("network-select").value = data.id;
        await onNetworkSelected();
    } catch (e) {
        log(`❌ Error: ${e.message}`);
    }
}

async function deleteCurrent() {
    if (!currentNetworkId) return;
    if (!confirm("¿Eliminar la red actual?")) return;
    await fetch(`${API}/networks/${currentNetworkId}`, { method: "DELETE" });
    currentNetworkId = null;
    document.getElementById("net-info").innerHTML = "";
    clearMapLayers();
    await refreshNetworks();
}

async function onNetworkSelected() {
    const select = document.getElementById("network-select");
    currentNetworkId = select.value || null;
    if (!currentNetworkId) {
        clearMapLayers();
        document.getElementById("net-info").innerHTML = "";
        return;
    }
    try {
        const res = await fetch(`${API}/networks/${currentNetworkId}`);
        const detail = await res.json();
        document.getElementById("net-info").innerHTML = `
            <strong>${detail.name}</strong><br>
            ${detail.n_buses} buses (${detail.n_buses_mt} MT, ${detail.n_buses_bt} BT)<br>
            ${detail.n_branches} branches · ${detail.n_assets} assets<br>
            Demanda: ${detail.total_demand_kw.toFixed(2)} kW
        `;
        setMetric("m-buses", detail.n_buses);
        setMetric("m-branches", detail.n_branches);
        setMetric("m-demand", detail.total_demand_kw, "fixed1");

        await loadTopologyOnMap();
    } catch (e) {
        log(`❌ Error cargando red: ${e}`);
    }
}

// =============================================================================
// Topología en el mapa
// =============================================================================
async function loadTopologyOnMap() {
    if (!currentNetworkId) return;
    const res = await fetch(`${API}/networks/${currentNetworkId}/results/geojson`);
    const data = await res.json();
    drawNetwork(data);
}

function drawNetwork(data) {
    clearMapLayers();

    const buses = projectFC(data.buses);
    const lines = projectFC(data.lines);
    const trafos = projectFC(data.transformers);

    // Source y layer para líneas (debajo)
    map.addSource("lines", { type: "geojson", data: lines });
    map.addLayer({
        id: "lines-layer",
        type: "line",
        source: "lines",
        paint: {
            "line-width": [
                "case",
                [">", ["get", "loading_pct"], 100], 4,
                [">", ["get", "loading_pct"], 80], 3,
                [">", ["get", "loading_pct"], 50], 2,
                1.5
            ],
            "line-color": [
                "match", ["get", "compliance"],
                "violation", "#c0392b",
                "warning", "#e67e22",
                "ok", "#46c46b",
                "#bdc3c7"
            ]
        }
    });

    // Source y layer para buses
    map.addSource("buses", { type: "geojson", data: buses });
    map.addLayer({
        id: "buses-layer",
        type: "circle",
        source: "buses",
        paint: {
            "circle-radius": [
                "case",
                ["get", "is_mt"], 6, 5
            ],
            "circle-color": [
                "match", ["get", "compliance"],
                "violation", "#e74c3c",
                "warning", "#f39c12",
                "ok", "#46c46b",
                "#95a5a6"
            ],
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#1a1d23"
        }
    });

    // Source y layer para trafos
    map.addSource("trafos", { type: "geojson", data: trafos });
    map.addLayer({
        id: "trafos-layer",
        type: "symbol",
        source: "trafos",
        layout: {
            "icon-image": "marker_15",
            "text-field": "T",
            "text-size": 12,
            "text-allow-overlap": true,
            "text-ignore-placement": true,
        },
        paint: {
            "text-color": "#ffffff",
            "text-halo-color": [
                "match", ["get", "compliance"],
                "violation", "#c0392b",
                "warning", "#e67e22",
                "ok", "#46c46b",
                "#7f8c8d"
            ],
            "text-halo-width": 5
        }
    });

    // Popups (o diálogo edit-mode)
    map.on("click", "buses-layer", (e) => {
        // Si está en modo edición, abrir diálogo agregar asset
        if (onBusClickedForEdit(e)) return;
        const p = e.features[0].properties;
        new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`
            <strong>${p.id}</strong><br>
            ${p.voltage_kv_nom} kV (${p.is_mt ? 'MT' : 'BT'})<br>
            V: ${p.v_pu ?? '?'} pu (ΔV ${p.v_drop_pct ?? '?'}%)<br>
            <span class="badge-${p.compliance}">${p.compliance}</span>
        `).addTo(map);
    });
    map.on("click", "lines-layer", (e) => {
        const p = e.features[0].properties;
        new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`
            <strong>${p.id}</strong><br>
            ${p.length_m} m · cargabilidad ${p.loading_pct}%<br>
            P: ${p.p_kw ?? '?'} kW · I: ${p.current_a ?? '?'} A
        `).addTo(map);
    });

    // Ajustar bounds
    fitToBuses(buses);
}

function clearMapLayers() {
    for (const id of ["buses-layer", "lines-layer", "trafos-layer"]) {
        if (map && map.getLayer(id)) map.removeLayer(id);
    }
    for (const s of ["buses", "lines", "trafos"]) {
        if (map && map.getSource(s)) map.removeSource(s);
    }
}

// =============================================================================
// Proyección EPSG:32717 → WGS84 (aproximación lineal para Ecuador continental)
// =============================================================================
function projectFC(fc) {
    if (!fc || !fc.features) return { type: "FeatureCollection", features: [] };
    const out = { type: "FeatureCollection", features: [] };
    for (const feat of fc.features) {
        const g = feat.geometry;
        let newCoords;
        if (g.type === "Point") {
            newCoords = utmToLngLat(g.coordinates[0], g.coordinates[1]);
        } else if (g.type === "LineString") {
            newCoords = g.coordinates.map(c => utmToLngLat(c[0], c[1]));
        } else continue;
        out.features.push({
            type: "Feature",
            properties: feat.properties,
            geometry: { type: g.type, coordinates: newCoords }
        });
    }
    return out;
}

// Aproximación rápida UTM zone 17S → WGS84 (suficiente para visualización)
function utmToLngLat(easting, northing) {
    // Centro de UTM zone 17S: lon = -81° (meridiano central), origen 500000 m
    // Northing southern hemisphere: false_northing = 10000000
    const k0 = 0.9996;
    const a = 6378137;            // WGS84 semi-major
    const e2 = 0.00669437999014;
    const e = Math.sqrt(e2);

    const x = easting - 500000;
    const y = northing - 10000000;   // hemisferio sur

    const M = y / k0;
    const mu = M / (a * (1 - e2/4 - 3*e2*e2/64 - 5*e2*e2*e2/256));
    const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
    const phi1 = mu + (3*e1/2 - 27*e1*e1*e1/32) * Math.sin(2*mu)
                + (21*e1*e1/16 - 55*e1*e1*e1*e1/32) * Math.sin(4*mu);

    const N1 = a / Math.sqrt(1 - e2 * Math.sin(phi1) ** 2);
    const T1 = Math.tan(phi1) ** 2;
    const C1 = (e2 / (1 - e2)) * Math.cos(phi1) ** 2;
    const R1 = a * (1 - e2) / Math.pow(1 - e2 * Math.sin(phi1) ** 2, 1.5);
    const D = x / (N1 * k0);

    const phi = phi1 - (N1 * Math.tan(phi1) / R1) *
        (D*D/2
         - (5 + 3*T1 + 10*C1 - 4*C1*C1 - 9*(e2/(1-e2))) * D**4 / 24);
    const lambda0 = -81 * Math.PI / 180;
    const lambda = lambda0 + (D
         - (1 + 2*T1 + C1) * D**3 / 6
         + (5 - 2*C1 + 28*T1 - 3*C1*C1 + 8*(e2/(1-e2)) + 24*T1*T1) * D**5 / 120
        ) / Math.cos(phi1);

    return [lambda * 180 / Math.PI, phi * 180 / Math.PI];
}

function fitToBuses(buses) {
    if (!buses.features.length) return;
    const coords = buses.features.map(f => f.geometry.coordinates);
    const lons = coords.map(c => c[0]);
    const lats = coords.map(c => c[1]);
    map.fitBounds([
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)]
    ], { padding: 60, maxZoom: 18, duration: 800 });
}

// =============================================================================
// Análisis
// =============================================================================
async function runSolve() {
    if (!currentNetworkId) { alert("Selecciona una red"); return; }
    log("⚡ Resolviendo flujo de potencia...");
    try {
        const res = await fetch(`${API}/networks/${currentNetworkId}/solve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({})
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        log(`✓ ${data.iterations} iteraciones · pérdidas ${data.losses_pct.toFixed(2)}% · ${data.n_violations} violaciones`);
        setMetric("m-losses", data.losses_pct, "fixed2");
        setMetric("m-viol", data.n_violations);
        setMetric("m-trafo", "–");
        await loadTopologyOnMap();
    } catch (e) {
        log(`❌ Solve error: ${e.message}`);
    }
}

async function runHosting() {
    if (!currentNetworkId) { alert("Selecciona una red"); return; }
    log("🏠 Analizando Host Capacity...");
    try {
        const res = await fetch(`${API}/networks/${currentNetworkId}/hosting`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ n_critical_hours: 30, max_kw: 200, tolerance_kw: 5 })
        });
        const data = await res.json();
        log(`✓ ${data.n_buses_analyzed} buses analizados en ${data.elapsed_seconds}s`);
        log(`  Total PV: ${data.total_pv_capacity_kw} kW · Total carga: ${data.total_load_capacity_kw} kW`);
        const top = data.bus_results.sort((a,b) => b.pv_hosting_kw - a.pv_hosting_kw).slice(0,3);
        for (const b of top) {
            log(`  ${b.bus_id}: PV ${b.pv_hosting_kw} kW (${b.pv_limiting_factor}) · Carga ${b.load_hosting_kw} kW`);
        }
    } catch (e) {
        log(`❌ Hosting error: ${e.message}`);
    }
}

async function runTimeseries() {
    if (!currentNetworkId) { alert("Selecciona una red"); return; }
    log("⏱ Análisis 24h con perfiles realistas...");
    try {
        const res = await fetch(`${API}/networks/${currentNetworkId}/timeseries`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hours: 24, scenario_name: "Demo 24h" })
        });
        const data = await res.json();
        log(`✓ ${data.n_hours_simulated}h · pico ${data.peak_demand_kw} kW (h=${data.peak_demand_hour})`);
        log(`  Energía: ${data.total_energy_served_mwh} MWh · pérdidas ${data.losses_pct}%`);
        log(`  Trafo más cargado: ${data.peak_transformer_id} @ ${data.peak_transformer_loading_pct}%`);
        setMetric("m-trafo", data.peak_transformer_loading_pct, "fixed1");
    } catch (e) {
        log(`❌ Timeseries error: ${e.message}`);
    }
}

// =============================================================================
// Edit mode — añadir assets clickeando en el mapa
// =============================================================================
let editMode = false;
let pendingBusId = null;

function toggleEditMode() {
    editMode = document.getElementById("edit-mode").checked;
    if (editMode) {
        log("✏ Modo edición ACTIVO. Haz clic en un bus para agregar un asset.");
        if (map.getCanvas()) map.getCanvas().style.cursor = "crosshair";
    } else {
        log("✏ Modo edición desactivado.");
        if (map.getCanvas()) map.getCanvas().style.cursor = "";
    }
}

// Override del click handler de buses
function onBusClickedForEdit(e) {
    if (!editMode) return false;
    const bus_id = e.features[0].properties.id;
    pendingBusId = bus_id;
    document.getElementById("modal-bus-id").textContent = bus_id;
    document.getElementById("asset-modal").style.display = "flex";
    updateModalFields();
    return true;
}

// Modal helpers
async function updateModalFields() {
    const type = document.getElementById("modal-asset-type").value;
    const kwh_input = document.getElementById("modal-kwh");
    const kw_input = document.getElementById("modal-kw");
    const catalog_select = document.getElementById("modal-catalog");

    // Visibilidad de kWh
    const needs_kwh = type.startsWith("bess") || type === "v2g" || type === "pv_bess";
    kwh_input.style.opacity = needs_kwh ? "1" : "0.4";
    if (!needs_kwh) kwh_input.value = "";
    if (needs_kwh && !kwh_input.value) kwh_input.value = String(parseFloat(kw_input.value || 5) * 2);

    // Defaults sensatos por tipo
    const defaults = {
        "load_residencial": 4, "load_comercial": 30, "alumbrado": 1.5,
        "ev_ac_l2": 7.4, "ev_dc_fast": 50, "v2g": 11,
        "pv_resid": 5, "pv_comercial": 50,
        "bess_btm": 5, "bess_ci": 25
    };
    if (kw_input.dataset.userTouched !== "1") {
        kw_input.value = defaults[type] || 5;
    }

    // Cargar catálogo correspondiente
    catalog_select.innerHTML = '<option value="">— Manual / sin catálogo —</option>';
    let endpoint = null;
    if (type.startsWith("ev_") || type === "v2g") endpoint = "ev_chargers";
    else if (type.startsWith("bess")) endpoint = "bess";
    if (endpoint) {
        try {
            const res = await fetch(`/api/v1/catalogs/${endpoint}`);
            const items = await res.json();
            for (const it of items) {
                const matches = (
                    (type === "v2g" && it.category === "v2g_bidirectional") ||
                    (type === "ev_ac_l2" && it.category === "ev_ac_l2") ||
                    (type === "ev_dc_fast" && it.category === "ev_dc_fast") ||
                    (type === "ev_dc_ultra" && it.category === "ev_dc_ultra") ||
                    (type === "bess_btm" && it.category === "bess_btm") ||
                    (type === "bess_ci" && it.category === "bess_ci")
                );
                if (!matches) continue;
                const opt = document.createElement("option");
                opt.value = it.model;
                const cap = it.capacity_kwh ? `, ${it.capacity_kwh} kWh` : "";
                opt.textContent = `${it.manufacturer} ${it.model} (${it.rated_kw} kW${cap})`;
                catalog_select.appendChild(opt);
            }
        } catch (e) { /* silent */ }
    }
}

function closeAssetModal() {
    document.getElementById("asset-modal").style.display = "none";
    pendingBusId = null;
    const kw = document.getElementById("modal-kw");
    delete kw.dataset.userTouched;
}

async function confirmAddAsset() {
    if (!pendingBusId || !currentNetworkId) return;
    const body = {
        bus_id: pendingBusId,
        asset_type: document.getElementById("modal-asset-type").value,
        rated_kw: parseFloat(document.getElementById("modal-kw").value),
    };
    const kwh_val = document.getElementById("modal-kwh").value;
    if (kwh_val) body.capacity_kwh = parseFloat(kwh_val);

    const cat = document.getElementById("modal-catalog").value;
    if (cat) body.catalog_model = cat;

    if (body.asset_type === "v2g" || body.asset_type.startsWith("bess")) {
        body.controllable = true;
        body.bidirectional = true;
    }

    try {
        const res = await fetch(`${API}/networks/${currentNetworkId}/assets`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        log(`✓ Asset ${data.id} (${data.asset_type}, ${data.rated_kw} kW) añadido a ${data.bus_id}`);
        closeAssetModal();
        // Refrescar detalle de la red
        await onNetworkSelected();
    } catch (e) {
        log(`❌ Error añadiendo asset: ${e.message}`);
    }
}

// =============================================================================
// Persistencia .rsproj
// =============================================================================
async function downloadProject() {
    if (!currentNetworkId) { alert("Selecciona una red"); return; }
    try {
        const res = await fetch(`${API}/projects/save/${currentNetworkId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
        });
        if (!res.ok) throw new Error(await res.text());
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "proyecto.rsproj";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        log("💾 Proyecto descargado.");
    } catch (e) {
        log(`❌ Error guardando: ${e.message}`);
    }
}

async function uploadProject(event) {
    const file = event.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
        const res = await fetch(`${API}/projects/load`, {
            method: "POST", body: fd,
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        log(`✓ Proyecto cargado: ${data.name} (id=${data.id})`);
        currentNetworkId = data.id;
        await refreshNetworks();
        document.getElementById("network-select").value = data.id;
        await onNetworkSelected();
    } catch (e) {
        log(`❌ Error cargando: ${e.message}`);
    }
    event.target.value = "";
}

// =============================================================================
// Bootstrap
// =============================================================================
document.addEventListener("DOMContentLoaded", async () => {
    initMap();
    document.getElementById("network-select").addEventListener("change", onNetworkSelected);
    document.getElementById("modal-kw").addEventListener("input", e => {
        e.target.dataset.userTouched = "1";
    });
    await checkHealth();
    await refreshNetworks();
});
