import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_flow():
    # 1. Health check
    res = client.get("/api/health")
    assert res.status_code == 200, res.text
    print("Health check OK:", res.json())

    # 2. Login
    login_res = client.post("/api/auth/login", json={"email": "jane@example.com", "password": "Password123!"})
    assert login_res.status_code == 200, login_res.text
    data = login_res.json()
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Export PDF
    html_sample = """<!DOCTYPE html>
<html>
<head><style>body { font-family: sans-serif; padding: 20px; }</style></head>
<body>
<h1>Jane Doe</h1>
<p>Senior Software Engineer</p>
<hr/>
<h2>Experience</h2>
<p>TechCorp - Architected cloud solutions.</p>
</body>
</html>"""

    pdf_res = client.post("/api/exports/pdf", json={
        "resume_id": 1,
        "name": "Jane_Doe_Resume",
        "html": html_sample
    }, headers=headers)
    assert pdf_res.status_code == 201, pdf_res.text
    pdf_data = pdf_res.json()
    print("Exported PDF:", pdf_data)

    # 4. Download PDF
    dl_res = client.get(f"/api/exports/download/{pdf_data['id']}", headers=headers)
    assert dl_res.status_code == 200
    assert len(dl_res.content) > 1000
    print("Downloaded PDF successfully, bytes:", len(dl_res.content))

    print("ALL TESTS (INCLUDING PDF GENERATION) PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_flow()
