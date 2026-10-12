
# Employee Attendance & Analytics API

A REST API built with FastAPI and MongoDB for employee management, attendance tracking, attendance regularization, and analytics.

## Features

- Employee creation and listing
- Attendance punch-in and punch-out
- Attendance filtering and pagination
- Attendance regularization with audit history
- Monthly employee attendance analytics
- Department summary and daily trend analytics
- Late-arrival leaderboard
- MongoDB query-plan inspection

## Tech Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic

## Requirements

- Python 3.10+
- MongoDB running locally or on an accessible server
- pip

## Setup

1. Clone this repository.
2. Open the project directory in a terminal.
3. Create and activate a virtual environment.
4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Configure `MONGO_URI` and `MONGO_DB` environment variables if needed. The default database name is `attendance_db`.
6. Start the API:

   ```bash
   py -m uvicorn app.main:app --port 8000
   ```

7. Open the interactive API documentation at:

   http://127.0.0.1:8000/docs

## Configuration

- `MONGO_URI`: MongoDB connection URI.
- `MONGO_DB`: MongoDB database name.

Do not commit `.env` files, credentials, or other secrets.

## API Endpoints

- `GET /health`
- `POST /employees`
- `GET /employees`
- `POST /attendance/punch-in`
- `POST /attendance/punch-out`
- `GET /attendance`
- `PATCH /attendance/{emp_code}/{date}`
- `GET /analytics/employees/{emp_code}/monthly`
- `GET /analytics/departments/summary`
- `GET /analytics/leaderboard/late`
- `GET /analytics/departments/{department}/trend`
- `GET /admin/explain/{endpoint}`

## Testing

Use `/docs` to test endpoints and review their response codes and response bodies. Verify attendance calculations, validation rules, audit history, and MongoDB query plans before submission.
