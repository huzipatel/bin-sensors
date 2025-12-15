"""
Westminster Footfall Analysis - Simplified Version
This version works with minimal dependencies (numpy, pandas only)
and produces CSV/JSON outputs that can be visualized in any GIS tool.

For the full version with interactive maps, install all packages:
pip install geopandas h3 folium scipy scikit-learn seaborn tqdm matplotlib
Then run: python westminster_footfall_analysis.py

This simplified version:
1. Creates a regular grid instead of H3 hexagons
2. Calculates footfall scores based on tube, bus, and premises data
3. Outputs CSV files for use in QGIS, ArcGIS, or Excel
4. Includes bin sensor optimization logic
"""

import json
import math
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
import csv

# Try to import optional dependencies
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("Note: numpy not available. Using pure Python (slower)")

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Note: pandas not available. Using pure Python data structures")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Configuration for the analysis"""
    # Westminster bounding box
    MIN_LON: float = -0.20
    MAX_LON: float = -0.11
    MIN_LAT: float = 51.485
    MAX_LAT: float = 51.535
    
    # Grid resolution (in degrees, ~100m at London latitude)
    GRID_RESOLUTION: float = 0.001
    
    # Footfall influence radii (in degrees, ~100m = 0.0009 degrees at London)
    TUBE_INFLUENCE_RADIUS: float = 0.005  # ~500m
    BUS_INFLUENCE_RADIUS: float = 0.002   # ~200m
    PREMISES_INFLUENCE_RADIUS: float = 0.0015  # ~150m
    
    # Footfall weights
    TUBE_WEIGHT: float = 0.45
    BUS_WEIGHT: float = 0.30
    PREMISES_WEIGHT: float = 0.25
    
    # Number of footfall categories
    N_FOOTFALL_CATEGORIES: int = 8
    
    # Output directory
    OUTPUT_DIR: str = "output"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Point:
    lat: float
    lon: float
    
    def distance_to(self, other: 'Point') -> float:
        """Calculate approximate distance in degrees"""
        return math.sqrt((self.lat - other.lat)**2 + (self.lon - other.lon)**2)


@dataclass
class TubeStation:
    name: str
    lat: float
    lon: float
    annual_usage: float  # millions


@dataclass 
class BusStop:
    stop_id: str
    lat: float
    lon: float
    frequency: int  # buses per hour


@dataclass
class LicensedPremises:
    premises_id: str
    area: str
    type: str
    lat: float
    lon: float
    capacity: int


@dataclass
class GridCell:
    cell_id: str
    center_lat: float
    center_lon: float
    tube_score: float = 0.0
    bus_score: float = 0.0
    premises_score: float = 0.0
    footfall_score: float = 0.0
    footfall_category: int = 0
    footfall_category_name: str = ""
    ward: str = ""
    road_name: str = ""
    locality: str = ""
    estimated_people_per_hour: float = 0.0
    estimated_bin_fill_rate: float = 0.0  # Percentage per day


@dataclass
class BinLocation:
    bin_id: str
    lat: float
    lon: float
    bin_type: str = ""
    capacity_liters: int = 0
    cell_id: str = ""
    footfall_category: int = 0
    footfall_score: float = 0.0
    selected_for_sensor: bool = False
    selection_rank: int = 0
    ward: str = ""
    road_name: str = ""
    estimated_people_per_hour: float = 0.0
    estimated_bin_fill_rate: float = 0.0


# =============================================================================
# DATA LOADING
# =============================================================================

def load_tube_stations() -> List[TubeStation]:
    """Westminster tube stations with usage data"""
    stations_data = [
        ("Victoria", 51.4965, -0.1447, 82.0),
        ("Oxford Circus", 51.5152, -0.1418, 98.0),
        ("Paddington", 51.5154, -0.1755, 50.0),
        ("King's Cross St. Pancras", 51.5308, -0.1238, 97.0),
        ("Baker Street", 51.5226, -0.1571, 30.0),
        ("Westminster", 51.5010, -0.1254, 25.0),
        ("Green Park", 51.5067, -0.1428, 35.0),
        ("Piccadilly Circus", 51.5100, -0.1347, 40.0),
        ("Leicester Square", 51.5113, -0.1281, 35.0),
        ("Tottenham Court Road", 51.5165, -0.1310, 32.0),
        ("Bond Street", 51.5142, -0.1494, 28.0),
        ("Marble Arch", 51.5136, -0.1586, 18.0),
        ("Hyde Park Corner", 51.5027, -0.1527, 12.0),
        ("Knightsbridge", 51.5015, -0.1607, 15.0),
        ("Pimlico", 51.4893, -0.1334, 8.0),
        ("St. James's Park", 51.4994, -0.1335, 10.0),
        ("Charing Cross", 51.5074, -0.1270, 15.0),
        ("Embankment", 51.5074, -0.1223, 18.0),
        ("Covent Garden", 51.5129, -0.1243, 20.0),
        ("Holborn", 51.5174, -0.1200, 25.0),
        ("Warren Street", 51.5247, -0.1384, 12.0),
        ("Great Portland Street", 51.5238, -0.1439, 8.0),
        ("Regent's Park", 51.5234, -0.1466, 6.0),
        ("Edgware Road (Bakerloo)", 51.5199, -0.1679, 7.0),
        ("Edgware Road (Circle)", 51.5203, -0.1680, 8.0),
        ("Marylebone", 51.5225, -0.1631, 15.0),
        ("Lancaster Gate", 51.5119, -0.1756, 8.0),
        ("Queensway", 51.5107, -0.1871, 10.0),
        ("Bayswater", 51.5122, -0.1879, 7.0),
        ("Warwick Avenue", 51.5235, -0.1835, 5.0),
        ("Maida Vale", 51.5298, -0.1854, 4.0),
    ]
    
    return [TubeStation(name, lat, lon, usage) for name, lat, lon, usage in stations_data]


def load_bus_stops(config: Config) -> List[BusStop]:
    """Generate representative bus stops"""
    import random
    random.seed(42)
    
    # Major corridors with high frequency
    corridors = [
        ("Oxford Street", 51.5154, (-0.16, -0.13), 60, "horizontal"),
        ("Piccadilly", 51.5088, (-0.17, -0.13), 45, "horizontal"),
        ("Victoria Street", 51.4985, (-0.145, -0.125), 40, "horizontal"),
        ("Edgware Road", (-0.1679,), (51.50, 51.53), 35, "vertical"),
        ("Park Lane", (-0.1510,), (51.50, 51.52), 30, "vertical"),
        ("Whitehall", (-0.1265,), (51.50, 51.51), 35, "vertical"),
        ("Regent Street", (-0.1400,), (51.51, 51.52), 40, "vertical"),
        ("Strand", 51.5108, (-0.13, -0.12), 45, "horizontal"),
        ("Marylebone Road", 51.5225, (-0.18, -0.13), 35, "horizontal"),
    ]
    
    bus_stops = []
    stop_id = 0
    
    for corridor in corridors:
        name, coord1, coord2, freq, direction = corridor
        
        if direction == "horizontal":
            lat = coord1
            for i in range(8):
                lon = coord2[0] + (coord2[1] - coord2[0]) * i / 7
                bus_stops.append(BusStop(
                    f"BS{stop_id:04d}",
                    lat + random.uniform(-0.001, 0.001),
                    lon,
                    freq + random.randint(-5, 5)
                ))
                stop_id += 1
        else:
            lon = coord1[0]
            for i in range(6):
                lat = coord2[0] + (coord2[1] - coord2[0]) * i / 5
                bus_stops.append(BusStop(
                    f"BS{stop_id:04d}",
                    lat,
                    lon + random.uniform(-0.001, 0.001),
                    freq + random.randint(-5, 5)
                ))
                stop_id += 1
    
    # Additional random stops
    for _ in range(150):
        lat = random.uniform(config.MIN_LAT + 0.01, config.MAX_LAT - 0.01)
        lon = random.uniform(config.MIN_LON + 0.01, config.MAX_LON - 0.01)
        bus_stops.append(BusStop(
            f"BS{stop_id:04d}",
            lat, lon,
            random.randint(5, 25)
        ))
        stop_id += 1
    
    return bus_stops


def load_licensed_premises() -> List[LicensedPremises]:
    """Generate representative licensed premises"""
    import random
    random.seed(43)
    
    hotspots = [
        ("Soho", 51.5136, -0.1340, 0.008, 150),
        ("Covent Garden", 51.5117, -0.1240, 0.006, 100),
        ("Leicester Square", 51.5105, -0.1300, 0.005, 80),
        ("West End Theatre", 51.5115, -0.1260, 0.007, 60),
        ("Mayfair", 51.5095, -0.1470, 0.010, 70),
        ("Fitzrovia", 51.5190, -0.1380, 0.007, 50),
        ("Marylebone", 51.5200, -0.1550, 0.008, 45),
        ("Victoria", 51.4970, -0.1440, 0.007, 55),
        ("Pimlico", 51.4880, -0.1350, 0.008, 30),
        ("Paddington", 51.5165, -0.1780, 0.008, 40),
        ("Bayswater", 51.5115, -0.1870, 0.007, 35),
        ("Chinatown", 51.5112, -0.1310, 0.003, 90),
        ("St James", 51.5060, -0.1380, 0.006, 40),
    ]
    
    premises = []
    premises_id = 0
    types = ['Restaurant', 'Pub', 'Bar', 'Club', 'Cafe', 'Hotel Bar']
    type_probs = [0.35, 0.25, 0.20, 0.05, 0.10, 0.05]
    capacities = {
        'Restaurant': (30, 150),
        'Pub': (50, 200),
        'Bar': (40, 150),
        'Club': (100, 500),
        'Cafe': (15, 60),
        'Hotel Bar': (30, 100)
    }
    
    for name, center_lat, center_lon, radius, n_premises in hotspots:
        for _ in range(n_premises):
            angle = random.uniform(0, 2 * math.pi)
            r = radius * math.sqrt(random.random())
            lat = center_lat + r * math.cos(angle)
            lon = center_lon + r * math.sin(angle)
            
            ptype = random.choices(types, weights=type_probs)[0]
            cap_range = capacities[ptype]
            capacity = random.randint(cap_range[0], cap_range[1])
            
            premises.append(LicensedPremises(
                f"LP{premises_id:05d}",
                name, ptype, lat, lon, capacity
            ))
            premises_id += 1
    
    return premises


# =============================================================================
# WESTMINSTER WARD DEFINITIONS
# =============================================================================

# Westminster ward boundaries (expanded to cover full borough)
WESTMINSTER_WARDS = {
    "West End": [
        (-0.1500, 51.5200), (-0.1250, 51.5200), (-0.1250, 51.5050),
        (-0.1500, 51.5050), (-0.1500, 51.5200)
    ],
    "St James's": [
        (-0.1500, 51.5050), (-0.1200, 51.5050), (-0.1200, 51.4950),
        (-0.1500, 51.4950), (-0.1500, 51.5050)
    ],
    "Marylebone High Street": [
        (-0.1650, 51.5280), (-0.1450, 51.5280), (-0.1450, 51.5150),
        (-0.1650, 51.5150), (-0.1650, 51.5280)
    ],
    "Regent's Park": [
        (-0.1700, 51.5400), (-0.1350, 51.5400), (-0.1350, 51.5280),
        (-0.1700, 51.5280), (-0.1700, 51.5400)
    ],
    "Hyde Park": [
        (-0.1850, 51.5150), (-0.1500, 51.5150), (-0.1500, 51.4950),
        (-0.1850, 51.4950), (-0.1850, 51.5150)
    ],
    "Lancaster Gate": [
        (-0.1950, 51.5200), (-0.1750, 51.5200), (-0.1750, 51.5050),
        (-0.1950, 51.5050), (-0.1950, 51.5200)
    ],
    "Bayswater": [
        (-0.2050, 51.5200), (-0.1850, 51.5200), (-0.1850, 51.5050),
        (-0.2050, 51.5050), (-0.2050, 51.5200)
    ],
    "Maida Vale": [
        (-0.2050, 51.5400), (-0.1850, 51.5400), (-0.1850, 51.5280),
        (-0.2050, 51.5280), (-0.2050, 51.5400)
    ],
    "Little Venice": [
        (-0.1900, 51.5280), (-0.1700, 51.5280), (-0.1700, 51.5200),
        (-0.1900, 51.5200), (-0.1900, 51.5280)
    ],
    "Church Street": [
        (-0.1800, 51.5350), (-0.1600, 51.5350), (-0.1600, 51.5200),
        (-0.1800, 51.5200), (-0.1800, 51.5350)
    ],
    "Vincent Square": [
        (-0.1400, 51.4980), (-0.1200, 51.4980), (-0.1200, 51.4880),
        (-0.1400, 51.4880), (-0.1400, 51.4980)
    ],
    "Pimlico North": [
        (-0.1450, 51.4900), (-0.1200, 51.4900), (-0.1200, 51.4850),
        (-0.1450, 51.4850), (-0.1450, 51.4900)
    ],
    "Pimlico South": [
        (-0.1450, 51.4850), (-0.1100, 51.4850), (-0.1100, 51.4800),
        (-0.1450, 51.4800), (-0.1450, 51.4850)
    ],
    "Churchill": [
        (-0.1500, 51.5000), (-0.1300, 51.5000), (-0.1300, 51.4930),
        (-0.1500, 51.4930), (-0.1500, 51.5000)
    ],
    "Knightsbridge & Belgravia": [
        (-0.1850, 51.5050), (-0.1500, 51.5050), (-0.1500, 51.4900),
        (-0.1850, 51.4900), (-0.1850, 51.5050)
    ],
    "Warwick": [
        (-0.1500, 51.4950), (-0.1300, 51.4950), (-0.1300, 51.4850),
        (-0.1500, 51.4850), (-0.1500, 51.4950)
    ],
    "Fitzrovia": [
        (-0.1500, 51.5280), (-0.1250, 51.5280), (-0.1250, 51.5150),
        (-0.1500, 51.5150), (-0.1500, 51.5280)
    ],
    "Abbey Road": [
        (-0.2050, 51.5350), (-0.1800, 51.5350), (-0.1800, 51.5200),
        (-0.2050, 51.5200), (-0.2050, 51.5350)
    ],
    "Bryanston & Dorset Square": [
        (-0.1750, 51.5250), (-0.1550, 51.5250), (-0.1550, 51.5150),
        (-0.1750, 51.5150), (-0.1750, 51.5250)
    ],
    "Westbourne": [
        (-0.2050, 51.5150), (-0.1850, 51.5150), (-0.1850, 51.5000),
        (-0.2050, 51.5000), (-0.2050, 51.5150)
    ],
    "Queen's Park": [
        (-0.2050, 51.5350), (-0.1900, 51.5350), (-0.1900, 51.5250),
        (-0.2050, 51.5250), (-0.2050, 51.5350)
    ],
    "Harrow Road": [
        (-0.2050, 51.5280), (-0.1850, 51.5280), (-0.1850, 51.5200),
        (-0.2050, 51.5200), (-0.2050, 51.5280)
    ],
    "Tachbrook": [
        (-0.1400, 51.4880), (-0.1200, 51.4880), (-0.1200, 51.4800),
        (-0.1400, 51.4800), (-0.1400, 51.4880)
    ]
}

# Sample road names for each ward (representative streets)
WARD_ROADS = {
    "West End": ["Oxford Street", "Regent Street", "Bond Street", "Carnaby Street", "Wardour Street", "Dean Street", "Frith Street", "Old Compton Street", "Shaftesbury Avenue", "Charing Cross Road"],
    "St James's": ["Piccadilly", "Pall Mall", "St James's Street", "Jermyn Street", "The Mall", "Haymarket", "Whitehall", "Trafalgar Square"],
    "Marylebone High Street": ["Marylebone High Street", "George Street", "Baker Street", "Gloucester Place", "Welbeck Street", "Wigmore Street"],
    "Regent's Park": ["Park Road", "Prince Albert Road", "Outer Circle", "Albany Street", "Portland Place"],
    "Hyde Park": ["Park Lane", "Mount Street", "South Audley Street", "North Audley Street", "Grosvenor Square"],
    "Lancaster Gate": ["Lancaster Gate", "Bayswater Road", "Craven Road", "Leinster Gardens", "Westbourne Street"],
    "Bayswater": ["Queensway", "Westbourne Grove", "Porchester Road", "Moscow Road", "Inverness Terrace"],
    "Maida Vale": ["Maida Vale", "Elgin Avenue", "Sutherland Avenue", "Randolph Avenue", "Clifton Gardens"],
    "Little Venice": ["Warwick Avenue", "Clifton Road", "Formosa Street", "Blomfield Road", "Delamere Terrace"],
    "Church Street": ["Church Street", "Lisson Grove", "Bell Street", "Salisbury Street", "Frampton Street"],
    "Vincent Square": ["Vincent Square", "Rochester Row", "Greycoat Place", "Francis Street", "Artillery Row"],
    "Pimlico North": ["Belgrave Road", "St George's Drive", "Lupus Street", "Claverton Street", "Cambridge Street"],
    "Pimlico South": ["Lupus Street", "Moreton Street", "Churton Street", "Tachbrook Street", "Warwick Way"],
    "Churchill": ["Victoria Street", "Buckingham Gate", "Petty France", "Broadway", "Palace Street"],
    "Knightsbridge & Belgravia": ["Knightsbridge", "Sloane Street", "Belgrave Square", "Eaton Square", "Pont Street"],
    "Warwick": ["Vauxhall Bridge Road", "Belgrave Road", "Warwick Street", "St George's Square", "Dolphin Square"],
    "Fitzrovia": ["Charlotte Street", "Goodge Street", "Tottenham Court Road", "Cleveland Street", "Rathbone Place"],
    "Abbey Road": ["Abbey Road", "Boundary Road", "Carlton Vale", "Kilburn Park Road", "Quex Road"],
    "Bryanston & Dorset Square": ["Edgware Road", "Seymour Place", "Crawford Street", "Dorset Street", "Boston Place"],
    "Westbourne": ["Westbourne Park Road", "Great Western Road", "Harrow Road", "Westbourne Park Villas", "Porchester Gardens"],
    "Queen's Park": ["Queen's Park", "Salusbury Road", "Kilburn Lane", "Chamberlayne Road", "Harvist Road"],
    "Harrow Road": ["Harrow Road", "Shirland Road", "Ashmore Road", "Fernhead Road", "Walterton Road"],
    "Tachbrook": ["Tachbrook Street", "Charlwood Street", "Aylesford Street", "Clarendon Street", "Denbigh Street"]
}


def get_ward_for_location(lon: float, lat: float) -> str:
    """Determine which ward a location belongs to"""
    # First, try exact polygon match
    for ward_name, boundary in WESTMINSTER_WARDS.items():
        if point_in_polygon(lon, lat, boundary):
            return ward_name
    
    # If no exact match, find nearest ward by centroid
    min_dist = float('inf')
    nearest_ward = "West End"  # Default to central ward
    
    for ward_name, boundary in WESTMINSTER_WARDS.items():
        # Calculate centroid of ward
        cx = sum(p[0] for p in boundary[:-1]) / (len(boundary) - 1)
        cy = sum(p[1] for p in boundary[:-1]) / (len(boundary) - 1)
        dist = math.sqrt((lon - cx)**2 + (lat - cy)**2)
        if dist < min_dist:
            min_dist = dist
            nearest_ward = ward_name
    
    return nearest_ward


def get_road_for_cell(cell_lat: float, cell_lon: float, ward: str) -> str:
    """Assign a representative road name based on cell location within ward"""
    import random
    random.seed(int((cell_lat * 10000 + cell_lon * 10000) % 1000000))
    
    if ward in WARD_ROADS:
        roads = WARD_ROADS[ward]
        # Weight towards certain roads based on position
        return random.choice(roads)
    return "Unknown Road"


# =============================================================================
# FOOTFALL ESTIMATION FORMULAS
# =============================================================================

def estimate_people_per_hour(footfall_score: float, footfall_category: int) -> float:
    """
    Convert footfall score to estimated people per hour.
    Based on typical London pedestrian count data:
    - Peak areas (Oxford Circus): ~5000 people/hour
    - High footfall: ~2000-3000 people/hour
    - Medium footfall: ~500-1500 people/hour
    - Low footfall: ~50-300 people/hour
    """
    # Base estimation using category
    category_bases = [50, 150, 350, 700, 1200, 2000, 3500, 5000]
    base = category_bases[footfall_category]
    
    # Adjust by score within category
    variation = base * 0.3 * (footfall_score * 2 - 0.5)
    
    return max(10, base + variation)


def estimate_bin_fill_rate(people_per_hour: float, bin_capacity: int = 240) -> float:
    """
    Estimate bin fill rate as percentage per day.
    Assumptions:
    - Average waste generation: 0.02kg per person passing
    - Average waste density: 0.1kg per liter
    - Standard bin: 240L = 24kg capacity
    - Active hours: 12 hours/day
    """
    waste_per_person = 0.02  # kg
    waste_density = 0.1  # kg per liter
    active_hours = 12
    
    daily_waste_kg = people_per_hour * active_hours * waste_per_person
    daily_waste_liters = daily_waste_kg / waste_density
    
    fill_rate = (daily_waste_liters / bin_capacity) * 100
    return min(200, fill_rate)  # Cap at 200% (bins can overflow)


# =============================================================================
# GRID GENERATION
# =============================================================================

def create_grid(config: Config) -> List[GridCell]:
    """Create a regular grid covering Westminster"""
    print(f"Creating grid (resolution: {config.GRID_RESOLUTION} degrees)...")
    
    cells = []
    cell_id = 0
    
    lat = config.MIN_LAT
    while lat <= config.MAX_LAT:
        lon = config.MIN_LON
        while lon <= config.MAX_LON:
            # Check if point is roughly within Westminster (simplified boundary)
            if is_in_westminster(lat, lon):
                cells.append(GridCell(
                    cell_id=f"CELL{cell_id:05d}",
                    center_lat=lat,
                    center_lon=lon
                ))
                cell_id += 1
            lon += config.GRID_RESOLUTION
        lat += config.GRID_RESOLUTION
    
    print(f"  Created {len(cells)} grid cells")
    return cells


def is_in_westminster(lat: float, lon: float) -> bool:
    """Check if point is approximately within Westminster boundary"""
    # Simplified Westminster polygon check
    # Westminster is bounded roughly by:
    # North: ~51.54, South: ~51.48
    # West: ~-0.20, East: ~-0.11
    
    # Exclude areas that are clearly not Westminster
    if lat < 51.485 or lat > 51.535:
        return False
    if lon < -0.20 or lon > -0.11:
        return False
    
    # Simple polygon containment for Westminster shape
    westminster_boundary = [
        (-0.1634, 51.5275),
        (-0.1343, 51.5246),
        (-0.1165, 51.5180),
        (-0.1150, 51.5000),
        (-0.1240, 51.4870),
        (-0.1450, 51.4850),
        (-0.1600, 51.4867),
        (-0.1800, 51.5000),
        (-0.2000, 51.5100),
        (-0.1900, 51.5200),
        (-0.1634, 51.5275),
    ]
    
    return point_in_polygon(lon, lat, westminster_boundary)


def point_in_polygon(x: float, y: float, polygon: List[Tuple[float, float]]) -> bool:
    """Ray casting algorithm to check if point is inside polygon"""
    n = len(polygon)
    inside = False
    
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    
    return inside


# =============================================================================
# FOOTFALL SCORING
# =============================================================================

def calculate_footfall_scores(
    cells: List[GridCell],
    tubes: List[TubeStation],
    buses: List[BusStop],
    premises: List[LicensedPremises],
    config: Config
) -> List[GridCell]:
    """Calculate footfall scores for each grid cell"""
    print("Calculating footfall scores...")
    
    # Calculate individual component scores
    print("  - Tube station influence...")
    max_tube = 0
    for cell in cells:
        for tube in tubes:
            dist = Point(cell.center_lat, cell.center_lon).distance_to(
                Point(tube.lat, tube.lon)
            )
            if dist < config.TUBE_INFLUENCE_RADIUS:
                influence = tube.annual_usage * (1 - dist / config.TUBE_INFLUENCE_RADIUS) ** 2
                cell.tube_score += influence
        max_tube = max(max_tube, cell.tube_score)
    
    print("  - Bus stop influence...")
    max_bus = 0
    for cell in cells:
        for bus in buses:
            dist = Point(cell.center_lat, cell.center_lon).distance_to(
                Point(bus.lat, bus.lon)
            )
            if dist < config.BUS_INFLUENCE_RADIUS:
                influence = bus.frequency * (1 - dist / config.BUS_INFLUENCE_RADIUS)
                cell.bus_score += influence
        max_bus = max(max_bus, cell.bus_score)
    
    print("  - Licensed premises influence...")
    max_premises = 0
    for cell in cells:
        for p in premises:
            dist = Point(cell.center_lat, cell.center_lon).distance_to(
                Point(p.lat, p.lon)
            )
            if dist < config.PREMISES_INFLUENCE_RADIUS:
                influence = p.capacity * (1 - dist / config.PREMISES_INFLUENCE_RADIUS)
                cell.premises_score += influence
        max_premises = max(max_premises, cell.premises_score)
    
    # Normalize and calculate composite score
    print("  - Calculating composite scores...")
    for cell in cells:
        tube_norm = cell.tube_score / max_tube if max_tube > 0 else 0
        bus_norm = cell.bus_score / max_bus if max_bus > 0 else 0
        premises_norm = cell.premises_score / max_premises if max_premises > 0 else 0
        
        cell.footfall_score = (
            config.TUBE_WEIGHT * tube_norm +
            config.BUS_WEIGHT * bus_norm +
            config.PREMISES_WEIGHT * premises_norm
        )
    
    return cells


def categorize_cells(cells: List[GridCell], config: Config) -> List[GridCell]:
    """Assign footfall categories based on score distribution"""
    print(f"Categorizing cells into {config.N_FOOTFALL_CATEGORIES} categories...")
    
    # Sort cells by footfall score
    sorted_cells = sorted(cells, key=lambda c: c.footfall_score)
    n = len(sorted_cells)
    
    category_names = [
        "Very Low Footfall (Residential)",
        "Low Footfall",
        "Low-Medium Footfall",
        "Medium Footfall",
        "Medium-High Footfall",
        "High Footfall",
        "Very High Footfall",
        "Peak Footfall (Commercial Core)"
    ]
    
    # Assign categories based on percentile
    for i, cell in enumerate(sorted_cells):
        percentile = i / n
        category = min(int(percentile * config.N_FOOTFALL_CATEGORIES), config.N_FOOTFALL_CATEGORIES - 1)
        cell.footfall_category = category
        cell.footfall_category_name = category_names[category]
    
    # Assign wards, roads, and estimate footfall metrics
    print("  Assigning wards and estimating footfall metrics...")
    for cell in cells:
        # Assign ward
        cell.ward = get_ward_for_location(cell.center_lon, cell.center_lat)
        
        # Assign road name
        cell.road_name = get_road_for_cell(cell.center_lat, cell.center_lon, cell.ward)
        
        # Estimate people per hour
        cell.estimated_people_per_hour = estimate_people_per_hour(
            cell.footfall_score, cell.footfall_category
        )
        
        # Estimate bin fill rate
        cell.estimated_bin_fill_rate = estimate_bin_fill_rate(cell.estimated_people_per_hour)
    
    # Print statistics
    category_counts = {}
    ward_counts = {}
    for cell in cells:
        cat = cell.footfall_category
        category_counts[cat] = category_counts.get(cat, 0) + 1
        ward_counts[cell.ward] = ward_counts.get(cell.ward, 0) + 1
    
    print("\n  Category Distribution:")
    for cat in range(config.N_FOOTFALL_CATEGORIES):
        count = category_counts.get(cat, 0)
        print(f"    {category_names[cat]}: {count} cells")
    
    print("\n  Ward Distribution:")
    for ward, count in sorted(ward_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {ward}: {count} cells")
    
    return cells


# =============================================================================
# BIN SENSOR OPTIMIZATION
# =============================================================================

def load_bins_from_csv(file_path: str) -> List[BinLocation]:
    """Load bin locations from CSV file"""
    print(f"Loading bin locations from {file_path}...")
    
    bins = []
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            lat_key = next((k for k in row.keys() if k.lower() in ['lat', 'latitude']), None)
            lon_key = next((k for k in row.keys() if k.lower() in ['lon', 'longitude', 'lng']), None)
            
            if lat_key and lon_key:
                bins.append(BinLocation(
                    bin_id=row.get('bin_id', f"BIN{len(bins):05d}"),
                    lat=float(row[lat_key]),
                    lon=float(row[lon_key]),
                    bin_type=row.get('bin_type', ''),
                    capacity_liters=int(row.get('capacity_liters', 0)) if row.get('capacity_liters') else 0
                ))
    
    print(f"  Loaded {len(bins)} bin locations")
    return bins


def assign_bins_to_cells(bins: List[BinLocation], cells: List[GridCell], config: Config) -> List[BinLocation]:
    """Assign each bin to its nearest grid cell"""
    print("Assigning bins to grid cells...")
    
    cell_dict = {(c.center_lat, c.center_lon): c for c in cells}
    
    assigned = 0
    for bin_loc in bins:
        # Find nearest cell
        min_dist = float('inf')
        nearest_cell = None
        
        for cell in cells:
            dist = Point(bin_loc.lat, bin_loc.lon).distance_to(
                Point(cell.center_lat, cell.center_lon)
            )
            if dist < min_dist:
                min_dist = dist
                nearest_cell = cell
        
        if nearest_cell and min_dist < config.GRID_RESOLUTION * 2:
            bin_loc.cell_id = nearest_cell.cell_id
            bin_loc.footfall_category = nearest_cell.footfall_category
            bin_loc.footfall_score = nearest_cell.footfall_score
            bin_loc.ward = nearest_cell.ward
            bin_loc.road_name = nearest_cell.road_name
            bin_loc.estimated_people_per_hour = nearest_cell.estimated_people_per_hour
            bin_loc.estimated_bin_fill_rate = nearest_cell.estimated_bin_fill_rate
            assigned += 1
    
    print(f"  Assigned {assigned} bins to grid cells")
    return bins


def optimize_sensor_placement(
    bins: List[BinLocation],
    n_sensors: int = 1000,
    n_categories: int = 8
) -> List[BinLocation]:
    """Select optimal bin locations for sensor placement"""
    print(f"\nOptimizing placement of {n_sensors} sensors...")
    
    # Filter bins that have been assigned to cells
    assigned_bins = [b for b in bins if b.cell_id]
    
    if len(assigned_bins) < n_sensors:
        print(f"  Warning: Only {len(assigned_bins)} bins available, selecting all")
        for i, b in enumerate(assigned_bins):
            b.selected_for_sensor = True
            b.selection_rank = i + 1
        return assigned_bins
    
    # Count bins per category
    category_counts = {}
    for b in assigned_bins:
        cat = b.footfall_category
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    # Calculate target distribution (sqrt-proportional for balanced coverage)
    import math
    total_sqrt = sum(math.sqrt(c) for c in category_counts.values())
    target_per_category = {}
    
    for cat, count in category_counts.items():
        target = int(n_sensors * math.sqrt(count) / total_sqrt)
        target = max(target, min(20, count))  # At least 20 or all available
        target_per_category[cat] = min(target, count)
    
    # Adjust to match total
    current_total = sum(target_per_category.values())
    while current_total < n_sensors:
        for cat in sorted(target_per_category.keys()):
            if target_per_category[cat] < category_counts[cat]:
                target_per_category[cat] += 1
                current_total += 1
                if current_total >= n_sensors:
                    break
    
    print("\n  Target distribution by category:")
    for cat in sorted(target_per_category.keys()):
        print(f"    Category {cat}: {target_per_category[cat]} sensors")
    
    # Select bins with spatial diversity within each category
    selected = []
    rank = 1
    
    for cat in sorted(target_per_category.keys()):
        target = target_per_category[cat]
        cat_bins = [b for b in assigned_bins if b.footfall_category == cat]
        
        # Sort by location to spread them out spatially
        cat_bins.sort(key=lambda b: (b.lat, b.lon))
        
        # Select evenly spaced bins
        step = max(1, len(cat_bins) // target)
        selected_indices = []
        for i in range(0, len(cat_bins), step):
            if len(selected_indices) < target:
                selected_indices.append(i)
        
        for idx in selected_indices:
            cat_bins[idx].selected_for_sensor = True
            cat_bins[idx].selection_rank = rank
            selected.append(cat_bins[idx])
            rank += 1
    
    print(f"\n  Total sensors selected: {len(selected)}")
    return selected


# =============================================================================
# OUTPUT GENERATION
# =============================================================================

def save_grid_csv(cells: List[GridCell], output_path: str):
    """Save grid cells to CSV"""
    fieldnames = ['cell_id', 'center_lat', 'center_lon', 'tube_score', 'bus_score',
                  'premises_score', 'footfall_score', 'footfall_category', 'footfall_category_name',
                  'ward', 'road_name', 'locality', 'estimated_people_per_hour', 'estimated_bin_fill_rate']
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for cell in cells:
            writer.writerow(asdict(cell))
    
    print(f"  Saved grid data to {output_path}")


def save_selected_bins_csv(bins: List[BinLocation], output_path: str):
    """Save selected bin locations to CSV"""
    selected = [b for b in bins if b.selected_for_sensor]
    
    fieldnames = ['selection_rank', 'bin_id', 'lat', 'lon', 'bin_type', 'capacity_liters',
                  'cell_id', 'footfall_category', 'footfall_score', 'ward', 'road_name',
                  'estimated_people_per_hour', 'estimated_bin_fill_rate']
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for b in sorted(selected, key=lambda x: x.selection_rank):
            writer.writerow({
                'selection_rank': b.selection_rank,
                'bin_id': b.bin_id,
                'lat': b.lat,
                'lon': b.lon,
                'bin_type': b.bin_type,
                'capacity_liters': b.capacity_liters,
                'cell_id': b.cell_id,
                'footfall_category': b.footfall_category,
                'footfall_score': b.footfall_score,
                'ward': b.ward,
                'road_name': b.road_name,
                'estimated_people_per_hour': b.estimated_people_per_hour,
                'estimated_bin_fill_rate': b.estimated_bin_fill_rate
            })
    
    print(f"  Saved {len(selected)} recommended sensor locations to {output_path}")


def save_geojson(cells: List[GridCell], output_path: str, config: Config):
    """Save grid as GeoJSON for visualization"""
    features = []
    
    half_size = config.GRID_RESOLUTION / 2
    
    for cell in cells:
        # Create square polygon for each cell
        coords = [
            [cell.center_lon - half_size, cell.center_lat - half_size],
            [cell.center_lon + half_size, cell.center_lat - half_size],
            [cell.center_lon + half_size, cell.center_lat + half_size],
            [cell.center_lon - half_size, cell.center_lat + half_size],
            [cell.center_lon - half_size, cell.center_lat - half_size],
        ]
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            },
            "properties": {
                "cell_id": cell.cell_id,
                "footfall_score": round(cell.footfall_score, 4),
                "footfall_category": cell.footfall_category,
                "footfall_category_name": cell.footfall_category_name,
                "tube_score": round(cell.tube_score, 2),
                "bus_score": round(cell.bus_score, 2),
                "premises_score": round(cell.premises_score, 2)
            }
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(output_path, 'w') as f:
        json.dump(geojson, f)
    
    print(f"  Saved GeoJSON to {output_path}")


def generate_sample_bins(n_bins: int = 3000, output_path: str = "data/sample_bins.csv"):
    """Generate sample bin locations for testing"""
    import random
    random.seed(44)
    
    print(f"Generating {n_bins} sample bin locations...")
    
    Path(output_path).parent.mkdir(exist_ok=True)
    
    bins = []
    for i in range(n_bins):
        lat = random.uniform(51.485, 51.535)
        lon = random.uniform(-0.20, -0.11)
        
        # Cluster some around high footfall areas
        if i < n_bins // 3:
            hotspots = [(51.5154, -0.1418), (51.4965, -0.1447), (51.5117, -0.1240)]
            hotspot = random.choice(hotspots)
            lat = hotspot[0] + random.gauss(0, 0.003)
            lon = hotspot[1] + random.gauss(0, 0.003)
        
        bins.append({
            'bin_id': f'BIN{i:05d}',
            'lat': lat,
            'lon': lon,
            'bin_type': random.choice(['General Waste', 'Recycling', 'Food Waste']),
            'capacity_liters': random.choice([120, 240, 360, 1100])
        })
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['bin_id', 'lat', 'lon', 'bin_type', 'capacity_liters'])
        writer.writeheader()
        writer.writerows(bins)
    
    print(f"  Saved to {output_path}")
    return output_path


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def run_analysis(config: Config = None, bin_file: str = None, n_sensors: int = 1000):
    """Run the complete analysis"""
    if config is None:
        config = Config()
    
    # Create output directory
    Path(config.OUTPUT_DIR).mkdir(exist_ok=True)
    
    print("=" * 70)
    print("WESTMINSTER FOOTFALL ANALYSIS FOR BIN SENSOR PLACEMENT")
    print("(Simplified Version)")
    print("=" * 70)
    print()
    
    # Load data
    print("STEP 1: Loading Data")
    print("-" * 40)
    tubes = load_tube_stations()
    print(f"  Loaded {len(tubes)} tube stations")
    
    buses = load_bus_stops(config)
    print(f"  Loaded {len(buses)} bus stops")
    
    premises = load_licensed_premises()
    print(f"  Loaded {len(premises)} licensed premises")
    print()
    
    # Create grid
    print("STEP 2: Creating Grid")
    print("-" * 40)
    cells = create_grid(config)
    print()
    
    # Calculate footfall scores
    print("STEP 3: Calculating Footfall Scores")
    print("-" * 40)
    cells = calculate_footfall_scores(cells, tubes, buses, premises, config)
    print()
    
    # Categorize cells
    print("STEP 4: Categorizing Footfall Zones")
    print("-" * 40)
    cells = categorize_cells(cells, config)
    print()
    
    # Save results
    print("STEP 5: Saving Analysis Results")
    print("-" * 40)
    save_grid_csv(cells, f"{config.OUTPUT_DIR}/westminster_footfall_grid.csv")
    save_geojson(cells, f"{config.OUTPUT_DIR}/westminster_footfall_grid.geojson", config)
    print()
    
    # Optimize bin sensors if bin file provided
    if bin_file:
        print("STEP 6: Optimizing Bin Sensor Placement")
        print("-" * 40)
        bins = load_bins_from_csv(bin_file)
        bins = assign_bins_to_cells(bins, cells, config)
        selected = optimize_sensor_placement(bins, n_sensors, config.N_FOOTFALL_CATEGORIES)
        save_selected_bins_csv(bins, f"{config.OUTPUT_DIR}/recommended_sensor_locations.csv")
        print()
    
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"\nOutputs saved to: {Path(config.OUTPUT_DIR).absolute()}")
    
    return cells


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Westminster Footfall Analysis (Simplified Version)'
    )
    parser.add_argument(
        '--bins', '-b',
        type=str,
        help='Path to bin locations CSV file'
    )
    parser.add_argument(
        '--n-sensors', '-n',
        type=int,
        default=1000,
        help='Number of sensors to place (default: 1000)'
    )
    parser.add_argument(
        '--generate-sample',
        action='store_true',
        help='Generate sample bin locations for testing'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        default='output',
        help='Output directory (default: output)'
    )
    parser.add_argument(
        '--resolution', '-r',
        type=float,
        default=0.001,
        help='Grid resolution in degrees (default: 0.001 ≈ 100m)'
    )
    
    args = parser.parse_args()
    
    # Create config
    config = Config()
    config.OUTPUT_DIR = args.output_dir
    config.GRID_RESOLUTION = args.resolution
    
    # Generate sample bins if requested
    if args.generate_sample:
        Path("data").mkdir(exist_ok=True)
        args.bins = generate_sample_bins()
    
    # Run analysis
    run_analysis(config, args.bins, args.n_sensors)

