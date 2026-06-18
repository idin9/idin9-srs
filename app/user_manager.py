import re
import subprocess
import logging
import pwd
import grp

# Only allow safe usernames: alphanumeric, underscore, hyphen, starting with alpha
SAFE_USER_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
VALID_ROLES = {"admin", "auditor"}

def _validate_username(username: str) -> bool:
    return bool(SAFE_USER_RE.match(username))

logger = logging.getLogger(__name__)

def check_and_create_groups():
    groups_to_ensure = ["idin9-srs-auditor", "idin9-srs-admin"]
    for g in groups_to_ensure:
        try:
            grp.getgrnam(g)
        except KeyError:
            logger.info(f"Creating group {g}")
            subprocess.run(["groupadd", g], check=False)

def list_users():
    check_and_create_groups()
    users = []
    
    # Get all users in the system and filter those belonging to our groups
    try:
        admin_group = grp.getgrnam("idin9-srs-admin").gr_mem
    except KeyError:
        admin_group = []
        
    try:
        auditor_group = grp.getgrnam("idin9-srs-auditor").gr_mem
    except KeyError:
        auditor_group = []
        
    all_related_users = set(admin_group + auditor_group)
    # also add root
    all_related_users.add("root")
    
    for u in all_related_users:
        try:
            user_info = pwd.getpwnam(u)
            role = "admin" if u in admin_group or user_info.pw_uid == 0 else "auditor"
            users.append({"username": u, "role": role})
        except KeyError:
            continue
            
    return users

def create_user(username, password, role):
    if not _validate_username(username):
        return False, "Invalid username — only alphanumeric, underscore, hyphen allowed"
    if role not in VALID_ROLES:
        return False, f"Invalid role — must be one of {VALID_ROLES}"

    check_and_create_groups()
    group = f"idin9-srs-{role}"
    
    try:
        subprocess.run(["useradd", "-M", "-s", "/usr/sbin/nologin", "-G", group, username], check=True, capture_output=True)
        proc = subprocess.Popen(["chpasswd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate(f"{username}:{password}".encode())
        return True, "User created successfully"
    except subprocess.CalledProcessError:
        return False, "Failed to create user (may already exist)"
    except Exception as e:
        return False, str(e)

def delete_user(username):
    if username == "root":
        return False, "Cannot delete root user"
    if not _validate_username(username):
        return False, "Invalid username"
    try:
        subprocess.run(["userdel", username], check=True, capture_output=True)
        return True, "User deleted successfully"
    except subprocess.CalledProcessError:
        return False, "Failed to delete user"
    except Exception as e:
        return False, str(e)

def change_user_role(username, role):
    if username == "root":
        return False, "Cannot change root user role"
    if not _validate_username(username):
        return False, "Invalid username"
    if role not in VALID_ROLES:
        return False, f"Invalid role — must be one of {VALID_ROLES}"
    
    check_and_create_groups()
    target_group = f"idin9-srs-{role}"
    other_group = "idin9-srs-admin" if role == "auditor" else "idin9-srs-auditor"
    
    try:
        subprocess.run(["gpasswd", "-d", username, other_group], check=False, capture_output=True)
        subprocess.run(["usermod", "-aG", target_group, username], check=True, capture_output=True)
        return True, "Role updated successfully"
    except subprocess.CalledProcessError:
        return False, "Failed to update role"
    except Exception as e:
        return False, str(e)
