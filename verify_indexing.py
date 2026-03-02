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
    
    # 1. Simulate Upload
    # Since we can't easily get a JWT here without auth service, 
    # we'll use a test script that bypasses JWT if possible or we use the Webhook Key if the endpoint allows.
    # Actually, let's use the actual DocumentIndexWebhookView in Chat Service directly to test the indexing part.
    
    document_id = str(uuid.uuid4())
    print(f"Generated Document ID: {document_id}")
    
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
    
    if resp.status_code not in [200, 202]:
        print("Indexing trigger failed!")
        return
    
    # 2. Poll for status
    print("Waiting for indexing to complete...")
    for _ in range(10):
        time.sleep(2)
        # Check Stats or use an internal endpoint if available
        stats_resp = requests.get(f"{CHAT_SERVICE_URL}/api/chat/stats/?tenant_id={tenant_id}")
        if stats_resp.status_code == 200:
            stats = stats_resp.json()
            completed = stats.get('documents', {}).get('completed', 0)
            if completed > 0:
                print(f"Indexing completed for tenant {tenant_id}!")
                break
        print(".", end="", flush=True)
    
    # 3. Test Deletion
    print(f"\nTriggering deletion for {document_id}...")
    del_payload = {
        "event": "document.deleted",
        "data": {
            "document_id": document_id,
            "tenant_id": tenant_id
        }
    }
    resp = requests.post(f"{CHAT_SERVICE_URL}/api/chat/webhooks/delete-document/", json=del_payload, headers=headers)
    print(f"Response: {resp.status_code} - {resp.text}")
    
    # 4. Verify Cleanup
    stats_resp = requests.get(f"{CHAT_SERVICE_URL}/api/chat/stats/?tenant_id={tenant_id}")
    stats = stats_resp.json()
    chunks = stats.get('documents', {}).get('total_chunks', 0)
    print(f"Remaining chunks for tenant {tenant_id}: {chunks}")
    if chunks == 0:
        print("SUCCESS: Deletion cleanup verified.")
    else:
        print("FAILURE: Chunks still remain after deletion.")

if __name__ == "__main__":
    # Create a dummy file for testing
    test_file = "C:/Users/CHUNGATH/Desktop/TenantIQ/test_doc.txt"
    with open(test_file, "w") as f:
        f.write("This is a test document for TenantIQ. It contains information about multi-tenancy.")
    
    try:
        test_document_flow("tenant_alpha", "user_1", test_file)
        test_document_flow("tenant_beta", "user_2", test_file)
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
