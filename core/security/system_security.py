#!/usr/bin/env python3
"""
System Security
===============
Core security functions for TorinAI system

Purpose:
- Input validation and sanitization
- SQL injection prevention
- Path traversal prevention
- Rate limiting
- Authentication helpers
- Security audit logging
"""

import re
import hashlib
import secrets
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

from core.security.content_security import (
    sanitize_input, validate_email, validate_url, check_malicious_patterns
)

logger = logging.getLogger(__name__)


class SystemSecurity:
    """
    System security manager

    Provides core security functions:
    - Input validation and sanitization
    - SQL injection prevention
    - Path traversal checks
    - Rate limiting
    - Password hashing
    - Security audit logging
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Rate limiting (IP -> timestamp list)
        self.rate_limits = {}
        self.rate_limit_window = self.config.get('rate_limit_window', 60)  # seconds
        self.rate_limit_max = self.config.get('rate_limit_max', 100)  # requests per window

        # Blocked IPs and patterns
        self.blocked_ips = set()
        self.blocked_patterns = set()

        # Audit log
        self.audit_log = []
        self.max_audit_size = 10000

        # SQL injection patterns - require SQL syntax context, not just keywords
        # These patterns look for SQL keywords combined with special characters
        self.sql_injection_patterns = [
            # SQL keywords with quotes or comment markers (actual injection attempts)
            r"('.*?(\bor\b|\band\b|\bunion\b|\bselect\b|\bdrop\b|\binsert\b|\bupdate\b|\bdelete\b).*?)",
            r"(--.*?(\bor\b|\band\b|\bunion\b|\bselect\b))",
            r"(;.*?(\bdrop\b|\bdelete\b|\binsert\b|\bupdate\b|\bselect\b))",

            # UNION-based injection
            r"(\bunion\b.*?\bselect\b)",

            # Boolean-based blind injection (requires operators)
            r"(\bor\b\s*['\"0-9].*?[=<>])",
            r"(\band\b\s*['\"0-9].*?[=<>])",

            # Comment-based injection — requires SQL context (a quote or statement
            # separator before the marker). The previous form, r"(--[^\n]*$)",
            # matched ANY trailing token starting with `--`, so ordinary CLI
            # arguments like `ls --color` or `pytest --verbose` were flagged as
            # SQL injection.
            r"['\";]\s*--",
            r"(/\*.*?\*/)",

            # Stacked queries
            r"(;\s*\b(drop|delete|insert|update|select)\b)",

            # Dangerous functions with parens (exec, execute, cast require SQL context)
            r"(\b(exec|execute|cast|declare|shutdown)\s*\()"
        ]

        logger.info(f"SystemSecurity initialized")

    def validate_sql_input(self, input_str: str, is_internal: bool = False) -> Tuple[bool, str]:
        """
        Check input for SQL injection patterns

        Args:
            input_str: Input string to validate
            is_internal: If True, skip validation (internal system-generated content)

        Returns:
            (is_safe, reason)
        """
        if not input_str:
            return True, ""

        # Skip validation for internal system-generated content
        if is_internal:
            return True, ""

        # Check for SQL injection patterns (requires SQL syntax context)
        for pattern in self.sql_injection_patterns:
            if re.search(pattern, input_str, re.IGNORECASE):
                self.audit_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'event': 'sql_injection_attempt',
                    'input': input_str[:100],
                    'pattern': pattern
                })
                return False, f"Potential SQL injection detected"

        return True, ""

    def validate_path(self, path: str, allowed_base: str = None) -> Tuple[bool, str]:
        """
        Check for path traversal attacks

        Returns:
            (is_safe, reason)
        """
        if not path:
            return True, ""

        # Check for path traversal patterns
        dangerous_patterns = ['../', '..\\', '%2e%2e', '%252e', '....', '.....']
        for pattern in dangerous_patterns:
            if pattern in path.lower():
                return False, f"Path traversal attempt detected"

        # If base path specified, ensure path is within it
        if allowed_base:
            import os
            abs_path = os.path.abspath(path)
            abs_base = os.path.abspath(allowed_base)
            if not abs_path.startswith(abs_base):
                return False, f"Path outside allowed directory"

        return True, ""

    def check_rate_limit(self, identifier: str, max_requests: int = None) -> Tuple[bool, int]:
        """
        Check rate limiting for identifier (IP, user ID, etc.)

        Returns:
            (is_allowed, requests_remaining)
        """
        max_req = max_requests or self.rate_limit_max
        now = datetime.now()

        # Get request history for identifier
        if identifier not in self.rate_limits:
            self.rate_limits[identifier] = []

        # Remove old requests outside window
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        self.rate_limits[identifier] = [
            ts for ts in self.rate_limits[identifier]
            if ts > cutoff
        ]

        # Check limit
        current_count = len(self.rate_limits[identifier])
        if current_count >= max_req:
            return False, 0

        # Add new request
        self.rate_limits[identifier].append(now)
        return True, max_req - current_count - 1

    def hash_password(self, password: str) -> str:
        """
        Hash password with salt

        Returns:
            Hashed password string
        """
        # Generate salt
        salt = secrets.token_hex(16)

        # Hash with SHA-256
        hash_obj = hashlib.sha256()
        hash_obj.update((password + salt).encode('utf-8'))
        hashed = hash_obj.hexdigest()

        # Return salt + hash
        return f"{salt}:{hashed}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        """
        Verify password against stored hash

        Args:
            password: Plain text password
            stored_hash: Stored hash (salt:hash format)

        Returns:
            True if password matches
        """
        try:
            # Extract salt and hash
            salt, expected_hash = stored_hash.split(':')

            # Hash provided password with same salt
            hash_obj = hashlib.sha256()
            hash_obj.update((password + salt).encode('utf-8'))
            actual_hash = hash_obj.hexdigest()

            # Compare
            return secrets.compare_digest(actual_hash, expected_hash)

        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False

    def generate_token(self, length: int = 32) -> str:
        """Generate secure random token"""
        return secrets.token_urlsafe(length)

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to prevent path traversal"""
        # Remove path separators
        filename = filename.replace('/', '_').replace('\\', '_')

        # Remove dangerous characters
        filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

        # Remove leading dots
        filename = filename.lstrip('.')

        return filename

    def block_ip(self, ip: str, reason: str = None):
        """Add IP to blocklist"""
        self.blocked_ips.add(ip)
        logger.warning(f"Blocked IP: {ip} (reason: {reason})")

    def is_ip_blocked(self, ip: str) -> bool:
        """Check if IP is blocked"""
        return ip in self.blocked_ips

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit log entries"""
        return self.audit_log[-limit:]

    def clear_audit_log(self):
        """Clear audit log"""
        self.audit_log.clear()
        logger.info("Audit log cleared")


# Singleton instance
_system_security = None


def get_system_security() -> SystemSecurity:
    """Get global system security instance"""
    global _system_security
    if _system_security is None:
        _system_security = SystemSecurity()
    return _system_security


# Helper functions
def validate_input(input_str: str, input_type: str = "text") -> Tuple[bool, str]:
    """
    Validate input based on type

    Args:
        input_str: Input string to validate
        input_type: Type of input (text, email, url, path, sql)

    Returns:
        (is_valid, error_message)
    """
    security = get_system_security()

    if input_type == "sql":
        return security.validate_sql_input(input_str)
    elif input_type == "path":
        return security.validate_path(input_str)
    elif input_type == "email":
        return validate_email(input_str), "" if validate_email(input_str) else "Invalid email"
    elif input_type == "url":
        return validate_url(input_str), "" if validate_url(input_str) else "Invalid URL"
    else:
        # Generic text validation
        is_safe = not check_malicious_patterns(input_str)
        return is_safe, "" if is_safe else "Malicious content detected"


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)

    security = get_system_security()

    # Test SQL injection detection
    safe, reason = security.validate_sql_input("SELECT * FROM users")
    print(f"SQL injection test: safe={safe}, reason={reason}")

    # Test path traversal
    safe, reason = security.validate_path("../../etc/passwd")
    print(f"Path traversal test: safe={safe}, reason={reason}")

    # Test password hashing
    import os
    password = os.getenv("SYSTEM_SECURITY_PASSWORD")
    hashed = security.hash_password(password)
    verified = security.verify_password(password, hashed)
    print(f"Password test: verified={verified}")

    # Test rate limiting
    allowed, remaining = security.check_rate_limit("192.168.1.1")
    print(f"Rate limit test: allowed={allowed}, remaining={remaining}")
