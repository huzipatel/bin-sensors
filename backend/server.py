"""
Westminster Footfall Analysis - Backend API Server
Provides endpoints to run analysis and serve data to the frontend
"""

import json
import sys
import os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import traceback
import time

# Add parent directory to path to import the analysis module
sys.path.insert(0, str(Path(__file__).parent.parent))

from westminster_footfall_analysis_simple import (
    Config, create_grid, load_tube_stations, load_bus_stops,
    load_licensed_premises, calculate_footfall_scores, categorize_cells,
    save_grid_csv, save_geojson, load_bins_from_csv, assign_bins_to_cells,
    optimize_sensor_placement, save_selected_bins_csv, generate_sample_bins,
    Point, is_in_westminster, WESTMINSTER_WARDS, WARD_ROADS
)


class AnalysisState:
    """Holds the current state of the analysis - thread safe"""
    def __init__(self):
        self.lock = threading.Lock()
        self.config = Config()
        self._tubes = None
        self._buses = None
        self._premises = None
        self._cells = None
        self._bins = None
        self._selected_bins = None
        self._status = "idle"
        self._progress = 0
        self._message = "Ready to run"
    
    @property
    def tubes(self):
        with self.lock:
            return self._tubes
    
    @tubes.setter
    def tubes(self, value):
        with self.lock:
            self._tubes = value
    
    @property
    def buses(self):
        with self.lock:
            return self._buses
    
    @buses.setter
    def buses(self, value):
        with self.lock:
            self._buses = value
    
    @property
    def premises(self):
        with self.lock:
            return self._premises
    
    @premises.setter
    def premises(self, value):
        with self.lock:
            self._premises = value
    
    @property
    def cells(self):
        with self.lock:
            return self._cells
    
    @cells.setter
    def cells(self, value):
        with self.lock:
            self._cells = value
    
    @property
    def bins(self):
        with self.lock:
            return self._bins
    
    @bins.setter
    def bins(self, value):
        with self.lock:
            self._bins = value
    
    @property
    def status(self):
        with self.lock:
            return self._status
    
    @status.setter
    def status(self, value):
        with self.lock:
            self._status = value
            print(f"[STATUS] {value}")
    
    @property
    def progress(self):
        with self.lock:
            return self._progress
    
    @progress.setter
    def progress(self, value):
        with self.lock:
            self._progress = value
            print(f"[PROGRESS] {value}%")
    
    @property
    def message(self):
        with self.lock:
            return self._message
    
    @message.setter
    def message(self, value):
        with self.lock:
            self._message = value
            print(f"[MESSAGE] {value}")
    
    def get_state(self):
        """Get all state at once"""
        with self.lock:
            return {
                "status": self._status,
                "progress": self._progress,
                "message": self._message,
                "has_data": self._cells is not None
            }
    
    def reset(self):
        with self.lock:
            self._cells = None
            self._bins = None
            self._selected_bins = None
            self._status = "idle"
            self._progress = 0
            self._message = "Ready to run"


state = AnalysisState()


def tubes_to_geojson(tubes):
    """Convert tube stations to GeoJSON"""
    features = []
    for tube in tubes:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [tube.lon, tube.lat]
            },
            "properties": {
                "name": tube.name,
                "annual_usage": tube.annual_usage,
                "type": "tube_station"
            }
        })
    return {"type": "FeatureCollection", "features": features}


def buses_to_geojson(buses):
    """Convert bus stops to GeoJSON"""
    features = []
    for bus in buses:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [bus.lon, bus.lat]
            },
            "properties": {
                "stop_id": bus.stop_id,
                "frequency": bus.frequency,
                "type": "bus_stop"
            }
        })
    return {"type": "FeatureCollection", "features": features}


def premises_to_geojson(premises):
    """Convert licensed premises to GeoJSON"""
    features = []
    for p in premises:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [p.lon, p.lat]
            },
            "properties": {
                "premises_id": p.premises_id,
                "area": p.area,
                "type": p.type,
                "capacity": p.capacity
            }
        })
    return {"type": "FeatureCollection", "features": features}


def cells_to_geojson(cells, config, score_type="footfall"):
    """Convert grid cells to GeoJSON with specified score type"""
    features = []
    half_size = config.GRID_RESOLUTION / 2
    
    # Find max scores for normalization
    max_scores = {"tube": 0, "bus": 0, "premises": 0, "footfall": 0}
    for cell in cells:
        max_scores["tube"] = max(max_scores["tube"], cell.tube_score)
        max_scores["bus"] = max(max_scores["bus"], cell.bus_score)
        max_scores["premises"] = max(max_scores["premises"], cell.premises_score)
        max_scores["footfall"] = max(max_scores["footfall"], cell.footfall_score)
    
    for cell in cells:
        coords = [
            [cell.center_lon - half_size, cell.center_lat - half_size],
            [cell.center_lon + half_size, cell.center_lat - half_size],
            [cell.center_lon + half_size, cell.center_lat + half_size],
            [cell.center_lon - half_size, cell.center_lat + half_size],
            [cell.center_lon - half_size, cell.center_lat - half_size],
        ]
        
        # Determine which score to highlight
        if score_type == "tube":
            highlight_score = cell.tube_score / max_scores["tube"] if max_scores["tube"] > 0 else 0
        elif score_type == "bus":
            highlight_score = cell.bus_score / max_scores["bus"] if max_scores["bus"] > 0 else 0
        elif score_type == "premises":
            highlight_score = cell.premises_score / max_scores["premises"] if max_scores["premises"] > 0 else 0
        else:
            highlight_score = cell.footfall_score
        
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            },
            "properties": {
                "cell_id": cell.cell_id,
                "footfall_score": round(cell.footfall_score, 4),
                "tube_score": round(cell.tube_score, 2),
                "bus_score": round(cell.bus_score, 2),
                "premises_score": round(cell.premises_score, 2),
                "footfall_category": cell.footfall_category,
                "footfall_category_name": cell.footfall_category_name,
                "highlight_score": round(highlight_score, 4),
                "ward": getattr(cell, 'ward', ''),
                "road_name": getattr(cell, 'road_name', ''),
                "estimated_people_per_hour": round(getattr(cell, 'estimated_people_per_hour', 0), 0),
                "estimated_bin_fill_rate": round(getattr(cell, 'estimated_bin_fill_rate', 0), 1)
            }
        })
    
    return {"type": "FeatureCollection", "features": features}


def bins_to_geojson(bins, selected_only=False):
    """Convert bins to GeoJSON"""
    features = []
    for b in bins:
        if selected_only and not b.selected_for_sensor:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [b.lon, b.lat]
            },
            "properties": {
                "bin_id": b.bin_id,
                "bin_type": b.bin_type,
                "capacity_liters": b.capacity_liters,
                "footfall_category": b.footfall_category,
                "footfall_score": round(b.footfall_score, 4),
                "selected_for_sensor": b.selected_for_sensor,
                "selection_rank": b.selection_rank,
                "ward": getattr(b, 'ward', ''),
                "road_name": getattr(b, 'road_name', ''),
                "estimated_people_per_hour": round(getattr(b, 'estimated_people_per_hour', 0), 0),
                "estimated_bin_fill_rate": round(getattr(b, 'estimated_bin_fill_rate', 0), 1)
            }
        })
    return {"type": "FeatureCollection", "features": features}


class APIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with API endpoints"""
    
    def __init__(self, *args, **kwargs):
        # Set directory to serve static files from frontend
        self.directory = str(Path(__file__).parent.parent / "frontend")
        super().__init__(*args, directory=self.directory, **kwargs)
    
    def log_message(self, format, *args):
        """Custom logging"""
        if '/api/' in str(args[0]):
            print(f"[API] {args[0]}")
    
    def send_json(self, data, status=200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        try:
            # API Routes
            if path == '/api/status':
                self.send_json(state.get_state())
                return
                
            elif path == '/api/tubes':
                tubes = state.tubes
                if tubes is None:
                    state.tubes = load_tube_stations()
                    tubes = state.tubes
                self.send_json(tubes_to_geojson(tubes))
                return
                
            elif path == '/api/buses':
                buses = state.buses
                if buses is None:
                    state.buses = load_bus_stops(state.config)
                    buses = state.buses
                self.send_json(buses_to_geojson(buses))
                return
                
            elif path == '/api/premises':
                premises = state.premises
                if premises is None:
                    state.premises = load_licensed_premises()
                    premises = state.premises
                self.send_json(premises_to_geojson(premises))
                return
                
            elif path == '/api/grid':
                cells = state.cells
                if cells is None:
                    self.send_json({"error": "Run analysis first"}, 400)
                    return
                self.send_json(cells_to_geojson(cells, state.config, "footfall"))
                return
                    
            elif path == '/api/grid/tube':
                cells = state.cells
                if cells is None:
                    self.send_json({"error": "Run analysis first"}, 400)
                    return
                self.send_json(cells_to_geojson(cells, state.config, "tube"))
                return
                    
            elif path == '/api/grid/bus':
                cells = state.cells
                if cells is None:
                    self.send_json({"error": "Run analysis first"}, 400)
                    return
                self.send_json(cells_to_geojson(cells, state.config, "bus"))
                return
                    
            elif path == '/api/grid/premises':
                cells = state.cells
                if cells is None:
                    self.send_json({"error": "Run analysis first"}, 400)
                    return
                self.send_json(cells_to_geojson(cells, state.config, "premises"))
                return
            
            elif path == '/api/bins':
                bins = state.bins
                if bins is None:
                    self.send_json({"error": "No bins loaded"}, 400)
                    return
                selected_only = params.get('selected', ['false'])[0] == 'true'
                self.send_json(bins_to_geojson(bins, selected_only))
                return
                    
            elif path == '/api/selected-bins':
                bins = state.bins
                if bins is None:
                    self.send_json({"error": "No bins loaded"}, 400)
                    return
                self.send_json(bins_to_geojson(bins, selected_only=True))
                return
                    
            elif path == '/api/stats':
                self.send_json(get_analysis_stats())
                return
            
            elif path == '/api/summary/wards':
                self.send_json(get_ward_summary())
                return
            
            elif path == '/api/summary/sensors':
                self.send_json(get_sensor_summary())
                return
                
            elif path == '/api/run-analysis':
                if state.status == "running":
                    self.send_json({"status": "already_running", "message": "Analysis already in progress"})
                    return
                    
                # Run analysis in background thread
                thread = threading.Thread(target=run_full_analysis, daemon=True)
                thread.start()
                self.send_json({"status": "started", "message": "Analysis started"})
                return
            
            # Serve static files for non-API routes
            super().do_GET()
            
        except Exception as e:
            print(f"[ERROR] {path}: {e}")
            traceback.print_exc()
            self.send_json({"error": str(e)}, 500)
    
    def do_POST(self):
        """Handle POST requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/api/run-analysis':
            if state.status == "running":
                self.send_json({"status": "already_running", "message": "Analysis already in progress"})
                return
                
            thread = threading.Thread(target=run_full_analysis, daemon=True)
            thread.start()
            self.send_json({"status": "started", "message": "Analysis started"})
        else:
            self.send_json({"error": "Not found"}, 404)


def run_full_analysis():
    """Run the complete analysis pipeline"""
    global state
    
    print("\n" + "="*60)
    print("STARTING ANALYSIS")
    print("="*60)
    
    try:
        state.status = "running"
        state.progress = 0
        state.message = "Initializing..."
        time.sleep(0.1)  # Let the state propagate
        
        # Step 1: Load data sources
        state.progress = 5
        state.message = "Loading tube station data..."
        time.sleep(0.1)
        state.tubes = load_tube_stations()
        print(f"  Loaded {len(state.tubes)} tube stations")
        
        state.progress = 15
        state.message = "Loading bus stop data..."
        time.sleep(0.1)
        state.buses = load_bus_stops(state.config)
        print(f"  Loaded {len(state.buses)} bus stops")
        
        state.progress = 25
        state.message = "Loading licensed premises data..."
        time.sleep(0.1)
        state.premises = load_licensed_premises()
        print(f"  Loaded {len(state.premises)} premises")
        
        # Step 2: Create grid
        state.progress = 35
        state.message = "Creating analysis grid..."
        time.sleep(0.1)
        cells = create_grid(state.config)
        print(f"  Created {len(cells)} grid cells")
        
        # Step 3: Calculate footfall scores
        state.progress = 45
        state.message = "Calculating footfall scores..."
        time.sleep(0.1)
        
        # Get thread-safe copies
        tubes = state.tubes
        buses = state.buses
        premises = state.premises
        
        cells = calculate_footfall_scores(cells, tubes, buses, premises, state.config)
        print("  Footfall scores calculated")
        
        state.progress = 60
        state.message = "Categorizing footfall zones..."
        time.sleep(0.1)
        
        # Step 4: Categorize cells
        cells = categorize_cells(cells, state.config)
        state.cells = cells
        print("  Cells categorized")
        
        # Step 5: Generate sample bins and optimize
        state.progress = 70
        state.message = "Generating sample bin locations..."
        time.sleep(0.1)
        
        # Create data directory if needed
        Path("data").mkdir(exist_ok=True)
        generate_sample_bins(3000, "data/sample_bins.csv")
        bins = load_bins_from_csv("data/sample_bins.csv")
        print(f"  Generated {len(bins)} sample bins")
        
        state.progress = 80
        state.message = "Assigning bins to grid cells..."
        time.sleep(0.1)
        bins = assign_bins_to_cells(bins, cells, state.config)
        
        state.progress = 90
        state.message = "Optimizing sensor placement..."
        time.sleep(0.1)
        selected = optimize_sensor_placement(bins, 1000, state.config.N_FOOTFALL_CATEGORIES)
        state.bins = bins
        print(f"  Selected {len([b for b in bins if b.selected_for_sensor])} sensor locations")
        
        # Step 6: Save outputs
        state.progress = 95
        state.message = "Saving results..."
        time.sleep(0.1)
        
        Path("output").mkdir(exist_ok=True)
        save_grid_csv(cells, "output/westminster_footfall_grid.csv")
        save_geojson(cells, "output/westminster_footfall_grid.geojson", state.config)
        save_selected_bins_csv(bins, "output/recommended_sensor_locations.csv")
        print("  Results saved")
        
        state.progress = 100
        state.message = "Analysis complete!"
        state.status = "complete"
        
        print("="*60)
        print("ANALYSIS COMPLETE")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] Analysis failed: {e}")
        traceback.print_exc()
        state.status = "error"
        state.message = f"Error: {str(e)}"


def get_analysis_stats():
    """Get current analysis statistics"""
    tubes = state.tubes
    buses = state.buses
    premises = state.premises
    cells = state.cells
    bins = state.bins
    
    stats = {
        "tubes_count": len(tubes) if tubes else 0,
        "buses_count": len(buses) if buses else 0,
        "premises_count": len(premises) if premises else 0,
        "cells_count": len(cells) if cells else 0,
        "bins_count": len(bins) if bins else 0,
        "selected_bins_count": sum(1 for b in bins if b.selected_for_sensor) if bins else 0,
        "category_distribution": {},
        "sensor_distribution": {}
    }
    
    if cells:
        for cell in cells:
            cat = cell.footfall_category
            stats["category_distribution"][cat] = stats["category_distribution"].get(cat, 0) + 1
    
    if bins:
        for b in bins:
            if b.selected_for_sensor:
                cat = b.footfall_category
                stats["sensor_distribution"][cat] = stats["sensor_distribution"].get(cat, 0) + 1
    
    return stats


def get_ward_summary():
    """Get summary statistics grouped by ward"""
    cells = state.cells
    bins = state.bins
    
    if not cells:
        return {"wards": [], "totals": {}}
    
    ward_data = {}
    
    # Aggregate cell data by ward
    for cell in cells:
        ward = getattr(cell, 'ward', 'Unknown') or 'Unknown'
        if ward not in ward_data:
            ward_data[ward] = {
                "ward": ward,
                "cell_count": 0,
                "total_people_per_hour": 0,
                "avg_fill_rate": 0,
                "fill_rates": [],
                "categories": {},
                "roads": {},
                "sensor_count": 0
            }
        
        wd = ward_data[ward]
        wd["cell_count"] += 1
        wd["total_people_per_hour"] += getattr(cell, 'estimated_people_per_hour', 0)
        wd["fill_rates"].append(getattr(cell, 'estimated_bin_fill_rate', 0))
        
        cat = cell.footfall_category
        wd["categories"][cat] = wd["categories"].get(cat, 0) + 1
        
        road = getattr(cell, 'road_name', 'Unknown') or 'Unknown'
        if road not in wd["roads"]:
            wd["roads"][road] = {
                "road": road,
                "cell_count": 0,
                "total_people_per_hour": 0,
                "avg_fill_rate": 0,
                "fill_rates": [],
                "sensor_count": 0
            }
        rd = wd["roads"][road]
        rd["cell_count"] += 1
        rd["total_people_per_hour"] += getattr(cell, 'estimated_people_per_hour', 0)
        rd["fill_rates"].append(getattr(cell, 'estimated_bin_fill_rate', 0))
    
    # Count sensors per ward/road
    if bins:
        for b in bins:
            if b.selected_for_sensor:
                ward = getattr(b, 'ward', 'Unknown') or 'Unknown'
                road = getattr(b, 'road_name', 'Unknown') or 'Unknown'
                if ward in ward_data:
                    ward_data[ward]["sensor_count"] += 1
                    if road in ward_data[ward]["roads"]:
                        ward_data[ward]["roads"][road]["sensor_count"] += 1
    
    # Calculate averages and format output
    wards = []
    total_people = 0
    total_fill_rates = []
    total_sensors = 0
    
    for ward, wd in ward_data.items():
        if wd["fill_rates"]:
            wd["avg_fill_rate"] = sum(wd["fill_rates"]) / len(wd["fill_rates"])
        del wd["fill_rates"]
        
        # Format roads
        roads = []
        for road, rd in wd["roads"].items():
            if rd["fill_rates"]:
                rd["avg_fill_rate"] = sum(rd["fill_rates"]) / len(rd["fill_rates"])
            del rd["fill_rates"]
            roads.append(rd)
        
        # Sort roads by people per hour
        roads.sort(key=lambda x: -x["total_people_per_hour"])
        wd["roads"] = roads[:15]  # Top 15 roads per ward
        
        total_people += wd["total_people_per_hour"]
        total_fill_rates.append(wd["avg_fill_rate"])
        total_sensors += wd["sensor_count"]
        
        wards.append(wd)
    
    # Sort wards by total footfall
    wards.sort(key=lambda x: -x["total_people_per_hour"])
    
    return {
        "wards": wards,
        "totals": {
            "total_people_per_hour": total_people,
            "avg_fill_rate": sum(total_fill_rates) / len(total_fill_rates) if total_fill_rates else 0,
            "total_sensors": total_sensors,
            "ward_count": len(wards)
        }
    }


def get_sensor_summary():
    """Get sensor placement summary grouped by ward"""
    bins = state.bins
    
    if not bins:
        return {"wards": [], "totals": {}}
    
    selected_bins = [b for b in bins if b.selected_for_sensor]
    
    ward_data = {}
    
    for b in selected_bins:
        ward = getattr(b, 'ward', 'Unknown') or 'Unknown'
        if ward not in ward_data:
            ward_data[ward] = {
                "ward": ward,
                "sensor_count": 0,
                "total_people_per_hour": 0,
                "avg_fill_rate": 0,
                "fill_rates": [],
                "categories": {},
                "roads": {}
            }
        
        wd = ward_data[ward]
        wd["sensor_count"] += 1
        wd["total_people_per_hour"] += getattr(b, 'estimated_people_per_hour', 0)
        wd["fill_rates"].append(getattr(b, 'estimated_bin_fill_rate', 0))
        
        cat = b.footfall_category
        wd["categories"][cat] = wd["categories"].get(cat, 0) + 1
        
        road = getattr(b, 'road_name', 'Unknown') or 'Unknown'
        if road not in wd["roads"]:
            wd["roads"][road] = {
                "road": road,
                "sensor_count": 0,
                "total_people_per_hour": 0,
                "avg_fill_rate": 0,
                "fill_rates": [],
                "bins": []
            }
        rd = wd["roads"][road]
        rd["sensor_count"] += 1
        rd["total_people_per_hour"] += getattr(b, 'estimated_people_per_hour', 0)
        rd["fill_rates"].append(getattr(b, 'estimated_bin_fill_rate', 0))
        rd["bins"].append({
            "bin_id": b.bin_id,
            "rank": b.selection_rank,
            "fill_rate": round(getattr(b, 'estimated_bin_fill_rate', 0), 1)
        })
    
    # Calculate averages and format output
    wards = []
    total_sensors = 0
    total_people = 0
    total_fill_rates = []
    
    for ward, wd in ward_data.items():
        if wd["fill_rates"]:
            wd["avg_fill_rate"] = sum(wd["fill_rates"]) / len(wd["fill_rates"])
        del wd["fill_rates"]
        
        # Format roads
        roads = []
        for road, rd in wd["roads"].items():
            if rd["fill_rates"]:
                rd["avg_fill_rate"] = sum(rd["fill_rates"]) / len(rd["fill_rates"])
            del rd["fill_rates"]
            # Keep only top 5 bins per road
            rd["bins"] = sorted(rd["bins"], key=lambda x: x["rank"])[:5]
            roads.append(rd)
        
        roads.sort(key=lambda x: -x["sensor_count"])
        wd["roads"] = roads[:10]  # Top 10 roads per ward
        
        total_sensors += wd["sensor_count"]
        total_people += wd["total_people_per_hour"]
        total_fill_rates.append(wd["avg_fill_rate"])
        
        wards.append(wd)
    
    wards.sort(key=lambda x: -x["sensor_count"])
    
    return {
        "wards": wards,
        "totals": {
            "total_sensors": total_sensors,
            "total_people_per_hour": total_people,
            "avg_fill_rate": sum(total_fill_rates) / len(total_fill_rates) if total_fill_rates else 0,
            "ward_count": len(wards)
        }
    }


def run_server(port=8080):
    """Start the API server"""
    server = HTTPServer(('localhost', port), APIHandler)
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║     Westminster Footfall Analysis - Server Running               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   Open in browser: http://localhost:{port}                        ║
║                                                                  ║
║   API Endpoints:                                                 ║
║     GET  /api/status        - Analysis status                    ║
║     GET  /api/run-analysis  - Start analysis                     ║
║     GET  /api/tubes         - Tube station data                  ║
║     GET  /api/buses         - Bus stop data                      ║
║     GET  /api/premises      - Licensed premises data             ║
║     GET  /api/grid          - Footfall grid                      ║
║     GET  /api/grid/tube     - Grid with tube scores              ║
║     GET  /api/grid/bus      - Grid with bus scores               ║
║     GET  /api/grid/premises - Grid with premises scores          ║
║     GET  /api/bins          - All bin locations                  ║
║     GET  /api/selected-bins - Selected sensor locations          ║
║     GET  /api/stats         - Analysis statistics                ║
║                                                                  ║
║   Press Ctrl+C to stop                                           ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', '-p', type=int, default=8080)
    args = parser.parse_args()
    run_server(args.port)
