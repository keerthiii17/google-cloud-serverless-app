# Use official lightweight Python image
FROM python:3.11-slim

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True

# Set working directory inside container
ENV APP_HOME /app
WORKDIR $APP_HOME

# Copy application files
COPY . ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the web service using gunicorn
# - Port is dynamically assigned by Cloud Run (default is 8080)
# - Set worker/thread limits for serverless scalability
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
