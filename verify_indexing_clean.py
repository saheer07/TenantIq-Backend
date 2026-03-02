import requests
import json
import time
import uuid
import os

DOC_SERVICE_URL = "http://127.0.0.1:8003"
CHAT_SERVICE_URL = "http://127.0.0.1:8002"
WEBHOOK_KEY = "webhook-secret-key-12345-CHANGE-IN-PRODUCTION"

def test_document_flow(tenant_id, user_id, file_path):
    print(f"\n--- Testing Flow for Tenant: {tenant_id} ---")
    
    # 0. Clear Stats/Collection if possible (optional but good for clean test)
    
    document_id = str(uuid.uuid4())
    print(f"Generated Document ID: {document_id}")
    
    # 1. Trigger Indexing
    payload = {
        "event": "document.uploaded",
        "data": {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "file_path": file_path,
            "file_type": "text/plain",
            "title": f"Test Document {tenant_id}",
            "file_name": "test.txt"
        }
    }
    
    headers = {
        "X-API-Key": WEBHOOK_KEY,
        "Content-Type": "application/json"
    }
    
    print(f"Triggering indexing for {document_id}...")
    resp = requests.post(f"{CHAT_SERVICE_URL}/api/chat/webhooks/index-document/", json=payload, headers=headers)
    print(f"Response: {resp.status_code} - {resp.text}")
    
    # 2. Poll for status (should be fast now)
    print("Waiting for indexing to complete...")
    for _ in range(20):
        time.sleep(2)
        stats_resp = requests.get(f"{CHAT_SERVICE_URL}/api/chat/stats/?tenant_id={tenant_id}")
        if stats_resp.status_code == 200:
            stats = stats_resp.json()
            # Look for the specific document in stats if possible or just check completed count
            # Here we just check if total_chunks > 0 (assuming we started clean)
            if stats.get('documents', {}).get('completed', 0) > 0:
                print(f"Indexing completed for tenant {tenant_id}!")
                initial_chunks = stats.get('documents', {}).get('total_chunks', 0)
                print(f"Chunks created: {initial_chunks}")
                break
        print(".", end="", flush=True)
    
    # 3. Test Deletion
    print(f"\nTriggering deletion for {document_id}...")
    del_payload = {
        "document_id": document_id,
        "tenant_id": tenant_id
    }
    resp = requests.post(f"{CHAT_SERVICE_URL}/api/chat/webhooks/delete-document/", json=del_payload, headers=headers)
    print(f"Response: {resp.status_code} - {resp.text}")
    
    # 4. Verify Cleanup
    time.sleep(1)
    stats_resp = requests.get(f"{CHAT_SERVICE_URL}/api/chat/stats/?tenant_id={tenant_id}")
    stats = stats_resp.json()
    chunks = stats.get('documents', {}).get('total_chunks', 0)
    print(f"Remaining chunks for tenant {tenant_id}: {chunks}")
    if chunks == 0:
        print("SUCCESS: Deletion cleanup verified.")
    else:
        print(f"FAILURE: {chunks} chunks still remain.")

if __name__ == "__main__":
    test_file = "C:/Users/CHUNGATH/Desktop/TenantIQ/test_doc_clean.txt"
    with open(test_file, "w") as f:
        f.write("A clean test document for TenantIQ multi-tenancy verification.")
    
    try:
        # Use fresh tenant IDs to ensure clean start
        test_document_flow(f"clean_tenant_{uuid.uuid4().hex[:6]}", "user_1", test_file)
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
