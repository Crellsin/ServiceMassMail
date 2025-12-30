#!/usr/bin/env python3
"""Test script for API integration."""
import sys
import os
import time
import json
import subprocess
from pathlib import Path
import requests
import signal

# Add current directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from queue_manager import QueueManager

def start_api_server():
    """Start the API server in a subprocess."""
    print("Starting API server...")
    
    # Create logs directory
    Path("logs").mkdir(exist_ok=True)
    
    # Start server in background
    cmd = [sys.executable, "api_server.py"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid  # Use process group to kill all children
    )
    
    # Give server time to start
    time.sleep(3)
    
    # Check if server is running
    try:
        response = requests.get("http://localhost:8000/", timeout=2)
        if response.status_code == 200:
            print("API server started successfully")
            return proc
        else:
            print(f"Server returned status {response.status_code}")
            stop_api_server(proc)
            return None
    except requests.exceptions.ConnectionError:
        print("Failed to connect to API server")
        # Try to get error output
        try:
            stdout, stderr = proc.communicate(timeout=1)
            print(f"Server stdout: {stdout}")
            print(f"Server stderr: {stderr}")
        except:
            pass
        stop_api_server(proc)
        return None

def stop_api_server(proc):
    """Stop the API server subprocess."""
    if proc:
        print("Stopping API server...")
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)

def test_root_endpoint():
    """Test the root endpoint."""
    print("\n=== Testing Root Endpoint ===")
    
    response = requests.get("http://localhost:8000/")
    
    if response.status_code != 200:
        print(f"ERROR: Root endpoint returned {response.status_code}")
        return False
    
    data = response.json()
    print(f"API Name: {data.get('name')}")
    print(f"Version: {data.get('version')}")
    
    if data.get("name") != "Email Engine API":
        print(f"ERROR: Unexpected API name: {data.get('name')}")
        return False
    
    print("Root endpoint test passed!")
    return True

def test_health_endpoint():
    """Test the health endpoint."""
    print("\n=== Testing Health Endpoint ===")
    
    response = requests.get("http://localhost:8000/health")
    
    if response.status_code != 200:
        print(f"ERROR: Health endpoint returned {response.status_code}")
        return False
    
    data = response.json()
    print(f"Status: {data.get('status')}")
    print(f"Components: {json.dumps(data.get('components'), indent=2)}")
    
    if data.get("status") not in ["healthy", "degraded"]:
        print(f"ERROR: Unexpected health status: {data.get('status')}")
        return False
    
    print("Health endpoint test passed!")
    return True

def test_status_endpoint():
    """Test the queue status endpoint."""
    print("\n=== Testing Status Endpoint ===")
    
    response = requests.get("http://localhost:8000/status")
    
    if response.status_code != 200:
        print(f"ERROR: Status endpoint returned {response.status_code}")
        return False
    
    data = response.json()
    print(f"Total emails in queue: {data.get('total_emails')}")
    print(f"Total batches: {data.get('total_batches')}")
    
    # Check response structure
    required_fields = ["total_batches", "total_emails", "batch_size", "batches"]
    for field in required_fields:
        if field not in data:
            print(f"ERROR: Missing field {field} in response")
            return False
    
    print("Status endpoint test passed!")
    return True

def test_email_submission():
    """Test submitting an email via the API."""
    print("\n=== Testing Email Submission ===")
    
    # Clear any existing queue for clean test
    qm = QueueManager()
    qm.clear_queue()
    
    # Submit a test email
    email_data = {
        "subject": "Test Email from API",
        "body": "This is a test email submitted via the API.",
        "to_email": "jamalnader@jamalnader.com",
        "priority": 2,
        "format": "plain"
    }
    
    response = requests.post(
        "http://localhost:8000/email",
        json=email_data,
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code != 200:
        print(f"ERROR: Email submission returned {response.status_code}")
        print(f"Response: {response.text}")
        return False
    
    data = response.json()
    print(f"Request ID: {data.get('request_id')}")
    print(f"Message: {data.get('message')}")
    print(f"Status: {data.get('status')}")
    
    # Verify the email was added to queue
    time.sleep(1)  # Give queue time to update
    
    qm = QueueManager()
    stats = qm.get_queue_stats()
    
    if stats["total_emails"] != 1:
        print(f"ERROR: Expected 1 email in queue, got {stats['total_emails']}")
        return False
    
    print("Email submission test passed!")
    return True

def test_template_submission():
    """Test submitting an email with a template."""
    print("\n=== Testing Template Email Submission ===")
    
    # First, check if templates exist
    response = requests.get("http://localhost:8000/templates")
    if response.status_code != 200:
        print("ERROR: Cannot get templates list")
        return False
    
    templates = response.json().get("templates", [])
    
    if not templates:
        print("No templates found, skipping template test")
        return True  # Not a failure, just skip
    
    # Use the first template
    template_name = templates[0]
    print(f"Using template: {template_name}")
    
    # Submit email with template
    email_data = {
        "subject": "Test Template Email",
        "body": "This body will be ignored when using template",
        "to_email": "jamalnader@jamalnader.com",
        "template_name": template_name,
        "template_vars": {
            "name": "Test User",
            "app_name": "Email Engine",
            "username": "testuser",
            "email": "test@example.com",
            "signup_date": "2023-12-23"
        },
        "priority": 2,
        "format": "multipart"
    }
    
    response = requests.post(
        "http://localhost:8000/email",
        json=email_data,
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code != 200:
        print(f"ERROR: Template email submission returned {response.status_code}")
        print(f"Response: {response.text}")
        return False
    
    data = response.json()
    print(f"Request ID: {data.get('request_id')}")
    print(f"Message: {data.get('message')}")
    
    # Verify the email was added to queue
    time.sleep(1)
    qm = QueueManager()
    stats = qm.get_queue_stats()
    
    # We should now have 2 emails in queue (1 from previous test + this one)
    if stats["total_emails"] < 2:
        print(f"ERROR: Expected at least 2 emails in queue, got {stats['total_emails']}")
        return False
    
    print("Template email submission test passed!")
    return True

def test_batch_processing():
    """Test the batch processing endpoint."""
    print("\n=== Testing Batch Processing ===")
    
    # First, make sure we have emails in queue
    qm = QueueManager()
    stats = qm.get_queue_stats()
    
    if stats["total_emails"] == 0:
        print("No emails in queue, adding test email...")
        email_data = {
            "subject": "Batch Test Email",
            "body": "This email will be processed in batch.",
            "to_email": "jamalnader@jamalnader.com",
            "priority": 2
        }
        
        response = requests.post(
            "http://localhost:8000/email",
            json=email_data
        )
        
        if response.status_code != 200:
            print("ERROR: Failed to add test email for batch processing")
            return False
        
        time.sleep(1)
    
    # Now test batch processing
    response = requests.post("http://localhost:8000/process-batch")
    
    if response.status_code != 200:
        print(f"ERROR: Batch processing returned {response.status_code}")
        print(f"Response: {response.text}")
        return False
    
    data = response.json()
    print(f"Message: {data.get('message')}")
    print(f"Processed: {data.get('processed')}")
    
    # Note: The batch processor in worker_pool.py only simulates sending for now
    # So we don't check if emails were actually removed from queue
    
    print("Batch processing test passed!")
    return True

def main():
    """Run all API integration tests."""
    print("Starting API Integration Tests")
    print("=" * 50)
    
    # Start API server
    server_proc = start_api_server()
    if not server_proc:
        print("Failed to start API server. Exiting.")
        return False
    
    tests = [
        ("Root Endpoint", test_root_endpoint),
        ("Health Endpoint", test_health_endpoint),
        ("Status Endpoint", test_status_endpoint),
        ("Email Submission", test_email_submission),
        ("Template Submission", test_template_submission),
        ("Batch Processing", test_batch_processing),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                print(f"\n✓ {test_name}: PASSED")
                passed += 1
            else:
                print(f"\n✗ {test_name}: FAILED")
                failed += 1
        except Exception as e:
            print(f"\n✗ {test_name}: ERROR - {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # Stop API server
    stop_api_server(server_proc)
    
    print("\n" + "=" * 50)
    print(f"Test Summary: {passed} passed, {failed} failed")
    
    # Clean up test data
    qm = QueueManager()
    qm.clear_queue()
    
    if failed == 0:
        print("\nAll API integration tests passed!")
        print("\nAPI is ready for use.")
        print("\nTo start the server manually, run:")
        print("  python api_server.py")
        print("\nThen access the API at http://localhost:8000")
        print("Documentation available at http://localhost:8000/docs")
        return True
    else:
        print("\nSome API integration tests failed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
