/**
 * Westminster Bin Sensor Analysis - Frontend Application v2
 * Handles multiple maps, API calls, and analysis execution
 */

// ============================================
// Configuration
// ============================================
const CONFIG = {
    apiBase: '',  // Same origin
    mapCenter: [51.51, -0.14],
    mapZoom: 13,
    categoryColors: [
        '#1a9850', '#91cf60', '#d9ef8b', '#fee08b',
        '#fdae61', '#f46d43', '#d73027', '#a50026'
    ],
    categoryNames: [
        'Very Low (Residential)', 'Low', 'Low-Medium', 'Medium',
        'Medium-High', 'High', 'Very High', 'Peak (Commercial)'
    ],
    tubeColor: '#dc2626',
    busColor: '#ea580c',
    premisesColor: '#9333ea',
    sensorColor: '#818cf8',
    binColor: '#10b981',
    selectedBinColor: '#f59e0b',
    // Minimum footfall score to display (filters out low-activity areas)
    minFootfallThreshold: 0,
    // Whether to show only street-adjacent cells
    streetsOnlyMode: false,
    // Current ward filter (can be 'all' or array of ward names)
    wardFilter: 'all',
    selectedWards: [],
    // Color palette for multi-ward selection
    wardColors: [
        '#6366f1', '#ec4899', '#14b8a6', '#f59e0b', '#8b5cf6',
        '#ef4444', '#22c55e', '#3b82f6', '#f97316', '#06b6d4'
    ],
    // Sensor distribution weights (must sum to 1)
    sensorWeights: {
        high: 0.3,    // Categories 5-7
        medium: 0.4,  // Categories 2-4
        low: 0.3      // Categories 0-1
    }
};

// ============================================
// Geocoding Cache (for hover info)
// ============================================
const geocodeCache = new Map();
let geocodePending = new Set();
let lastGeocodeTime = 0;
const GEOCODE_RATE_LIMIT = 1100; // ms between requests (Nominatim: 1 request/second)

// ============================================
// State
// ============================================
let maps = {};
let layers = {
    tubes: { points: null, grid: null },
    buses: { points: null, grid: null },
    premises: { points: null, grid: null },
    combined: { grid: null, bins: null },
    sensors: { all: null, selected: null }
};

// Selected bins for manual selection
let selectedBinIds = new Set();
let uploadedBins = null;
let analysisData = {
    tubes: null,
    buses: null,
    premises: null,
    grid: null,
    gridTube: null,
    gridBus: null,
    gridPremises: null,
    bins: null,
    selectedBins: null
};
let isRunning = false;

// ============================================
// Initialize
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Init] DOM loaded, initializing app...');
    
    // Set up run button handler FIRST
    const runBtn = document.getElementById('run-button');
    if (runBtn) {
        console.log('[Init] Setting up run button');
        // Remove any existing onclick and add proper handler
        runBtn.removeAttribute('onclick');
        runBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Button] Run button clicked!');
            await runAnalysis();
        });
    } else {
        console.error('[Init] Run button not found!');
    }
    
    // Initialize maps
    initMaps();
    
    // Load data (don't await - let it run in background)
    loadInitialData();
    
    // Set up scroll animations
    initScrollAnimations();
    
    // Check if there's existing data (one-time check, not polling)
    checkAnalysisStatus();
});

// ============================================
// Map Initialization
// ============================================
function initMaps() {
    const mapConfigs = [
        { id: 'map-tubes', name: 'tubes' },
        { id: 'map-buses', name: 'buses' },
        { id: 'map-premises', name: 'premises' },
        { id: 'map-combined', name: 'combined' },
        { id: 'map-sensors', name: 'sensors' }
    ];
    
    mapConfigs.forEach(config => {
        const el = document.getElementById(config.id);
        if (el) {
            maps[config.name] = L.map(config.id, {
                center: CONFIG.mapCenter,
                zoom: CONFIG.mapZoom,
                zoomControl: true,
                attributionControl: false
            });
            
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 19
            }).addTo(maps[config.name]);
        }
    });
}

// ============================================
// Data Loading
// ============================================
async function loadInitialData() {
    // Load data sources (available before analysis)
    try {
        await Promise.all([
            loadTubeData(),
            loadBusData(),
            loadPremisesData()
        ]);
    } catch (e) {
        console.log('Initial data loading:', e);
    }
    
    // Try to load grid data if analysis was run before
    loadGridData();
    loadSensorData();
}

async function loadTubeData() {
    try {
        const res = await fetch(`${CONFIG.apiBase}/api/tubes`);
        if (res.ok) {
            analysisData.tubes = await res.json();
            displayTubePoints();
            updateStat('tubes-count', analysisData.tubes.features.length);
        }
    } catch (e) {
        console.log('Loading tube data with samples');
        analysisData.tubes = generateSampleTubes();
        displayTubePoints();
    }
}

async function loadBusData() {
    try {
        const res = await fetch(`${CONFIG.apiBase}/api/buses`);
        if (res.ok) {
            analysisData.buses = await res.json();
            displayBusPoints();
            updateStat('buses-count', analysisData.buses.features.length);
        }
    } catch (e) {
        console.log('Loading bus data with samples');
        analysisData.buses = generateSampleBuses();
        displayBusPoints();
    }
}

async function loadPremisesData() {
    try {
        const res = await fetch(`${CONFIG.apiBase}/api/premises`);
        if (res.ok) {
            analysisData.premises = await res.json();
            displayPremisesPoints();
            updateStat('premises-count', analysisData.premises.features.length);
        }
    } catch (e) {
        console.log('Loading premises data with samples');
        analysisData.premises = generateSamplePremises();
        displayPremisesPoints();
    }
}

async function loadGridData() {
    try {
        // Load different grid views
        const [gridRes, tubeRes, busRes, premisesRes] = await Promise.all([
            fetch(`${CONFIG.apiBase}/api/grid`),
            fetch(`${CONFIG.apiBase}/api/grid/tube`),
            fetch(`${CONFIG.apiBase}/api/grid/bus`),
            fetch(`${CONFIG.apiBase}/api/grid/premises`)
        ]);
        
        if (gridRes.ok) {
            analysisData.grid = await gridRes.json();
            displayCombinedGrid();
        }
        if (tubeRes.ok) {
            analysisData.gridTube = await tubeRes.json();
        }
        if (busRes.ok) {
            analysisData.gridBus = await busRes.json();
        }
        if (premisesRes.ok) {
            analysisData.gridPremises = await premisesRes.json();
        }
    } catch (e) {
        console.log('Grid data not yet available');
    }
}

async function loadSensorData() {
    try {
        const [binsRes, selectedRes] = await Promise.all([
            fetch(`${CONFIG.apiBase}/api/bins`),
            fetch(`${CONFIG.apiBase}/api/selected-bins`)
        ]);
        
        if (binsRes.ok) {
            analysisData.bins = await binsRes.json();
        }
        if (selectedRes.ok) {
            analysisData.selectedBins = await selectedRes.json();
            displaySensorMap();
            updateSensorDistribution();
        }
    } catch (e) {
        console.log('Sensor data not yet available');
    }
}

// ============================================
// Display Functions
// ============================================
function displayTubePoints() {
    if (!maps.tubes || !analysisData.tubes) return;
    
    if (layers.tubes.points) {
        maps.tubes.removeLayer(layers.tubes.points);
    }
    
    layers.tubes.points = L.geoJSON(analysisData.tubes, {
        pointToLayer: (feature, latlng) => {
            const usage = feature.properties.annual_usage || 20;
            const radius = Math.max(6, Math.min(18, usage / 5));
            
            return L.circleMarker(latlng, {
                radius: radius,
                fillColor: CONFIG.tubeColor,
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8
            });
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            layer.bindPopup(`
                <div style="min-width: 150px;">
                    <strong style="font-size: 14px;">${p.name}</strong>
                    <div style="margin-top: 8px; font-size: 12px; color: #9ca3af;">
                        <div>Annual usage: <span style="color: #f87171; font-weight: 600;">${p.annual_usage}M</span></div>
                    </div>
                </div>
            `);
        }
    }).addTo(maps.tubes);
}

function displayBusPoints() {
    if (!maps.buses || !analysisData.buses) return;
    
    if (layers.buses.points) {
        maps.buses.removeLayer(layers.buses.points);
    }
    
    layers.buses.points = L.geoJSON(analysisData.buses, {
        pointToLayer: (feature, latlng) => {
            const freq = feature.properties.frequency || 10;
            const radius = Math.max(3, Math.min(8, freq / 8));
            
            return L.circleMarker(latlng, {
                radius: radius,
                fillColor: CONFIG.busColor,
                color: CONFIG.busColor,
                weight: 1,
                opacity: 0.8,
                fillOpacity: 0.6
            });
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            layer.bindPopup(`
                <div>
                    <strong style="font-size: 13px;">Bus Stop ${p.stop_id}</strong>
                    <div style="margin-top: 6px; font-size: 12px; color: #9ca3af;">
                        Frequency: <span style="color: #fb923c; font-weight: 600;">${p.frequency} buses/hr</span>
                    </div>
                </div>
            `);
        }
    }).addTo(maps.buses);
}

function displayPremisesPoints() {
    if (!maps.premises || !analysisData.premises) return;
    
    if (layers.premises.points) {
        maps.premises.removeLayer(layers.premises.points);
    }
    
    layers.premises.points = L.geoJSON(analysisData.premises, {
        pointToLayer: (feature, latlng) => {
            const cap = feature.properties.capacity || 50;
            const radius = Math.max(3, Math.min(8, cap / 40));
            
            return L.circleMarker(latlng, {
                radius: radius,
                fillColor: CONFIG.premisesColor,
                color: CONFIG.premisesColor,
                weight: 1,
                opacity: 0.8,
                fillOpacity: 0.5
            });
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            layer.bindPopup(`
                <div>
                    <strong style="font-size: 13px;">${p.type}</strong>
                    <div style="margin-top: 6px; font-size: 12px; color: #9ca3af;">
                        <div>Area: ${p.area}</div>
                        <div>Capacity: <span style="color: #c084fc; font-weight: 600;">${p.capacity}</span></div>
                    </div>
                </div>
            `);
        }
    }).addTo(maps.premises);
}

function displayGridOnMap(map, gridData, scoreType, color) {
    if (!map || !gridData) return null;
    
    // Find max score for normalization
    let maxScore = 0;
    gridData.features.forEach(f => {
        const score = f.properties.highlight_score || f.properties.footfall_score || 0;
        if (score > maxScore) maxScore = score;
    });
    
    return L.geoJSON(gridData, {
        style: feature => {
            const score = feature.properties.highlight_score || feature.properties.footfall_score || 0;
            const normalized = maxScore > 0 ? score / maxScore : 0;
            
            return {
                fillColor: color,
                fillOpacity: Math.min(0.8, normalized * 0.9 + 0.05),
                color: color,
                weight: 0.5,
                opacity: 0.3
            };
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            layer.bindPopup(`
                <div>
                    <strong style="font-size: 13px;">Cell ${p.cell_id}</strong>
                    <div style="margin-top: 8px; font-size: 12px; color: #9ca3af;">
                        <div>${scoreType} Score: <span style="color: ${color}; font-weight: 600;">${p.highlight_score?.toFixed(2) || p.footfall_score?.toFixed(3)}</span></div>
                    </div>
                </div>
            `);
            
            layer.on('mouseover', function() {
                this.setStyle({ fillOpacity: 0.9, weight: 2 });
            });
            layer.on('mouseout', function() {
                const score = p.highlight_score || p.footfall_score || 0;
                const normalized = maxScore > 0 ? score / maxScore : 0;
                this.setStyle({ fillOpacity: Math.min(0.8, normalized * 0.9 + 0.05), weight: 0.5 });
            });
        }
    }).addTo(map);
}

function displayCombinedGrid() {
    if (!maps.combined || !analysisData.grid) return;
    
    if (layers.combined.grid) {
        maps.combined.removeLayer(layers.combined.grid);
    }
    
    // Filter by threshold and ward(s)
    let filteredFeatures = analysisData.grid.features;
    
    // Apply threshold filter
    if (CONFIG.minFootfallThreshold > 0) {
        filteredFeatures = filteredFeatures.filter(f => f.properties.footfall_score >= CONFIG.minFootfallThreshold);
    }
    
    // Apply ward filter (single or multi)
    if (CONFIG.selectedWards.length > 0) {
        filteredFeatures = filteredFeatures.filter(f => CONFIG.selectedWards.includes(f.properties.ward));
    } else if (CONFIG.wardFilter !== 'all') {
        filteredFeatures = filteredFeatures.filter(f => f.properties.ward === CONFIG.wardFilter);
    }
    
    const filteredGrid = {
        type: "FeatureCollection",
        features: filteredFeatures
    };
    
    const wardCount = CONFIG.selectedWards.length || (CONFIG.wardFilter === 'all' ? 'all' : 1);
    console.log(`[Grid] Displaying ${filteredFeatures.length} cells (threshold: ${CONFIG.minFootfallThreshold}, wards: ${wardCount})`);
    
    // Update visible cells count
    const countEl = document.getElementById('visible-cells-count');
    if (countEl) {
        countEl.textContent = `${filteredFeatures.length.toLocaleString()} of ${analysisData.grid.features.length.toLocaleString()}`;
    }
    
    // Update threshold info display
    updateThresholdInfo();
    
    // Create ward-to-color mapping for multi-ward mode
    const wardColorMap = {};
    CONFIG.selectedWards.forEach((ward, i) => {
        wardColorMap[ward] = CONFIG.wardColors[i % CONFIG.wardColors.length];
    });
    
    layers.combined.grid = L.geoJSON(filteredGrid, {
        style: feature => {
            const cat = feature.properties.footfall_category || 0;
            const score = feature.properties.footfall_score || 0;
            const ward = feature.properties.ward;
            
            // Use ward color if in multi-ward mode, otherwise category color
            let fillColor;
            if (CONFIG.selectedWards.length > 0 && wardColorMap[ward]) {
                fillColor = wardColorMap[ward];
            } else {
                fillColor = CONFIG.categoryColors[cat];
            }
            
            // More transparent for better road visibility
            const baseOpacity = 0.25 + (score * 0.35);
            return {
                fillColor: fillColor,
                fillOpacity: Math.min(0.6, baseOpacity),
                color: fillColor,
                weight: 0.3,
                opacity: 0.5
            };
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            const coords = feature.geometry.coordinates[0];
            // Get center point of the polygon
            const centerLat = (coords[0][1] + coords[2][1]) / 2;
            const centerLon = (coords[0][0] + coords[2][0]) / 2;
            
            // Create initial popup content (will be enriched on hover)
            const createPopupContent = (locationInfo = null) => {
                // Use ward/road from grid data if available, fallback to geocoded
                const wardName = p.ward || (locationInfo?.ward) || null;
                const roadName = p.road_name || (locationInfo?.road) || null;
                const locality = locationInfo?.locality || null;
                
                const locationHtml = (wardName || roadName) ? `
                    <div style="margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid #374151;">
                        ${roadName ? `<div style="font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 4px;">${roadName}</div>` : ''}
                        ${locality ? `<div style="color: #9ca3af; font-size: 12px;">${locality}</div>` : ''}
                        ${wardName ? `<div style="color: #818cf8; font-size: 11px; margin-top: 4px;">Ward: ${wardName}</div>` : ''}
                    </div>
                ` : `
                    <div style="margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid #374151;">
                        <div style="color: #6b7280; font-size: 12px; font-style: italic;">Loading location info...</div>
                    </div>
                `;
                
                const peoplePerHour = p.estimated_people_per_hour || 0;
                const fillRate = p.estimated_bin_fill_rate || 0;
                const fillRateClass = fillRate >= 80 ? '#ef4444' : fillRate >= 40 ? '#eab308' : '#22c55e';
                
                return `
                    <div style="min-width: 220px; padding: 4px;">
                        ${locationHtml}
                        <div style="display: flex; align-items: center; margin-bottom: 10px;">
                            <span style="display: inline-block; width: 12px; height: 12px; border-radius: 2px; background: ${CONFIG.categoryColors[p.footfall_category]}; margin-right: 8px;"></span>
                            <strong style="font-size: 13px; color: ${CONFIG.categoryColors[p.footfall_category]};">
                                ${p.footfall_category_name}
                            </strong>
                        </div>
                        
                        <div style="background: #1f2937; border-radius: 6px; padding: 12px; margin-bottom: 10px;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                                <span style="font-size: 11px; color: #9ca3af;">👥 Est. People/Hour</span>
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 14px; color: #fff; font-weight: 600;">${Math.round(peoplePerHour).toLocaleString()}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-size: 11px; color: #9ca3af;">🗑️ Est. Daily Fill Rate</span>
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 14px; color: ${fillRateClass}; font-weight: 600;">${fillRate.toFixed(1)}%</span>
                            </div>
                        </div>
                        
                        <div style="font-size: 11px; color: #6b7280;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                                <span>Footfall Score:</span>
                                <span style="color: #9ca3af;">${(p.footfall_score * 100).toFixed(1)}%</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                                <span style="color: #dc2626;">Tube:</span>
                                <span>${p.tube_score?.toFixed(1) || 0}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                                <span style="color: #ea580c;">Bus:</span>
                                <span>${p.bus_score?.toFixed(1) || 0}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: #9333ea;">Premises:</span>
                                <span>${p.premises_score?.toFixed(1) || 0}</span>
                            </div>
                        </div>
                    </div>
                `;
            };
            
            // Bind initial popup
            layer.bindPopup(createPopupContent());
            
            // Hover effects
            layer.on('mouseover', async function(e) {
                this.setStyle({ fillOpacity: 0.8, weight: 2, color: '#fff' });
                
                // Fetch location info and update popup
                const locationInfo = await reverseGeocode(centerLat, centerLon);
                if (locationInfo && this._popup) {
                    this._popup.setContent(createPopupContent(locationInfo));
                }
            });
            
            layer.on('mouseout', function() {
                const score = p.footfall_score || 0;
                const baseOpacity = 0.25 + (score * 0.35);
                this.setStyle({ 
                    fillOpacity: Math.min(0.6, baseOpacity), 
                    weight: 0.3, 
                    color: CONFIG.categoryColors[p.footfall_category] 
                });
            });
            
            // On popup open, fetch fresh location data
            layer.on('popupopen', async function() {
                const locationInfo = await reverseGeocode(centerLat, centerLon);
                if (locationInfo && this._popup) {
                    this._popup.setContent(createPopupContent(locationInfo));
                }
            });
        }
    }).addTo(maps.combined);
}

// ============================================
// Reverse Geocoding (for hover location info)
// ============================================
async function reverseGeocode(lat, lon) {
    const cacheKey = `${lat.toFixed(5)},${lon.toFixed(5)}`;
    
    // Return from cache if available
    if (geocodeCache.has(cacheKey)) {
        return geocodeCache.get(cacheKey);
    }
    
    // Avoid duplicate requests
    if (geocodePending.has(cacheKey)) {
        // Wait for the pending request
        let attempts = 0;
        while (geocodePending.has(cacheKey) && attempts < 50) {
            await new Promise(resolve => setTimeout(resolve, 100));
            attempts++;
        }
        return geocodeCache.get(cacheKey);
    }
    
    geocodePending.add(cacheKey);
    
    try {
        // Rate limiting - wait if needed
        const now = Date.now();
        const timeSinceLastRequest = now - lastGeocodeTime;
        if (timeSinceLastRequest < GEOCODE_RATE_LIMIT) {
            await new Promise(resolve => setTimeout(resolve, GEOCODE_RATE_LIMIT - timeSinceLastRequest));
        }
        lastGeocodeTime = Date.now();
        
        // Use OpenStreetMap Nominatim for reverse geocoding
        const response = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&addressdetails=1&zoom=18`,
            {
                headers: {
                    'Accept': 'application/json',
                    'User-Agent': 'WestminsterBinAnalysis/1.0'
                }
            }
        );
        
        if (!response.ok) {
            throw new Error('Geocoding failed');
        }
        
        const data = await response.json();
        const address = data.address || {};
        
        const locationInfo = {
            road: address.road || address.pedestrian || address.footway || address.path || null,
            locality: address.suburb || address.neighbourhood || address.quarter || address.hamlet || null,
            ward: address.city_district || address.district || null,
            postcode: address.postcode || null,
            fullAddress: data.display_name || null
        };
        
        geocodeCache.set(cacheKey, locationInfo);
        geocodePending.delete(cacheKey);
        
        return locationInfo;
        
    } catch (error) {
        console.log('[Geocode] Error:', error.message);
        geocodePending.delete(cacheKey);
        
        // Return placeholder on error
        const fallback = { road: null, locality: 'Westminster', ward: 'City of Westminster' };
        geocodeCache.set(cacheKey, fallback);
        return fallback;
    }
}

function displaySensorMap() {
    if (!maps.sensors) return;
    
    // Display all bins as small dots
    if (analysisData.bins && layers.sensors.all) {
        maps.sensors.removeLayer(layers.sensors.all);
    }
    
    // Display selected bins
    if (analysisData.selectedBins) {
        if (layers.sensors.selected) {
            maps.sensors.removeLayer(layers.sensors.selected);
        }
        
        layers.sensors.selected = L.geoJSON(analysisData.selectedBins, {
            pointToLayer: (feature, latlng) => {
                const cat = feature.properties.footfall_category || 0;
                return L.circleMarker(latlng, {
                    radius: 5,
                    fillColor: CONFIG.categoryColors[cat],
                    color: '#fff',
                    weight: 1.5,
                    opacity: 1,
                    fillOpacity: 0.9
                });
            },
            onEachFeature: (feature, layer) => {
                const p = feature.properties;
                layer.bindPopup(`
                    <div>
                        <strong style="font-size: 13px;">Sensor #${p.selection_rank}</strong>
                        <div style="margin-top: 8px; font-size: 12px; color: #9ca3af;">
                            <div>Bin ID: ${p.bin_id}</div>
                            <div>Category: <span style="color: ${CONFIG.categoryColors[p.footfall_category]};">${CONFIG.categoryNames[p.footfall_category]}</span></div>
                            <div>Score: ${(p.footfall_score * 100).toFixed(1)}%</div>
                        </div>
                    </div>
                `);
            }
        }).addTo(maps.sensors);
    }
}

// ============================================
// Layer Toggle Functions
// ============================================
function toggleTubeLayer(layerType, button) {
    updateButtonState(button);
    
    if (layerType === 'points') {
        if (layers.tubes.grid) {
            maps.tubes.removeLayer(layers.tubes.grid);
            layers.tubes.grid = null;
        }
        displayTubePoints();
    } else if (layerType === 'influence') {
        if (layers.tubes.points) {
            maps.tubes.removeLayer(layers.tubes.points);
        }
        if (analysisData.gridTube) {
            if (layers.tubes.grid) maps.tubes.removeLayer(layers.tubes.grid);
            layers.tubes.grid = displayGridOnMap(maps.tubes, analysisData.gridTube, 'Tube', CONFIG.tubeColor);
        } else {
            showNoDataMessage(maps.tubes);
        }
    }
}

function toggleBusLayer(layerType, button) {
    updateButtonState(button);
    
    if (layerType === 'points') {
        if (layers.buses.grid) {
            maps.buses.removeLayer(layers.buses.grid);
            layers.buses.grid = null;
        }
        displayBusPoints();
    } else if (layerType === 'influence') {
        if (layers.buses.points) {
            maps.buses.removeLayer(layers.buses.points);
        }
        if (analysisData.gridBus) {
            if (layers.buses.grid) maps.buses.removeLayer(layers.buses.grid);
            layers.buses.grid = displayGridOnMap(maps.buses, analysisData.gridBus, 'Bus', CONFIG.busColor);
        } else {
            showNoDataMessage(maps.buses);
        }
    }
}

function togglePremisesLayer(layerType, button) {
    updateButtonState(button);
    
    if (layerType === 'points') {
        if (layers.premises.grid) {
            maps.premises.removeLayer(layers.premises.grid);
            layers.premises.grid = null;
        }
        displayPremisesPoints();
    } else if (layerType === 'influence') {
        if (layers.premises.points) {
            maps.premises.removeLayer(layers.premises.points);
        }
        if (analysisData.gridPremises) {
            if (layers.premises.grid) maps.premises.removeLayer(layers.premises.grid);
            layers.premises.grid = displayGridOnMap(maps.premises, analysisData.gridPremises, 'Premises', CONFIG.premisesColor);
        } else {
            showNoDataMessage(maps.premises);
        }
    }
}

function updateButtonState(activeButton) {
    const parent = activeButton.parentElement;
    parent.querySelectorAll('.map-control').forEach(btn => {
        btn.classList.remove('active');
    });
    activeButton.classList.add('active');
}

function showNoDataMessage(map) {
    const popup = L.popup()
        .setLatLng(CONFIG.mapCenter)
        .setContent('<div style="padding: 10px; text-align: center;"><strong>Run Analysis First</strong><br><span style="font-size: 12px; color: #9ca3af;">Click "Run Analysis" to generate the influence grid</span></div>')
        .openOn(map);
    
    setTimeout(() => map.closePopup(), 3000);
}

// ============================================
// Analysis Runner
// ============================================
async function runAnalysis() {
    if (isRunning) return;
    
    const button = document.getElementById('run-button');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    const progressPercent = document.getElementById('progress-percent');
    const steps = document.querySelectorAll('.runner-step');
    
    console.log('[Analysis] Starting...');
    
    isRunning = true;
    button.disabled = true;
    button.classList.add('running');
    button.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;">
            <circle cx="12" cy="12" r="10"/>
        </svg>
        <span>Starting Analysis...</span>
    `;
    
    // Reset progress UI
    progressFill.style.width = '0%';
    progressText.textContent = 'Initializing...';
    progressPercent.textContent = '0%';
    
    // Reset steps
    steps.forEach(s => {
        s.classList.remove('active', 'complete');
        s.querySelector('.step-icon').textContent = '○';
    });
    
    try {
        // Start the analysis
        console.log('[Analysis] Calling /api/run-analysis');
        const startRes = await fetch(`${CONFIG.apiBase}/api/run-analysis`);
        const startData = await startRes.json();
        console.log('[Analysis] Start response:', startData);
        
        if (startData.status === 'already_running') {
            console.log('[Analysis] Already running, will poll status');
        }
        
        // Poll for status
        let pollCount = 0;
        const maxPolls = 600; // 5 minutes max
        
        const pollStatus = async () => {
            pollCount++;
            
            if (pollCount > maxPolls) {
                console.error('[Analysis] Timeout after max polls');
                handleAnalysisError('Analysis timed out');
                return;
            }
            
            try {
                const res = await fetch(`${CONFIG.apiBase}/api/status`);
                if (!res.ok) {
                    console.error('[Analysis] Status request failed:', res.status);
                    setTimeout(pollStatus, 1000);
                    return;
                }
                
                const status = await res.json();
                console.log(`[Analysis] Poll #${pollCount}:`, status);
                
                // Update UI
                progressFill.style.width = `${status.progress}%`;
                progressText.textContent = status.message || 'Processing...';
                progressPercent.textContent = `${status.progress}%`;
                button.querySelector('span').textContent = `Running... ${status.progress}%`;
                
                // Update steps
                updateStepProgress(status.progress, steps);
                
                if (status.status === 'complete') {
                    console.log('[Analysis] Complete!');
                    handleAnalysisComplete(button);
                    
                } else if (status.status === 'error') {
                    console.error('[Analysis] Error:', status.message);
                    handleAnalysisError(status.message);
                    
                } else if (status.status === 'running' || status.status === 'idle') {
                    // Still running or just started, poll again
                    setTimeout(pollStatus, 500);
                } else {
                    // Unknown status
                    console.warn('[Analysis] Unknown status:', status.status);
                    setTimeout(pollStatus, 500);
                }
            } catch (e) {
                console.error('[Analysis] Poll error:', e);
                // Network error, retry
                setTimeout(pollStatus, 1000);
            }
        };
        
        // Start polling after a brief delay
        setTimeout(pollStatus, 300);
        
    } catch (e) {
        console.error('[Analysis] Start error:', e);
        handleAnalysisError('Failed to start analysis: ' + e.message);
    }
}

async function handleAnalysisComplete(button) {
    isRunning = false;
    button.disabled = false;
    button.classList.remove('running');
    button.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M5 13l4 4L19 7"/>
        </svg>
        <span>Analysis Complete!</span>
    `;
    
    // Reload all data
    console.log('[Analysis] Loading results...');
    await loadGridData();
    await loadSensorData();
    
    // Refresh displays
    displayCombinedGrid();
    displayBinsOnCombinedMap();
    displaySensorMap();
    updateSensorDistribution();
    populateWardFilter();
    
    // Load summary data
    console.log('[Analysis] Loading summaries...');
    await loadWardSummary();
    await loadSensorSummary();
    
    console.log('[Analysis] Results displayed');
    
    // Reset button after delay
    setTimeout(() => {
        button.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            <span>Run Again</span>
        `;
    }, 3000);
}

function handleAnalysisError(message) {
    const button = document.getElementById('run-button');
    const progressText = document.getElementById('progress-text');
    
    isRunning = false;
    button.disabled = false;
    button.classList.remove('running');
    button.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M15 9l-6 6M9 9l6 6"/>
        </svg>
        <span>Error - Try Again</span>
    `;
    progressText.textContent = message || 'An error occurred';
}

function updateStepProgress(progress, steps) {
    const thresholds = [30, 40, 60, 80, 95];
    
    steps.forEach((step, i) => {
        if (progress >= thresholds[i]) {
            step.classList.remove('active');
            step.classList.add('complete');
            step.querySelector('.step-icon').textContent = '✓';
        } else if (progress >= (thresholds[i] - 15)) {
            step.classList.add('active');
        }
    });
}

async function checkAnalysisStatus() {
    console.log('[Status] Checking initial analysis status...');
    try {
        const res = await fetch(`${CONFIG.apiBase}/api/status`);
        if (!res.ok) {
            console.log('[Status] Server returned error:', res.status);
            return;
        }
        const status = await res.json();
        console.log('[Status] Current status:', status);
        
        if (status.has_data) {
            document.getElementById('progress-text').textContent = 'Previous analysis data available - click Run to refresh';
            document.getElementById('progress-fill').style.width = '100%';
            document.getElementById('progress-percent').textContent = '100%';
            
            // Load existing data
            await loadGridData();
            await loadSensorData();
            displayCombinedGrid();
            displayBinsOnCombinedMap();
            displaySensorMap();
            updateSensorDistribution();
            populateWardFilter();
            
            // Load summaries
            await loadWardSummary();
            await loadSensorSummary();
        }
    } catch (e) {
        console.log('[Status] Backend not available:', e.message);
    }
}

// ============================================
// Update UI Elements
// ============================================
function updateStat(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value.toLocaleString();
}

function updateSensorDistribution() {
    const container = document.getElementById('sensor-dist-bars');
    if (!container || !analysisData.selectedBins) return;
    
    // Count sensors per category
    const counts = {};
    analysisData.selectedBins.features.forEach(f => {
        const cat = f.properties.footfall_category;
        counts[cat] = (counts[cat] || 0) + 1;
    });
    
    // Find max for scaling
    const maxCount = Math.max(...Object.values(counts), 1);
    
    // Generate bars
    container.innerHTML = '';
    for (let i = 0; i < 8; i++) {
        const count = counts[i] || 0;
        const width = (count / maxCount) * 100;
        
        container.innerHTML += `
            <div class="mini-bar">
                <span class="mini-bar-color" style="background: ${CONFIG.categoryColors[i]}"></span>
                <div class="mini-bar-track">
                    <div class="mini-bar-fill" style="width: ${width}%; background: ${CONFIG.categoryColors[i]}"></div>
                </div>
                <span class="mini-bar-value">${count}</span>
            </div>
        `;
    }
}

// ============================================
// Sample Data Generators
// ============================================
function generateSampleTubes() {
    const stations = [
        { name: "Oxford Circus", lat: 51.5152, lon: -0.1418, usage: 98 },
        { name: "Victoria", lat: 51.4965, lon: -0.1447, usage: 82 },
        { name: "Paddington", lat: 51.5154, lon: -0.1755, usage: 50 },
        { name: "Green Park", lat: 51.5067, lon: -0.1428, usage: 35 },
        { name: "Piccadilly Circus", lat: 51.5100, lon: -0.1347, usage: 40 },
        { name: "Leicester Square", lat: 51.5113, lon: -0.1281, usage: 35 },
        { name: "Westminster", lat: 51.5010, lon: -0.1254, usage: 25 },
        { name: "Baker Street", lat: 51.5226, lon: -0.1571, usage: 30 },
        { name: "Bond Street", lat: 51.5142, lon: -0.1494, usage: 28 },
        { name: "Marble Arch", lat: 51.5136, lon: -0.1586, usage: 18 }
    ];
    
    return {
        type: "FeatureCollection",
        features: stations.map(s => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [s.lon, s.lat] },
            properties: { name: s.name, annual_usage: s.usage, type: "tube_station" }
        }))
    };
}

function generateSampleBuses() {
    const features = [];
    const corridors = [
        { lat: 51.5154, lonRange: [-0.16, -0.13], freq: 60 },
        { lat: 51.5088, lonRange: [-0.17, -0.13], freq: 45 },
        { lat: 51.4985, lonRange: [-0.145, -0.125], freq: 40 }
    ];
    
    let id = 0;
    corridors.forEach(c => {
        for (let i = 0; i < 8; i++) {
            const lon = c.lonRange[0] + (c.lonRange[1] - c.lonRange[0]) * i / 7;
            features.push({
                type: "Feature",
                geometry: { type: "Point", coordinates: [lon, c.lat + (Math.random() - 0.5) * 0.002] },
                properties: { stop_id: `BS${String(id++).padStart(4, '0')}`, frequency: c.freq + Math.floor(Math.random() * 10 - 5) }
            });
        }
    });
    
    // Add random stops
    for (let i = 0; i < 100; i++) {
        features.push({
            type: "Feature",
            geometry: {
                type: "Point",
                coordinates: [-0.20 + Math.random() * 0.09, 51.485 + Math.random() * 0.05]
            },
            properties: { stop_id: `BS${String(id++).padStart(4, '0')}`, frequency: 5 + Math.floor(Math.random() * 20) }
        });
    }
    
    return { type: "FeatureCollection", features };
}

function generateSamplePremises() {
    const hotspots = [
        { name: "Soho", lat: 51.5136, lon: -0.1340, count: 80 },
        { name: "Covent Garden", lat: 51.5117, lon: -0.1240, count: 60 },
        { name: "Leicester Square", lat: 51.5105, lon: -0.1300, count: 50 },
        { name: "Mayfair", lat: 51.5095, lon: -0.1470, count: 40 },
        { name: "Fitzrovia", lat: 51.5190, lon: -0.1380, count: 30 }
    ];
    
    const types = ['Restaurant', 'Pub', 'Bar', 'Club', 'Cafe'];
    const features = [];
    let id = 0;
    
    hotspots.forEach(h => {
        for (let i = 0; i < h.count; i++) {
            const angle = Math.random() * Math.PI * 2;
            const r = Math.random() * 0.006;
            features.push({
                type: "Feature",
                geometry: {
                    type: "Point",
                    coordinates: [h.lon + r * Math.sin(angle), h.lat + r * Math.cos(angle)]
                },
                properties: {
                    premises_id: `LP${String(id++).padStart(5, '0')}`,
                    area: h.name,
                    type: types[Math.floor(Math.random() * types.length)],
                    capacity: 30 + Math.floor(Math.random() * 150)
                }
            });
        }
    });
    
    return { type: "FeatureCollection", features };
}

// ============================================
// Scroll Animations
// ============================================
function initScrollAnimations() {
    // Smooth scroll
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });
    
    // Animate distribution bars on scroll
    const distBars = document.querySelectorAll('.dist-fill');
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.height = entry.target.style.getPropertyValue('--width');
            }
        });
    }, { threshold: 0.2 });
    
    distBars.forEach(bar => {
        bar.style.height = '0';
        observer.observe(bar);
    });
    
    // Nav background on scroll
    const nav = document.querySelector('.nav');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            nav.style.background = 'rgba(8, 9, 12, 0.95)';
            nav.style.boxShadow = '0 4px 30px rgba(0,0,0,0.3)';
        } else {
            nav.style.background = 'rgba(8, 9, 12, 0.85)';
            nav.style.boxShadow = 'none';
        }
    });
}

// ============================================
// Ward Summary Functions
// ============================================
async function loadWardSummary() {
    try {
        const res = await fetch(`${CONFIG.apiBase}/api/summary/wards`);
        if (!res.ok) return;
        const data = await res.json();
        displayWardSummary(data);
    } catch (e) {
        console.log('[Summary] Ward summary not available:', e.message);
    }
}

async function loadSensorSummary() {
    try {
        const res = await fetch(`${CONFIG.apiBase}/api/summary/sensors`);
        if (!res.ok) return;
        const data = await res.json();
        displaySensorSummary(data);
    } catch (e) {
        console.log('[Summary] Sensor summary not available:', e.message);
    }
}

// Store ward data for sorting/filtering
let wardTableData = [];
let wardSortColumn = 'people';
let wardSortAsc = false;

function displayWardSummary(data) {
    if (!data || !data.totals) return;
    
    // Update totals
    document.getElementById('total-people').textContent = formatNumber(data.totals.total_people_per_hour);
    document.getElementById('avg-fill-rate').textContent = `${data.totals.avg_fill_rate.toFixed(1)}%`;
    document.getElementById('total-wards').textContent = data.totals.ward_count;
    
    // Store data for sorting/filtering
    wardTableData = data.wards || [];
    
    // Render table
    renderWardTable();
}

function renderWardTable(filter = '') {
    const tbody = document.getElementById('ward-table-body');
    if (!tbody) return;
    
    // Filter data
    let filteredData = wardTableData;
    if (filter) {
        const lowerFilter = filter.toLowerCase();
        filteredData = wardTableData.filter(w => w.ward.toLowerCase().includes(lowerFilter));
    }
    
    // Sort data
    filteredData = [...filteredData].sort((a, b) => {
        let aVal, bVal;
        switch (wardSortColumn) {
            case 'ward': aVal = a.ward; bVal = b.ward; break;
            case 'people': aVal = a.total_people_per_hour; bVal = b.total_people_per_hour; break;
            case 'fill': aVal = a.avg_fill_rate; bVal = b.avg_fill_rate; break;
            case 'zones': aVal = a.cell_count; bVal = b.cell_count; break;
            case 'sensors': aVal = a.sensor_count || 0; bVal = b.sensor_count || 0; break;
            default: aVal = a.total_people_per_hour; bVal = b.total_people_per_hour;
        }
        
        if (typeof aVal === 'string') {
            return wardSortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        }
        return wardSortAsc ? aVal - bVal : bVal - aVal;
    });
    
    if (filteredData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading-placeholder">No wards match your search</td></tr>';
        return;
    }
    
    tbody.innerHTML = filteredData.map(ward => `
        <tr data-ward="${ward.ward}">
            <td class="ward-name-cell">
                <span class="ward-name-link" onclick="filterByWard('${ward.ward}')">${ward.ward}</span>
            </td>
            <td class="numeric">${formatNumber(ward.total_people_per_hour)}</td>
            <td class="numeric">
                ${renderFillRateBar(ward.avg_fill_rate)}
                <span class="${getFillRateClass(ward.avg_fill_rate)}">${ward.avg_fill_rate.toFixed(1)}%</span>
            </td>
            <td class="numeric">${ward.cell_count}</td>
            <td class="numeric">${ward.sensor_count || 0}</td>
            <td>
                <button onclick="showRoadDetails('${ward.ward}')" class="view-roads-btn">View Roads</button>
            </td>
        </tr>
    `).join('');
}

function sortWardTable(column) {
    if (wardSortColumn === column) {
        wardSortAsc = !wardSortAsc;
    } else {
        wardSortColumn = column;
        wardSortAsc = false;
    }
    
    // Update sort indicators
    document.querySelectorAll('#ward-table th.sortable').forEach(th => {
        th.classList.remove('sorted-asc', 'sorted-desc');
    });
    
    const currentTh = document.querySelector(`#ward-table th[onclick*="${column}"]`);
    if (currentTh) {
        currentTh.classList.add(wardSortAsc ? 'sorted-asc' : 'sorted-desc');
    }
    
    const searchValue = document.getElementById('ward-search')?.value || '';
    renderWardTable(searchValue);
}

function filterWardTable(value) {
    renderWardTable(value);
}

function showRoadDetails(wardName) {
    const ward = wardTableData.find(w => w.ward === wardName);
    if (!ward || !ward.roads) return;
    
    const panel = document.getElementById('road-details-panel');
    const title = document.getElementById('road-panel-title');
    const tbody = document.getElementById('road-table-body');
    
    title.textContent = `Roads in ${wardName}`;
    
    tbody.innerHTML = ward.roads.map(road => `
        <tr>
            <td>${road.road}</td>
            <td class="numeric">${formatNumber(road.total_people_per_hour)}</td>
            <td class="numeric">
                ${renderFillRateBar(road.avg_fill_rate)}
                <span class="${getFillRateClass(road.avg_fill_rate)}">${road.avg_fill_rate.toFixed(1)}%</span>
            </td>
            <td class="numeric">${road.cell_count}</td>
        </tr>
    `).join('');
    
    panel.style.display = 'block';
}

function closeRoadPanel() {
    document.getElementById('road-details-panel').style.display = 'none';
}

// ============================================
// Sensor Weighting Functions
// ============================================
function updateSensorWeight(category, value) {
    value = parseInt(value);
    
    // Get current values of other sliders
    const categories = ['high', 'medium', 'low'];
    const otherCategories = categories.filter(c => c !== category);
    const otherTotal = otherCategories.reduce((sum, c) => sum + Math.round(CONFIG.sensorWeights[c] * 100), 0);
    
    // Constrain value so total doesn't exceed 100
    const maxAllowed = 100 - otherTotal;
    const minAllowed = 10; // Minimum 10% each
    
    if (value > maxAllowed) {
        value = maxAllowed;
        document.getElementById(`weight-${category}`).value = value;
    }
    if (value < minAllowed) {
        value = minAllowed;
        document.getElementById(`weight-${category}`).value = value;
    }
    
    CONFIG.sensorWeights[category] = value / 100;
    
    // Update display
    document.getElementById(`weight-${category}-value`).textContent = `${value}%`;
    
    // Calculate and show total
    updateWeightTotal();
    
    // Auto-adjust if total is less than 100
    autoBalanceWeights(category);
}

function autoBalanceWeights(changedCategory) {
    const total = Math.round((CONFIG.sensorWeights.high + CONFIG.sensorWeights.medium + CONFIG.sensorWeights.low) * 100);
    
    if (total < 100) {
        // Distribute remaining to other categories proportionally
        const remaining = 100 - total;
        const categories = ['high', 'medium', 'low'].filter(c => c !== changedCategory);
        const otherTotal = categories.reduce((sum, c) => sum + CONFIG.sensorWeights[c], 0);
        
        if (otherTotal > 0) {
            categories.forEach(cat => {
                const proportion = CONFIG.sensorWeights[cat] / otherTotal;
                const addition = Math.round(remaining * proportion);
                CONFIG.sensorWeights[cat] += addition / 100;
                
                const newVal = Math.round(CONFIG.sensorWeights[cat] * 100);
                document.getElementById(`weight-${cat}`).value = newVal;
                document.getElementById(`weight-${cat}-value`).textContent = `${newVal}%`;
            });
        }
    }
    
    updateWeightTotal();
}

function updateWeightTotal() {
    const total = Math.round((CONFIG.sensorWeights.high + CONFIG.sensorWeights.medium + CONFIG.sensorWeights.low) * 100);
    const totalEl = document.getElementById('weight-total');
    
    if (totalEl) {
        totalEl.textContent = `${total}%`;
        totalEl.style.color = total === 100 ? '#22c55e' : (total < 100 ? '#eab308' : '#ef4444');
    }
}

async function recalculateSensorDistribution() {
    const total = CONFIG.sensorWeights.high + CONFIG.sensorWeights.medium + CONFIG.sensorWeights.low;
    
    if (Math.abs(total - 1) > 0.01) {
        alert('Weights must sum to 100%. Please adjust the sliders.');
        return;
    }
    
    if (!analysisData.bins) {
        alert('Please run the analysis first to generate bin data.');
        return;
    }
    
    // Recalculate sensor selection based on new weights
    const bins = analysisData.bins.features;
    const targetTotal = 1000;
    
    // Clear existing selections
    selectedBinIds.clear();
    
    // Group bins by category
    const highBins = bins.filter(b => b.properties.footfall_category >= 6);
    const medBins = bins.filter(b => b.properties.footfall_category >= 3 && b.properties.footfall_category < 6);
    const lowBins = bins.filter(b => b.properties.footfall_category < 3);
    
    // Calculate targets
    const highTarget = Math.round(targetTotal * CONFIG.sensorWeights.high);
    const medTarget = Math.round(targetTotal * CONFIG.sensorWeights.medium);
    const lowTarget = Math.round(targetTotal * CONFIG.sensorWeights.low);
    
    // Select bins from each category (sorted by fill rate for variety)
    const selectFromCategory = (categoryBins, target) => {
        const sorted = [...categoryBins].sort((a, b) => 
            (b.properties.estimated_bin_fill_rate || 0) - (a.properties.estimated_bin_fill_rate || 0)
        );
        
        // Select evenly distributed
        const step = Math.max(1, Math.floor(sorted.length / target));
        let count = 0;
        for (let i = 0; count < target && i < sorted.length; i += step) {
            selectedBinIds.add(sorted[i].properties.bin_id);
            count++;
        }
        
        // Fill remaining if needed
        for (let i = 0; count < target && i < sorted.length; i++) {
            if (!selectedBinIds.has(sorted[i].properties.bin_id)) {
                selectedBinIds.add(sorted[i].properties.bin_id);
                count++;
            }
        }
    };
    
    selectFromCategory(highBins, highTarget);
    selectFromCategory(medBins, medTarget);
    selectFromCategory(lowBins, lowTarget);
    
    console.log(`[Sensors] Recalculated: High=${highTarget}, Med=${medTarget}, Low=${lowTarget}, Total=${selectedBinIds.size}`);
    
    // Update displays
    displayBinsOnCombinedMap();
    updateSelectionCount();
    
    // Show confirmation
    alert(`Sensor distribution recalculated!\n\nHigh footfall: ${highTarget} sensors\nMedium footfall: ${medTarget} sensors\nLow footfall: ${lowTarget} sensors\n\nTotal: ${selectedBinIds.size} sensors selected.\n\nYou can export these selections using the "Export Selection to CSV" button on the map.`);
}

// Store sensor ward data for sorting/filtering
let sensorWardTableData = [];
let sensorSortColumn = 'sensors';
let sensorSortAsc = false;

function displaySensorSummary(data) {
    if (!data || !data.totals) return;
    
    // Update totals
    document.getElementById('total-sensors').textContent = formatNumber(data.totals.total_sensors);
    document.getElementById('sensor-coverage-people').textContent = formatNumber(data.totals.total_people_per_hour);
    document.getElementById('sensor-avg-fill').textContent = `${data.totals.avg_fill_rate.toFixed(1)}%`;
    
    // Store data for sorting/filtering
    sensorWardTableData = data.wards || [];
    
    // Render table
    renderSensorWardTable();
}

function renderSensorWardTable(filter = '') {
    const tbody = document.getElementById('sensor-ward-table-body');
    if (!tbody) return;
    
    // Filter data
    let filteredData = sensorWardTableData;
    if (filter) {
        const lowerFilter = filter.toLowerCase();
        filteredData = sensorWardTableData.filter(w => w.ward.toLowerCase().includes(lowerFilter));
    }
    
    // Sort data
    filteredData = [...filteredData].sort((a, b) => {
        let aVal, bVal;
        switch (sensorSortColumn) {
            case 'ward': aVal = a.ward; bVal = b.ward; break;
            case 'sensors': aVal = a.sensor_count || 0; bVal = b.sensor_count || 0; break;
            case 'people': aVal = a.total_people_per_hour; bVal = b.total_people_per_hour; break;
            case 'fill': aVal = a.avg_fill_rate; bVal = b.avg_fill_rate; break;
            default: aVal = a.sensor_count || 0; bVal = b.sensor_count || 0;
        }
        
        if (typeof aVal === 'string') {
            return sensorSortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        }
        return sensorSortAsc ? aVal - bVal : bVal - aVal;
    });
    
    if (filteredData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="loading-placeholder">No wards match your search</td></tr>';
        return;
    }
    
    tbody.innerHTML = filteredData.map(ward => `
        <tr data-ward="${ward.ward}">
            <td class="ward-name-cell">
                <span class="ward-name-link" onclick="filterByWard('${ward.ward}')">${ward.ward}</span>
            </td>
            <td class="numeric sensor-count">${ward.sensor_count || 0}</td>
            <td class="numeric">${formatNumber(ward.total_people_per_hour)}</td>
            <td class="numeric">
                ${renderFillRateBar(ward.avg_fill_rate)}
                <span class="${getFillRateClass(ward.avg_fill_rate)}">${ward.avg_fill_rate.toFixed(1)}%</span>
            </td>
            <td>
                <button onclick="showSensorRoadDetails('${ward.ward}')" class="view-roads-btn">View Roads</button>
            </td>
        </tr>
    `).join('');
}

function sortSensorWardTable(column) {
    if (sensorSortColumn === column) {
        sensorSortAsc = !sensorSortAsc;
    } else {
        sensorSortColumn = column;
        sensorSortAsc = false;
    }
    
    // Update sort indicators
    document.querySelectorAll('#sensor-ward-table th.sortable').forEach(th => {
        th.classList.remove('sorted-asc', 'sorted-desc');
    });
    
    const currentTh = document.querySelector(`#sensor-ward-table th[onclick*="${column}"]`);
    if (currentTh) {
        currentTh.classList.add(sensorSortAsc ? 'sorted-asc' : 'sorted-desc');
    }
    
    const searchValue = document.getElementById('sensor-ward-search')?.value || '';
    renderSensorWardTable(searchValue);
}

function filterSensorWardTable(value) {
    renderSensorWardTable(value);
}

function showSensorRoadDetails(wardName) {
    const ward = sensorWardTableData.find(w => w.ward === wardName);
    if (!ward || !ward.roads) return;
    
    const panel = document.getElementById('sensor-road-details-panel');
    const title = document.getElementById('sensor-road-panel-title');
    const tbody = document.getElementById('sensor-road-table-body');
    
    title.textContent = `Sensors in ${wardName}`;
    
    tbody.innerHTML = ward.roads.map(road => `
        <tr>
            <td>${road.road}</td>
            <td class="numeric sensor-count">${road.sensor_count}</td>
            <td class="numeric">${formatNumber(road.total_people_per_hour)}</td>
            <td class="numeric">
                ${renderFillRateBar(road.avg_fill_rate)}
                <span class="${getFillRateClass(road.avg_fill_rate)}">${road.avg_fill_rate.toFixed(1)}%</span>
            </td>
        </tr>
    `).join('');
    
    panel.style.display = 'block';
}

function closeSensorRoadPanel() {
    document.getElementById('sensor-road-details-panel').style.display = 'none';
}

function toggleWardExpand(header) {
    const card = header.closest('.ward-card');
    card.classList.toggle('expanded');
}

function getFillRateClass(rate) {
    if (rate >= 80) return 'high';
    if (rate >= 40) return 'medium';
    return 'low';
}

function renderFillRateBar(rate) {
    const width = Math.min(100, rate);
    const fillClass = getFillRateClass(rate);
    return `<span class="fill-rate-bar"><span class="fill-rate-bar-fill ${fillClass}" style="width: ${width}%"></span></span>`;
}

function formatNumber(num) {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return Math.round(num).toLocaleString();
}

// ============================================
// Grid Display Controls
// ============================================
function toggleStreetsOnlyMode(enabled) {
    CONFIG.streetsOnlyMode = enabled;
    console.log(`[Grid] Streets-only mode: ${enabled}`);
    displayCombinedGrid();
    updateVisibleCellsCount();
}

function updateThreshold(value) {
    const threshold = parseFloat(value) / 100;
    CONFIG.minFootfallThreshold = threshold;
    document.getElementById('threshold-value').textContent = `${value}%`;
    console.log(`[Grid] Threshold: ${threshold}`);
    displayCombinedGrid();
    displayBinsOnCombinedMap();
    updateVisibleCellsCount();
    updateThresholdInfo();
}

function updateThresholdInfo() {
    const infoEl = document.getElementById('threshold-info');
    if (!infoEl || !analysisData.grid) return;
    
    const threshold = CONFIG.minFootfallThreshold;
    
    // Find cells at this threshold level to determine category and fill rate
    const cellsAtThreshold = analysisData.grid.features.filter(f => 
        f.properties.footfall_score >= threshold && f.properties.footfall_score < threshold + 0.05
    );
    
    if (cellsAtThreshold.length > 0) {
        // Get average values at this threshold
        const avgCategory = Math.round(cellsAtThreshold.reduce((sum, f) => sum + f.properties.footfall_category, 0) / cellsAtThreshold.length);
        const avgFillRate = cellsAtThreshold.reduce((sum, f) => sum + (f.properties.estimated_bin_fill_rate || 0), 0) / cellsAtThreshold.length;
        const avgPeople = cellsAtThreshold.reduce((sum, f) => sum + (f.properties.estimated_people_per_hour || 0), 0) / cellsAtThreshold.length;
        
        infoEl.innerHTML = `
            <span class="info-item">Category: <strong style="color: ${CONFIG.categoryColors[avgCategory]}">${CONFIG.categoryNames[avgCategory]}</strong></span>
            <span class="info-item">~${Math.round(avgFillRate)}% fill rate</span>
            <span class="info-item">~${formatNumber(avgPeople)} people/hr</span>
        `;
    } else {
        infoEl.innerHTML = '<span class="info-item">Adjust threshold to see metrics</span>';
    }
}

function filterByWard(wardName) {
    // If ward is clicked from table, add to multi-select
    if (wardName !== 'all') {
        toggleWardSelection(wardName);
    } else {
        CONFIG.selectedWards = [];
        CONFIG.wardFilter = 'all';
    }
    
    console.log(`[Grid] Ward filter: ${CONFIG.selectedWards.length > 0 ? CONFIG.selectedWards.join(', ') : 'all'}`);
    displayCombinedGrid();
    displayBinsOnCombinedMap();
    updateVisibleCellsCount();
    updateWardSelectionDisplay();
}

function toggleWardSelection(wardName) {
    const index = CONFIG.selectedWards.indexOf(wardName);
    if (index > -1) {
        CONFIG.selectedWards.splice(index, 1);
    } else {
        if (CONFIG.selectedWards.length < 10) { // Max 10 wards
            CONFIG.selectedWards.push(wardName);
        }
    }
    
    displayCombinedGrid();
    displayBinsOnCombinedMap();
    updateWardSelectionDisplay();
}

function clearWardSelection() {
    CONFIG.selectedWards = [];
    CONFIG.wardFilter = 'all';
    displayCombinedGrid();
    displayBinsOnCombinedMap();
    updateWardSelectionDisplay();
}

function updateWardSelectionDisplay() {
    const container = document.getElementById('selected-wards-display');
    if (!container) return;
    
    if (CONFIG.selectedWards.length === 0) {
        container.innerHTML = '<span class="no-selection">All wards (click table rows to filter)</span>';
        return;
    }
    
    container.innerHTML = CONFIG.selectedWards.map((ward, i) => {
        const color = CONFIG.wardColors[i % CONFIG.wardColors.length];
        return `<span class="ward-chip" style="background: ${color}20; border-color: ${color}; color: ${color}">
            ${ward}
            <button onclick="toggleWardSelection('${ward}')" class="chip-remove">×</button>
        </span>`;
    }).join('') + 
    `<button onclick="clearWardSelection()" class="clear-wards-btn">Clear all</button>`;
}

function populateWardFilter() {
    const container = document.getElementById('ward-checkboxes');
    if (!container || !analysisData.grid) return;
    
    // Get unique wards with counts
    const wardCounts = {};
    analysisData.grid.features.forEach(f => {
        const ward = f.properties.ward;
        if (ward) wardCounts[ward] = (wardCounts[ward] || 0) + 1;
    });
    
    // Sort by count
    const sortedWards = Object.entries(wardCounts)
        .sort((a, b) => b[1] - a[1])
        .map(([ward, count]) => ({ ward, count }));
    
    container.innerHTML = sortedWards.map(({ ward, count }) => `
        <label class="ward-checkbox">
            <input type="checkbox" value="${ward}" onchange="toggleWardSelection('${ward}')" 
                   ${CONFIG.selectedWards.includes(ward) ? 'checked' : ''}>
            <span class="ward-name">${ward}</span>
            <span class="ward-count">${count}</span>
        </label>
    `).join('');
}

function displayBinsOnCombinedMap() {
    if (!maps.combined) return;
    
    // Remove existing bin layer
    if (layers.combined.bins) {
        maps.combined.removeLayer(layers.combined.bins);
    }
    
    // Use uploaded bins or generated bins
    const binsData = uploadedBins || analysisData.bins;
    if (!binsData) return;
    
    // Filter by ward if set
    let filteredBins = binsData.features;
    if (CONFIG.wardFilter !== 'all') {
        filteredBins = filteredBins.filter(f => f.properties.ward === CONFIG.wardFilter);
    }
    
    layers.combined.bins = L.geoJSON({ type: "FeatureCollection", features: filteredBins }, {
        pointToLayer: (feature, latlng) => {
            const isSelected = selectedBinIds.has(feature.properties.bin_id);
            return L.circleMarker(latlng, {
                radius: isSelected ? 7 : 4,
                fillColor: isSelected ? CONFIG.selectedBinColor : CONFIG.binColor,
                color: isSelected ? '#fff' : CONFIG.binColor,
                weight: isSelected ? 2 : 1,
                opacity: 0.9,
                fillOpacity: isSelected ? 0.9 : 0.6
            });
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            const isSelected = selectedBinIds.has(p.bin_id);
            
            layer.bindPopup(`
                <div style="min-width: 180px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <strong style="font-size: 14px;">Bin ${p.bin_id}</strong>
                        ${isSelected ? '<span style="background: #f59e0b; color: #000; padding: 2px 8px; border-radius: 10px; font-size: 11px;">SELECTED</span>' : ''}
                    </div>
                    <div style="font-size: 12px; color: #9ca3af; margin-bottom: 8px;">
                        ${p.ward ? `<div>Ward: <span style="color: #818cf8;">${p.ward}</span></div>` : ''}
                        ${p.road_name ? `<div>Road: <span style="color: #fff;">${p.road_name}</span></div>` : ''}
                    </div>
                    <div style="background: #1f2937; border-radius: 6px; padding: 10px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                            <span style="font-size: 11px; color: #9ca3af;">Est. Fill Rate:</span>
                            <span style="font-family: monospace; color: ${p.estimated_bin_fill_rate >= 80 ? '#ef4444' : p.estimated_bin_fill_rate >= 40 ? '#eab308' : '#22c55e'};">${p.estimated_bin_fill_rate?.toFixed(1) || 0}%</span>
                        </div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size: 11px; color: #9ca3af;">Category:</span>
                            <span style="color: ${CONFIG.categoryColors[p.footfall_category]};">${CONFIG.categoryNames[p.footfall_category]}</span>
                        </div>
                    </div>
                    <button onclick="toggleBinSelection('${p.bin_id}')" 
                            style="width: 100%; padding: 8px; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600;
                                   background: ${isSelected ? '#ef4444' : '#10b981'}; color: white;">
                        ${isSelected ? '✕ Remove from Selection' : '✓ Add to Selection'}
                    </button>
                </div>
            `);
            
            layer.on('click', function() {
                this.openPopup();
            });
        }
    }).addTo(maps.combined);
    
    // Update selection counter
    updateSelectionCount();
}

function toggleBinSelection(binId) {
    if (selectedBinIds.has(binId)) {
        selectedBinIds.delete(binId);
    } else {
        selectedBinIds.add(binId);
    }
    
    // Close all popups and refresh
    maps.combined.closePopup();
    displayBinsOnCombinedMap();
    updateSelectionCount();
}

function updateSelectionCount() {
    const countEl = document.getElementById('selected-bins-count');
    if (countEl) {
        countEl.textContent = selectedBinIds.size;
    }
    
    // Enable/disable export button
    const exportBtn = document.getElementById('export-selection-btn');
    if (exportBtn) {
        exportBtn.disabled = selectedBinIds.size === 0;
    }
}

function clearBinSelection() {
    selectedBinIds.clear();
    displayBinsOnCombinedMap();
    updateSelectionCount();
}

function selectAllVisibleBins() {
    const binsData = uploadedBins || analysisData.bins;
    if (!binsData) return;
    
    let bins = binsData.features;
    if (CONFIG.wardFilter !== 'all') {
        bins = bins.filter(f => f.properties.ward === CONFIG.wardFilter);
    }
    
    // Select up to 1000
    bins.slice(0, 1000).forEach(f => {
        selectedBinIds.add(f.properties.bin_id);
    });
    
    displayBinsOnCombinedMap();
    updateSelectionCount();
}

function exportSelectedBins() {
    const binsData = uploadedBins || analysisData.bins;
    if (!binsData || selectedBinIds.size === 0) return;
    
    const selectedFeatures = binsData.features.filter(f => selectedBinIds.has(f.properties.bin_id));
    
    // Create CSV
    const headers = ['bin_id', 'lat', 'lon', 'ward', 'road_name', 'footfall_category', 'estimated_fill_rate'];
    const rows = selectedFeatures.map(f => {
        const p = f.properties;
        const coords = f.geometry.coordinates;
        return [
            p.bin_id,
            coords[1],
            coords[0],
            p.ward || '',
            p.road_name || '',
            p.footfall_category,
            p.estimated_bin_fill_rate?.toFixed(1) || 0
        ].join(',');
    });
    
    const csv = [headers.join(','), ...rows].join('\n');
    
    // Download
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `selected_bins_${selectedBinIds.size}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

function handleBinFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        const lines = text.split('\n');
        const headers = lines[0].toLowerCase().split(',').map(h => h.trim());
        
        // Find column indices
        const idIdx = headers.findIndex(h => h.includes('bin') && h.includes('id') || h === 'id');
        const latIdx = headers.findIndex(h => h === 'lat' || h === 'latitude');
        const lonIdx = headers.findIndex(h => h === 'lon' || h === 'lng' || h === 'longitude');
        const wardIdx = headers.findIndex(h => h === 'ward');
        
        if (latIdx === -1 || lonIdx === -1) {
            alert('CSV must contain lat/latitude and lon/longitude columns');
            return;
        }
        
        const features = [];
        for (let i = 1; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue;
            
            const cols = line.split(',').map(c => c.trim());
            const lat = parseFloat(cols[latIdx]);
            const lon = parseFloat(cols[lonIdx]);
            
            if (isNaN(lat) || isNaN(lon)) continue;
            
            features.push({
                type: "Feature",
                geometry: { type: "Point", coordinates: [lon, lat] },
                properties: {
                    bin_id: idIdx >= 0 ? cols[idIdx] : `UPLOADED_${i}`,
                    ward: wardIdx >= 0 ? cols[wardIdx] : '',
                    road_name: '',
                    footfall_category: 4,
                    estimated_bin_fill_rate: 50,
                    uploaded: true
                }
            });
        }
        
        uploadedBins = { type: "FeatureCollection", features };
        console.log(`[Bins] Uploaded ${features.length} bins`);
        
        // Update UI
        document.getElementById('uploaded-bins-count').textContent = features.length;
        document.getElementById('upload-status').style.display = 'block';
        
        // Refresh map
        displayBinsOnCombinedMap();
    };
    reader.readAsText(file);
}

function clearUploadedBins() {
    uploadedBins = null;
    document.getElementById('upload-status').style.display = 'none';
    document.getElementById('bin-upload-input').value = '';
    displayBinsOnCombinedMap();
}

function updateVisibleCellsCount() {
    if (!analysisData.grid) {
        document.getElementById('visible-cells-count').textContent = 'No data';
        return;
    }
    
    const total = analysisData.grid.features.length;
    const visible = CONFIG.streetsOnlyMode 
        ? analysisData.grid.features.filter(f => f.properties.footfall_score >= CONFIG.minFootfallThreshold).length
        : total;
    
    document.getElementById('visible-cells-count').textContent = `${visible.toLocaleString()} of ${total.toLocaleString()}`;
}

// Make functions globally available
window.runAnalysis = runAnalysis;
window.toggleTubeLayer = toggleTubeLayer;
window.toggleBusLayer = toggleBusLayer;
window.togglePremisesLayer = togglePremisesLayer;
window.toggleStreetsOnlyMode = toggleStreetsOnlyMode;
window.updateThreshold = updateThreshold;
window.toggleWardExpand = toggleWardExpand;
window.filterByWard = filterByWard;
window.toggleBinSelection = toggleBinSelection;
window.clearBinSelection = clearBinSelection;
window.selectAllVisibleBins = selectAllVisibleBins;
window.exportSelectedBins = exportSelectedBins;
window.handleBinFileUpload = handleBinFileUpload;
window.clearUploadedBins = clearUploadedBins;
window.sortWardTable = sortWardTable;
window.filterWardTable = filterWardTable;
window.showRoadDetails = showRoadDetails;
window.closeRoadPanel = closeRoadPanel;
window.sortSensorWardTable = sortSensorWardTable;
window.filterSensorWardTable = filterSensorWardTable;
window.showSensorRoadDetails = showSensorRoadDetails;
window.closeSensorRoadPanel = closeSensorRoadPanel;
window.updateSensorWeight = updateSensorWeight;
window.recalculateSensorDistribution = recalculateSensorDistribution;
window.toggleWardSelection = toggleWardSelection;
window.clearWardSelection = clearWardSelection;

console.log('[App] Westminster Bin Sensor Analysis script loaded');
