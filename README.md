# Westminster Footfall Analysis for Bin Sensor Placement

## Overview

This analysis tool identifies optimal bin sensor placement locations across the Borough of Westminster by analyzing footfall patterns. The goal is to achieve a **representative sample** of bin fill rates across the borough, rather than simply targeting the highest footfall areas.

## Strategic Objectives

The analysis supports three key strategic drivers:

1. **Optimising collection of overflowing bins** - Identify areas where bins fill quickly
2. **Auditing collection schedule adherence** - Monitor if collections happen as planned
3. **Reduced inspection costs** - Smart sensors eliminate manual inspections

## Methodology

### 1. Footfall Zone Tessellation

The borough is divided into **hexagonal cells** using the H3 geospatial indexing system. This provides:
- Uniform cell sizes (~150m² at resolution 10)
- Efficient spatial querying
- Natural grid for categorization

### 2. Footfall Scoring

Each hexagonal cell receives a composite footfall score based on:

| Data Source | Weight | Rationale |
|------------|--------|-----------|
| **Tube Station Usage** | 45% | High correlation with pedestrian density |
| **Bus Stop Locations** | 30% | Indicates street-level foot traffic |
| **Licensed Premises** | 25% | Evening/night economy activity |

Scores are calculated using inverse-distance weighting from each footfall generator to surrounding cells.

### 3. Footfall Categories

Cells are clustered into **8 distinct footfall categories**:

| Category | Description | Typical Locations |
|----------|-------------|-------------------|
| 0 | Very Low (Residential) | Quiet residential streets |
| 1 | Low | Side streets, parks edges |
| 2 | Low-Medium | Secondary roads |
| 3 | Medium | Local high streets |
| 4 | Medium-High | Busy intersections |
| 5 | High | Major stations approach |
| 6 | Very High | Shopping areas |
| 7 | Peak (Commercial) | Oxford Street, Leicester Sq |

### 4. Sensor Placement Optimization

When bin locations are provided, the algorithm:

1. **Distributes sensors proportionally** across all footfall categories
2. **Maximizes spatial coverage** within each category
3. **Ensures minimum distance** between selected bins (default 50m)
4. **Balances representation** - uses sqrt-proportional allocation to ensure low-footfall areas aren't under-represented

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Analysis (No Bin Locations)

Run the footfall analysis to generate footfall zones:

```bash
python westminster_footfall_analysis.py
```

This will generate:
- `output/westminster_footfall_map.html` - Interactive map of footfall zones
- `output/westminster_footfall_hexgrid.geojson` - Hexagonal grid with scores
- `output/westminster_footfall_data.csv` - Tabular data
- `output/footfall_distribution.png` - Statistical charts
- `output/analysis_summary.json` - Summary statistics

### With Bin Locations (Sensor Optimization)

```bash
# With your bin data
python westminster_footfall_analysis.py --bins path/to/your/bins.csv --n-sensors 1000

# Generate sample data for testing
python westminster_footfall_analysis.py --generate-sample --n-sensors 1000
```

### Bin Location File Format

**CSV Format:**
```csv
bin_id,lat,lon,bin_type,capacity_liters
BIN00001,51.5154,-0.1418,General Waste,240
BIN00002,51.4965,-0.1447,Recycling,120
```

Required columns: `lat`/`latitude` and `lon`/`longitude`

**GeoJSON Format:**
Standard GeoJSON with Point geometries.

### Python API

```python
from westminster_footfall_analysis import WestminsterFootfallAnalysis, Config

# Initialize with custom config if needed
config = Config()
config.N_FOOTFALL_CATEGORIES = 10  # More granular categories
config.H3_RESOLUTION = 11  # Smaller hexagons

# Run analysis
analysis = WestminsterFootfallAnalysis(config)
hex_grid = analysis.run_analysis()

# Optimize sensor placement
selected_bins = analysis.optimize_bin_sensors(
    bin_file_path='data/bins.csv',
    n_sensors=1000,
    min_distance_m=50
)

# Access results
print(f"Selected {len(selected_bins)} bins")
print(selected_bins[['bin_id', 'footfall_category', 'footfall_score']].head())
```

## Output Files

### Footfall Analysis

| File | Description |
|------|-------------|
| `westminster_footfall_map.html` | Interactive Folium map with footfall zones |
| `westminster_footfall_hexgrid.geojson` | Hexagonal grid with all scores |
| `westminster_footfall_data.csv` | Tabular data for further analysis |
| `footfall_distribution.png` | Distribution charts |
| `analysis_summary.json` | Summary statistics |

### Sensor Placement

| File | Description |
|------|-------------|
| `sensor_placement_map.html` | Interactive map with selected locations |
| `recommended_sensor_locations.csv` | Selected bins with coordinates |
| `recommended_sensor_locations.geojson` | GeoJSON for GIS import |
| `sensor_selection_distribution.png` | Selection distribution charts |

## Data Sources

The analysis uses data representative of London Datastore datasets:

1. **TfL Station Entry/Exit Figures** - Tube station annual usage
2. **TfL Bus Stops** - Bus stop locations and frequencies  
3. **Licensed Premises** - Pubs, restaurants, clubs, cafes

*Note: The current implementation uses representative synthetic data. For production use, download actual datasets from [London Datastore](https://data.london.gov.uk/).*

## Configuration Options

Edit the `Config` class in `westminster_footfall_analysis.py`:

```python
@dataclass
class Config:
    # H3 hexagon resolution (9=~0.1km², 10=~0.015km², 11=~0.002km²)
    H3_RESOLUTION = 10
    
    # Influence radii (meters)
    TUBE_INFLUENCE_RADIUS = 500  # How far tube stations affect footfall
    BUS_INFLUENCE_RADIUS = 200
    PREMISES_INFLUENCE_RADIUS = 150
    
    # Component weights (must sum to 1.0)
    TUBE_WEIGHT = 0.45
    BUS_WEIGHT = 0.30
    PREMISES_WEIGHT = 0.25
    
    # Number of footfall categories
    N_FOOTFALL_CATEGORIES = 8
```

## Interpretation Guide

### Understanding Footfall Scores

- **0.0 - 0.2**: Residential areas, quiet streets
- **0.2 - 0.4**: Secondary commercial, local shops
- **0.4 - 0.6**: Busy local areas, minor transport hubs
- **0.6 - 0.8**: Major shopping streets, stations
- **0.8 - 1.0**: Peak commercial (Oxford Street, Leicester Square)

### Sensor Selection Strategy

The optimization ensures:

1. **Representative coverage** - All footfall levels are sampled
2. **Spatial distribution** - No clustering of sensors in one area
3. **Statistical validity** - Enables borough-wide fill rate estimation

### Expected Bin Fill Correlations

| Footfall Category | Expected Fill Rate | Collection Frequency |
|-------------------|-------------------|---------------------|
| Very Low (0) | 2-3 days | Weekly |
| Low (1-2) | 1-2 days | Twice weekly |
| Medium (3-4) | Daily | Daily |
| High (5-6) | Multiple/day | Twice daily |
| Peak (7) | Constant | 3x daily |

## Extending the Analysis

### Adding New Data Sources

```python
class DataLoader:
    def load_custom_footfall_data(self) -> gpd.GeoDataFrame:
        """Add your custom footfall indicator"""
        # Load and return as GeoDataFrame with 'geometry' and 'weight' columns
        pass
```

### Custom Optimization Strategies

The `BinSensorOptimizer` class can be extended with alternative selection algorithms:

- **Stratified random** - Random selection within each category
- **K-medoids** - Cluster centers as representative bins
- **Coverage maximization** - Greedy maximum coverage

## License

MIT License - Free for commercial and non-commercial use.

## Contact

For questions about the methodology or implementation, please raise an issue in the repository.

