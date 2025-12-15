# Deployment Guide

This guide covers deploying the Westminster Bin Sensor Analysis application.

## Quick Start Options

### Option 1: Render (Recommended - Free Tier Available)

1. **Create a Render account** at [render.com](https://render.com)

2. **Connect your GitHub repository**
   - Go to Dashboard → New → Web Service
   - Connect your GitHub account and select this repository

3. **Configure the service**
   ```
   Name: westminster-bin-sensors
   Environment: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: python backend/server.py --port $PORT
   ```

4. **Deploy**
   - Click "Create Web Service"
   - Render will automatically build and deploy

5. **Set up auto-deploy** (optional)
   - In your Render service settings, enable "Auto-Deploy"
   - Add the deploy hook URL to GitHub Secrets as `RENDER_DEPLOY_HOOK_URL`

**Free Tier Limitations:**
- Service sleeps after 15 minutes of inactivity
- 750 hours/month free
- No persistent disk storage

---

### Option 2: Railway

1. **Create a Railway account** at [railway.app](https://railway.app)

2. **Deploy from GitHub**
   ```bash
   # Install Railway CLI
   npm install -g @railway/cli
   
   # Login
   railway login
   
   # Initialize project
   railway init
   
   # Deploy
   railway up
   ```

3. **Or use the web interface**
   - New Project → Deploy from GitHub repo
   - Railway auto-detects Python and uses `railway.json` config

**Pricing:**
- $5/month free credits
- Pay-as-you-go after that

---

### Option 3: Docker (Self-hosted)

1. **Build the Docker image**
   ```bash
   docker build -t westminster-bin-sensors .
   ```

2. **Run the container**
   ```bash
   docker run -p 8080:8080 westminster-bin-sensors
   ```

3. **With Docker Compose** (create `docker-compose.yml`):
   ```yaml
   version: '3.8'
   services:
     app:
       build: .
       ports:
         - "8080:8080"
       volumes:
         - ./output:/app/output
       environment:
         - PORT=8080
   ```

   Then run:
   ```bash
   docker-compose up -d
   ```

---

### Option 4: Azure Web App

1. **Install Azure CLI**
   ```bash
   # Windows
   winget install Microsoft.AzureCLI
   
   # Or download from https://aka.ms/installazurecliwindows
   ```

2. **Login and create resources**
   ```bash
   az login
   
   # Create resource group
   az group create --name bin-sensors-rg --location uksouth
   
   # Create App Service plan (Free tier)
   az appservice plan create \
     --name bin-sensors-plan \
     --resource-group bin-sensors-rg \
     --sku F1 \
     --is-linux
   
   # Create Web App
   az webapp create \
     --resource-group bin-sensors-rg \
     --plan bin-sensors-plan \
     --name westminster-bin-sensors \
     --runtime "PYTHON:3.11"
   
   # Configure startup command
   az webapp config set \
     --resource-group bin-sensors-rg \
     --name westminster-bin-sensors \
     --startup-file "python backend/server.py --port 8000"
   ```

3. **Deploy from GitHub**
   ```bash
   az webapp deployment source config \
     --name westminster-bin-sensors \
     --resource-group bin-sensors-rg \
     --repo-url https://github.com/YOUR_USERNAME/bin-sensors \
     --branch main \
     --manual-integration
   ```

---

## CI/CD with GitHub Actions

The repository includes a GitHub Actions workflow (`.github/workflows/ci-cd.yml`) that:

1. **On every push/PR:**
   - Runs linting (flake8)
   - Tests module imports
   - Runs basic analysis test
   - Builds Docker image

2. **On push to main:**
   - Triggers deployment to Render/Railway

### Setting up GitHub Secrets

Go to your repository → Settings → Secrets and variables → Actions

Add these secrets:

| Secret Name | Description | Required For |
|------------|-------------|--------------|
| `RENDER_DEPLOY_HOOK_URL` | Render deploy hook URL | Render deployment |
| `RAILWAY_TOKEN` | Railway API token | Railway deployment |

### Getting the Render Deploy Hook

1. Go to your Render service dashboard
2. Settings → Deploy Hook
3. Copy the URL and add it as a GitHub secret

### Getting the Railway Token

1. Go to Railway dashboard
2. Account Settings → Tokens
3. Create a new token and add it as a GitHub secret

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Server port | 8080 |
| `PYTHON_VERSION` | Python version | 3.11 |

---

## Health Checks

The application exposes a health check endpoint:

```
GET /api/status
```

Response:
```json
{
  "status": "idle|running|complete|error",
  "progress": 0-100,
  "message": "Status message",
  "has_data": true|false
}
```

---

## Troubleshooting

### Common Issues

**1. Port already in use**
```bash
# Find process using port
netstat -ano | findstr :8080

# Kill process (Windows)
taskkill /PID <pid> /F
```

**2. Module not found errors**
```bash
# Ensure all dependencies are installed
pip install -r requirements.txt
```

**3. Analysis takes too long**
- Increase the grid resolution (larger number = fewer cells)
- The default is 0.001 (~100m), try 0.002 (~200m) for faster analysis

**4. Memory issues on free tier**
- Free tiers typically have 512MB RAM
- The analysis is designed to work within these limits
- If issues occur, increase grid resolution

---

## Local Development

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
.\venv\Scripts\activate

# Activate (Unix/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
python backend/server.py

# Open browser
start http://localhost:8080
```

---

## Production Considerations

1. **Persistent Storage**: Analysis results are stored in memory. For production, consider:
   - Adding a database (PostgreSQL, SQLite)
   - Using cloud storage (S3, Azure Blob)

2. **Caching**: Add Redis for caching analysis results

3. **Rate Limiting**: Add rate limiting for the API endpoints

4. **HTTPS**: Render and Railway provide free SSL certificates

5. **Monitoring**: 
   - Render has built-in metrics
   - Consider adding Sentry for error tracking

