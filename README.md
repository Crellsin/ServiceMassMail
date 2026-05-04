# Email Engine

A high-performance Microservice, asynchronous email processing pipeline with a file-based queuing system, multipart template rendering engine, and RESTful API interface. Designed for reliable bulk email dispatch with configurable concurrency, retry semantics, and fault isolation.

## Features

### Queue Management

- **Persistent storage**: Egress emails are serialized as JSON and organized into paginated batch files (default: 100 emails per batch), bounded only by available disk space.
- **FIFO ordering**: Batches are processed in first-in, first-out order. Batch processing order is deterministic based on file system enumeration.
- **Thread-safe operations**: All queue mutations are guarded by a reentrant lock (`threading.RLock`), ensuring correctness under concurrent access from multiple worker threads.
- **Atomic file operations**: Writes are performed via temporary file creation followed by atomic rename to prevent partial writes and data corruption.
- **Automatic cleanup**: Processed batches are moved to a trash directory with a timestamp and status annotation; permanently failed emails are routed to a dead-letter store.

### Email Dispatch

- **Retry with exponential backoff**: Configurable retry attempts (default: 3) with exponential delay scaling (base: 1 second).
- **Connection pooling**: SMTP connections are cached and reused across sends. Pooled connections are validated via `NOOP` before reuse; stale connections are evicted automatically.
- **Multi-format support**: Supports plain text, HTML, and multipart (alternative) MIME structures.
- **Priority classification**: Three-tier priority (High, Normal, Low) mapped to integer levels 1 through 3.
- **Batch processing**: Worker pool dispatches emails in configurable batch sizes with partial-failure isolation (individual email failures do not abort the batch).

### Template Engine

- **File-backed templates**: Templates are stored as plain text files in the `templates/` directory, with a JSON manifest (`templates/manifest.json`) for discovery.
- **Variable interpolation**: Uses `{{variable}}` double-curly-brace syntax for substitution at render time.
- **Automatic multipart generation**: When both `.txt` and `.html` variants of a template exist, the engine produces a multipart/alternative MIME message automatically.
- **Pre-defined templates**: Four default templates (verify, welcome, password_reset, notification) are generated on first run.
- **RESTful management**: Templates are discoverable via the API with optional metadata output.

### REST API

The API is implemented with FastAPI and exposes the following endpoints:

| Method | Endpoint               | Description                                           |
|--------|------------------------|-------------------------------------------------------|
| POST   | `/email`               | Submits an email to the processing queue              |
| GET    | `/status`              | Returns queue statistics and batch metadata           |
| GET    | `/health`              | Performs a health check on all system components      |
| GET    | `/templates`           | Lists available templates (supports `?detailed=true`) |
| GET    | `/workers/status`      | Reports background worker pool state                  |
| POST   | `/process-batch`       | Manually triggers processing of the next batch        |
| GET    | `/docs`                | Interactive API documentation (Swagger UI)            |

### Observability

- **Structured logging**: Each module writes to a dedicated log file under `logs/` with automatic rotation (5 MB per file, 3 backup rotations).
- **Health monitoring**: The `/health` endpoint validates the queue manager, template engine, and SMTP sender connectivity, returning a degraded status if any component is non-functional.
- **Dead-letter queue**: Emails that exhaust their retry limit are persisted to `data/dead_letter/` with the failure reason and original payload for forensic analysis.

## Architecture

```
+----------------+    +----------------+    +----------------+    +----------------+
|   HTTP Client  |--->|  API Server    |--->|  Queue Manager |--->|  Worker Pool   |
|   (External)   |    |  (FastAPI)     |    |  (JSON Batches)|    |  (Thread Pool) |
+----------------+    +----------------+    +----------------+    +--------+-------+
                                                                           |
+----------------+    +----------------+    +----------------+             |
|  Template      |<---|  Template      |    |  Email Sender  |<-----------+
|  Files         |    |  Engine        |    |  (SMTP Client) |
+----------------+    +----------------+    +----------------+
```

The processing pipeline operates as follows:

1. Incoming email requests are received by the FastAPI server and converted into `EmailRequest` data objects.
2. If a template name is specified, the template engine renders the subject and body using variable substitution before enqueuing.
3. The queue manager persists the request to a JSON batch file using atomic write semantics.
4. Worker threads in the pool poll the queue manager for available batches, claim a batch via atomic file rename (`.processing` suffix), and dispatch emails via the `EmailSender`.
5. Completed batches are moved to the trash directory. Emails that exceed the retry threshold are routed to the dead-letter store.

## Quick Start

### Prerequisites

- Python 3.8 or later
- Access to an SMTP server with credentials
- `pip` package installer

### Installation

1. Clone the repository and configure environment variables:

```bash
cp .env.example .env
```

2. Edit `.env` with your SMTP credentials:

```bash
nano .env
```

3. Install dependencies:

```bash
pip install fastapi uvicorn pydantic python-dotenv
```

4. Start the API server:

```bash
python api_server.py
```

5. Access the API documentation at `http://localhost:8000/docs`.

### Configuration

All configuration is managed through environment variables, read at process start by a Pydantic `Settings` model in `config.py`:

```env
SENDER_EMAIL=your-email@example.com
PASSWORD="your-smtp-password"
SMTP_SERVER=smtp.gmail.com
PORT=465
AUTO_PROCESSING_ENABLED=True
NUM_WORKERS=3
WORKER_POLLING_INTERVAL=5
```

| Variable                  | Type    | Default | Description                                    |
|---------------------------|---------|---------|------------------------------------------------|
| `SENDER_EMAIL`            | string  | --      | SMTP authentication username and From address  |
| `PASSWORD`                | string  | --      | SMTP authentication password                   |
| `SMTP_SERVER`             | string  | --      | SMTP server hostname                           |
| `PORT`                    | integer | --      | SMTP server port (typically 465 for SSL)       |
| `AUTO_PROCESSING_ENABLED` | boolean | True    | Enable background worker pool on startup       |
| `NUM_WORKERS`             | integer | 3       | Number of concurrent worker threads            |
| `WORKER_POLLING_INTERVAL` | integer | 5       | Polling interval in seconds for workers        |

## Usage

### Submit an Email

```bash
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Welcome Email",
    "body": "Welcome to our service.",
    "to_email": "user@example.com",
    "format": "multipart"
  }'
```

### Submit an Email Using a Template

The system includes four pre-defined templates (`verify`, `welcome`, `password_reset`, `notification`). Provide the template name and the required variables.

```bash
# Verification email with a confirmation code
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

# Welcome message for new user registrations
curl -X POST "http://localhost:8000/email" \
  -H "Content-Type: application/json" \
  -d '{
    "to_email": "user@example.com",
    "template_name": "welcome",
    "template_vars": {
      "name": "John Doe",
      "username": "johndoe",
      "email": "john@example.com",
      "signup_date": "2026-05-04",
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

### Queue Status

```bash
curl "http://localhost:8000/status"
```

### Health Check

```bash
curl "http://localhost:8000/health"
```

### List Templates

```bash
# Basic listing
curl "http://localhost:8000/templates"

# Detailed metadata including placeholders
curl "http://localhost:8000/templates?detailed=true"
```

## Project Structure

```
Email_engine/
+-- api_server.py            FastAPI REST API server with endpoint definitions
+-- queue_manager.py         JSON-serialized queue with file-based pagination
+-- worker_pool.py           Thread pool for concurrent batch processing
+-- email_sender.py          SMTP client with retry, pooling, and multipart support
+-- template_engine.py       File-backed template rendering with variable substitution
+-- config.py                Pydantic-based environment configuration model
+-- logger_engine.py         Rotating file logger setup utility
+-- email_engine.py          Legacy module maintained for backward compatibility
+-- .env                     Environment variables (SMTP credentials, runtime config)
+-- LICENSE                  PolyForm Strictly Noncommercial License 1.0.0
+-- README.md                This document

+-- data/
|   +-- queue/               Active batch files (auto-generated)
|   +-- dead_letter/         Permanently failed emails with metadata
|   +-- trash/               Processed or stale batch files

+-- templates/               Email template files (auto-generated)
|   +-- manifest.json        Template metadata and variable definitions
|   +-- verify.txt
|   +-- verify.html
|   +-- welcome.txt
|   +-- welcome.html
|   +-- password_reset.txt
|   +-- password_reset.html
|   +-- notification.txt
|   +-- notification.html

+-- logs/                    Rotating log output (auto-generated)

+-- tests/                   Test suite
    +-- test_queue_system.py
    +-- test_email_sender.py
    +-- test_template_engine.py
    +-- test_api_integration.py
    +-- integration_test.py
```

## Testing

Execute individual test modules or the full integration suite:

```bash
python tests/test_queue_system.py
python tests/test_email_sender.py
python tests/test_template_engine.py
python tests/test_api_integration.py
python tests/integration_test.py
```

## Performance Characteristics

| Metric                    | Value                              |
|---------------------------|------------------------------------|
| Queue capacity            | Disk-bound (JSON batch files)      |
| Batch size                | Configurable (default: 100 emails) |
| Worker threads            | Configurable (default: 3)          |
| Retry attempts            | Configurable (default: 3)          |
| Retry backoff strategy    | Exponential (2^n * base delay)     |
| Memory footprint          | O(1) per batch (streamed from disk)|
| SMTP connection pool      | LRU-style with live-connection check|

## Error Handling

- **Transient failures**: SMTP send failures trigger automatic retry with exponential backoff. Failed connections are evicted from the pool and re-established.
- **Permanent failures**: Emails that exhaust their retry limit are persisted to `data/dead_letter/` with failure metadata and are not re-queued automatically.
- **Template errors**: Missing templates or invalid variable references raise `ValueError`, which is surfaced to the client as HTTP 400.
- **Queue corruption**: Invalid JSON in batch files is detected on read; corrupted files are moved to the trash directory and logged.
- **Stale processing files**: Batch files left in `.processing` state for more than one hour are assumed orphaned and are moved to trash on the next queue poll.
- **API errors**: All internal exceptions are caught and returned as structured HTTP error responses with appropriate status codes.

## Monitoring

- **Log rotation**: Each component writes to a dedicated log file; files are rotated at 5 MB with up to 3 historical backups.
- **Queue statistics**: The `/status` endpoint reports total batch count, pending email count, and per-batch metadata.
- **Health checks**: The `/health` endpoint validates queue manager, template engine, and email sender connectivity.
- **Worker monitoring**: The `/workers/status` endpoint reports active worker count and per-worker state.

## Production Deployment

### Recommended Setup

1. Use a process supervisor (systemd, supervisor) to manage the `api_server.py` process with automatic restart.
2. Centralize logs to a dedicated monitoring platform (e.g., journald, ELK stack, or equivalent).
3. Implement external monitoring for queue depth, processing latency, and failure rates.
4. Configure alerting for sustained queue growth or elevated dead-letter rates.
5. Schedule regular backups of the `templates/` directory and configuration.

### Scaling

- Increase `NUM_WORKERS` to improve throughput on systems with sufficient CPU and SMTP capacity.
- Adjust `batch_size` to balance per-batch processing duration against polling overhead.
- Monitor disk I/O under sustained load; queue storage is file-system-backed and may become a bottleneck at high throughput.
- For production workloads exceeding 1 million emails, consider migrating from file-backed storage to a database-backed queue.

## Backward Compatibility

The legacy `send_simple_email` function from the original `email_engine.py` module is preserved:

```python
from email_sender import send_simple_email

send_simple_email(
    subject="Test",
    body="Hello",
    to_email="user@example.com",
    format="plain"  # Accepts "plain", "html", or "multipart"
)
```

## Known Limitations

- **No authentication or authorization middleware**: The API has no built-in access control. In its current state, any client capable of reaching the HTTP endpoint can submit emails and query system status. Production deployments must implement authentication at the reverse proxy or application layer.
- **Race conditions in batch claiming**: The worker pool uses atomic file rename as a distributed lock for batch claiming. Under high concurrency with a large number of workers, contention on file system operations may lead to transient `FileNotFoundError` or `PermissionError` exceptions. These are handled gracefully (the worker retries), but the approach is not equivalent to a proper distributed locking mechanism.
- **File-system-based queue**: Queue persistence relies on the local file system. This implementation does not provide the transactional guarantees, replication, or durability semantics of a dedicated message broker. Data loss is possible in the event of an unclean shutdown during a write operation.
- **No TLS termination**: The FastAPI server runs over plain HTTP on port 8000. In production, a reverse proxy (e.g., nginx, Caddy, or a cloud load balancer) should terminate TLS.

## License

This project is licensed under the [PolyForm Strictly Noncommercial License 1.0.0](https://polyformproject.org/licenses/strictly-noncommercial/1.0.0). See the `LICENSE` file for the full license text.

Copyright Crellsin. All rights reserved.
