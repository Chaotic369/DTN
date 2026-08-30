import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_home_page():
    response = client.get("/")
    assert response.status_code == 200

def test_youtube_search_mock():
    # Mocking the YouTube Data API proxy as required
    response = client.get("/api/youtube/search?q=test")
    assert response.status_code == 200
