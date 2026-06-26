import crypt
import pwd
import grp
import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Rate limiting ──────────────────────────────────────
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_LOGIN_WINDOW = 60       # seconds
_LOGIN_MAX_ATTEMPTS = 5

def check_login_rate_limit(username: str) -> bool:
    now = time.monotonic()
    _LOGIN_ATTEMPTS[username] = [t for t in _LOGIN_ATTEMPTS[username] if now - t < _LOGIN_WINDOW]
    if len(_LOGIN_ATTEMPTS[username]) >= _LOGIN_MAX_ATTEMPTS:
        return False
    _LOGIN_ATTEMPTS[username].append(now)
    return True

def authenticate_local_user(username: str, password: str) -> dict | None:
    """
    Authenticate a user against local Linux system shadow passwords.
    Returns user info dict if successful, None otherwise.
    """
    try:
        # Get user info
        user_info = pwd.getpwnam(username)
        
        # Verify password (requires reading /etc/shadow, which requires root usually, 
        # but crypt can verify against existing shadow hashes if readable, or we use PAM/spwd)
        import spwd
        shadow_info = spwd.getspnam(username)
        hashed_password = shadow_info.sp_pwdp
        
        if crypt.crypt(password, hashed_password) == hashed_password:
            # Check groups to assign roles
            role = "none"
            try:
                admin_group = grp.getgrnam("idin9-srs-admin")
                if username in admin_group.gr_mem or user_info.pw_gid == admin_group.gr_gid:
                    role = "admin"
            except KeyError:
                pass
            
            if role == "none":
                try:
                    auditor_group = grp.getgrnam("idin9-srs-auditor")
                    if username in auditor_group.gr_mem or user_info.pw_gid == auditor_group.gr_gid:
                        role = "auditor"
                except KeyError:
                    pass
            
            # Root is always admin
            if user_info.pw_uid == 0:
                role = "admin"
                
            return {"username": username, "role": role}
    except KeyError:
        # User not found
        logger.warning(f"Failed login attempt for unknown user: {username}")
        return None
    except PermissionError:
        logger.error("Permission denied reading shadow passwords. Run as root or adjust permissions.")
        return None
    except ImportError:
        logger.error("spwd module not available on this OS.")
        return None
    except Exception as e:
        logger.error(f"Error during authentication: {e}")
        return None
        
    return None
