# Automated Scraper

This folder contains the FastAPI-based monitoring application for the CDSCO alert workflow. It is used to discover new regulatory documents, download the associated PDFs, and expose the results through a local web interface and JSON API.

This application is separate from the numbered ingestion pipeline under [initial_data_ingestion](../initial_data_ingestion). It is designed as a small operational monitoring tool rather than a large batch research pipeline.

## Purpose

The scraper app is meant to:

- monitor the CDSCO Alerts website for new entries
- fetch and store PDF documents
- keep metadata in PostgreSQL
- expose document records through a simple API
- provide a lightweight UI for checking discovered content

## Folder structure

```text
automated_scraper/
├── README.md
├── __init__.py
├── config.py
├── database.py
├── init_db.py
├── jobs.py
├── main.py
├── models.py
├── pdf_handler.py
├── scheduler.py
├── scraper.py
├── seed.py
├── storage/
│   └── pdfs/
├── templates/
│   └── index.html
└── __pycache__/
```

## Main modules

### `main.py`

Entry point for the FastAPI app. This file sets up the routes, API endpoints, scheduler lifecycle, and static/template serving.

### `config.py`

Configuration values for the app, including database-related settings and storage paths.

### `database.py`

Database session and engine setup for SQLAlchemy access.

### `models.py`

ORM models for the scraped document data and scheduler-related records.

### `scraper.py`

Logic for visiting the CDSCO Alerts page and collecting candidate document metadata.

### `pdf_handler.py`

Handles PDF resolution, wrapped/iframe document handling, and local storage of downloaded files.

### `jobs.py`

Background/triggered job logic to scrape and fetch new documents.

### `scheduler.py`

Configures the app scheduler and startup/shutdown lifecycle behavior.

### `init_db.py`

Creates SQL tables needed by the app.

### `seed.py`

Loads demo sample data and triggers an initial scraping/download cycle.

### `templates/index.html`

Basic HTML UI used to review documents and monitor the app.

## Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Make sure PostgreSQL is running and set the environment variables required by the app.

## Run the app

Create the database tables and seed demo data:

```powershell
python -m automated_scraper.init_db
python -m automated_scraper.seed
```

Start the app:

```powershell
uvicorn automated_scraper.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/
```

## Useful endpoints

- `GET /health` — health check
- `GET /api/documents` — list available documents
- `GET /api/documents/{document_id}` — fetch one document
- `POST /api/scrape-now?limit=20` — trigger a scrape run
- `GET /api/scheduler` — inspect scheduler state
- `PUT /api/scheduler` — update scheduler settings
- `GET /static-pdf/{document_id}.pdf` — serve a saved PDF inline

## Notes

- This app is operational and monitoring-oriented, not the main batch ETL engine.
- The numbered pipeline under [initial_data_ingestion](../initial_data_ingestion) is the project’s main extraction and normalization workflow.
- The app is intended to be a lightweight, database-backed monitoring layer for newly published alerts and PDFs.
