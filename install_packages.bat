@echo off
echo Installing required packages for Westminster Footfall Analysis...
echo.
echo Please run this script as Administrator if you encounter permission errors.
echo.

REM Upgrade pip first
python -m pip install --upgrade pip

REM Install packages one by one to see which ones fail
echo Installing geopandas...
python -m pip install geopandas

echo Installing h3...
python -m pip install h3

echo Installing folium...
python -m pip install folium

echo Installing scipy...
python -m pip install scipy

echo Installing scikit-learn...
python -m pip install scikit-learn

echo Installing seaborn...
python -m pip install seaborn

echo Installing tqdm...
python -m pip install tqdm

echo Installing matplotlib...
python -m pip install matplotlib

echo.
echo Installation complete. Testing imports...
python -c "import geopandas, h3, folium, scipy, sklearn, seaborn, tqdm, matplotlib; print('All packages imported successfully!')"

pause

