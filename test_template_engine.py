#!/usr/bin/env python3
"""Test script for the template engine."""
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add current directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from template_engine import TemplateEngine, Template

def test_template_creation_and_rendering():
    """Test creating a template and rendering it."""
    print("=== Testing Template Creation and Rendering ===")
    
    # Create a temporary directory for templates
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")
    
    try:
        # Initialize template engine with temp directory
        engine = TemplateEngine(template_dir=temp_dir)
        
        # Create a test template
        template_name = "test_template"
        subject = "Hello {{name}}!"
        plain_body = "Welcome, {{name}} to {{company}}."
        html_body = "<h1>Welcome, {{name}}!</h1><p>Welcome to {{company}}.</p>"
        
        engine.create_template(
            name=template_name,
            subject=subject,
            plain_body=plain_body,
            html_body=html_body
        )
        
        # Verify template was created
        templates = engine.list_templates()
        if template_name not in templates:
            print(f"ERROR: Template {template_name} not found in list: {templates}")
            return False
        
        print(f"Created template: {template_name}")
        
        # Test rendering
        variables = {
            "name": "John",
            "company": "Acme Inc"
        }
        
        template = engine.get_template(template_name)
        if not template:
            print(f"ERROR: Could not get template {template_name}")
            return False
        
        # Render template
        rendered_subject, rendered_plain, rendered_html = template.render(variables)
        
        # Check results
        expected_subject = "Hello John!"
        expected_plain = "Welcome, John to Acme Inc."
        expected_html = "<h1>Welcome, John!</h1><p>Welcome to Acme Inc.</p>"
        
        if rendered_subject != expected_subject:
            print(f"ERROR: Subject mismatch. Expected: {expected_subject}, Got: {rendered_subject}")
            return False
        
        if rendered_plain != expected_plain:
            print(f"ERROR: Plain body mismatch. Expected: {expected_plain}, Got: {rendered_plain}")
            return False
        
        if rendered_html != expected_html:
            print(f"ERROR: HTML body mismatch. Expected: {expected_html}, Got: {rendered_html}")
            return False
        
        print("Template rendering test passed!")
        return True
        
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_template_engine_integration():
    """Test the template engine's integration with email generation."""
    print("\n=== Testing Template Engine Integration ===")
    
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")
    
    try:
        engine = TemplateEngine(template_dir=temp_dir)
        
        # Create a template
        engine.create_template(
            name="integration_test",
            subject="Test: {{title}}",
            plain_body="Hello {{user}},\nThis is a test for {{feature}}.",
            html_body="<h1>Test: {{title}}</h1><p>Hello {{user}},</p><p>This is a test for {{feature}}.</p>"
        )
        
        # Render an email
        variables = {
            "title": "Integration Test",
            "user": "Jane Doe",
            "feature": "template engine"
        }
        
        email = engine.render_email(
            template_name="integration_test",
            variables=variables,
            to_email="test@example.com"
        )
        
        # Check email properties
        if email.subject != "Test: Integration Test":
            print(f"ERROR: Email subject mismatch. Got: {email.subject}")
            return False
        
        if email.to_email != "test@example.com":
            print(f"ERROR: Email to mismatch. Got: {email.to_email}")
            return False
        
        if email.format.value != "multipart":
            print(f"ERROR: Email format should be multipart. Got: {email.format}")
            return False
        
        # Check that the email has both plain and HTML parts
        if not email.body:
            print("ERROR: Email has no plain body")
            return False
        
        if not email.html_body:
            print("ERROR: Email has no HTML body")
            return False
        
        print("Template engine integration test passed!")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_missing_variable_handling():
    """Test that missing variables are handled gracefully."""
    print("\n=== Testing Missing Variable Handling ===")
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        engine = TemplateEngine(template_dir=temp_dir)
        
        engine.create_template(
            name="missing_vars",
            subject="Test {{missing1}}",
            plain_body="Test {{missing2}} and {{existing}}",
            html_body="<p>{{missing3}} and {{existing}}</p>"
        )
        
        variables = {
            "existing": "found"
        }
        
        template = engine.get_template("missing_vars")
        rendered_subject, rendered_plain, rendered_html = template.render(variables)
        
        # Missing variables should remain as placeholders
        if "{{missing1}}" not in rendered_subject:
            print(f"ERROR: Missing variable should remain. Got: {rendered_subject}")
            return False
        
        if "{{missing2}}" not in rendered_plain:
            print(f"ERROR: Missing variable should remain. Got: {rendered_plain}")
            return False
        
        if "{{missing3}}" not in rendered_html:
            print(f"ERROR: Missing variable should remain. Got: {rendered_html}")
            return False
        
        # Existing variable should be replaced
        if "found" not in rendered_plain:
            print(f"ERROR: Existing variable not replaced. Got: {rendered_plain}")
            return False
        
        print("Missing variable handling test passed!")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_template_deletion():
    """Test deleting a template."""
    print("\n=== Testing Template Deletion ===")
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        engine = TemplateEngine(template_dir=temp_dir)
        
        # Create a template
        engine.create_template(
            name="to_delete",
            subject="Test",
            plain_body="Test"
        )
        
        # Verify it exists
        if "to_delete" not in engine.list_templates():
            print("ERROR: Template not created")
            return False
        
        # Delete it
        engine.delete_template("to_delete")
        
        # Verify it's gone
        if "to_delete" in engine.list_templates():
            print("ERROR: Template not deleted")
            return False
        
        # Verify files are deleted
        txt_file = Path(temp_dir) / "to_delete.txt"
        if txt_file.exists():
            print("ERROR: Template file still exists")
            return False
        
        print("Template deletion test passed!")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def main():
    """Run all template engine tests."""
    print("Starting Template Engine Tests")
    print("=" * 50)
    
    tests = [
        ("Template Creation and Rendering", test_template_creation_and_rendering),
        ("Template Engine Integration", test_template_engine_integration),
        ("Missing Variable Handling", test_missing_variable_handling),
        ("Template Deletion", test_template_deletion),
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
        print("\nAll template engine tests passed!")
        return True
    else:
        print("\nSome template engine tests failed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
