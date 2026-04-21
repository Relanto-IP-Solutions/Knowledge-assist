import asyncio

import httpx


# Mock Zoom Recording Completed Payload
# Meets the regex: (?i)opp[_-]?id[_-]?(\d+)
MOCK_TOPIC = "Final SASE Review - oid999"
MOCK_MEETING_ID = "888111222"
MOCK_DOWNLOAD_URL = "https://zoom.us/v2/recording/files/download/mock_transcript_vtt"

MOCK_PAYLOAD = {
    "event": "recording.completed",
    "payload": {
        "account_id": "mock_account",
        "object": {
            "id": MOCK_MEETING_ID,
            "uuid": "mock_uuid",
            "host_id": "mock_host",
            "topic": MOCK_TOPIC,
            "type": 2,
            "recording_files": [
                {
                    "id": "file_123",
                    "meeting_id": MOCK_MEETING_ID,
                    "file_type": "TRANSCRIPT",
                    "download_url": MOCK_DOWNLOAD_URL,
                    "status": "completed",
                }
            ],
        },
    },
}


async def trigger_mock_webhook():
    """Submit a mock Zoom webhook to the local server."""
    url = "http://localhost:8000/integrations/zoom/webhook"

    print(f"Sending mock Zoom webhook for topic: '{MOCK_TOPIC}'...")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=MOCK_PAYLOAD)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
        except Exception as e:
            print(
                "Error: Could not connect to the server. Make sure 'uv run python main.py' is running."
            )
            print(f"Details: {e}")


if __name__ == "__main__":
    asyncio.run(trigger_mock_webhook())
