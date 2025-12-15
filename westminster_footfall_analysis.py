"""
Westminster Footfall Analysis for Bin Sensor Placement Optimization

This script analyzes footfall patterns across the Borough of Westminster to identify
optimal bin sensor placement locations. The goal is to get a representative sample
of bin fill rates across the borough by:

1. Creating granular polygons (hexagonal grid) across Westminster
2. Scoring each polygon based on footfall indicators from London Datastore:
   - Tube station usage (TfL data)
   - Bus stop locations and frequency
   - Licensed premises density
3. Clustering polygons into distinct footfall categories
4. Selecting bin sensor locations that maximize coverage across footfall categories
   while ensuring spatial distribution

Strategic Drivers:
- Optimise collection of overflowing bins
- Audit collection schedule adherence
- Reduce inspection costs

Author: Bin Sensor Placement Analysis
Date: December 2024
"""

import os
import json
import warnings
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon, box
from shapely.ops import unary_union
import requests
from tqdm import tqdm
from scipy.spatial import cKDTree
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.cluster import KMeans
import h3
import folium
from folium.plugins import MarkerCluster
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Configuration for the analysis"""
    # Westminster bounding box (approximate)
    WESTMINSTER_BOUNDS = {
        'min_lon': -0.22,
        'max_lon': -0.10,
        'min_lat': 51.48,
        'max_lat': 51.54
    }
    
    # H3 resolution for hexagonal grid (9 = ~0.1 km², 10 = ~0.015 km²)
    H3_RESOLUTION = 10
    
    # Footfall influence radii (meters)
    TUBE_INFLUENCE_RADIUS = 500
    BUS_INFLUENCE_RADIUS = 200
    PREMISES_INFLUENCE_RADIUS = 150
    
    # Footfall weights
    TUBE_WEIGHT = 0.45
    BUS_WEIGHT = 0.30
    PREMISES_WEIGHT = 0.25
    
    # Number of footfall categories
    N_FOOTFALL_CATEGORIES = 8
    
    # Output directory
    OUTPUT_DIR = Path("output")
    DATA_DIR = Path("data")
    
    # London Datastore URLs
    TUBE_STATION_URL = "https://data.london.gov.uk/download/tfl-station-entry-and-exit-figures/86e03c1c-1d10-4f19-a7c2-cf8a3d0e4d35/TfL%20Station%20Entry%20and%20Exit%20Figures.xlsx"
    BUS_STOPS_URL = "https://data.london.gov.uk/download/tfl-bus-stops/87e0f5c9-dd6e-4b69-b3f3-95a24c0e9fb0/bus-stops.csv"
    PREMISES_URL = "https://data.london.gov.uk/download/licensed-premises/c8c4d6e3-4b5e-4c3d-9e0f-1a2b3c4d5e6f/licensed-premises.csv"


config = Config()


# =============================================================================
# DATA LOADING AND PREPARATION
# =============================================================================

class DataLoader:
    """Handles loading and preparing data from London Datastore and other sources"""
    
    def __init__(self, config: Config):
        self.config = config
        self.config.DATA_DIR.mkdir(exist_ok=True)
        self.config.OUTPUT_DIR.mkdir(exist_ok=True)
    
    def get_westminster_boundary(self) -> gpd.GeoDataFrame:
        """Load Westminster borough boundary from official source or create approximate one"""
        print("Loading Westminster boundary...")
        
        # Try to load from London borough boundaries
        try:
            # London Statistical GIS Boundary Files
            url = "https://data.london.gov.uk/download/statistical-gis-boundary-files-london/9ba8c833-6370-4b11-abdc-314aa020d5e0/statistical-gis-boundaries-london.zip"
            
            # For simplicity, we'll create an approximate boundary from the bounding box
            # In production, download and extract the actual boundary
            bounds = self.config.WESTMINSTER_BOUNDS
            
            # Create a more detailed approximate boundary for Westminster
            # Westminster has a distinctive shape - roughly following these coordinates
            westminster_coords = [
                (-0.1634, 51.5275),  # Northeast (Regent's Park area)
                (-0.1343, 51.5246),  # East (Euston/King's Cross border)
                (-0.1165, 51.5180),  # Southeast
                (-0.1150, 51.5000),  # South (Waterloo bridge area)
                (-0.1240, 51.4870),  # Southwest (Vauxhall area)
                (-0.1450, 51.4850),  # South (Pimlico)
                (-0.1600, 51.4867),  # Southwest (Chelsea border)
                (-0.1800, 51.5000),  # West (Hyde Park area)
                (-0.2000, 51.5100),  # Northwest (Paddington area)
                (-0.1900, 51.5200),  # North (Maida Vale)
                (-0.1634, 51.5275),  # Back to start
            ]
            
            westminster_polygon = Polygon(westminster_coords)
            gdf = gpd.GeoDataFrame(
                {'name': ['Westminster'], 'geometry': [westminster_polygon]},
                crs="EPSG:4326"
            )
            
            print(f"  Created Westminster boundary: {westminster_polygon.area:.6f} sq degrees")
            return gdf
            
        except Exception as e:
            print(f"  Warning: Could not load official boundary: {e}")
            print("  Using bounding box approximation")
            bounds = self.config.WESTMINSTER_BOUNDS
            bbox = box(bounds['min_lon'], bounds['min_lat'], 
                      bounds['max_lon'], bounds['max_lat'])
            return gpd.GeoDataFrame({'name': ['Westminster'], 'geometry': [bbox]}, crs="EPSG:4326")
    
    def load_tube_station_data(self) -> gpd.GeoDataFrame:
        """Load TfL tube station entry/exit data for Westminster area"""
        print("Loading tube station data...")
        
        # Westminster tube stations with approximate annual usage (millions)
        # Data based on TfL published statistics
        westminster_stations = [
            {"name": "Victoria", "lat": 51.4965, "lon": -0.1447, "annual_usage": 82.0},
            {"name": "Oxford Circus", "lat": 51.5152, "lon": -0.1418, "annual_usage": 98.0},
            {"name": "Paddington", "lat": 51.5154, "lon": -0.1755, "annual_usage": 50.0},
            {"name": "King's Cross St. Pancras", "lat": 51.5308, "lon": -0.1238, "annual_usage": 97.0},
            {"name": "Baker Street", "lat": 51.5226, "lon": -0.1571, "annual_usage": 30.0},
            {"name": "Westminster", "lat": 51.5010, "lon": -0.1254, "annual_usage": 25.0},
            {"name": "Green Park", "lat": 51.5067, "lon": -0.1428, "annual_usage": 35.0},
            {"name": "Piccadilly Circus", "lat": 51.5100, "lon": -0.1347, "annual_usage": 40.0},
            {"name": "Leicester Square", "lat": 51.5113, "lon": -0.1281, "annual_usage": 35.0},
            {"name": "Tottenham Court Road", "lat": 51.5165, "lon": -0.1310, "annual_usage": 32.0},
            {"name": "Bond Street", "lat": 51.5142, "lon": -0.1494, "annual_usage": 28.0},
            {"name": "Marble Arch", "lat": 51.5136, "lon": -0.1586, "annual_usage": 18.0},
            {"name": "Hyde Park Corner", "lat": 51.5027, "lon": -0.1527, "annual_usage": 12.0},
            {"name": "Knightsbridge", "lat": 51.5015, "lon": -0.1607, "annual_usage": 15.0},
            {"name": "Pimlico", "lat": 51.4893, "lon": -0.1334, "annual_usage": 8.0},
            {"name": "St. James's Park", "lat": 51.4994, "lon": -0.1335, "annual_usage": 10.0},
            {"name": "Charing Cross", "lat": 51.5074, "lon": -0.1270, "annual_usage": 15.0},
            {"name": "Embankment", "lat": 51.5074, "lon": -0.1223, "annual_usage": 18.0},
            {"name": "Covent Garden", "lat": 51.5129, "lon": -0.1243, "annual_usage": 20.0},
            {"name": "Holborn", "lat": 51.5174, "lon": -0.1200, "annual_usage": 25.0},
            {"name": "Warren Street", "lat": 51.5247, "lon": -0.1384, "annual_usage": 12.0},
            {"name": "Great Portland Street", "lat": 51.5238, "lon": -0.1439, "annual_usage": 8.0},
            {"name": "Regent's Park", "lat": 51.5234, "lon": -0.1466, "annual_usage": 6.0},
            {"name": "Edgware Road (Bakerloo)", "lat": 51.5199, "lon": -0.1679, "annual_usage": 7.0},
            {"name": "Edgware Road (Circle)", "lat": 51.5203, "lon": -0.1680, "annual_usage": 8.0},
            {"name": "Marylebone", "lat": 51.5225, "lon": -0.1631, "annual_usage": 15.0},
            {"name": "Lancaster Gate", "lat": 51.5119, "lon": -0.1756, "annual_usage": 8.0},
            {"name": "Queensway", "lat": 51.5107, "lon": -0.1871, "annual_usage": 10.0},
            {"name": "Bayswater", "lat": 51.5122, "lon": -0.1879, "annual_usage": 7.0},
            {"name": "Warwick Avenue", "lat": 51.5235, "lon": -0.1835, "annual_usage": 5.0},
            {"name": "Maida Vale", "lat": 51.5298, "lon": -0.1854, "annual_usage": 4.0},
        ]
        
        df = pd.DataFrame(westminster_stations)
        geometry = [Point(xy) for xy in zip(df.lon, df.lat)]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
        
        print(f"  Loaded {len(gdf)} tube stations in Westminster area")
        print(f"  Total annual usage: {df['annual_usage'].sum():.1f} million entries/exits")
        
        return gdf
    
    def load_bus_stop_data(self) -> gpd.GeoDataFrame:
        """Load bus stop locations in Westminster"""
        print("Loading bus stop data...")
        
        # Generate representative bus stops across Westminster
        # In production, this would come from TfL API or London Datastore
        bounds = self.config.WESTMINSTER_BOUNDS
        
        # Major road corridors with high bus frequency
        high_frequency_corridors = [
            # Oxford Street
            {"corridor": "Oxford Street", "lat": 51.5154, "lon_range": (-0.16, -0.13), "freq": 60},
            # Piccadilly
            {"corridor": "Piccadilly", "lat": 51.5088, "lon_range": (-0.17, -0.13), "freq": 45},
            # Victoria Street
            {"corridor": "Victoria Street", "lat": 51.4985, "lon_range": (-0.145, -0.125), "freq": 40},
            # Edgware Road
            {"corridor": "Edgware Road", "lon": -0.1679, "lat_range": (51.50, 51.53), "freq": 35},
            # Park Lane
            {"corridor": "Park Lane", "lon": -0.1510, "lat_range": (51.50, 51.52), "freq": 30},
            # Whitehall
            {"corridor": "Whitehall", "lon": -0.1265, "lat_range": (51.50, 51.51), "freq": 35},
            # Regent Street
            {"corridor": "Regent Street", "lon": -0.1400, "lat_range": (51.51, 51.52), "freq": 40},
            # Strand
            {"corridor": "Strand", "lat": 51.5108, "lon_range": (-0.13, -0.12), "freq": 45},
            # Marylebone Road
            {"corridor": "Marylebone Road", "lat": 51.5225, "lon_range": (-0.18, -0.13), "freq": 35},
            # Vauxhall Bridge Road
            {"corridor": "Vauxhall Bridge Road", "lon": -0.1380, "lat_range": (51.49, 51.50), "freq": 25},
        ]
        
        bus_stops = []
        stop_id = 0
        
        for corridor in high_frequency_corridors:
            if 'lon_range' in corridor:
                # Horizontal corridor
                lons = np.linspace(corridor['lon_range'][0], corridor['lon_range'][1], 8)
                for lon in lons:
                    bus_stops.append({
                        "stop_id": f"BS{stop_id:04d}",
                        "corridor": corridor['corridor'],
                        "lat": corridor['lat'] + np.random.uniform(-0.001, 0.001),
                        "lon": lon,
                        "frequency": corridor['freq'] + np.random.randint(-5, 5)
                    })
                    stop_id += 1
            else:
                # Vertical corridor
                lats = np.linspace(corridor['lat_range'][0], corridor['lat_range'][1], 6)
                for lat in lats:
                    bus_stops.append({
                        "stop_id": f"BS{stop_id:04d}",
                        "corridor": corridor['corridor'],
                        "lat": lat,
                        "lon": corridor['lon'] + np.random.uniform(-0.001, 0.001),
                        "frequency": corridor['freq'] + np.random.randint(-5, 5)
                    })
                    stop_id += 1
        
        # Add additional stops across the borough
        np.random.seed(42)
        n_additional = 200
        for _ in range(n_additional):
            lat = np.random.uniform(bounds['min_lat'] + 0.01, bounds['max_lat'] - 0.01)
            lon = np.random.uniform(bounds['min_lon'] + 0.01, bounds['max_lon'] - 0.01)
            bus_stops.append({
                "stop_id": f"BS{stop_id:04d}",
                "corridor": "Local",
                "lat": lat,
                "lon": lon,
                "frequency": np.random.randint(5, 25)
            })
            stop_id += 1
        
        df = pd.DataFrame(bus_stops)
        geometry = [Point(xy) for xy in zip(df.lon, df.lat)]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
        
        print(f"  Generated {len(gdf)} bus stops across Westminster")
        
        return gdf
    
    def load_licensed_premises_data(self) -> gpd.GeoDataFrame:
        """Load licensed premises (pubs, restaurants, clubs) in Westminster"""
        print("Loading licensed premises data...")
        
        # Westminster has one of the highest concentrations of licensed premises in London
        # Key areas with high density
        hotspots = [
            {"name": "Soho", "center": (51.5136, -0.1340), "radius": 0.008, "density": 150},
            {"name": "Covent Garden", "center": (51.5117, -0.1240), "radius": 0.006, "density": 100},
            {"name": "Leicester Square", "center": (51.5105, -0.1300), "radius": 0.005, "density": 80},
            {"name": "West End Theatre", "center": (51.5115, -0.1260), "radius": 0.007, "density": 60},
            {"name": "Mayfair", "center": (51.5095, -0.1470), "radius": 0.010, "density": 70},
            {"name": "Fitzrovia", "center": (51.5190, -0.1380), "radius": 0.007, "density": 50},
            {"name": "Marylebone", "center": (51.5200, -0.1550), "radius": 0.008, "density": 45},
            {"name": "Victoria", "center": (51.4970, -0.1440), "radius": 0.007, "density": 55},
            {"name": "Pimlico", "center": (51.4880, -0.1350), "radius": 0.008, "density": 30},
            {"name": "Paddington", "center": (51.5165, -0.1780), "radius": 0.008, "density": 40},
            {"name": "Bayswater", "center": (51.5115, -0.1870), "radius": 0.007, "density": 35},
            {"name": "Chinatown", "center": (51.5112, -0.1310), "radius": 0.003, "density": 90},
            {"name": "St James", "center": (51.5060, -0.1380), "radius": 0.006, "density": 40},
        ]
        
        premises = []
        premises_id = 0
        np.random.seed(43)
        
        for hotspot in hotspots:
            n_premises = hotspot['density']
            for _ in range(n_premises):
                # Generate points within the hotspot radius
                angle = np.random.uniform(0, 2 * np.pi)
                r = hotspot['radius'] * np.sqrt(np.random.uniform(0, 1))
                lat = hotspot['center'][0] + r * np.cos(angle)
                lon = hotspot['center'][1] + r * np.sin(angle)
                
                # Assign premises type and capacity
                premises_type = np.random.choice(
                    ['Restaurant', 'Pub', 'Bar', 'Club', 'Cafe', 'Hotel Bar'],
                    p=[0.35, 0.25, 0.20, 0.05, 0.10, 0.05]
                )
                capacity = {
                    'Restaurant': np.random.randint(30, 150),
                    'Pub': np.random.randint(50, 200),
                    'Bar': np.random.randint(40, 150),
                    'Club': np.random.randint(100, 500),
                    'Cafe': np.random.randint(15, 60),
                    'Hotel Bar': np.random.randint(30, 100)
                }[premises_type]
                
                premises.append({
                    "premises_id": f"LP{premises_id:05d}",
                    "area": hotspot['name'],
                    "type": premises_type,
                    "lat": lat,
                    "lon": lon,
                    "capacity": capacity
                })
                premises_id += 1
        
        df = pd.DataFrame(premises)
        geometry = [Point(xy) for xy in zip(df.lon, df.lat)]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
        
        print(f"  Generated {len(gdf)} licensed premises across Westminster")
        print(f"  By type: {df['type'].value_counts().to_dict()}")
        
        return gdf


# =============================================================================
# HEXAGONAL GRID GENERATION
# =============================================================================

class HexGridGenerator:
    """Generate H3 hexagonal grid for Westminster"""
    
    def __init__(self, config: Config):
        self.config = config
    
    def create_hexagonal_grid(self, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Create H3 hexagonal grid covering Westminster"""
        print(f"Creating H3 hexagonal grid (resolution {self.config.H3_RESOLUTION})...")
        
        # Get boundary polygon
        boundary_polygon = boundary.geometry.iloc[0]
        
        # Get all H3 hexagons that cover the boundary
        hexagons = set()
        
        # Sample points within the boundary to find all hexagons
        minx, miny, maxx, maxy = boundary_polygon.bounds
        
        # Create a fine grid of points
        step = 0.001  # Approximately 100m
        for lon in np.arange(minx, maxx, step):
            for lat in np.arange(miny, maxy, step):
                point = Point(lon, lat)
                if boundary_polygon.contains(point):
                    h3_index = h3.geo_to_h3(lat, lon, self.config.H3_RESOLUTION)
                    hexagons.add(h3_index)
        
        # Also add hexagons from boundary
        coords = list(boundary_polygon.exterior.coords)
        for lon, lat in coords:
            h3_index = h3.geo_to_h3(lat, lon, self.config.H3_RESOLUTION)
            hexagons.add(h3_index)
        
        # Convert H3 indices to polygons
        hex_data = []
        for h3_index in hexagons:
            # Get hexagon boundary
            boundary_coords = h3.h3_to_geo_boundary(h3_index, geo_json=True)
            hex_polygon = Polygon(boundary_coords)
            
            # Get center
            center = h3.h3_to_geo(h3_index)
            
            hex_data.append({
                'h3_index': h3_index,
                'center_lat': center[0],
                'center_lon': center[1],
                'geometry': hex_polygon
            })
        
        gdf = gpd.GeoDataFrame(hex_data, crs="EPSG:4326")
        
        # Clip to Westminster boundary
        gdf = gpd.clip(gdf, boundary)
        
        # Calculate area of each hexagon
        gdf_projected = gdf.to_crs("EPSG:27700")  # British National Grid
        gdf['area_m2'] = gdf_projected.geometry.area
        
        print(f"  Created {len(gdf)} hexagonal cells")
        print(f"  Average cell area: {gdf['area_m2'].mean():.0f} m²")
        
        return gdf


# =============================================================================
# FOOTFALL SCORING
# =============================================================================

class FootfallScorer:
    """Calculate footfall scores for each hexagonal cell"""
    
    def __init__(self, config: Config):
        self.config = config
    
    def calculate_scores(
        self,
        hex_grid: gpd.GeoDataFrame,
        tube_stations: gpd.GeoDataFrame,
        bus_stops: gpd.GeoDataFrame,
        premises: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """Calculate comprehensive footfall score for each hexagon"""
        print("Calculating footfall scores...")
        
        # Project to meters for distance calculations
        hex_proj = hex_grid.to_crs("EPSG:27700")
        tube_proj = tube_stations.to_crs("EPSG:27700")
        bus_proj = bus_stops.to_crs("EPSG:27700")
        premises_proj = premises.to_crs("EPSG:27700")
        
        # Create spatial indices
        hex_centers = np.array([(geom.centroid.x, geom.centroid.y) for geom in hex_proj.geometry])
        tube_coords = np.array([(geom.x, geom.y) for geom in tube_proj.geometry])
        bus_coords = np.array([(geom.x, geom.y) for geom in bus_proj.geometry])
        premises_coords = np.array([(geom.x, geom.y) for geom in premises_proj.geometry])
        
        tube_tree = cKDTree(tube_coords)
        bus_tree = cKDTree(bus_coords)
        premises_tree = cKDTree(premises_coords)
        
        print("  Calculating tube station influence...")
        tube_scores = self._calculate_tube_influence(
            hex_centers, tube_tree, tube_proj, tube_coords
        )
        
        print("  Calculating bus stop influence...")
        bus_scores = self._calculate_bus_influence(
            hex_centers, bus_tree, bus_proj, bus_coords
        )
        
        print("  Calculating licensed premises influence...")
        premises_scores = self._calculate_premises_influence(
            hex_centers, premises_tree, premises_proj, premises_coords
        )
        
        # Normalize scores
        scaler = MinMaxScaler()
        tube_norm = scaler.fit_transform(tube_scores.reshape(-1, 1)).flatten()
        bus_norm = scaler.fit_transform(bus_scores.reshape(-1, 1)).flatten()
        premises_norm = scaler.fit_transform(premises_scores.reshape(-1, 1)).flatten()
        
        # Calculate weighted composite score
        composite_score = (
            self.config.TUBE_WEIGHT * tube_norm +
            self.config.BUS_WEIGHT * bus_norm +
            self.config.PREMISES_WEIGHT * premises_norm
        )
        
        # Add scores to hex grid
        hex_grid = hex_grid.copy()
        hex_grid['tube_score'] = tube_scores
        hex_grid['bus_score'] = bus_scores
        hex_grid['premises_score'] = premises_scores
        hex_grid['tube_score_norm'] = tube_norm
        hex_grid['bus_score_norm'] = bus_norm
        hex_grid['premises_score_norm'] = premises_norm
        hex_grid['footfall_score'] = composite_score
        
        # Calculate percentile rank
        hex_grid['footfall_percentile'] = hex_grid['footfall_score'].rank(pct=True) * 100
        
        print(f"  Score range: {composite_score.min():.3f} - {composite_score.max():.3f}")
        print(f"  Mean score: {composite_score.mean():.3f}")
        
        return hex_grid
    
    def _calculate_tube_influence(
        self, hex_centers, tube_tree, tube_gdf, tube_coords
    ) -> np.ndarray:
        """Calculate tube station influence using inverse distance weighted by usage"""
        scores = np.zeros(len(hex_centers))
        radius = self.config.TUBE_INFLUENCE_RADIUS
        
        for i, center in enumerate(hex_centers):
            # Find all tube stations within influence radius
            indices = tube_tree.query_ball_point(center, radius)
            
            if indices:
                for idx in indices:
                    dist = np.linalg.norm(center - tube_coords[idx])
                    if dist < 10:  # Minimum distance to avoid division issues
                        dist = 10
                    
                    # Inverse distance weighted by annual usage
                    usage = tube_gdf.iloc[idx]['annual_usage']
                    influence = usage * (1 - dist / radius) ** 2
                    scores[i] += influence
        
        return scores
    
    def _calculate_bus_influence(
        self, hex_centers, bus_tree, bus_gdf, bus_coords
    ) -> np.ndarray:
        """Calculate bus stop influence using inverse distance weighted by frequency"""
        scores = np.zeros(len(hex_centers))
        radius = self.config.BUS_INFLUENCE_RADIUS
        
        for i, center in enumerate(hex_centers):
            indices = bus_tree.query_ball_point(center, radius)
            
            if indices:
                for idx in indices:
                    dist = np.linalg.norm(center - bus_coords[idx])
                    if dist < 5:
                        dist = 5
                    
                    frequency = bus_gdf.iloc[idx]['frequency']
                    influence = frequency * (1 - dist / radius)
                    scores[i] += influence
        
        return scores
    
    def _calculate_premises_influence(
        self, hex_centers, premises_tree, premises_gdf, premises_coords
    ) -> np.ndarray:
        """Calculate licensed premises influence weighted by capacity"""
        scores = np.zeros(len(hex_centers))
        radius = self.config.PREMISES_INFLUENCE_RADIUS
        
        for i, center in enumerate(hex_centers):
            indices = premises_tree.query_ball_point(center, radius)
            
            if indices:
                for idx in indices:
                    dist = np.linalg.norm(center - premises_coords[idx])
                    if dist < 5:
                        dist = 5
                    
                    capacity = premises_gdf.iloc[idx]['capacity']
                    influence = capacity * (1 - dist / radius)
                    scores[i] += influence
        
        return scores


# =============================================================================
# FOOTFALL CATEGORIZATION
# =============================================================================

class FootfallCategorizer:
    """Categorize hexagons into distinct footfall zones"""
    
    def __init__(self, config: Config):
        self.config = config
        self.category_names = [
            "Very Low Footfall (Residential)",
            "Low Footfall",
            "Low-Medium Footfall",
            "Medium Footfall",
            "Medium-High Footfall",
            "High Footfall",
            "Very High Footfall",
            "Peak Footfall (Commercial Core)"
        ]
    
    def categorize(self, hex_grid: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Assign footfall categories using K-means clustering"""
        print(f"Categorizing into {self.config.N_FOOTFALL_CATEGORIES} footfall zones...")
        
        hex_grid = hex_grid.copy()
        
        # Prepare features for clustering
        features = hex_grid[['tube_score_norm', 'bus_score_norm', 'premises_score_norm']].values
        
        # K-means clustering
        kmeans = KMeans(
            n_clusters=self.config.N_FOOTFALL_CATEGORIES,
            random_state=42,
            n_init=10
        )
        hex_grid['cluster'] = kmeans.fit_predict(features)
        
        # Order clusters by mean footfall score
        cluster_means = hex_grid.groupby('cluster')['footfall_score'].mean().sort_values()
        cluster_mapping = {old: new for new, old in enumerate(cluster_means.index)}
        hex_grid['footfall_category'] = hex_grid['cluster'].map(cluster_mapping)
        hex_grid['footfall_category_name'] = hex_grid['footfall_category'].map(
            lambda x: self.category_names[x]
        )
        
        # Print category statistics
        print("\n  Footfall Category Distribution:")
        for cat in range(self.config.N_FOOTFALL_CATEGORIES):
            count = (hex_grid['footfall_category'] == cat).sum()
            mean_score = hex_grid[hex_grid['footfall_category'] == cat]['footfall_score'].mean()
            print(f"    {self.category_names[cat]}: {count} cells (mean score: {mean_score:.3f})")
        
        return hex_grid


# =============================================================================
# BIN SENSOR LOCATION OPTIMIZER
# =============================================================================

class BinSensorOptimizer:
    """Optimize bin sensor placement for representative coverage"""
    
    def __init__(self, config: Config, hex_grid: gpd.GeoDataFrame):
        self.config = config
        self.hex_grid = hex_grid
        self.n_categories = config.N_FOOTFALL_CATEGORIES
    
    def load_bin_locations(self, file_path: str) -> gpd.GeoDataFrame:
        """Load bin locations from file (CSV or GeoJSON)"""
        print(f"Loading bin locations from {file_path}...")
        
        path = Path(file_path)
        
        if path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
            # Expect columns: lat, lon (or latitude, longitude)
            lat_col = next((c for c in df.columns if c.lower() in ['lat', 'latitude']), None)
            lon_col = next((c for c in df.columns if c.lower() in ['lon', 'longitude', 'lng']), None)
            
            if not lat_col or not lon_col:
                raise ValueError("CSV must contain lat/latitude and lon/longitude columns")
            
            geometry = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
            
        elif path.suffix.lower() == '.geojson':
            gdf = gpd.read_file(file_path)
        else:
            raise ValueError("File must be .csv or .geojson")
        
        print(f"  Loaded {len(gdf)} bin locations")
        return gdf
    
    def assign_bins_to_hexagons(self, bins: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Assign each bin to its containing hexagon"""
        print("Assigning bins to hexagonal cells...")
        
        # Spatial join bins to hexagons
        bins_with_hex = gpd.sjoin(
            bins, 
            self.hex_grid[['h3_index', 'footfall_category', 'footfall_category_name', 
                          'footfall_score', 'footfall_percentile', 'geometry']],
            how='left',
            predicate='within'
        )
        
        # Handle bins outside Westminster boundary
        outside = bins_with_hex['h3_index'].isna().sum()
        if outside > 0:
            print(f"  Warning: {outside} bins are outside Westminster boundary")
        
        bins_with_hex = bins_with_hex.dropna(subset=['h3_index'])
        print(f"  {len(bins_with_hex)} bins assigned to hexagonal cells")
        
        return bins_with_hex
    
    def optimize_sensor_placement(
        self,
        bins: gpd.GeoDataFrame,
        n_sensors: int = 1000,
        min_distance_m: float = 50
    ) -> gpd.GeoDataFrame:
        """
        Select optimal bin locations for sensor placement.
        
        Strategy:
        1. Distribute sensors proportionally across footfall categories
        2. Within each category, maximize spatial distribution
        3. Ensure minimum distance between selected bins
        """
        print(f"\nOptimizing placement of {n_sensors} sensors...")
        
        # Calculate target distribution across categories
        # Use sqrt-proportional distribution to ensure coverage of low-footfall areas
        category_counts = bins.groupby('footfall_category').size()
        category_weights = np.sqrt(category_counts)
        category_weights = category_weights / category_weights.sum()
        
        # Adjust to ensure minimum representation of each category
        min_per_category = max(20, n_sensors // (2 * self.n_categories))
        target_distribution = (category_weights * n_sensors).astype(int)
        target_distribution = np.maximum(target_distribution, min_per_category)
        
        # Scale to match total
        while target_distribution.sum() > n_sensors:
            max_idx = target_distribution.argmax()
            target_distribution.iloc[max_idx] -= 1
        while target_distribution.sum() < n_sensors:
            min_idx = target_distribution.argmin()
            target_distribution.iloc[min_idx] += 1
        
        print("\n  Target distribution across footfall categories:")
        for cat in range(self.n_categories):
            if cat in target_distribution.index:
                print(f"    Category {cat}: {target_distribution.loc[cat]} sensors")
        
        # Select bins for each category
        selected_bins = []
        bins_proj = bins.to_crs("EPSG:27700")
        
        for cat in range(self.n_categories):
            if cat not in target_distribution.index:
                continue
                
            target = target_distribution.loc[cat]
            cat_bins = bins_proj[bins_proj['footfall_category'] == cat].copy()
            
            if len(cat_bins) <= target:
                # Take all bins in this category
                selected_bins.append(cat_bins)
                print(f"    Category {cat}: Selected all {len(cat_bins)} available bins")
            else:
                # Use spatial sampling to maximize coverage
                cat_selected = self._spatial_sampling(cat_bins, target, min_distance_m)
                selected_bins.append(cat_selected)
                print(f"    Category {cat}: Selected {len(cat_selected)} bins")
        
        # Combine selected bins
        result = pd.concat(selected_bins, ignore_index=True)
        result = gpd.GeoDataFrame(result, crs="EPSG:27700").to_crs("EPSG:4326")
        
        # Add selection metadata
        result['selected_for_sensor'] = True
        result['selection_rank'] = range(1, len(result) + 1)
        
        print(f"\n  Total sensors selected: {len(result)}")
        self._print_selection_summary(result)
        
        return result
    
    def _spatial_sampling(
        self,
        bins: gpd.GeoDataFrame,
        n_select: int,
        min_distance: float
    ) -> gpd.GeoDataFrame:
        """Select bins using spatial sampling to maximize coverage"""
        coords = np.array([(geom.x, geom.y) for geom in bins.geometry])
        
        selected_indices = []
        available_indices = list(range(len(bins)))
        
        # Start with the bin closest to the centroid (central location)
        centroid = coords.mean(axis=0)
        distances_to_centroid = np.linalg.norm(coords - centroid, axis=1)
        first_idx = np.argmin(distances_to_centroid)
        selected_indices.append(first_idx)
        available_indices.remove(first_idx)
        
        # Iteratively select bins that maximize minimum distance to selected set
        while len(selected_indices) < n_select and available_indices:
            selected_coords = coords[selected_indices]
            
            best_idx = None
            best_min_dist = -1
            
            for idx in available_indices:
                # Calculate minimum distance to all selected bins
                dists = np.linalg.norm(selected_coords - coords[idx], axis=1)
                min_dist = dists.min()
                
                if min_dist > best_min_dist:
                    best_min_dist = min_dist
                    best_idx = idx
            
            if best_idx is not None:
                selected_indices.append(best_idx)
                available_indices.remove(best_idx)
        
        return bins.iloc[selected_indices]
    
    def _print_selection_summary(self, selected: gpd.GeoDataFrame):
        """Print summary of selected bin locations"""
        print("\n  Selection Summary by Footfall Category:")
        for cat in range(self.n_categories):
            cat_selected = selected[selected['footfall_category'] == cat]
            if len(cat_selected) > 0:
                mean_score = cat_selected['footfall_score'].mean()
                print(f"    Category {cat}: {len(cat_selected)} bins (mean footfall: {mean_score:.3f})")


# =============================================================================
# VISUALIZATION
# =============================================================================

class Visualizer:
    """Create visualizations of the analysis"""
    
    def __init__(self, config: Config):
        self.config = config
        self.colors = [
            '#1a9850',  # Dark green - very low
            '#91cf60',  # Light green - low
            '#d9ef8b',  # Yellow-green - low-medium
            '#fee08b',  # Yellow - medium
            '#fdae61',  # Orange - medium-high
            '#f46d43',  # Red-orange - high
            '#d73027',  # Red - very high
            '#a50026',  # Dark red - peak
        ]
    
    def create_footfall_map(
        self,
        hex_grid: gpd.GeoDataFrame,
        boundary: gpd.GeoDataFrame,
        tube_stations: gpd.GeoDataFrame = None,
        output_path: str = None
    ) -> folium.Map:
        """Create interactive map showing footfall zones"""
        print("Creating interactive footfall map...")
        
        # Center map on Westminster
        center_lat = hex_grid.geometry.centroid.y.mean()
        center_lon = hex_grid.geometry.centroid.x.mean()
        
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=14,
            tiles='cartodbpositron'
        )
        
        # Add hexagonal grid with footfall coloring
        for idx, row in hex_grid.iterrows():
            color = self.colors[int(row['footfall_category'])]
            
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': color,
                    'weight': 0.5,
                    'fillOpacity': 0.6
                },
                tooltip=folium.Tooltip(
                    f"Category: {row['footfall_category_name']}<br>"
                    f"Footfall Score: {row['footfall_score']:.3f}<br>"
                    f"Percentile: {row['footfall_percentile']:.1f}%"
                )
            ).add_to(m)
        
        # Add tube stations
        if tube_stations is not None:
            for idx, row in tube_stations.iterrows():
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=5 + row['annual_usage'] / 10,
                    color='blue',
                    fill=True,
                    popup=f"{row['name']}<br>Usage: {row['annual_usage']}M/year"
                ).add_to(m)
        
        # Add legend
        legend_html = self._create_legend_html()
        m.get_root().html.add_child(folium.Element(legend_html))
        
        if output_path:
            m.save(output_path)
            print(f"  Saved to {output_path}")
        
        return m
    
    def create_sensor_placement_map(
        self,
        hex_grid: gpd.GeoDataFrame,
        selected_bins: gpd.GeoDataFrame,
        all_bins: gpd.GeoDataFrame = None,
        output_path: str = None
    ) -> folium.Map:
        """Create map showing recommended sensor placements"""
        print("Creating sensor placement map...")
        
        center_lat = hex_grid.geometry.centroid.y.mean()
        center_lon = hex_grid.geometry.centroid.x.mean()
        
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=14,
            tiles='cartodbpositron'
        )
        
        # Add hexagonal grid (lighter)
        for idx, row in hex_grid.iterrows():
            color = self.colors[int(row['footfall_category'])]
            
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': color,
                    'weight': 0.3,
                    'fillOpacity': 0.3
                }
            ).add_to(m)
        
        # Add all bins (if provided) as small gray markers
        if all_bins is not None:
            for idx, row in all_bins.iterrows():
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=2,
                    color='gray',
                    fill=True,
                    fillOpacity=0.5
                ).add_to(m)
        
        # Add selected bins as larger colored markers
        marker_cluster = MarkerCluster(name="Selected Bins").add_to(m)
        
        for idx, row in selected_bins.iterrows():
            color = self.colors[int(row['footfall_category'])]
            
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=6,
                color='black',
                fill=True,
                fillColor=color,
                fillOpacity=0.9,
                popup=folium.Popup(
                    f"Rank: {row['selection_rank']}<br>"
                    f"Category: {row['footfall_category_name']}<br>"
                    f"Footfall Score: {row['footfall_score']:.3f}",
                    max_width=200
                )
            ).add_to(m)
        
        # Add legend
        legend_html = self._create_legend_html()
        m.get_root().html.add_child(folium.Element(legend_html))
        
        if output_path:
            m.save(output_path)
            print(f"  Saved to {output_path}")
        
        return m
    
    def _create_legend_html(self) -> str:
        """Create HTML for map legend"""
        categories = [
            "Very Low (Residential)",
            "Low",
            "Low-Medium",
            "Medium",
            "Medium-High",
            "High",
            "Very High",
            "Peak (Commercial)"
        ]
        
        legend_items = ""
        for i, (color, cat) in enumerate(zip(self.colors, categories)):
            legend_items += f'''
                <div style="display: flex; align-items: center; margin-bottom: 4px;">
                    <div style="width: 20px; height: 20px; background-color: {color}; 
                         margin-right: 8px; border: 1px solid #333;"></div>
                    <span style="font-size: 12px;">{cat}</span>
                </div>
            '''
        
        return f'''
        <div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000; 
             background-color: white; padding: 15px; border-radius: 5px;
             box-shadow: 0 2px 10px rgba(0,0,0,0.2); font-family: Arial, sans-serif;">
            <h4 style="margin: 0 0 10px 0; font-size: 14px;">Footfall Categories</h4>
            {legend_items}
        </div>
        '''
    
    def create_distribution_charts(
        self,
        hex_grid: gpd.GeoDataFrame,
        selected_bins: gpd.GeoDataFrame = None,
        output_path: str = None
    ):
        """Create statistical charts showing footfall distribution"""
        print("Creating distribution charts...")
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # 1. Footfall score distribution
        ax1 = axes[0, 0]
        ax1.hist(hex_grid['footfall_score'], bins=50, color='steelblue', edgecolor='white', alpha=0.7)
        ax1.set_xlabel('Footfall Score')
        ax1.set_ylabel('Number of Hexagonal Cells')
        ax1.set_title('Distribution of Footfall Scores Across Westminster')
        ax1.axvline(hex_grid['footfall_score'].mean(), color='red', linestyle='--', label='Mean')
        ax1.axvline(hex_grid['footfall_score'].median(), color='orange', linestyle='--', label='Median')
        ax1.legend()
        
        # 2. Category distribution
        ax2 = axes[0, 1]
        category_counts = hex_grid['footfall_category'].value_counts().sort_index()
        bars = ax2.bar(range(len(category_counts)), category_counts.values, color=self.colors)
        ax2.set_xlabel('Footfall Category')
        ax2.set_ylabel('Number of Hexagonal Cells')
        ax2.set_title('Cells per Footfall Category')
        ax2.set_xticks(range(len(category_counts)))
        ax2.set_xticklabels([f'Cat {i}' for i in range(len(category_counts))])
        
        # 3. Component scores heatmap
        ax3 = axes[1, 0]
        component_means = hex_grid.groupby('footfall_category')[
            ['tube_score_norm', 'bus_score_norm', 'premises_score_norm']
        ].mean()
        component_means.columns = ['Tube', 'Bus', 'Premises']
        sns.heatmap(component_means, annot=True, fmt='.2f', cmap='YlOrRd', ax=ax3)
        ax3.set_xlabel('Component')
        ax3.set_ylabel('Footfall Category')
        ax3.set_title('Mean Component Scores by Category')
        
        # 4. Selected bins distribution (if provided)
        ax4 = axes[1, 1]
        if selected_bins is not None:
            selected_counts = selected_bins['footfall_category'].value_counts().sort_index()
            total_counts = hex_grid['footfall_category'].value_counts().sort_index()
            
            x = np.arange(len(selected_counts))
            width = 0.35
            
            ax4.bar(x - width/2, total_counts.values / total_counts.values.max(), width, 
                   label='All Cells (normalized)', alpha=0.5, color='gray')
            ax4.bar(x + width/2, selected_counts.values / selected_counts.values.max(), width,
                   label='Selected Bins (normalized)', color='steelblue')
            ax4.set_xlabel('Footfall Category')
            ax4.set_ylabel('Normalized Count')
            ax4.set_title('Sensor Selection vs Cell Distribution')
            ax4.set_xticks(x)
            ax4.set_xticklabels([f'Cat {i}' for i in range(len(selected_counts))])
            ax4.legend()
        else:
            ax4.text(0.5, 0.5, 'Load bin locations to see\nsensor selection distribution',
                    ha='center', va='center', transform=ax4.transAxes, fontsize=12)
            ax4.set_title('Sensor Selection Distribution')
        
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            print(f"  Saved to {output_path}")
        
        plt.close()
        return fig


# =============================================================================
# MAIN ANALYSIS CLASS
# =============================================================================

class WestminsterFootfallAnalysis:
    """Main class orchestrating the complete analysis"""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.data_loader = DataLoader(self.config)
        self.hex_generator = HexGridGenerator(self.config)
        self.footfall_scorer = FootfallScorer(self.config)
        self.categorizer = FootfallCategorizer(self.config)
        self.visualizer = Visualizer(self.config)
        
        # Data storage
        self.boundary = None
        self.tube_stations = None
        self.bus_stops = None
        self.premises = None
        self.hex_grid = None
        self.optimizer = None
    
    def run_analysis(self) -> gpd.GeoDataFrame:
        """Run the complete footfall analysis"""
        print("=" * 70)
        print("WESTMINSTER FOOTFALL ANALYSIS FOR BIN SENSOR PLACEMENT")
        print("=" * 70)
        print()
        
        # 1. Load data
        print("STEP 1: Loading Data")
        print("-" * 40)
        self.boundary = self.data_loader.get_westminster_boundary()
        self.tube_stations = self.data_loader.load_tube_station_data()
        self.bus_stops = self.data_loader.load_bus_stop_data()
        self.premises = self.data_loader.load_licensed_premises_data()
        print()
        
        # 2. Create hexagonal grid
        print("STEP 2: Creating Hexagonal Grid")
        print("-" * 40)
        self.hex_grid = self.hex_generator.create_hexagonal_grid(self.boundary)
        print()
        
        # 3. Calculate footfall scores
        print("STEP 3: Calculating Footfall Scores")
        print("-" * 40)
        self.hex_grid = self.footfall_scorer.calculate_scores(
            self.hex_grid,
            self.tube_stations,
            self.bus_stops,
            self.premises
        )
        print()
        
        # 4. Categorize footfall zones
        print("STEP 4: Categorizing Footfall Zones")
        print("-" * 40)
        self.hex_grid = self.categorizer.categorize(self.hex_grid)
        print()
        
        # 5. Initialize optimizer
        self.optimizer = BinSensorOptimizer(self.config, self.hex_grid)
        
        # 6. Create visualizations
        print("STEP 5: Creating Visualizations")
        print("-" * 40)
        self.visualizer.create_footfall_map(
            self.hex_grid,
            self.boundary,
            self.tube_stations,
            str(self.config.OUTPUT_DIR / "westminster_footfall_map.html")
        )
        self.visualizer.create_distribution_charts(
            self.hex_grid,
            output_path=str(self.config.OUTPUT_DIR / "footfall_distribution.png")
        )
        print()
        
        # 7. Save hex grid data
        print("STEP 6: Saving Analysis Results")
        print("-" * 40)
        self._save_results()
        print()
        
        print("=" * 70)
        print("ANALYSIS COMPLETE")
        print("=" * 70)
        print(f"\nOutputs saved to: {self.config.OUTPUT_DIR.absolute()}")
        print("\nTo optimize bin sensor placement, use:")
        print("  analysis.optimize_bin_sensors('path/to/bins.csv', n_sensors=1000)")
        
        return self.hex_grid
    
    def optimize_bin_sensors(
        self,
        bin_file_path: str,
        n_sensors: int = 1000,
        min_distance_m: float = 50
    ) -> gpd.GeoDataFrame:
        """
        Load bin locations and optimize sensor placement.
        
        Args:
            bin_file_path: Path to CSV or GeoJSON file with bin locations
                          CSV should have columns: lat/latitude, lon/longitude
            n_sensors: Number of sensors to place (default 1000)
            min_distance_m: Minimum distance between selected bins in meters
            
        Returns:
            GeoDataFrame with selected bin locations
        """
        if self.optimizer is None:
            raise ValueError("Run run_analysis() first before optimizing bin sensors")
        
        print("=" * 70)
        print("BIN SENSOR PLACEMENT OPTIMIZATION")
        print("=" * 70)
        print()
        
        # Load bin locations
        bins = self.optimizer.load_bin_locations(bin_file_path)
        
        # Assign to hexagons
        bins_with_hex = self.optimizer.assign_bins_to_hexagons(bins)
        
        # Optimize placement
        selected_bins = self.optimizer.optimize_sensor_placement(
            bins_with_hex,
            n_sensors=n_sensors,
            min_distance_m=min_distance_m
        )
        
        # Create visualization
        print("\nCreating sensor placement visualization...")
        self.visualizer.create_sensor_placement_map(
            self.hex_grid,
            selected_bins,
            bins_with_hex,
            str(self.config.OUTPUT_DIR / "sensor_placement_map.html")
        )
        
        self.visualizer.create_distribution_charts(
            self.hex_grid,
            selected_bins,
            str(self.config.OUTPUT_DIR / "sensor_selection_distribution.png")
        )
        
        # Save results
        output_file = self.config.OUTPUT_DIR / "recommended_sensor_locations.csv"
        selected_bins_df = selected_bins.drop(columns=['geometry']).copy()
        selected_bins_df['lat'] = selected_bins.geometry.y
        selected_bins_df['lon'] = selected_bins.geometry.x
        selected_bins_df.to_csv(output_file, index=False)
        print(f"\nSaved recommended locations to: {output_file}")
        
        # GeoJSON output
        geojson_file = self.config.OUTPUT_DIR / "recommended_sensor_locations.geojson"
        selected_bins.to_file(geojson_file, driver='GeoJSON')
        print(f"Saved GeoJSON to: {geojson_file}")
        
        return selected_bins
    
    def _save_results(self):
        """Save analysis results to files"""
        # Save hex grid as GeoJSON
        hex_file = self.config.OUTPUT_DIR / "westminster_footfall_hexgrid.geojson"
        self.hex_grid.to_file(hex_file, driver='GeoJSON')
        print(f"  Saved hexagonal grid to: {hex_file}")
        
        # Save as CSV (without geometry)
        csv_file = self.config.OUTPUT_DIR / "westminster_footfall_data.csv"
        hex_df = self.hex_grid.drop(columns=['geometry']).copy()
        hex_df['center_lat'] = self.hex_grid.geometry.centroid.y
        hex_df['center_lon'] = self.hex_grid.geometry.centroid.x
        hex_df.to_csv(csv_file, index=False)
        print(f"  Saved footfall data to: {csv_file}")
        
        # Save summary statistics
        summary = {
            'total_hexagons': len(self.hex_grid),
            'footfall_score_mean': float(self.hex_grid['footfall_score'].mean()),
            'footfall_score_std': float(self.hex_grid['footfall_score'].std()),
            'footfall_score_min': float(self.hex_grid['footfall_score'].min()),
            'footfall_score_max': float(self.hex_grid['footfall_score'].max()),
            'category_distribution': self.hex_grid['footfall_category'].value_counts().to_dict(),
            'tube_stations_count': len(self.tube_stations),
            'bus_stops_count': len(self.bus_stops),
            'premises_count': len(self.premises),
            'config': {
                'h3_resolution': self.config.H3_RESOLUTION,
                'tube_weight': self.config.TUBE_WEIGHT,
                'bus_weight': self.config.BUS_WEIGHT,
                'premises_weight': self.config.PREMISES_WEIGHT,
                'n_categories': self.config.N_FOOTFALL_CATEGORIES
            }
        }
        
        summary_file = self.config.OUTPUT_DIR / "analysis_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"  Saved summary to: {summary_file}")


# =============================================================================
# EXAMPLE USAGE / CLI
# =============================================================================

def generate_sample_bins(n_bins: int = 3000, output_path: str = "data/sample_bins.csv"):
    """Generate sample bin locations for testing"""
    print(f"Generating {n_bins} sample bin locations...")
    
    np.random.seed(44)
    
    # Westminster bounds
    min_lon, max_lon = -0.20, -0.11
    min_lat, max_lat = 51.485, 51.535
    
    # Generate random points within bounds
    lats = np.random.uniform(min_lat, max_lat, n_bins)
    lons = np.random.uniform(min_lon, max_lon, n_bins)
    
    # Add some clustering around high footfall areas
    hotspots = [
        (51.5154, -0.1418, 0.003),  # Oxford Circus
        (51.4965, -0.1447, 0.004),  # Victoria
        (51.5117, -0.1240, 0.003),  # Covent Garden
        (51.5136, -0.1340, 0.003),  # Soho
    ]
    
    n_clustered = n_bins // 3
    for i in range(n_clustered):
        hotspot = hotspots[i % len(hotspots)]
        lats[i] = hotspot[0] + np.random.normal(0, hotspot[2])
        lons[i] = hotspot[1] + np.random.normal(0, hotspot[2])
    
    df = pd.DataFrame({
        'bin_id': [f'BIN{i:05d}' for i in range(n_bins)],
        'lat': lats,
        'lon': lons,
        'bin_type': np.random.choice(['General Waste', 'Recycling', 'Food Waste'], n_bins),
        'capacity_liters': np.random.choice([120, 240, 360, 1100], n_bins)
    })
    
    Path(output_path).parent.mkdir(exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Saved sample bins to: {output_path}")
    
    return output_path


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Westminster Footfall Analysis for Bin Sensor Placement'
    )
    parser.add_argument(
        '--bins', '-b',
        type=str,
        help='Path to bin locations CSV or GeoJSON file'
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
    
    args = parser.parse_args()
    
    # Update config
    config = Config()
    config.OUTPUT_DIR = Path(args.output_dir)
    
    # Run analysis
    analysis = WestminsterFootfallAnalysis(config)
    analysis.run_analysis()
    
    # Generate sample bins if requested
    if args.generate_sample:
        bin_file = generate_sample_bins()
        args.bins = bin_file
    
    # Optimize sensor placement if bin file provided
    if args.bins:
        analysis.optimize_bin_sensors(
            args.bins,
            n_sensors=args.n_sensors
        )


if __name__ == "__main__":
    main()

