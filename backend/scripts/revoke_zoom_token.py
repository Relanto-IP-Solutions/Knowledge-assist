import asyncio
import base64
import subprocess

import httpx


def get_secret(secret_name: str) -> str:
    """Fetch a secret directly from Google Cloud Secret Manager using the gcloud CLI."""
    result = subprocess.run(
        [
            "gcloud.cmd",
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            secret_name,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


async def main():
    print("Fetching secrets securely from Google Cloud Secret Manager...")
    try:
        account_id = get_secret("ZOOM_ACCOUNT_ID")
        client_id = get_secret("ZOOM_CLIENT_ID")
        client_secret = get_secret("ZOOM_CLIENT_SECRET")
    except Exception as e:
        print(f"Failed to fetch secrets. Ensure you are logged into gcloud. Error: {e}")
        return

    print("Success! Fetching the current active Zoom token...")

    # 1. Fetch current token
    auth_str = f"{client_id}:{client_secret}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers)
        if resp.status_code != 200:
            print(f"Failed to fetch token: {resp.text}")
            return
        token = resp.json()["access_token"]
        print(f"Token fetched (starts with: {token[:10]}...)")

        # 2. Revoke the token
        print("Revoking the token to flush Zoom's cache...")
        revoke_url = "https://zoom.us/oauth/revoke"
        revoke_data = {"token": token}
        revoke_resp = await client.post(revoke_url, headers=headers, data=revoke_data)

        if revoke_resp.status_code == 200:
            print(
                "Successfully revoked token! Next time the app asks, Zoom will generate a fresh token with all updated scopes."
            )
        else:
            print(f"Failed to revoke token: {revoke_resp.text}")


if __name__ == "__main__":
    asyncio.run(main())
