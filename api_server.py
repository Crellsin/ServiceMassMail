from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import uvicorn
import logging
from datetime import datetime

from queue_manager import QueueManager, EmailRequest
from template_engine import TemplateEngine
from email_sender import EmailSender, EmailMessage, EmailFormat
from worker_pool import WorkerPool
from logger_engine import setup_logger
from config import settings

# Initialize components
queue_manager = QueueManager()
template_engine = TemplateEngine()
worker_pool = None

# Start worker pool if auto-processing is enabled
if settings.AUTO_PROCESSING_ENABLED:
    worker_pool = WorkerPool(queue_manager, num_workers=settings.NUM_WORKERS)
    worker_pool.start()

# Setup logger
logger = setup_logger("api_server", "logs/api_server.log")

# FastAPI app
app = FastAPI(
    title="Email Engine API",
    description="High-performance email queue and processing system",
    version="1.0.0"
)

# Pydantic models for request/response
class EmailRequestModel(BaseModel):
    """Model for email request via API."""
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (plain text or HTML)")
    to_email: str = Field(..., description="Recipient email address")
    template_name: Optional[str] = Field(None, description="Template name to use (optional)")
    template_vars: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Template variables")
    priority: int = Field(2, ge=1, le=3, description="Priority: 1=High, 2=Normal, 3=Low")
    format: str = Field("plain", description="Email format: 'plain', 'html', or 'multipart'")

class EmailResponse(BaseModel):
    """Response model for email submission."""
    request_id: str
    message: str
    status: str
    timestamp: str

class QueueStatusResponse(BaseModel):
    """Response model for queue status."""
    total_batches: int
    total_emails: int
    batch_size: int
    batches: List[Dict[str, Any]]

class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    timestamp: str
    components: Dict[str, str]

@app.post("/email", response_model=EmailResponse)
async def send_email(request: EmailRequestModel):
    """
    Submit an email to the queue for processing.
    
    - **subject**: Email subject
    - **body**: Email body (plain text or HTML)
    - **to_email**: Recipient email address
    - **template_name**: Template name to use (optional)
    - **template_vars**: Template variables (if using template)
    - **priority**: Priority level (1=High, 2=Normal, 3=Low)
    - **format**: Email format ('plain', 'html', 'multipart')
    """
    try:
        logger.info(f"Received email request for {request.to_email}")
        
        # If template is specified, use template engine
        if request.template_name:
            logger.info(f"Using template: {request.template_name}")
            try:
                # Render email from template
                email_msg = template_engine.render_email(
                    template_name=request.template_name,
                    variables=request.template_vars,
                    to_email=request.to_email,
                )
                
                # Create EmailRequest for queue
                email_request = queue_manager.create_email_request(
                    subject=email_msg.subject,
                    body=email_msg.body,
                    to_email=email_msg.to_email,
                    template_name=request.template_name,
                    template_vars=request.template_vars,
                    priority=request.priority
                )
                
            except ValueError as e:
                logger.error(f"Template error: {e}")
                raise HTTPException(status_code=400, detail=f"Template error: {e}")
        else:
            # Create EmailRequest directly
            email_request = queue_manager.create_email_request(
                subject=request.subject,
                body=request.body,
                to_email=request.to_email,
                #from_email=request.from_email,
                template_name=None,
                template_vars=None,
                priority=request.priority
            )
        
        # Add to queue
        request_id = queue_manager.add_email(email_request)
        logger.info(f"Email queued with ID: {request_id}")
        
        return EmailResponse(
            request_id=request_id,
            message="Email successfully queued for processing",
            status="queued",
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Error processing email request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status", response_model=QueueStatusResponse)
async def get_status():
    """Get current queue status and statistics."""
    try:
        stats = queue_manager.get_queue_stats()
        return QueueStatusResponse(**stats)
    except Exception as e:
        logger.error(f"Error getting queue status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint to verify system components."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {}
    }
    
    # Check queue manager
    try:
        queue_manager.get_queue_stats()
        health_status["components"]["queue_manager"] = "healthy"
    except Exception as e:
        health_status["components"]["queue_manager"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check template engine
    try:
        template_engine.list_templates()
        health_status["components"]["template_engine"] = "healthy"
    except Exception as e:
        health_status["components"]["template_engine"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check email sender (SMTP connection)
    try:
        # Try to create a sender and test connection (without sending)
        test_sender = EmailSender(max_retries=1)
        health_status["components"]["email_sender"] = "healthy"
    except Exception as e:
        health_status["components"]["email_sender"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

@app.get("/templates")
async def list_templates(detailed: bool = False):
    """
    List all available email templates.
    
    - **detailed**: If true, returns template metadata including placeholders and descriptions
    """
    try:
        templates = template_engine.list_templates()
        
        if not detailed:
            return {
                "templates": templates,
                "count": len(templates)
            }
        
        # Load manifest for detailed information
        import json
        manifest_file = Path("templates/manifest.json")
        if manifest_file.exists():
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            return {
                "templates": templates,
                "count": len(templates),
                "manifest": manifest_data
            }
        else:
            # Fallback to basic information if manifest doesn't exist
            return {
                "templates": templates,
                "count": len(templates),
                "default_templates": ["verify", "welcome", "password_reset", "notification"],
                "note": "Manifest file not found. Run template engine to generate it."
            }
            
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-batch")
async def process_batch():
    """
    Manually trigger processing of the next batch in the queue.
    Note: In production, this would be handled by the worker pool automatically.
    """
    try:
        from worker_pool import BatchProcessor
        processor = BatchProcessor(queue_manager)
        
        if processor.process_single_batch():
            return {"message": "Batch processed successfully", "processed": True}
        else:
            return {"message": "No batches available to process", "processed": False}
            
    except Exception as e:
        logger.error(f"Error processing batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Email Engine API",
        "version": "1.0.0",
        "description": "High-performance email queue and processing system",
        "endpoints": {
            "/email": "POST - Submit email to queue",
            "/status": "GET - Get queue status",
            "/health": "GET - Health check",
            "/templates": "GET - List available templates",
            "/process-batch": "POST - Manually process a batch",
            "/workers/status": "GET - Get background worker status"
        },
        "documentation": "/docs"
    }

@app.on_event("shutdown")
def shutdown_event():
    """Stop the worker pool on shutdown."""
    global worker_pool
    if worker_pool:
        logger.info("Stopping worker pool...")
        worker_pool.stop()

@app.get("/workers/status")
async def workers_status():
    """Get status of background workers."""
    try:
        if worker_pool:
            status = worker_pool.get_status()
            return {
                "auto_processing_enabled": settings.AUTO_PROCESSING_ENABLED,
                "worker_pool_status": "running",
                "status": status
            }
        else:
            return {
                "auto_processing_enabled": settings.AUTO_PROCESSING_ENABLED,
                "worker_pool_status": "disabled",
                "status": {
                    "total_workers": 0,
                    "active_workers": 0,
                    "workers": []
                }
            }
    except Exception as e:
        logger.error(f"Error getting worker status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logger.info("Starting Email Engine API server")
    logger.info(f"Auto-processing enabled: {settings.AUTO_PROCESSING_ENABLED}")
    if settings.AUTO_PROCESSING_ENABLED:
        logger.info(f"Worker pool started with {settings.NUM_WORKERS} workers")
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
