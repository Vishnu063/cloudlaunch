from fastapi.testclient import TestClient
from app.backend import main


def test_metrics_reports_database_readiness_and_rejects_label_injection(monkeypatch):
    monkeypatch.setenv('APP_VERSION', 'release"\nmalicious')
    with TestClient(main.app) as client:
        response = client.get('/metrics')
        assert response.status_code == 200
        assert 'cloudlaunch_database_healthy 1' in response.text
        assert 'release_id="unknown"' in response.text
        assert 'malicious' not in response.text
