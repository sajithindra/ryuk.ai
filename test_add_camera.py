#!/usr/bin/env python3
"""
Test script to manually add a camera to the database.
Run with: python3 test_add_camera.py
"""
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_add_camera():
    try:
        from pymongo import MongoClient
        
        # Connect to MongoDB
        client = MongoClient('mongodb://localhost:27017')
        db = client.ryuk_ai
        
        # Camera data
        camera_data = {
            "client_id": "192.168.1.100",
            "username": "admin", 
            "password": "password123",
            "path": "/cam/realmonitor?channel=1&subtype=1",
            "source_type": "rtsp",
            "added_at": datetime.now()
        }
        
        # Insert/update camera
        result = db.cameras.update_one(
            {"client_id": camera_data["client_id"]}, 
            {"$set": camera_data}, 
            upsert=True
        )
        
        print("Camera added successfully!")
        print(f"Matched: {result.matched_count}, Modified: {result.modified_count}, Upserted: {result.upserted_id}")
        
        # Verify
        cameras = list(db.cameras.find({}))
        print(f"Total cameras in DB: {len(cameras)}")
        for cam in cameras:
            print(f"  - {cam['client_id']} ({cam['source_type']})")
            
    except ImportError:
        print("pymongo not available. Install with: pip install pymongo")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_add_camera()