"""
🔐 SECURITY LAYERS SYSTEM
Comprehensive multi-layer security protection for Speak2DB
"""

import sqlite3
import hashlib
import secrets
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from functools import wraps
from flask import session, request, jsonify, abort
import logging

class SecurityLayers:
    """🛡️ Multi-layer security protection system"""
    
    def __init__(self, db_path: str = "library_main.db"):
        self.db_path = db_path
        self.failed_attempts = {}
        self.blocked_ips = {}
        self.session_tokens = {}
        self.security_settings = self._load_security_settings()
        
    def _load_security_settings(self) -> Dict:
        """⚙️ Load security configuration"""
        return {
            'max_login_attempts': 5,
            'lockout_duration': 900,  # 15 minutes
            'session_timeout': 3600,  # 1 hour
            'password_min_length': 8,
            'password_require_uppercase': True,
            'password_require_lowercase': True,
            'password_require_numbers': True,
            'password_require_special': True,
            'max_concurrent_sessions': 3,
            'require_2fa': False,
            'audit_log_retention': 90,  # days
            'ip_whitelist': [],
            'ip_blacklist': [],
            'rate_limit_requests': 100,
            'rate_limit_window': 60,  # seconds
            'csrf_protection': True,
            'xss_protection': True,
            'sql_injection_protection': True,
            'file_upload_protection': True
        }
    
    def generate_secure_token(self, length: int = 32) -> str:
        """🔑 Generate cryptographically secure token"""
        return secrets.token_urlsafe(length)
    
    def hash_password(self, password: str, salt: str = None) -> Tuple[str, str]:
        """🔐 Hash password with salt"""
        if salt is None:
            salt = secrets.token_hex(16)
        
        # Use PBKDF2 for secure password hashing
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # iterations
        ).hex()
        
        return password_hash, salt
    
    def verify_password(self, password: str, stored_hash: str, salt: str) -> bool:
        """✅ Verify password against stored hash"""
        computed_hash, _ = self.hash_password(password, salt)
        return computed_hash == stored_hash
    
    def validate_password_strength(self, password: str) -> Tuple[bool, List[str]]:
        """🔍 Validate password strength"""
        errors = []
        settings = self.security_settings
        
        # Length check
        if len(password) < settings['password_min_length']:
            errors.append(f"Password must be at least {settings['password_min_length']} characters")
        
        # Uppercase check
        if settings['password_require_uppercase'] and not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter")
        
        # Lowercase check
        if settings['password_require_lowercase'] and not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter")
        
        # Numbers check
        if settings['password_require_numbers'] and not re.search(r'\d', password):
            errors.append("Password must contain at least one number")
        
        # Special characters check
        if settings['password_require_special'] and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password must contain at least one special character")
        
        # Common password check
        common_passwords = ['password', '123456', 'qwerty', 'admin', 'letmein']
        if password.lower() in common_passwords:
            errors.append("Password is too common. Please choose a stronger password")
        
        return len(errors) == 0, errors
    
    def check_ip_reputation(self, ip_address: str) -> Tuple[bool, str]:
        """🌐 Check IP reputation"""
        settings = self.security_settings
        
        # Check blacklist
        if ip_address in settings['ip_blacklist']:
            return False, "IP address is blacklisted"
        
        # Check whitelist (if configured)
        if settings['ip_whitelist'] and ip_address not in settings['ip_whitelist']:
            return False, "IP address is not whitelisted"
        
        # Check failed attempts
        if ip_address in self.failed_attempts:
            attempts = self.failed_attempts[ip_address]
            if attempts >= settings['max_login_attempts']:
                return False, f"Too many failed attempts. Try again in {settings['lockout_duration']//60} minutes"
        
        return True, "IP address is allowed"
    
    def check_rate_limit(self, ip_address: str, action: str = 'login') -> Tuple[bool, str]:
        """⏱️ Check rate limiting"""
        settings = self.security_settings
        current_time = time.time()
        
        # Initialize rate limit tracking if not exists
        if 'rate_limits' not in self.failed_attempts:
            self.failed_attempts['rate_limits'] = {}
        
        key = f"{ip_address}:{action}"
        if key not in self.failed_attempts['rate_limits']:
            self.failed_attempts['rate_limits'][key] = []
        
        # Clean old requests outside the window
        window_start = current_time - settings['rate_limit_window']
        self.failed_attempts['rate_limits'][key] = [
            req_time for req_time in self.failed_attempts['rate_limits'][key]
            if req_time > window_start
        ]
        
        # Check if rate limit exceeded
        if len(self.failed_attempts['rate_limits'][key]) >= settings['rate_limit_requests']:
            return False, f"Rate limit exceeded. Maximum {settings['rate_limit_requests']} requests per {settings['rate_limit_window']} seconds"
        
        # Add current request
        self.failed_attempts['rate_limits'][key].append(current_time)
        return True, "Rate limit OK"
    
    def validate_session(self, session_id: str) -> Tuple[bool, str]:
        """🔍 Validate session security"""
        if session_id not in self.session_tokens:
            return False, "Invalid session"
        
        session_data = self.session_tokens[session_id]
        
        # Check session timeout
        if time.time() - session_data['created'] > self.security_settings['session_timeout']:
            del self.session_tokens[session_id]
            return False, "Session expired"
        
        # Check IP consistency
        current_ip = request.remote_addr if request else 'unknown'
        if session_data.get('ip_address') != current_ip:
            del self.session_tokens[session_id]
            return False, "Session IP mismatch"
        
        # Check user agent consistency
        current_ua = request.headers.get('User-Agent', 'unknown')
        if session_data.get('user_agent') != current_ua:
            del self.session_tokens[session_id]
            return False, "Session user agent mismatch"
        
        return True, "Session valid"
    
    def create_secure_session(self, user_id: str, role: str) -> str:
        """🔐 Create secure session"""
        session_id = self.generate_secure_token()
        current_time = time.time()
        
        self.session_tokens[session_id] = {
            'user_id': user_id,
            'role': role,
            'created': current_time,
            'last_activity': current_time,
            'ip_address': request.remote_addr if request else 'unknown',
            'user_agent': request.headers.get('User-Agent', 'unknown')
        }
        
        # Log session creation
        self.log_security_event('session_created', {
            'user_id': user_id,
            'role': role,
            'session_id': session_id,
            'ip_address': request.remote_addr if request else 'unknown'
        })
        
        return session_id
    
    def destroy_session(self, session_id: str):
        """🗑️ Destroy session securely"""
        if session_id in self.session_tokens:
            session_data = self.session_tokens[session_id]
            
            # Log session destruction
            self.log_security_event('session_destroyed', {
                'user_id': session_data['user_id'],
                'session_id': session_id,
                'duration': time.time() - session_data['created']
            })
            
            del self.session_tokens[session_id]
    
    def sanitize_input(self, input_data: str, input_type: str = 'general') -> str:
        """🧹 Sanitize user input to prevent XSS"""
        if not input_data:
            return ""
        
        # Remove potentially dangerous characters
        dangerous_chars = ['<', '>', '"', "'", '&', 'javascript:', 'vbscript:', 'onload=', 'onerror=']
        sanitized = input_data
        
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, '')
        
        # HTML entity encoding
        sanitized = sanitized.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # SQL injection protection
        if input_type == 'sql':
            sql_patterns = [
                r'(\bUNION\b.*\bSELECT\b)',
                r'(\bSELECT\b.*\bFROM\b)',
                r'(\bINSERT\b.*\bINTO\b)',
                r'(\bUPDATE\b.*\bSET\b)',
                r'(\bDELETE\b.*\bFROM\b)',
                r'(\bDROP\b.*\bTABLE\b)',
                r'(\bCREATE\b.*\bTABLE\b)',
                r'(\bALTER\b.*\bTABLE\b)',
                r'(\bEXEC\b.*\bXP_\w+)',
                r'(--)',
                r'(/\*.*\*/)'
            ]
            
            for pattern in sql_patterns:
                if re.search(pattern, sanitized, re.IGNORECASE):
                    self.log_security_event('sql_injection_attempt', {
                        'input': input_data,
                        'pattern': pattern,
                        'ip_address': request.remote_addr if request else 'unknown'
                    })
                    return ""
        
        return sanitized
    
    def validate_file_upload(self, file_data, allowed_extensions: List[str] = None) -> Tuple[bool, str]:
        """📁 Validate file upload security"""
        if allowed_extensions is None:
            allowed_extensions = ['.pdf', '.doc', '.docx', '.txt', '.csv', '.xlsx']
        
        # Check file size (max 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if hasattr(file_data, 'content_length') and file_data.content_length > max_size:
            return False, "File size exceeds maximum allowed size (10MB)"
        
        # Check file extension
        if hasattr(file_data, 'filename'):
            filename = file_data.filename.lower()
            if not any(filename.endswith(ext) for ext in allowed_extensions):
                return False, f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
        
        # Check file content
        if hasattr(file_data, 'content_type'):
            allowed_mime_types = [
                'application/pdf',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'text/plain',
                'text/csv',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            ]
            
            if file_data.content_type not in allowed_mime_types:
                return False, "File content type not allowed"
        
        return True, "File validation passed"
    
    def generate_csrf_token(self) -> str:
        """🛡️ Generate CSRF token"""
        return self.generate_secure_token()
    
    def validate_csrf_token(self, token: str, session_token: str) -> bool:
        """✅ Validate CSRF token"""
        return token == session_token and len(token) > 0
    
    def log_security_event(self, event_type: str, details: Dict):
        """📝 Log security events"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO SecurityLog (
                    event_type, details, ip_address, user_agent, timestamp
                ) VALUES (?, ?, ?, ?, ?)
            ''', (
                event_type,
                str(details),
                request.remote_addr if request else 'unknown',
                request.headers.get('User-Agent', 'unknown'),
                datetime.now().isoformat()
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"❌ Failed to log security event: {e}")
    
    def check_concurrent_sessions(self, user_id: str) -> Tuple[bool, int]:
        """👥 Check concurrent session limit"""
        user_sessions = [
            session_id for session_id, session_data in self.session_tokens.items()
            if session_data['user_id'] == user_id and 
            time.time() - session_data['last_activity'] < self.security_settings['session_timeout']
        ]
        
        max_sessions = self.security_settings['max_concurrent_sessions']
        return len(user_sessions) <= max_sessions, len(user_sessions)
    
    def update_session_activity(self, session_id: str):
        """⏰ Update session last activity"""
        if session_id in self.session_tokens:
            self.session_tokens[session_id]['last_activity'] = time.time()
    
    def get_security_headers(self) -> Dict[str, str]:
        """🔐 Get security headers for HTTP responses"""
        return {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Content-Security-Policy': (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
                "img-src 'self' data:; "
                "connect-src 'self'"
            ),
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Permissions-Policy': 'geolocation=(), microphone=(self), camera=()'
        }
    
    def cleanup_expired_data(self):
        """🧹 Clean up expired security data"""
        current_time = time.time()
        
        # Clean expired sessions
        expired_sessions = [
            session_id for session_id, session_data in self.session_tokens.items()
            if current_time - session_data['last_activity'] > self.security_settings['session_timeout']
        ]
        
        for session_id in expired_sessions:
            self.destroy_session(session_id)
        
        # Clean old rate limit data
        if 'rate_limits' in self.failed_attempts:
            window_start = current_time - self.security_settings['rate_limit_window']
            for key in list(self.failed_attempts['rate_limits'].keys()):
                self.failed_attempts['rate_limits'][key] = [
                    req_time for req_time in self.failed_attempts['rate_limits'][key]
                    if req_time > window_start
                ]
                
                # Remove empty rate limit entries
                if not self.failed_attempts['rate_limits'][key]:
                    del self.failed_attempts['rate_limits'][key]
        
        # Clean old failed attempts
        lockout_duration = self.security_settings['lockout_duration']
        for ip in list(self.failed_attempts.keys()):
            if isinstance(self.failed_attempts[ip], dict) and 'timestamp' in self.failed_attempts[ip]:
                if current_time - self.failed_attempts[ip]['timestamp'] > lockout_duration:
                    del self.failed_attempts[ip]

# Global security instance
security = SecurityLayers()

# Decorator functions for Flask routes
def require_secure_session(f):
    """🔐 Decorator to require secure session"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = session.get('session_id')
        if not session_id:
            return jsonify({'error': 'No session found'}), 401
        
        is_valid, message = security.validate_session(session_id)
        if not is_valid:
            session.clear()
            return jsonify({'error': message}), 401
        
        # Update session activity
        security.update_session_activity(session_id)
        return f(*args, **kwargs)
    return decorated_function

def require_csrf_token(f):
    """🛡️ Decorator to require CSRF token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method in ['POST', 'PUT', 'DELETE']:
            csrf_token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            session_token = session.get('csrf_token')
            
            if not security.validate_csrf_token(csrf_token, session_token):
                return jsonify({'error': 'Invalid CSRF token'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

def rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """⏱️ Decorator for rate limiting"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = request.remote_addr if request else 'unknown'
            is_allowed, message = security.check_rate_limit(ip_address, 'api')
            
            if not is_allowed:
                return jsonify({'error': message}), 429
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def ip_whitelist(allowed_ips: List[str] = None):
    """🌐 Decorator for IP whitelisting"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = request.remote_addr if request else 'unknown'
            
            if allowed_ips and ip_address not in allowed_ips:
                return jsonify({'error': 'IP address not allowed'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_security_event(event_type: str):
    """📝 Decorator to log security events"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Log the event
            security.log_security_event(event_type, {
                'endpoint': request.endpoint if request else 'unknown',
                'method': request.method if request else 'unknown',
                'ip_address': request.remote_addr if request else 'unknown',
                'user_agent': request.headers.get('User-Agent', 'unknown')
            })
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Security middleware for Flask
def apply_security_headers(response):
    """🔐 Apply security headers to response"""
    headers = security.get_security_headers()
    for header, value in headers.items():
        response.headers[header] = value
    return response

def sanitize_user_input(data: str, input_type: str = 'general') -> str:
    """🧹 Sanitize user input"""
    return security.sanitize_input(data, input_type)
