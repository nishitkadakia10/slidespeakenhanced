from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("slidespeak")

# Constants
API_BASE = "http://localhost:8004"
USER_AGENT = "slidespeak-mcp/1.0.0"
API_KEY = "" # TODO add your API key here

async def make_slidespeak_api_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": API_KEY
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


@mcp.tool()
async def check_if_authenticated() -> str:
    """Check if the user is authenticated."""
    me_url = f"{API_BASE}/api/v1/me"
    profile = await make_slidespeak_api_request(me_url)

    if not profile:
        return "Unable to fetch profile."

    if "error" in profile:
        return "Invalid API key. Please check your credentials."

    user_name = profile.get("user_name")

    if not user_name:
        return "Unable to fetch profile."

    return "You are authenticated."


@mcp.tool()
async def get_available_themes() -> str:
    """Get all available presentation themes."""
    themes_url = f"{API_BASE}/api/v1/presentation/themes"
    themes = await make_slidespeak_api_request(themes_url)

    if not themes:
        return "Unable to fetch themes."

    formatted_themes = "Available themes:\n"
    for theme in themes:
        name = theme.get("name", "Unknown")
        cover = theme["images"].get("cover", "No cover image")
        content = theme["images"].get("content", "No content image")
        formatted_themes += f"- {name}\n  Cover: {cover}\n  Content: {content}\n\n"

    return formatted_themes.strip()


import time


@mcp.tool()
async def generate_powerpoint(plain_text: str, length: int, theme: str) -> str:
    """Generate a PowerPoint presentation and wait up to 1 and a half minutes for the result."""
    generate_url = f"{API_BASE}/api/v1/presentation/generate"

    # Prepare the JSON body for the request
    payload = {
        "plain_text": plain_text,
        "length": length,
        "theme": theme
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": API_KEY
    }

    async with httpx.AsyncClient() as client:
        try:
            # Step 1: Make the POST request to generate the PowerPoint
            response = await client.post(generate_url, json=payload, headers=headers, timeout=90.0)
            response.raise_for_status()

            # Step 2: Get the task ID from the response
            result = response.json()
            task_id = result.get("task_id")

            if not task_id:
                return "Failed to initiate PowerPoint generation. No task ID received."

            # Step 3: Poll for the task status for up to 60 seconds
            status_url = f"{API_BASE}/api/v1/task_status/{task_id}"
            start_time = time.time()

            while time.time() - start_time < 90:
                status_response = await client.get(status_url, headers=headers, timeout=5.0)
                status_response.raise_for_status()

                status_result = status_response.json()

                # Check the task status (assuming 'status' indicates completion or failure)
                if status_result.get("task_status") == "SUCCESS":
                    return str(status_result)
                elif status_result.get("task_status") == "failed":
                    return f"PowerPoint generation failed. Task ID: {task_id}"

                # Wait before checking again
                time.sleep(2)

            return "Timeout while waiting for PowerPoint generation."

        except httpx.HTTPStatusError as e:
            return f"Error generating PowerPoint: {e.response.status_code} - {e.response.text}"
        except Exception as e:
            return f"An error occurred: {str(e)}"


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')