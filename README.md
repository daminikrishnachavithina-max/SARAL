# SARAL — For Every Citizen

**A citizen support and opportunity discovery platform**

**Find support for your next step.**

SARAL is a prototype designed to help people discover relevant support opportunities in one place, including scholarships, education support, employment opportunities, healthcare, and housing assistance.

## The Problem

Information about citizen support programs is often spread across different websites and sources. Finding relevant opportunities and understanding whether they match a person's circumstances can be difficult.

## Our Approach

SARAL brings opportunity discovery and eligibility checking into one platform.

### Key Features

- Browse opportunities by category and state.
- Check potential eligibility using profile details such as education level, income, and marks.
- Filter out listings that are not verified, open, or within their recorded validity period.
- Provide a local web interface with a Python API.

## Verification and Transparency

SARAL is an early-stage prototype. It currently has no verified open opportunities in its database, so it may return zero results. The included sample feed contains fictional demonstration data and must not be treated as a real scholarship or official listing.

Users should confirm details with the relevant official source before applying.

## Technology

- Python
- FastAPI
- Uvicorn
- SQLite
- Pytest

## Run Locally

1. Install Python.
2. Clone this repository.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the application:

   ```bash
   python -m uvicorn app.web:app --reload --port 8001
   ```

5. Open http://127.0.0.1:8001 in your browser.

The application runs locally. External information sources and public availability are not guaranteed by the prototype itself.

## Current Status

SARAL is a prototype. Future improvements include integrating reliable official data sources, expanding eligibility rules, and improving the opportunity verification workflow.

## Repository

https://github.com/daminikrishnachavithina-max/SARAL
