import requests
import json

url = "http://127.0.0.1:5000/api/deploy"

data = {
    "email": "test@example.com",
    "secret": "manifest-2025",
    "task": "test-app-001",
    "round": 1,
    "nonce": "test123",
    "brief": "Create a simple HTML page that displays 'Hello World' in an h1 tag with id='greeting'",
    "checks": ["Page has h1 with id greeting"],
    "attachments": [],
    "evaluation_url": "https://httpbin.org/post"
}

response = requests.post(url, json=data)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")