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
├── client/
│   ├── __init__.py
│   └── index.html
├── database/
│   ├── __init__.py
│   ├── database.py
│   ├── init_db.py
│   ├── models.py
│   └── seed.py
├── scraper/
│   ├── __init__.py
│   ├── jobs.py
│   ├── pdf_handler.py
│   └── scraper.py
├── server/
│   ├── __init__.py
│   ├── main.py
│   └── scheduler.py
├── storage/
│   └── *.pdf
└── __pycache__/
```

## Application layers

### Server
- [server/main.py](server/main.py) — FastAPI app, routes, API endpoints, and UI rendering
- [server/scheduler.py](server/scheduler.py) — background scheduler lifecycle and schedule configuration

### Client / frontend
- [client/index.html](client/index.html) — dashboard for documents and scheduler controls

### Database
- [database/database.py](database/database.py) — SQLAlchemy engine and session setup
- [database/models.py](database/models.py) — document and scheduler ORM models
- [database/init_db.py](database/init_db.py) — creates the PostgreSQL tables
- [database/seed.py](database/seed.py) — initial seed/demo job entry point

### Storage
- [storage](storage) — stores downloaded PDF files directly in this folder

### Scraper
- [scraper/scraper.py](scraper/scraper.py) — fetches CDSCO alert rows and extracts metadata
- [scraper/pdf_handler.py](scraper/pdf_handler.py) — resolves wrapped PDF links and downloads the real file
- [scraper/jobs.py](scraper/jobs.py) — watermark-based detection of new documents and scrape workflow

## Main modules

### `config.py`

Application configuration, including PostgreSQL credentials and the storage path.

### `server/main.py`

FastAPI entry point for the app. Handles document APIs, scheduler APIs, health checks, and HTML UI serving.

### `server/scheduler.py`

Background scheduling logic using APScheduler.

### `database/models.py`

ORM definitions for documents and scheduler settings.

### `scraper/scraper.py`

Visits the CDSCO Alerts page and extracts candidate document information.

### `scraper/pdf_handler.py`

Downloads and validates the PDF file from the resolved document URL.

### `scraper/jobs.py`

Main scraping workflow: fetch new documents, skip duplicates and old items, and store downloaded results.

### `client/index.html`

Simple HTML dashboard used to view documents and trigger scheduling actions.

## Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Make sure PostgreSQL is running and set the environment variables required by the app.

## Run the app

Create the database tables:

```powershell
python -m automated_scraper.database.init_db
```

Seed example data:

```powershell
python -m automated_scraper.database.seed
```

Start the app:

```powershell
uvicorn automated_scraper.server.main:app --reload
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
