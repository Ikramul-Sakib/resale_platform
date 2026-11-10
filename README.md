# ValuLens

**Resale Intelligence & E-Commerce Platform**

Snap a photo → identify your item → estimate its resale value → generate marketplace listings → manage inventory → track sales and profit.

## Tech Stack

- **Backend:** Python 3 + Django 5.1 LTS + Django REST Framework
- **Database:** PostgreSQL (required — no SQLite)
- **Frontend:** Django Templates + HTML5 + CSS3 + vanilla JS
- **Async:** Celery + Redis (optional in dev)
- **Images:** Pillow for validation, private storage

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis (optional for dev — Celery runs eagerly without it)

### Setup (macOS)

```bash
# 1. Clone and enter directory
cd resale_platform

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create PostgreSQL database
createdb valulens_dev
# Or via psql:
# psql -c "CREATE USER valulens_user WITH PASSWORD 'valulens_pass';"
# psql -c "CREATE DATABASE valulens_dev OWNER valulens_user;"

# 5. Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL and SECRET_KEY

# 6. Run migrations
python manage.py migrate

# 7. Create superuser
python manage.py createsuperuser

# 8. Run dev server
python manage.py runserver
```

### Setup (Ubuntu)

```bash
# Install system deps
sudo apt update
sudo apt install python3-dev python3-venv postgresql postgresql-contrib libpq-dev

# Create DB
sudo -u postgres createuser --interactive valulens_user
sudo -u postgres createdb valulens_dev -O valulens_user

# Then follow macOS steps 2-8 above
```

### Setup (Windows / PowerShell)

```powershell
# 1. Create venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install deps
pip install -r requirements.txt

# 3. Create DB via pgAdmin or psql
# psql -U postgres -c "CREATE USER valulens_user WITH PASSWORD 'valulens_pass';"
# psql -U postgres -c "CREATE DATABASE valulens_dev OWNER valulens_user;"

# 4. Configure environment
Copy-Item .env.example .env
# Edit .env

# 5. Migrate and run
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Running Tests

```bash
# Requires PostgreSQL (tests run against a real database)
pytest
```

## Project Structure

```
resale_platform/
├── manage.py
├── requirements.txt
├── .env.example
├── config/          # Settings (base/dev/prod), URLs, WSGI, ASGI, Celery
├── apps/
│   ├── accounts/    # Custom User model, auth, audit events
│   ├── catalog/     # Category, Brand
│   ├── scans/       # Scan, ScanImage
│   ├── recognition/ # IdentifiedItem, recognition providers
│   ├── pricing/     # PriceEstimate, MarketPriceObservation
│   ├── listings/    # ListingDraft, listing generators
│   ├── inventory/   # InventoryItem, Sale
│   ├── marketplaces/# Marketplace, fee rules, fee calculator
│   └── analytics/   # ResaleIndexSnapshot, index computation
├── templates/       # Django templates (base, components, pages)
├── static/          # CSS, JS, images
├── media/           # Private uploads (dev only)
├── tests/           # Cross-cutting test suites
└── docs/            # Architecture, database, API, deployment docs
```

## License

Proprietary — All rights reserved.
