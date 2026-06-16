import crypt
import pwd
import grp
import logging

logger = logging.getLogger(__name__)

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
