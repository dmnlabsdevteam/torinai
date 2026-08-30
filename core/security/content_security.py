#!/usr/bin/env python3
"""
Content Security
================
Content validation and sanitization for TorinAI

Purpose:
- Sanitize user input (XSS prevention)
- Validate emails, URLs, filenames
- Detect malicious patterns
- Content filtering
"""

import re
import html
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Malicious patterns
MALICIOUS_PATTERNS = [
    r'<script[^>]*>.*?</script>',  # Script tags
    r'javascript:',  # JavaScript protocol
    r'on\w+\s*=',  # Event handlers (onclick, onerror, etc.)
    r'<iframe',  # Iframes
    r'<object',  # Objects
    r'<embed',  # Embeds
    r'eval\s*\(',  # eval() calls
    r'expression\s*\(',  # CSS expressions
]

# Email regex
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'


def sanitize_input(text: str, allow_html: bool = False) -> str:
    """
    Sanitize user input to prevent XSS

    Args:
        text: Input text to sanitize
        allow_html: If False, escape all HTML

    Returns:
        Sanitized text
    """
    if not text:
        return ""

    # Escape HTML if not allowed
    if not allow_html:
        text = html.escape(text)

    # Remove malicious patterns
    for pattern in MALICIOUS_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    return text.strip()


def validate_email(email: str) -> bool:
    """
    Validate email address

    Returns:
        True if valid email
    """
    if not email:
        return False

    return bool(re.match(EMAIL_REGEX, email))


def validate_url(url: str) -> bool:
    """
    Validate URL

    Returns:
        True if valid URL
    """
    if not url:
        return False

    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except Exception:
        return False


def check_malicious_patterns(text: str) -> bool:
    """
    Check if text contains malicious patterns

    Returns:
        True if malicious content detected
    """
    if not text:
        return False

    for pattern in MALICIOUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Malicious pattern detected: {pattern}")
            return True

    return False


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename

    Returns:
        Safe filename
    """
    if not filename:
        return ""

    # Remove path separators
    filename = filename.replace('/', '_').replace('\\', '_')

    # Keep only safe characters
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    # Remove leading dots
    filename = filename.lstrip('.')

    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')

    return filename


class ContentSecurityScanner:
    """
    Content Security Scanner

    Wrapper class for content security functions
    Provides unified interface for security systems
    """

    def __init__(self):
        self.scans_performed = 0
        self.threats_found = 0

    def scan_content(self, content: str) -> dict:
        """
        Scan content for security issues

        Returns:
            {
                "safe": bool,
                "issues": List[str],
                "sanitized": str
            }
        """
        self.scans_performed += 1
        issues = []

        # Check for malicious patterns
        if check_malicious_patterns(content):
            issues.append("malicious_patterns")
            self.threats_found += 1

        # Check for XSS
        if '<script' in content.lower() or 'javascript:' in content.lower():
            issues.append("xss_attempt")
            self.threats_found += 1

        # Check for SQL injection patterns
        sql_patterns = ['DROP TABLE', 'DELETE FROM', 'INSERT INTO', '--', 'UNION SELECT']
        for pattern in sql_patterns:
            if pattern.lower() in content.lower():
                issues.append("sql_injection_attempt")
                self.threats_found += 1
                break

        # Sanitize content
        sanitized = sanitize_input(content)

        return {
            "safe": len(issues) == 0,
            "issues": issues,
            "sanitized": sanitized
        }

    def get_statistics(self) -> dict:
        """Get scanner statistics"""
        return {
            "scans_performed": self.scans_performed,
            "threats_found": self.threats_found
        }


if __name__ == "__main__":
    # Test
    print("Testing content security...")

    # Test sanitization
    unsafe = "<script>alert('XSS')</script>Hello"
    safe = sanitize_input(unsafe)
    print(f"Sanitized: {safe}")

    # Test email validation
    print(f"Email valid: {validate_email('user@example.com')}")
    print(f"Email invalid: {validate_email('notanemail')}")

    # Test URL validation
    print(f"URL valid: {validate_url('https://example.com')}")
    print(f"URL invalid: {validate_url('not a url')}")

    # Test malicious detection
    print(f"Malicious: {check_malicious_patterns('<script>bad</script>')}")
