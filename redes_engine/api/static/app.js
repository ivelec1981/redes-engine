// ═══════════════════════════════════════════════════════════════════════
// Redes Engine v3.0 — Web Console (state machine + workflow)
// ═══════════════════════════════════════════════════════════════════════

const API = "/api/v1";

// Estado global de la aplicación
const state = {
    networkId: null,
    activePhase: "captura",
    workflow: null,
    domains: [],
    map: null,
    editMode: false,
    pendingBusId: null,
};

// ═══════════════════════════════════════════════════════════════════════
// MAP INIT
// ═══════════════════════════════════════════════════════════════════════
function initMap() {
    state.map = new maplibregl.Map({
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
        center: [-78.5, -1.5],
        zoom: 6,
    });
    state.map.addControl(new maplibregl.NavigationControl());
    state.map.on("load", () => log("✓ Mapa listo"));
}

// ═══════════════════════════════════════════════════════════════════════
// LOG + MÉTRICAS
// ═══════════════════════════════════════════════════════════════════════
function log(msg) {
    const el = document.getElementById("log");
    const ts = new Date().toLocaleTimeString();
    el.textContent = `[${ts}] ${msg}\n` + el.textContent;
}

function setMetric(id, value, format = "raw") {
    const el = document.getElementById(id);
    if (!el) return;
    if (value === null || value === undefined) { el.textContent = "–"; return; }
    if (format === "fixed1") el.textContent = Number(value).toFixed(1);
    else if (format === "fixed2") el.textContent = Number(value).toFixed(2);
    else el.textContent = value;
}

function clearMetrics() {
    ["m-buses", "m-branches", "m-demand", "m-losses", "m-viol", "m-trafo"].forEach(id => {
        document.getElementById(id).textContent = "–";
    });
}

// ═══════════════════════════════════════════════════════════════════════
// HEALTH CHECK
// ═══════════════════════════════════════════════════════════════════════
async function checkHealth() {
    try {
        const r = await fetch(`${API}/health`);
        const data = await r.json();
        const opendss = data.opendss_available ? "✅ OpenDSS" : "⚠ Sin OpenDSS";
        document.getElementById("health-status").textContent =
            `v${data.version} · ${opendss} · ${data.networks_count} redes`;
    } catch (e) {
        document.getElementById("health-status").textContent = "API no disponible";
    }
}

// ═══════════════════════════════════════════════════════════════════════
// CRUD DE NETWORKS
// ═══════════════════════════════════════════════════════════════════════
async function refreshNetworks() {
    try {
        const r = await fetch(`${API}/networks`);
        const networks = await r.json();
        const sel = document.getElementById("network-select");
        sel.innerHTML = '<option value="">— sin proyecto —</option>';
        for (const n of networks) {
            const opt = document.createElement("option");
            opt.value = n.id;
            opt.textContent = `${n.name} (${n.n_buses} buses)`;
            sel.appendChild(opt);
        }
        if (state.networkId) sel.value = state.networkId;
    } catch (e) { log(`❌ ${e}`); }
}

async function loadDemoNetwork() {
    log("⚙ Cargando red demo Pastaza...");
    try {
        const r = await fetch(`${API}/demo/load`, { method: "POST" });
        const data = await r.json();
        state.networkId = data.id;
        log(`✓ Demo cargada: ${data.name}`);
        await refreshNetworks();
        document.getElementById("network-select").value = data.id;
        await onNetworkSelected();
    } catch (e) { log(`❌ ${e.message}`); }
}

async function deleteCurrent() {
    if (!state.networkId) return;
    if (!confirm("¿Eliminar el proyecto activo?")) return;
    await fetch(`${API}/networks/${state.networkId}`, { method: "DELETE" });
    state.networkId = null;
    state.workflow = null;
    state.domains = [];
    clearMapLayers();
    clearMetrics();
    document.getElementById("domains-list").innerHTML = '<span class="empty-msg">cargue una red…</span>';
    await refreshNetworks();
    await renderWorkflow();
}

async function onNetworkSelected() {
    const sel = document.getElementById("network-select");
    state.networkId = sel.value || null;

    if (!state.networkId) {
        clearMapLayers();
        clearMetrics();
        await renderWorkflow();
        return;
    }

    try {
        const r = await fetch(`${API}/networks/${state.networkId}`);
        const detail = await r.json();
        setMetric("m-buses", detail.n_buses);
        setMetric("m-branches", detail.n_branches);
        setMetric("m-demand", detail.total_demand_kw, "fixed1");

        await loadTopologyOnMap();
        await refreshDomains();
        await refreshWorkflow();
    } catch (e) { log(`❌ ${e}`); }
}

// ═══════════════════════════════════════════════════════════════════════
// WORKFLOW STATE MACHINE
// ═══════════════════════════════════════════════════════════════════════
async function refreshWorkflow() {
    if (!state.networkId) return;
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/workflow`);
        state.workflow = await r.json();
        // Si el active_phase del backend cambió porque progresamos, actualizar
        if (!state.activePhase || _phaseProgress(state.activePhase) === 100) {
            state.activePhase = state.workflow.active_phase;
        }
        await renderWorkflow();
    } catch (e) { log(`❌ workflow: ${e.message}`); }
}

function _phaseProgress(phaseId) {
    if (!state.workflow) return 0;
    const ph = state.workflow.phases.find(p => p.id === phaseId);
    return ph ? ph.progress_pct : 0;
}

async function renderWorkflow() {
    const phases = state.workflow ? state.workflow.phases : null;

    document.querySelectorAll(".phase").forEach(el => {
        const pid = el.dataset.phase;
        el.classList.remove("active", "locked", "completed");

        if (!phases) {
            // Sin red cargada
            el.classList.add(pid !== "captura" ? "locked" : "active");
            el.querySelector(".phase-fill").style.width = "0%";
            el.querySelector(".phase-pct").textContent = "0%";
            return;
        }

        const ph = phases.find(p => p.id === pid);
        if (!ph) return;

        el.querySelector(".phase-fill").style.width = `${ph.progress_pct}%`;
        el.querySelector(".phase-pct").textContent = `${Math.round(ph.progress_pct)}%`;

        if (!ph.is_unlocked) el.classList.add("locked");
        else if (ph.progress_pct >= 100) el.classList.add("completed");
        if (pid === state.activePhase) el.classList.add("active");
    });

    // Render del panel de tareas y acciones
    renderPhaseSteps();
    renderPhaseActions();
}

function renderPhaseSteps() {
    const target = document.getElementById("phase-steps");
    const titleEl = document.getElementById("phase-title");

    const phaseLabels = {
        captura: "① Captura — tareas",
        calculo: "② Cálculo — tareas",
        validar: "③ Validar — tareas",
        emitir:  "④ Emitir — tareas",
        operar:  "⑤ Operar — tareas",
    };
    titleEl.textContent = phaseLabels[state.activePhase] || "Tareas";

    if (!state.workflow) {
        target.innerHTML = '<span class="empty-msg">cargue una red…</span>';
        return;
    }
    const phase = state.workflow.phases.find(p => p.id === state.activePhase);
    if (!phase) return;

    const html = [];
    for (const s of phase.completed_steps)
        html.push(`<div class="step-item completed"><span class="step-icon">✅</span><span>${s}</span></div>`);
    for (const s of phase.pending_steps)
        html.push(`<div class="step-item pending"><span class="step-icon">⏳</span><span>${s}</span></div>`);

    target.innerHTML = html.join("") || '<span class="empty-msg">nada que hacer</span>';
}

function renderPhaseActions() {
    const target = document.getElementById("actions-pane");
    const titleEl = document.getElementById("actions-title");

    if (!state.networkId && state.activePhase !== "captura") {
        target.innerHTML = '<span class="empty-msg">cargue una red primero</span>';
        return;
    }

    const labels = {
        captura: "Acciones — Captura",
        calculo: "Acciones — Cálculo",
        validar: "Acciones — Validar",
        emitir:  "Acciones — Emitir",
        operar:  "Acciones — Operar",
    };
    titleEl.textContent = labels[state.activePhase];

    let html = "";

    if (state.activePhase === "captura") {
        html = `
            <button class="primary" onclick="loadDemoNetwork()">⚡ Cargar red demo</button>
            <button onclick="document.getElementById('upload-input').click()">📂 Cargar .rsproj</button>
            <label><input type="checkbox" id="edit-mode-cb" onchange="toggleEditMode()" ${state.editMode ? 'checked' : ''}>
                ✏ Modo edición (clic en bus → agregar asset)
            </label>
        `;
    }
    else if (state.activePhase === "calculo") {
        html = `
            <button class="primary" onclick="runSolve()">⚡ Resolver flujo de potencia</button>
            <button onclick="runHosting()">🏠 Análisis Host Capacity</button>
            <button onclick="runTimeseries()">⏱ Análisis temporal 24h</button>
        `;
    }
    else if (state.activePhase === "validar") {
        html = `
            <button class="primary" onclick="runSolve()">🛡 Re-evaluar ARCERNNR</button>
            <button onclick="showViolations()">📋 Ver violaciones</button>
            <button onclick="showRecommendations()">💡 Recomendaciones</button>
        `;
    }
    else if (state.activePhase === "emitir") {
        html = `
            <button class="primary" onclick="openReportModal()">📄 Generar reporte ejecutivo</button>
            <button onclick="downloadProject()">💾 Guardar .rsproj</button>
            <button onclick="exportGeoJSON()">🗺 Exportar GeoJSON resultados</button>
        `;
    }
    else if (state.activePhase === "operar") {
        html = `<span class="empty-msg">Integración SCADA — próximamente</span>`;
    }

    target.innerHTML = html;
}

function setActivePhase(phaseId) {
    if (!state.workflow) return;
    const phase = state.workflow.phases.find(p => p.id === phaseId);
    if (!phase || !phase.is_unlocked) {
        log(`⚠ Fase ${phaseId} aún no está desbloqueada`);
        return;
    }
    state.activePhase = phaseId;
    renderWorkflow();
}

// ═══════════════════════════════════════════════════════════════════════
// DOMINIOS
// ═══════════════════════════════════════════════════════════════════════
async function refreshDomains() {
    if (!state.networkId) return;
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/domains`);
        const data = await r.json();
        state.domains = data.domains;
        renderDomains();
    } catch (e) { log(`❌ domains: ${e.message}`); }
}

function renderDomains() {
    const target = document.getElementById("domains-list");
    if (!state.domains.length) {
        target.innerHTML = '<span class="empty-msg">cargue una red…</span>';
        return;
    }
    target.innerHTML = state.domains.map(d => {
        const cls = [
            "domain-chip",
            d.active ? "active" : "",
            !d.detected_in_network ? "empty" : "",
        ].filter(Boolean).join(" ");
        return `
            <div class="${cls}" onclick="toggleDomain('${d.id}', ${!d.active})">
                <span class="domain-chip-icon">${d.icon}</span>
                <span class="domain-chip-name">${d.name}</span>
                <span class="domain-chip-count">${d.n_elements}</span>
            </div>
        `;
    }).join("");
}

async function toggleDomain(domainId, newActive) {
    if (!state.networkId) return;
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/domains`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domain_ids: [domainId], active: newActive }),
        });
        const data = await r.json();
        state.domains = data.domains;
        renderDomains();
        log(`${newActive ? '✓ Activado' : '✗ Desactivado'}: dominio ${domainId}`);
    } catch (e) { log(`❌ ${e.message}`); }
}

// ═══════════════════════════════════════════════════════════════════════
// MAPA: TOPOLOGÍA + RESULTADOS
// ═══════════════════════════════════════════════════════════════════════
async function loadTopologyOnMap() {
    if (!state.networkId) return;
    const r = await fetch(`${API}/networks/${state.networkId}/results/geojson`);
    const data = await r.json();
    drawNetwork(data);
}

function drawNetwork(data) {
    clearMapLayers();
    const buses = projectFC(data.buses);
    const lines = projectFC(data.lines);
    const trafos = projectFC(data.transformers);

    state.map.addSource("lines", { type: "geojson", data: lines });
    state.map.addLayer({
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
                "#7f8c8d"
            ]
        }
    });

    state.map.addSource("buses", { type: "geojson", data: buses });
    state.map.addLayer({
        id: "buses-layer",
        type: "circle",
        source: "buses",
        paint: {
            "circle-radius": ["case", ["get", "is_mt"], 6, 5],
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

    state.map.addSource("trafos", { type: "geojson", data: trafos });
    state.map.addLayer({
        id: "trafos-layer",
        type: "circle",
        source: "trafos",
        paint: {
            "circle-radius": 8,
            "circle-color": [
                "match", ["get", "compliance"],
                "violation", "#c0392b",
                "warning", "#e67e22",
                "ok", "#46c46b",
                "#7f8c8d"
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff"
        }
    });

    state.map.on("click", "buses-layer", (e) => {
        if (onBusClickedForEdit(e)) return;
        const p = e.features[0].properties;
        new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`
            <strong>${p.id}</strong><br>
            ${p.voltage_kv_nom} kV (${p.is_mt ? 'MT' : 'BT'})<br>
            V: ${p.v_pu ?? '?'} pu (ΔV ${p.v_drop_pct ?? '?'}%)<br>
            <span class="badge-${p.compliance}">${p.compliance}</span>
        `).addTo(state.map);
    });
    state.map.on("click", "lines-layer", (e) => {
        const p = e.features[0].properties;
        new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`
            <strong>${p.id}</strong><br>
            ${p.length_m} m · cargabilidad ${p.loading_pct}%<br>
            P: ${p.p_kw ?? '?'} kW · I: ${p.current_a ?? '?'} A
        `).addTo(state.map);
    });

    fitToBuses(buses);
}

function clearMapLayers() {
    if (!state.map) return;
    for (const id of ["buses-layer", "lines-layer", "trafos-layer"]) {
        if (state.map.getLayer(id)) state.map.removeLayer(id);
    }
    for (const s of ["buses", "lines", "trafos"]) {
        if (state.map.getSource(s)) state.map.removeSource(s);
    }
}

// ═══════════════════════════════════════════════════════════════════════
// PROYECCIÓN UTM 17S → WGS84
// ═══════════════════════════════════════════════════════════════════════
function projectFC(fc) {
    if (!fc || !fc.features) return { type: "FeatureCollection", features: [] };
    return {
        type: "FeatureCollection",
        features: fc.features.map(feat => {
            const g = feat.geometry;
            let coords;
            if (g.type === "Point") coords = utmToLngLat(g.coordinates[0], g.coordinates[1]);
            else if (g.type === "LineString") coords = g.coordinates.map(c => utmToLngLat(c[0], c[1]));
            else return null;
            return { type: "Feature", properties: feat.properties, geometry: { type: g.type, coordinates: coords } };
        }).filter(Boolean)
    };
}

function utmToLngLat(easting, northing) {
    const k0 = 0.9996, a = 6378137, e2 = 0.00669437999014;
    const x = easting - 500000;
    const y = northing - 10000000;
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
        (D*D/2 - (5 + 3*T1 + 10*C1 - 4*C1*C1 - 9*(e2/(1-e2))) * D**4 / 24);
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
    state.map.fitBounds([
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)]
    ], { padding: 60, maxZoom: 18, duration: 800 });
}

// ═══════════════════════════════════════════════════════════════════════
// ANÁLISIS (FASE CÁLCULO)
// ═══════════════════════════════════════════════════════════════════════
async function runSolve() {
    if (!state.networkId) { alert("Cargue una red"); return; }
    log("⚡ Resolviendo flujo de potencia...");
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/solve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}"
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        log(`✓ ${data.iterations} iter · pérdidas ${data.losses_pct.toFixed(2)}% · ${data.n_violations} violaciones`);
        setMetric("m-losses", data.losses_pct, "fixed2");
        setMetric("m-viol", data.n_violations);
        await loadTopologyOnMap();
        await refreshWorkflow();
    } catch (e) { log(`❌ ${e.message}`); }
}

async function runHosting() {
    if (!state.networkId) return;
    log("🏠 Analizando Host Capacity...");
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/hosting`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ n_critical_hours: 30, max_kw: 200, tolerance_kw: 5 })
        });
        const data = await r.json();
        log(`✓ ${data.n_buses_analyzed} buses en ${data.elapsed_seconds}s · PV total: ${data.total_pv_capacity_kw} kW`);
        await refreshWorkflow();
    } catch (e) { log(`❌ ${e.message}`); }
}

async function runTimeseries() {
    if (!state.networkId) return;
    log("⏱ Análisis temporal 24h...");
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/timeseries`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hours: 24, scenario_name: "Demo 24h" })
        });
        const data = await r.json();
        log(`✓ pico ${data.peak_demand_kw} kW · trafo ${data.peak_transformer_loading_pct}%`);
        setMetric("m-trafo", data.peak_transformer_loading_pct, "fixed1");
        await refreshWorkflow();
    } catch (e) { log(`❌ ${e.message}`); }
}

// ═══════════════════════════════════════════════════════════════════════
// VALIDAR
// ═══════════════════════════════════════════════════════════════════════
function showViolations() {
    log("📋 Lista de violaciones — usa los popups en el mapa para detalles");
}
function showRecommendations() {
    log("💡 Las recomendaciones se incluyen en el reporte ejecutivo (fase 4)");
}

// ═══════════════════════════════════════════════════════════════════════
// EMITIR — REPORTES
// ═══════════════════════════════════════════════════════════════════════
function openReportModal() {
    if (!state.networkId) return;
    document.getElementById("report-modal").style.display = "flex";
}
function closeReportModal() {
    document.getElementById("report-modal").style.display = "none";
}

async function generateReport() {
    if (!state.networkId) return;
    const fmt = document.getElementById("report-format").value;
    const body = {
        format: fmt,
        company_name: document.getElementById("report-company").value || "Empresa Eléctrica",
        author_name: document.getElementById("report-author").value || "Ing. Responsable",
        author_id: document.getElementById("report-license").value || "",
        document_code: document.getElementById("report-code").value || "",
    };

    log(`📄 Generando reporte ${fmt.toUpperCase()}...`);
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/report`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(await r.text());
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `reporte_ejecutivo.${fmt}`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        log(`✓ Reporte ${fmt.toUpperCase()} descargado`);
        closeReportModal();
        await refreshWorkflow();
    } catch (e) { log(`❌ ${e.message}`); }
}

async function downloadProject() {
    if (!state.networkId) return;
    try {
        const r = await fetch(`${API}/projects/save/${state.networkId}`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: "{}"
        });
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "proyecto.rsproj";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        log("💾 Proyecto descargado");
        await refreshWorkflow();
    } catch (e) { log(`❌ ${e.message}`); }
}

async function uploadProject(event) {
    const file = event.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
        const r = await fetch(`${API}/projects/load`, { method: "POST", body: fd });
        const data = await r.json();
        log(`✓ Proyecto cargado: ${data.name}`);
        state.networkId = data.id;
        await refreshNetworks();
        document.getElementById("network-select").value = data.id;
        await onNetworkSelected();
    } catch (e) { log(`❌ ${e.message}`); }
    event.target.value = "";
}

async function exportGeoJSON() {
    if (!state.networkId) return;
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/results/geojson`);
        const data = await r.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = "resultados.geojson";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        log("🗺 GeoJSON exportado");
    } catch (e) { log(`❌ ${e.message}`); }
}

// ═══════════════════════════════════════════════════════════════════════
// MODO EDICIÓN — agregar assets
// ═══════════════════════════════════════════════════════════════════════
function toggleEditMode() {
    state.editMode = !state.editMode;
    const cb = document.getElementById("edit-mode-cb");
    if (cb) cb.checked = state.editMode;
    if (state.map && state.map.getCanvas()) {
        state.map.getCanvas().style.cursor = state.editMode ? "crosshair" : "";
    }
    log(state.editMode ? "✏ Modo edición ACTIVO" : "✏ Modo edición desactivado");
}

function onBusClickedForEdit(e) {
    if (!state.editMode) return false;
    state.pendingBusId = e.features[0].properties.id;
    document.getElementById("modal-bus-id").textContent = state.pendingBusId;
    document.getElementById("asset-modal").style.display = "flex";
    updateModalFields();
    return true;
}

async function updateModalFields() {
    const type = document.getElementById("modal-asset-type").value;
    const kwhI = document.getElementById("modal-kwh");
    const kwI = document.getElementById("modal-kw");
    const cat = document.getElementById("modal-catalog");

    const needsKwh = type.startsWith("bess") || type === "v2g";
    kwhI.style.opacity = needsKwh ? "1" : "0.4";
    if (!needsKwh) kwhI.value = "";
    if (needsKwh && !kwhI.value) kwhI.value = String(parseFloat(kwI.value || 5) * 2);

    const defaults = {
        load_residencial: 4, load_comercial: 30, alumbrado: 1.5,
        ev_ac_l2: 7.4, ev_dc_fast: 50, v2g: 11,
        pv_resid: 5, pv_comercial: 50, bess_btm: 5, bess_ci: 25
    };
    if (kwI.dataset.userTouched !== "1") kwI.value = defaults[type] || 5;

    cat.innerHTML = '<option value="">— Manual —</option>';
    let endpoint = null;
    if (type.startsWith("ev_") || type === "v2g") endpoint = "ev_chargers";
    else if (type.startsWith("bess")) endpoint = "bess";
    if (endpoint) {
        try {
            const items = await (await fetch(`/api/v1/catalogs/${endpoint}`)).json();
            for (const it of items) {
                const matches =
                    (type === "v2g" && it.category === "v2g_bidirectional") ||
                    (type === "ev_ac_l2" && it.category === "ev_ac_l2") ||
                    (type === "ev_dc_fast" && it.category === "ev_dc_fast") ||
                    (type === "bess_btm" && it.category === "bess_btm") ||
                    (type === "bess_ci" && it.category === "bess_ci");
                if (!matches) continue;
                const opt = document.createElement("option");
                opt.value = it.model;
                const c = it.capacity_kwh ? `, ${it.capacity_kwh} kWh` : "";
                opt.textContent = `${it.manufacturer} ${it.model} (${it.rated_kw} kW${c})`;
                cat.appendChild(opt);
            }
        } catch {}
    }
}

function closeAssetModal() {
    document.getElementById("asset-modal").style.display = "none";
    state.pendingBusId = null;
    delete document.getElementById("modal-kw").dataset.userTouched;
}

async function confirmAddAsset() {
    if (!state.pendingBusId || !state.networkId) return;
    const body = {
        bus_id: state.pendingBusId,
        asset_type: document.getElementById("modal-asset-type").value,
        rated_kw: parseFloat(document.getElementById("modal-kw").value),
    };
    const kwh = document.getElementById("modal-kwh").value;
    if (kwh) body.capacity_kwh = parseFloat(kwh);
    const cat = document.getElementById("modal-catalog").value;
    if (cat) body.catalog_model = cat;
    if (body.asset_type === "v2g" || body.asset_type.startsWith("bess")) {
        body.controllable = true;
        body.bidirectional = true;
    }
    try {
        const r = await fetch(`${API}/networks/${state.networkId}/assets`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        log(`✓ Asset ${data.id} (${data.asset_type}, ${data.rated_kw} kW) añadido`);
        closeAssetModal();
        await onNetworkSelected();
    } catch (e) { log(`❌ ${e.message}`); }
}

// ═══════════════════════════════════════════════════════════════════════
// BOOTSTRAP
// ═══════════════════════════════════════════════════════════════════════
document.addEventListener("DOMContentLoaded", async () => {
    initMap();

    // Listener del select
    document.getElementById("network-select").addEventListener("change", onNetworkSelected);

    // Listener del input kW para no sobreescribir
    document.getElementById("modal-kw").addEventListener("input", e => {
        e.target.dataset.userTouched = "1";
    });

    // Listeners de las fases del workflow
    document.querySelectorAll(".phase").forEach(el => {
        el.addEventListener("click", () => setActivePhase(el.dataset.phase));
    });

    await checkHealth();
    await refreshNetworks();
    await renderWorkflow();
});
