FROM python:3.11-slim

# Install system dependencies required for compiling C++ TagLib bindings
RUN apt-get update && apt-get install -y \
    build-essential \
    libtag1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Leverage Docker cache layers for Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .

# Streamlit network configuration
EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
