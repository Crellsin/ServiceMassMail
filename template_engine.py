import re
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from email_sender import EmailMessage, EmailFormat

@dataclass
class Template:
    """Represents a loaded email template."""
    name: str
    subject: str
    plain_body: str
    html_body: Optional[str] = None
    
    def render(self, variables: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
        """
        Render the template with the given variables.
        
        Args:
            variables: Dictionary of variables to substitute
            
        Returns:
            Tuple of (rendered_subject, rendered_plain_body, rendered_html_body)
        """
        # Render subject
        rendered_subject = self._render_template_string(self.subject, variables)
        
        # Render plain body
        rendered_plain = self._render_template_string(self.plain_body, variables)
        
        # Render HTML body if present
        rendered_html = None
        if self.html_body:
            rendered_html = self._render_template_string(self.html_body, variables)
        
        return rendered_subject, rendered_plain, rendered_html
    
    def _render_template_string(self, template: str, variables: Dict[str, Any]) -> str:
        """
        Render a single template string with variable substitution.
        
        Args:
            template: Template string with {{variable}} placeholders
            variables: Dictionary of variables to substitute
            
        Returns:
            Rendered string
        """
        def replace_match(match):
            var_name = match.group(1).strip()
            return str(variables.get(var_name, match.group(0)))
        
        # Replace {{variable}} with values from dictionary
        pattern = r'\{\{\s*([^}]+)\s*\}\}'
        return re.sub(pattern, replace_match, template)

class TemplateEngine:
    """File-based template engine for email templates."""
    
    def __init__(self, template_dir: str = "templates"):
        """
        Initialize the template engine.
        
        Args:
            template_dir: Directory containing template files
        """
        self.template_dir = Path(template_dir)
        self.templates = {}
        
        # Create template directory if it doesn't exist
        self.template_dir.mkdir(parents=True, exist_ok=True)
        
        # Create default templates if none exist
        self._create_default_templates()
        
        # Load existing templates
        self._load_templates()
        
        # Generate manifest file
        self._generate_manifest()
    
    def _create_default_templates(self):
        """Create default templates if they don't exist."""
        default_templates = [
            {
                "name": "verify",
                "subject": "Your Verification Code: {{code}}",
                "plain_body": """Hello,

Your verification code is: {{code}}

Please enter this code to verify your account with {{app_name}}.

This code will expire in {{expiry_minutes}} minutes.

If you didn't request this code, please ignore this email.

Best regards,
{{app_name}} Team""",
                "html_body": """<!DOCTYPE html>
<html>
<head>
    <title>Verification Code</title>
</head>
<body>
    <h1>Your Verification Code</h1>
    <p>Hello,</p>
    
    <p>Your verification code for <strong>{{app_name}}</strong> is:</p>
    
    <div style="background-color: #f5f5f5; padding: 20px; border-radius: 10px; margin: 20px 0; text-align: center;">
        <h2 style="color: #333; margin-bottom: 10px;">Verification Code</h2>
        <p style="font-size: 32px; font-weight: bold; color: #007bff; letter-spacing: 5px; margin: 0;">{{code}}</p>
    </div>
    
    <p>This code will expire in <strong>{{expiry_minutes}}</strong> minutes.</p>
    
    <p style="color: #666; font-style: italic;">
        If you didn't request this code, please ignore this email.
    </p>
    
    <p>Best regards,<br>{{app_name}} Team</p>
</body>
</html>"""
            },
            {
                "name": "welcome",
                "subject": "Welcome to {{app_name}}, {{name}}!",
                "plain_body": """Dear {{name}},

Welcome to {{app_name}}! We're excited to have you on board.

Your account details:
- Username: {{username}}
- Email: {{email}}
- Signup Date: {{signup_date}}

To get started, please verify your email address.

If you have any questions, please contact our support team.

Best regards,
{{app_name}} Team""",
                "html_body": """<!DOCTYPE html>
<html>
<head>
    <title>Welcome to {{app_name}}</title>
</head>
<body>
    <h1>Welcome to {{app_name}}, {{name}}!</h1>
    <p>Dear {{name}},</p>
    <p>Welcome to <strong>{{app_name}}</strong>! We're excited to have you on board.</p>
    
    <h2>Your account details:</h2>
    <ul>
        <li><strong>Username:</strong> {{username}}</li>
        <li><strong>Email:</strong> {{email}}</li>
        <li><strong>Signup Date:</strong> {{signup_date}}</li>
    </ul>
    
    <p>To get started, please verify your email address.</p>
    
    <p>If you have any questions, please contact our support team.</p>
    
    <p>Best regards,<br>{{app_name}} Team</p>
</body>
</html>"""
            },
            {
                "name": "password_reset",
                "subject": "Password Reset Request for {{app_name}}",
                "plain_body": """Hello {{name}},

We received a request to reset your password for {{app_name}}.

Your reset code is: {{reset_code}}

This code will expire in {{expiry_hours}} hours.

If you didn't request a password reset, please ignore this email.

Best regards,
{{app_name}} Support Team""",
                "html_body": """<!DOCTYPE html>
<html>
<head>
    <title>Password Reset</title>
</head>
<body>
    <h1>Password Reset Request</h1>
    <p>Hello {{name}},</p>
    <p>We received a request to reset your password for <strong>{{app_name}}</strong>.</p>
    
    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <h2 style="color: #333;">Your reset code:</h2>
        <p style="font-size: 24px; font-weight: bold; color: #007bff;">{{reset_code}}</p>
    </div>
    
    <p>This code will expire in <strong>{{expiry_hours}}</strong> hours.</p>
    
    <p style="color: #666; font-style: italic;">
        If you didn't request a password reset, please ignore this email.
    </p>
    
    <p>Best regards,<br>{{app_name}} Support Team</p>
</body>
</html>"""
            },
            {
                "name": "notification",
                "subject": "Notification: {{title}}",
                "plain_body": """{{title}}

{{message}}

This notification was sent by {{app_name}}.

Best regards,
{{app_name}} Team""",
                "html_body": """<!DOCTYPE html>
<html>
<head>
    <title>Notification: {{title}}</title>
</head>
<body>
    <h1>{{title}}</h1>
    
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0;">
        <p style="font-size: 16px; line-height: 1.6;">{{message}}</p>
    </div>
    
    <p style="color: #666; font-size: 14px;">
        This notification was sent by <strong>{{app_name}}</strong>.
    </p>
    
    <p>Best regards,<br>{{app_name}} Team</p>
</body>
</html>"""
            }
        ]
        
        # Check if any templates already exist
        existing_templates = list(self.template_dir.glob("*.txt"))
        
        if not existing_templates:
            # Create default templates
            for template_def in default_templates:
                self.create_template(
                    name=template_def["name"],
                    subject=template_def["subject"],
                    plain_body=template_def["plain_body"],
                    html_body=template_def["html_body"]
                )
    
    def _generate_manifest(self):
        """Generate a JSON manifest file for all templates."""
        manifest_data = {
            "templates": [],
            "generated_at": self._get_current_timestamp(),
            "total_templates": len(self.templates)
        }
        
        for template_name, template in self.templates.items():
            # Extract placeholders from subject and body
            all_text = f"{template.subject} {template.plain_body}"
            if template.html_body:
                all_text += f" {template.html_body}"
            
            # Find all placeholder patterns
            import re
            pattern = r'\{\{\s*([^}]+)\s*\}\}'
            placeholders = list(set(re.findall(pattern, all_text)))
            
            template_info = {
                "name": template_name,
                "file_path": str(self.template_dir / f"{template_name}.txt"),
                "html_file_path": str(self.template_dir / f"{template_name}.html") if template.html_body else None,
                "placeholders": sorted(placeholders),
                "description": self._get_template_description(template_name)
            }
            manifest_data["templates"].append(template_info)
        
        # Write manifest file
        manifest_file = self.template_dir / "manifest.json"
        import json
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)
    
    def _get_current_timestamp(self):
        """Get current timestamp for manifest."""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def _get_template_description(self, template_name: str) -> str:
        """Get description for a template."""
        descriptions = {
            "verify": "Verification code email template for account verification",
            "welcome": "Welcome email template for new user registration",
            "password_reset": "Password reset confirmation email template",
            "notification": "General notification email template"
        }
        return descriptions.get(template_name, "Email template")
    
    def _load_templates(self):
        """Load all templates from the template directory."""
        # Look for template files
        for template_file in self.template_dir.glob("*.txt"):
            template_name = template_file.stem
            
            # Try to load corresponding HTML file
            html_file = self.template_dir / f"{template_name}.html"
            html_content = None
            if html_file.exists():
                with open(html_file, 'r', encoding='utf-8') as f:
                    html_content = f.read()
            
            # Load plain text template
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse template (first line is subject, rest is body)
            lines = content.split('\n', 1)
            if len(lines) < 2:
                raise ValueError(f"Template {template_name} must have at least 2 lines (subject and body)")
            
            subject = lines[0].strip()
            plain_body = lines[1].strip()
            
            self.templates[template_name] = Template(
                name=template_name,
                subject=subject,
                plain_body=plain_body,
                html_body=html_content
            )
    
    def get_template(self, name: str) -> Optional[Template]:
        """
        Get a template by name.
        
        Args:
            name: Template name
            
        Returns:
            Template object or None if not found
        """
        return self.templates.get(name)
    
    def create_template(self, name: str, subject: str, plain_body: str, html_body: Optional[str] = None):
        """
        Create a new template and save it to disk.
        
        Args:
            name: Template name
            subject: Email subject template
            plain_body: Plain text body template
            html_body: HTML body template (optional)
        """
        # Save plain text template
        template_file = self.template_dir / f"{name}.txt"
        with open(template_file, 'w', encoding='utf-8') as f:
            f.write(f"{subject}\n{plain_body}")
        
        # Save HTML template if provided
        if html_body:
            html_file = self.template_dir / f"{name}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_body)
        
        # Reload templates
        self._load_templates()
    
    def render_email(self, template_name: str, variables: Dict[str, Any], 
                     to_email: str) -> EmailMessage:
        """
        Render an email from a template.
        
        Args:
            template_name: Name of the template to use
            variables: Dictionary of variables to substitute
            to_email: Recipient email address

            
        Returns:
            EmailMessage object ready to send
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")
        
        # Render template
        subject, plain_body, html_body = template.render(variables)
        
        # Determine email format
        if html_body:
            format = EmailFormat.MULTIPART
        else:
            format = EmailFormat.PLAIN
        
        # Create email message
        email = EmailMessage(
            subject=subject,
            body=plain_body,
            html_body=html_body,
            to_email=to_email,
            format=format
        )
        
        return email
    
    def list_templates(self) -> list:
        """
        List all available templates.
        
        Returns:
            List of template names
        """
        return list(self.templates.keys())
    
    def delete_template(self, name: str):
        """
        Delete a template.
        
        Args:
            name: Template name
        """
        # Delete template files
        template_file = self.template_dir / f"{name}.txt"
        html_file = self.template_dir / f"{name}.html"
        
        if template_file.exists():
            template_file.unlink()
        if html_file.exists():
            html_file.unlink()
        
        # Remove from cache
        if name in self.templates:
            del self.templates[name]
    # Initialize template engine
    engine = TemplateEngine()
    
    # Create a sample template if none exist
    if not engine.list_templates():
        print("Creating sample templates...")
        
        # Welcome email template
        engine.create_template(
            name="welcome",
            subject="Welcome to Our Service, {{name}}!",
            plain_body="""Dear {{name}},

Welcome to our service! We're excited to have you on board.

Your account details:
- Username: {{username}}
- Email: {{email}}
- Signup Date: {{signup_date}}

If you have any questions, please contact our support team.

Best regards,
The Team""",
            html_body="""<!DOCTYPE html>
<html>
<head>
    <title>Welcome Email</title>
</head>
<body>
    <h1>Welcome to Our Service, {{name}}!</h1>
    <p>Dear {{name}},</p>
    <p>Welcome to our service! We're excited to have you on board.</p>
    
    <h2>Your account details:</h2>
    <ul>
        <li><strong>Username:</strong> {{username}}</li>
        <li><strong>Email:</strong> {{email}}</li>
        <li><strong>Signup Date:</strong> {{signup_date}}</li>
    </ul>
    
    <p>If you have any questions, please contact our support team.</p>
    
    <p>Best regards,<br>The Team</p>
</body>
</html>"""
        )
        
        # Password reset template
        engine.create_template(
            name="password_reset",
            subject="Password Reset Request for {{app_name}}",
            plain_body="""Hello {{name}},

We received a request to reset your password for {{app_name}}.

Your reset code is: {{reset_code}}

This code will expire in {{expiry_hours}} hours.

If you didn't request a password reset, please ignore this email.

Best regards,
{{app_name}} Support Team""",
            html_body="""<!DOCTYPE html>
<html>
<head>
    <title>Password Reset</title>
</head>
<body>
    <h1>Password Reset Request</h1>
    <p>Hello {{name}},</p>
    <p>We received a request to reset your password for <strong>{{app_name}}</strong>.</p>
    
    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <h2 style="color: #333;">Your reset code:</h2>
        <p style="font-size: 24px; font-weight: bold; color: #007bff;">{{reset_code}}</p>
    </div>
    
    <p>This code will expire in <strong>{{expiry_hours}}</strong> hours.</p>
    
    <p style="color: #666; font-style: italic;">
        If you didn't request a password reset, please ignore this email.
    </p>
    
    <p>Best regards,<br>{{app_name}} Support Team</p>
</body>
</html>"""
        )
    
    # List templates
    templates = engine.list_templates()
    print(f"Available templates: {templates}")
    
    # Test rendering
    if "welcome" in templates:
        print("\nTesting template rendering...")
        
        variables = {
            "name": "John Doe",
            "username": "johndoe",
            "email": "john@example.com",
            "signup_date": "2023-12-23"
        }
        
        try:
            email = engine.render_email(
                template_name="welcome",
                variables=variables,
                to_email="jamalnader@jamalnader.com"
            )
            
            print(f"Subject: {email.subject}")
            print(f"Format: {email.format}")
            print(f"Plain text preview: {email.body[:100]}...")
            if email.html_body:
                print(f"HTML preview: {email.html_body[:100]}...")
            
            print("\nTemplate rendering test passed!")
            
        except Exception as e:
            print(f"Error rendering template: {e}")
    
    print("\nTemplate engine is ready!")
