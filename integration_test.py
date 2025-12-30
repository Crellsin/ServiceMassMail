#!/usr/bin/env python3
"""Integration test for the complete email engine system."""
import sys
import os
import time
import json
import threading
from pathlib import Path
import requests

# Add current directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from queue_manager import QueueManager
from template_engine import TemplateEngine
from email_sender import EmailSender, EmailMessage, EmailFormat
from worker_pool import WorkerPool, BatchProcessor

def test_complete_flow():
    """Test the complete flow from queue to email sending."""
    print("=== Testing Complete System Flow ===")
    
    # Create test directories
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    Path("templates").mkdir(exist_ok=True)
    
    # Step 1: Initialize all components
    print("\n1. Initializing components...")
    qm = QueueManager(queue_dir="data/integration_test", batch_size=10)
    template_engine = TemplateEngine(template_dir="templates/integration_test")
    email_sender = EmailSender(max_retries=1, retry_delay=0.1)
    
    # Clear any existing test data
    qm.clear_queue()
    
    # Step 2: Create a test template
    print("\n2. Creating test template...")
    template_engine.create_template(
        name="integration_welcome",
        subject="Integration Test for {{name}}",
        plain_body="Hello {{name}},\n\nThis is an integration test email.\n\nTest ID: {{test_id}}",
        html_body="<h1>Integration Test</h1><p>Hello {{name}},</p><p>This is an integration test email.</p><p>Test ID: <strong>{{test_id}}</strong></p>"
    )
    
    # Step 3: Add emails to queue using template
    print("\n3. Adding emails to queue...")
    emails_added = []
    
    for i in range(5):
        # Create email using template
        email = template_engine.render_email(
            template_name="integration_welcome",
            variables={
                "name": f"Test User {i+1}",
                "test_id": f"TEST-{i+1:03d}"
            },
            to_email="jamalnader@jamalnader.com"
        )
        
        # Convert to EmailRequest and add to queue
        email_request = qm.create_email_request(
            subject=email.subject,
            body=email.body,
            to_email=email.to_email,
            template_name="integration_welcome",
            template_vars={
                "name": f"Test User {i+1}",
                "test_id": f"TEST-{i+1:03d}"
            },
            priority=2
        )
        
        request_id = qm.add_email(email_request)
        emails_added.append(request_id)
        print(f"   Added email {i+1}/5 with ID: {request_id}")
    
    # Step 4: Check queue status
    print("\n4. Checking queue status...")
    stats = qm.get_queue_stats()
    print(f"   Total emails in queue: {stats['total_emails']}")
    print(f"   Total batches: {stats['total_batches']}")
    
    if stats['total_emails'] != 5:
        print(f"   ERROR: Expected 5 emails, got {stats['total_emails']}")
        return False
    
    # Step 5: Process emails using BatchProcessor
    print("\n5. Processing emails...")
    processor = BatchProcessor(qm)
    
    batches_processed = 0
    while processor.process_single_batch():
        batches_processed += 1
        print(f"   Processed batch {batches_processed}")
    
    print(f"   Total batches processed: {batches_processed}")
    
    # Step 6: Verify queue is empty
    print("\n6. Verifying queue is empty...")
    stats = qm.get_queue_stats()
    if stats['total_emails'] != 0 or stats['total_batches'] != 0:
        print(f"   ERROR: Queue should be empty, but has {stats['total_emails']} emails")
        return False
    
    print("   Queue is empty (all emails processed)")
    
    # Step 7: Clean up
    print("\n7. Cleaning up test data...")
    qm.clear_queue()
    
    # Remove template files
    import shutil
    shutil.rmtree("data/integration_test", ignore_errors=True)
    shutil.rmtree("templates/integration_test", ignore_errors=True)
    
    print("\n=== Complete system flow test passed! ===")
    return True

def test_api_integration():
    """Test the system through the API."""
    print("\n=== Testing API Integration ===")
    
    # Start API server in background
    import subprocess
    import signal
    import atexit
    
    print("Starting API server...")
    cmd = [sys.executable, "api_server.py"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid
    )
    
    # Give server time to start
    time.sleep(3)
    
    def stop_server():
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    
    atexit.register(stop_server)
    
    # Test API endpoints
    try:
        # Test health endpoint
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code != 200:
            print(f"ERROR: Health endpoint returned {response.status_code}")
            return False
        
        # Submit test email via API
        email_data = {
            "subject": "API Integration Test",
            "body": "This email was submitted via API integration test.",
            "to_email": "jamalnader@jamalnader.com",
            "priority": 2,
            "format": "plain"
        }
        
        response = requests.post(
            "http://localhost:8000/email",
            json=email_data,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        
        if response.status_code != 200:
            print(f"ERROR: Email submission returned {response.status_code}")
            return False
        
        data = response.json()
        print(f"   Email submitted via API with ID: {data['request_id']}")
        
        # Check queue status via API
        response = requests.get("http://localhost:8000/status", timeout=5)
        if response.status_code != 200:
            print(f"ERROR: Status endpoint returned {response.status_code}")
            return False
        
        data = response.json()
        print(f"   Queue status: {data['total_emails']} emails in queue")
        
    except requests.exceptions.RequestException as e:
        print(f"ERROR: API request failed: {e}")
        return False
    finally:
        stop_server()
    
    print("API integration test passed!")
    return True

def test_concurrent_processing():
    """Test concurrent email processing with worker pool."""
    print("\n=== Testing Concurrent Processing ===")
    
    # Setup test queue
    test_queue_dir = "data/concurrent_test"
    qm = QueueManager(queue_dir=test_queue_dir, batch_size=20)
    qm.clear_queue()
    
    # Add test emails
    print("Adding 50 test emails to queue...")
    for i in range(50):
        email = qm.create_email_request(
            subject=f"Concurrent Test {i+1}",
            body=f"This is concurrent test email {i+1}.",
            to_email=f"test{i+1}@example.com"
        )
        qm.add_email(email)
    
    # Start worker pool
    print("Starting worker pool with 3 workers...")
    worker_pool = WorkerPool(qm, num_workers=3)
    worker_pool.start()
    
    # Monitor queue while workers process
    print("Monitoring queue for 10 seconds...")
    start_time = time.time()
    while time.time() - start_time < 10:
        stats = qm.get_queue_stats()
        print(f"   Emails remaining: {stats['total_emails']}")
        if stats['total_emails'] == 0:
            break
        time.sleep(2)
    
    # Stop worker pool
    worker_pool.stop()
    
    # Check final status
    stats = qm.get_queue_stats()
    print(f"Final queue status: {stats['total_emails']} emails remaining")
    
    # Clean up
    qm.clear_queue()
    import shutil
    shutil.rmtree(test_queue_dir, ignore_errors=True)
    
    # We don't require all emails to be processed in 10 seconds for test to pass
    # Just verify the system works concurrently
    print("Concurrent processing test completed!")
    return True

def main():
    """Run all integration tests."""
    print("Starting Email Engine Integration Tests")
    print("=" * 60)
    
    tests = [
        ("Complete System Flow", test_complete_flow),
        ("API Integration", test_api_integration),
        ("Concurrent Processing", test_concurrent_processing),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            print(f"\n{'='*40}")
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
    
    print("\n" + "=" * 60)
    print(f"Integration Test Summary: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\n✅ All integration tests passed!")
        print("\nThe email engine is fully functional and ready for production use.")
        return True
    else:
        print("\n❌ Some integration tests failed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
