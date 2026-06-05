FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libsentencepiece-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY backend/requirements_docker.txt /app/requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir sentencepiece==0.1.99 protobuf

# Copy backend code
COPY backend /app/backend

# Copy local model if exists (Optional: Cloud Build context might not include it if too large, 
# but ignoring it is safer if we rely on HF download. 
# For now, we assume HF download strategy for Cloud Run to keep image size manageable)

# Set environment variables
ENV MOCK_MODE=False
ENV PORT=8080

# Expose port
EXPOSE 8080

# Command to run the application
# Cloud Run injects PORT env var
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
