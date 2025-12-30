#!/usr/bin/env python3
"""Test script for the queue system."""
import sys
import os
import time
import json
from pathlib import Path

# Add current directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from queue_manager import QueueManager, EmailRequest
from worker_pool import BatchProcessor

def test_basic_queue_operations():
    """Test basic queue add and remove operations."""
    print("=== Testing Basic Queue Operations ===")
    
    # Initialize queue manager with a test directory
    test_queue_dir = "data/test_queue"
    qm = QueueManager(queue_dir=test_queue_dir, batch_size=10)  # Small batch for testing
    
    # Clear any existing test data
    qm.clear_queue()
    
    # Test 1: Add a single email
    print("\n1. Adding a single email...")
    email = qm.create_email_request(
        subject="Test Email 1",
        body="This is the first test email.",
        to_email="jamalnader@jamalnader.com"
    )
    request_id = qm.add_email(email)
    print(f"   Added email with ID: {request_id}")
    
    # Test 2: Add multiple emails
    print("\n2. Adding multiple emails...")
    for i in range(15):  # Will create 2 batches (batch size 10)
        email = qm.create_email_request(
            subject=f"Test Email {i+2}",
            body=f"This is test email {i+2}.",
            to_email=f"test{i+2}@example.com"
        )
        qm.add_email(email)
    print(f"   Added 15 more emails (total 16)")
    
    # Test 3: Check queue stats
    print("\n3. Checking queue statistics...")
    stats = qm.get_queue_stats()
    print(f"   Total batches: {stats['total_batches']}")
    print(f"   Total emails: {stats['total_emails']}")
    print(f"   Batch size: {stats['batch_size']}")
    
    # Verify we have 2 batches (16 emails, batch size 10 -> 2 batches)
    expected_batches = 2
    if stats['total_batches'] != expected_batches:
        print(f"   ERROR: Expected {expected_batches} batches, got {stats['total_batches']}")
        return False
    if stats['total_emails'] != 16:
        print(f"   ERROR: Expected 16 emails, got {stats['total_emails']}")
        return False
    
    # Test 4: Check batch files exist
    print("\n4. Verifying batch files...")
    batch_files = list(Path(test_queue_dir).glob("batch_*.json"))
    print(f"   Found {len(batch_files)} batch files")
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            data = json.load(f)
        print(f"   - {batch_file.name}: {len(data.get('emails', []))} emails")
    
    # Test 5: Process batches
    print("\n5. Processing batches with BatchProcessor...")
    processor = BatchProcessor(qm)
    
    # Process first batch
    print("   Processing first batch...")
    if not processor.process_single_batch():
        print("   ERROR: Failed to process first batch")
        return False
    
    # Check stats after first batch
    stats = qm.get_queue_stats()
    print(f"   After first batch: {stats['total_batches']} batches, {stats['total_emails']} emails")
    
    # Process second batch
    print("   Processing second batch...")
    if not processor.process_single_batch():
        print("   ERROR: Failed to process second batch")
        return False
    
    # Check stats after second batch (should be empty)
    stats = qm.get_queue_stats()
    print(f"   After second batch: {stats['total_batches']} batches, {stats['total_emails']} emails")
    
    if stats['total_batches'] != 0 or stats['total_emails'] != 0:
        print(f"   ERROR: Queue should be empty after processing")
        return False
    
    # Test 6: Clean up
    print("\n6. Cleaning up test data...")
    qm.clear_queue()
    
    # Verify cleanup
    batch_files = list(Path(test_queue_dir).glob("batch_*.json"))
    if len(batch_files) > 0:
        print(f"   ERROR: {len(batch_files)} batch files still exist after cleanup")
        return False
    
    print("\n=== All basic queue tests passed! ===")
    return True

def test_concurrent_operations():
    """Test concurrent add operations (thread safety)."""
    print("\n=== Testing Concurrent Queue Operations ===")
    
    import threading
    
    test_queue_dir = "data/test_concurrent"
    qm = QueueManager(queue_dir=test_queue_dir, batch_size=50)
    qm.clear_queue()
    
    request_ids = []
    lock = threading.Lock()
    
    def add_emails(thread_id, count):
        for i in range(count):
            email = qm.create_email_request(
                subject=f"Thread {thread_id} Email {i}",
                body=f"Email from thread {thread_id}, number {i}",
                to_email=f"thread{thread_id}.{i}@example.com"
            )
            req_id = qm.add_email(email)
            with lock:
                request_ids.append(req_id)
    
    # Start multiple threads
    threads = []
    emails_per_thread = 20
    num_threads = 5
    
    print(f"Starting {num_threads} threads, each adding {emails_per_thread} emails...")
    
    for t in range(num_threads):
        thread = threading.Thread(target=add_emails, args=(t, emails_per_thread))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()
    
    # Check results
    stats = qm.get_queue_stats()
    total_expected = num_threads * emails_per_thread
    
    print(f"Total emails added: {stats['total_emails']} (expected: {total_expected})")
    print(f"Total batches: {stats['total_batches']}")
    print(f"Unique request IDs: {len(set(request_ids))}")
    
    # Verify
    if stats['total_emails'] != total_expected:
        print(f"ERROR: Expected {total_expected} emails, got {stats['total_emails']}")
        return False
    
    if len(set(request_ids)) != total_expected:
        print(f"ERROR: Expected {total_expected} unique request IDs, got {len(set(request_ids))}")
        return False
    
    # Clean up
    qm.clear_queue()
    
    print("=== Concurrent queue tests passed! ===")
    return True

def test_failed_email_handling():
    """Test handling of failed emails (simulated)."""
    print("\n=== Testing Failed Email Handling ===")
    
    test_queue_dir = "data/test_failed"
    qm = QueueManager(queue_dir=test_queue_dir, batch_size=5)
    qm.clear_queue()
    
    # Add a few emails
    for i in range(3):
        email = qm.create_email_request(
            subject=f"Test Email {i}",
            body=f"This is test email {i}.",
            to_email=f"test{i}@example.com"
        )
        qm.add_email(email)
    
    # Get the batch file
    batches = qm.get_next_batch(max_batches=1)
    if not batches:
        print("ERROR: No batch retrieved")
        return False
    
    batch_file = batches[0]["file"]
    
    # Manually mark the batch as failed (simulate processing failure)
    qm.mark_batch_complete(batch_file, successful=False)
    
    # Check that the batch file still exists and has status "failed"
    if not batch_file.exists():
        print("ERROR: Batch file should exist after marking as failed")
        return False
    
    with open(batch_file, 'r') as f:
        data = json.load(f)
    
    if data.get("status") != "failed":
        print(f"ERROR: Batch status should be 'failed', got '{data.get('status')}'")
        return False
    
    print("Failed email handling test passed.")
    
    # Clean up
    qm.clear_queue()
    return True

def main():
    """Run all tests."""
    print("Starting Queue System Tests")
    print("=" * 50)
    
    # Create necessary directories
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    
    tests = [
        ("Basic Queue Operations", test_basic_queue_operations),
        ("Concurrent Operations", test_concurrent_operations),
        ("Failed Email Handling", test_failed_email_handling),
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
    
    print("\n" + "=" * 50)
    print(f"Test Summary: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\nAll tests passed successfully!")
        return True
    else:
        print("\nSome tests failed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
