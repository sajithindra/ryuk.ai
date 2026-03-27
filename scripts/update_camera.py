import sys
import os
import argparse
from typing import Optional

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_sync_db
from core.logger import logger

def update_camera(client_id: str,
                  ip: Optional[str] = None,
                  username: Optional[str] = None,
                  password: Optional[str] = None):
    """Updates camera configuration in MongoDB."""
    db = get_sync_db()
    cam = db.cameras.find_one({"client_id": client_id})
    
    if not cam:
        print(f"Error: Camera with client_id '{client_id}' not found in database.")
        return False
        
    print(f"Updating camera: {client_id}")
    print(f"Current Source: {cam.get('source', 'N/A')}")
    
    # Simple Dahua/Generic RTSP replacement
    # rtsp://{username}:{password}@{ip}:{port}/...
    import re
    source = cam.get('source', '')
    
    if ip:
        # Replace IP (e.g. 192.168.1.34)
        source = re.sub(r'@[\d\.]+', f'@{ip}', source)
    if username:
        # Replace username (admin)
        source = re.sub(r'rtsp://[^:]+', f'rtsp://{username}', source)
    if password:
        # Replace password (L2577636)
        source = re.sub(r':([^@]+)@', f':{password}@', source)
        
    db.cameras.update_one(
        {"client_id": client_id},
        {"$set": {"source": source}}
    )
    
    print(f"New Source: {source}")
    print("Success: Database updated.")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update Ryuk AI Camera Credentials")
    parser.add_argument("--id", required=True, help="Camera Client ID (e.g. FRONT_DOOR)")
    parser.add_argument("--ip", help="New Camera IP")
    parser.add_argument("--user", help="New Camera Username")
    parser.add_argument("--pass", dest="password", help="New Camera Password")
    
    args = parser.parse_args()
    
    if not any([args.ip, args.user, args.password]):
        print("Error: Specify at least one of --ip, --user, or --pass.")
        sys.exit(1)
        
    update_camera(args.id, args.ip, args.user, args.password)
