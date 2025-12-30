# Enhanced Email Engine

A high-performance, scalable email processing system with queue management, template support, and REST API.

## Features

### Scalable Queue System

- **JSON-based persistent storage** with file pagination (100 emails per batch)
- **FIFO processing** with configurable batch sizes
- **Thread-safe operations** for concurrent access
- **Automatic cleanup** of processed emails

### 📧 Enhanced Email Sender

- **Retry logic** with exponential backoff (3 attempts by default)
- **Multipart email support** (HTML + plain text)
- **Connection pooling** for efficient SMTP connections
- **Priority levels** (High, Normal, Low)

### 🎨 Template Engine

- **File-based templates** stored in `templates/` directory
- **{{variable}} substitution** with double curly brace syntax
- **Automatic multipart generation** from single template
- **Template management** via API
- **Pre-defined templates** created automatically on first run
- **JSON manifest** (`templates/manifest.json`) for template discovery

### 🌐 REST API (FastAPI)

- **POST /email** - Submit emails to queue (with or without templates)
- **GET /status** - Get queue statistics and status
- **GET /health** - System health check
- **GET /templates** - List available templates
- **GET /workers/status** - Get background worker status
- **POST /process-batch** - Manually trigger batch processing
- **Interactive documentation** at `/docs`

### 📊 Performance & Reliability

- **Handles thousands of requests** with paginated queue storage
- **Worker pool** for concurrent email processing
- **Comprehensive logging** with rotation (5MB files, 3 backups)
- **Graceful error handling** and retry mechanisms

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│   API       │───▶│   Queue     │───▶│   Worker    │
│   (HTTP)    │    │   Server    │    │   Manager   │    │   Pool      │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                                 │
┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│   Template  │◀───│   Template  │    │   Email     │◀─────────┘
│   Files     │    │   Engine    │    │   Sender    │
└─────────────┘    └─────────────┘    └─────────────┘
```

## Quick Start

### Prerequisites

- Python 3.8+
- SMTP server credentials (configured in `.env` file)
- FastAPI and Uvicorn 

### Installation

1. **Clone and setup environment:**

```bash
# Create .env file from example
cp .env.example .env

# Edit .env with your SMTP credentials
nano .env
```

2. **Install dependencies:**

```bash
pip install fastapi uvicorn pydantic python-dotenv
```

3. **Start the API server:**

```bash
python api_server.py
```

4. **Access the API documentation:**

Open http://localhost:8000/docs in your browser

### Configuration (.env file)

```env
SENDER_EMAIL=your-email@example.com
PASSWORD="your-smtp-password"
SMTP_SERVER=smtp.gmail.com
PORT=465
```

## Usage Examples

### Submit an Email via API

```bash
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Welcome Email",
    "body": "Welcome to our service!",
    "to_email": "user@example.com",
    "format": "multipart"
  }'
```

### Submit Email with Template

The system comes with 4 pre-defined templates. Simply specify the template name and provide the required variables:

```bash
# Verification email with code
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "to_email": "user@example.com",
    "template_name": "verify",
    "template_vars": {
      "code": "123456",
      "app_name": "MyApp",
      "expiry_minutes": 30
    }
  }'

# Welcome email for new users
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "to_email": "user@example.com",
    "template_name": "welcome",
    "template_vars": {
      "name": "John Doe",
      "username": "johndoe",
      "email": "john@example.com",
      "signup_date": "2023-12-23",
      "app_name": "MyApp"
    }
  }'

# Password reset confirmation
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "to_email": "user@example.com",
    "template_name": "password_reset",
    "template_vars": {
      "name": "John Doe",
      "app_name": "MyApp",
      "reset_code": "ABC123",
      "expiry_hours": 24
    }
  }'

# General notification
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "to_email": "user@example.com",
    "template_name": "notification",
    "template_vars": {
      "title": "System Maintenance",
      "message": "Our system will undergo maintenance on Saturday from 2-4 AM UTC.",
      "app_name": "MyApp"
    }
  }'
```

### Check Queue Status

```bash
curl "http://localhost:8000/status"
```

### Health Check

```bash
curl "http://localhost:8000/health"
```

### List Available Templates

```bash
# Simple list
curl "http://localhost:8000/templates"

# Detailed information with placeholders
curl "http://localhost:8000/templates?detailed=true"
```

## Project Structure

```
Email_engine/
├── api_server.py           # FastAPI server with REST endpoints
├── queue_manager.py        # JSON-based queue system with pagination
├── worker_pool.py          # Worker threads for concurrent processing
├── email_sender.py         # Enhanced email sender with retry logic
├── template_engine.py      # Template system with variable substitution
├── config.py              # Configuration management (Pydantic)
├── logger_engine.py       # Logging system with rotation
├── email_engine.py        # Original email engine (backward compatibility)
├── .env                   # Environment variables (SMTP credentials)
├── PROGRESS.md            # Development progress tracking
├── README.md              # This file
│
├── data/                  # Queue storage (auto-generated)
│   └── queue/
│       ├── batch_001.json
│       ├── batch_002.json
│       └── ...
│
├── templates/             # Email templates (auto-generated)
│   ├── welcome.txt
│   ├── welcome.html
│   ├── password_reset.txt
│   └── password_reset.html
│
├── logs/                  # Log files (auto-generated)
│   ├── api_server.log
│   ├── email_sender.log
│   ├── worker_pool.log
│   └── ...
│
└── tests/                 # Test files
    ├── test_queue_system.py
    ├── test_email_sender.py
    ├── test_template_engine.py
    ├── test_api_integration.py
    └── integration_test.py
```

## Testing

Run the complete test suite:

```bash
# Test queue system
python test_queue_system.py

# Test email sender
python test_email_sender.py

# Test template engine
python test_template_engine.py

# Test API integration
python test_api_integration.py

# Run full integration test
python integration_test.py
```

## Performance Characteristics

- **Queue Capacity**: Limited only by disk space (JSON files with pagination)
- **Processing Speed**: Configurable worker threads (default: 3)
- **Batch Size**: Configurable (default: 100 emails per batch)
- **Retry Logic**: 3 attempts with exponential backoff
- **Memory Usage**: Minimal (processes emails in batches from disk)

## Error Handling

- **Failed emails**: Retried 3 times, then moved to failed queue
- **SMTP errors**: Connection pooling with automatic reconnection
- **Template errors**: Graceful fallback to plain text
- **Queue errors**: File locking for thread safety
- **API errors**: Proper HTTP status codes and error messages

## Monitoring

- **Log files**: Rotated automatically (5MB max, 3 backups)
- **Queue statistics**: Available via `/status` endpoint
- **System health**: Available via `/health` endpoint
- **Performance metrics**: Logged for each batch processed

## Production Deployment

### Recommended Setup

1. **Use process manager** (systemd, supervisor) to run `api_server.py`

2. **Configure logging** to central location
3. **Set up monitoring** for queue size and processing rate
4. **Implement alerting** for failed batches
5. **Regular backups** of template files

### Scaling Considerations

- Increase `num_workers` in `WorkerPool` for higher throughput
- Adjust `batch_size` in `QueueManager` based on email volume
- Monitor disk usage for queue storage
- Consider database backend for very high volumes (>1M emails)

## Backward Compatibility

The original `email_engine.py` function is preserved:

```python
from email_sender import send_simple_email

send_simple_email(
    subject="Test",
    body="Hello",
    to_email="user@example.com",
    format="plain"  # or "html" or "multipart"
)
```

 ## MISSING SECURYTY DONT USE
 
    - meh
