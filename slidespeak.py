from typing import Any, Optional, Literal
import httpx
import os
import time
import asyncio
import logging
from mcp.server.fastmcp import FastMCP

# --- Configuration & Constants ---

# Initialize FastMCP server
mcp = FastMCP("slidespeak")

# API Configuration
API_BASE = "https://api.slidespeak.co/api/v1"
USER_AGENT = "slidespeak-mcp/0.0.3"
API_KEY = os.environ.get('SLIDESPEAK_API_KEY')

if not API_KEY:
    logging.warning("SLIDESPEAK_API_KEY environment variable not set.")

# Default Timeouts
DEFAULT_TIMEOUT = 30.0
GENERATION_TIMEOUT = 90.0 # Total time allowed for generation + polling
POLLING_INTERVAL = 2.0 # Seconds between status checks
POLLING_TIMEOUT = 10.0 # Timeout for each individual status check request

async def _make_api_request(
    method: Literal["GET", "POST"],
    endpoint: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT
) -> Optional[dict[str, Any]]:
    """
    Makes an HTTP request to the SlideSpeak API.

    Args:
        method: HTTP method ('GET' or 'POST').
        endpoint: API endpoint path (e.g., '/presentation/templates').
        payload: JSON payload for POST requests. Ignored for GET.
        timeout: Request timeout in seconds.

    Returns:
        The parsed JSON response as a dictionary on success, None on failure.
    """
    if not API_KEY:
        logging.error("API Key is missing. Cannot make API request.")
        return None

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": API_KEY,
    }

    # Construct full URL
    url = f"{API_BASE}{endpoint}"

    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            else: # Default to GET
                response = await client.get(url, headers=headers, timeout=timeout)

            response.raise_for_status() # Raise exception for 4xx or 5xx status codes
            return response.json()

        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error calling {method} {url}: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logging.error(f"Request error calling {method} {url}: {str(e)}")
        except Exception as e:
            logging.error(f"An unexpected error occurred calling {method} {url}: {str(e)}")

        return None

@mcp.tool()
async def get_available_templates() -> str:
    """Get all available presentation templates."""
    templates_endpoint = "/presentation/templates"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    templates_data = await _make_api_request("GET", templates_endpoint)

    if not templates_data:
        return "Unable to fetch templates due to an API error. Check server logs."

    if not isinstance(templates_data, list):
         return f"Unexpected response format received for templates: {type(templates_data).__name__}"

    if not templates_data:
        return "No templates available."

    formatted_templates = "Available templates:\n"
    for template in templates_data:
        # Add more robust checking for expected keys
        name = template.get("name", "default")
        images = template.get("images", {})
        cover = images.get("cover", "No cover image URL")
        content = images.get("content", "No content image URL")
        formatted_templates += f"- {name}\n  Cover: {cover}\n  Content: {content}\n\n"

    return formatted_templates.strip()

@mcp.tool()
async def generate_powerpoint(plain_text: str, length: int, template: str) -> str:
    """
    Generate a PowerPoint presentation based on text, length, and template.
    Waits up to a configured time for the result.
    """
    generation_endpoint = "/presentation/generate"
    status_endpoint_base = "/task_status" # Base path for status checks

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    # Prepare the JSON body for the generation request
    payload = {
        "plain_text": plain_text,
        "length": length,
        "template": template
    }

    # Step 1: Initiate generation (POST request)
    init_result = await _make_api_request("POST", generation_endpoint, payload=payload, timeout=GENERATION_TIMEOUT)

    if not init_result:
        return "Failed to initiate PowerPoint generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        return f"Failed to initiate PowerPoint generation. API response did not contain a task ID. Response: {init_result}"

    logging.info(f"PowerPoint generation initiated. Task ID: {task_id}")

    # Step 2: Poll for the task status
    status_endpoint = f"{status_endpoint_base}/{task_id}"
    start_time = time.time()
    final_result = None

    while time.time() - start_time < GENERATION_TIMEOUT:
        logging.debug(f"Polling status for task {task_id}...")
        status_result = await _make_api_request("GET", status_endpoint, timeout=POLLING_TIMEOUT)

        if status_result:
            task_status = status_result.get("task_status")
            task_result = status_result.get("task_result") # Assuming result might be here

            if task_status == "SUCCESS":
                logging.info(f"Task {task_id} completed successfully.")
                # Prefer task_result if available, otherwise return the whole status dict as string
                final_result = str(task_result) if task_result else str(status_result)

                final_result = f"Make sure to return the pptx url to the user if available. Here is the result: {final_result}"
                break
            elif task_status == "FAILED": # Use 'FAILED' consistently if possible in API
                logging.error(f"Task {task_id} failed. Status response: {status_result}")
                error_message = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                final_result = f"PowerPoint generation failed for task {task_id}. Reason: {error_message}"
                break
            elif task_status == "PENDING" or task_status == "PROCESSING" or task_status == "SENT": # Add other intermediate states if known
                logging.debug(f"Task {task_id} status: {task_status}. Waiting...")
            else:
                 logging.warning(f"Task {task_id} has unknown status: {task_status}. Response: {status_result}")
                 # Continue polling, but log this unexpected state

        else:
            # Failure during polling
            logging.warning(f"Failed to get status for task {task_id} during polling. Will retry.")
            # Optionally add a counter to break after several consecutive polling failures

        await asyncio.sleep(POLLING_INTERVAL) # Use asyncio.sleep in async functions

    # After loop: check if we got a result or timed out
    if final_result:
        return final_result
    else:
        logging.warning(f"Timeout ({GENERATION_TIMEOUT}s) while waiting for PowerPoint generation task {task_id}.")
        return f"Timeout while waiting for PowerPoint generation (Task ID: {task_id}). The task might still be running."


@mcp.tool()
async def generate_slide_by_slide(
    template: str,
    slides: list[dict[str, Any]],
    language: Optional[str] = None,
    fetch_images: Optional[bool] = True,
) -> str:
    """
    Generate a PowerPoint presentation using Slide-by-Slide input.

    Parameters
    - template (string): The name of the template or the ID of a custom template. See the custom templates section for more information.
    - language (string, optional): Language code like 'ENGLISH' or 'ORIGINAL'.
    - include_cover (bool, optional): Whether to include a cover slide in addition to the specified slides.
    - include_table_of_contents (bool, optional): Whether to include the ‘table of contents’ slides.
    - slides (list[dict]): A list of slides, each defined as a dictionary with the following keys:
      - title (string): The title of the slide.
      - layout (string): The layout type for the slide. See available layout options below.
      - item_amount (integer): Number of items for the slide (must match the layout constraints).
      - content (string): The content that will be used for the slide.

    Available Layouts
    - items: 1-5 items
    - steps: 3-5 items
    - summary: 1-5 items
    - comparison: exactly 2 items
    - big-number: 1-5 items
    - milestone: 3-5 items
    - pestel: exactly 6 items
    - swot: exactly 4 items
    - pyramid: 1-5 items
    - timeline: 3-5 items
    - funnel: 3-5 items
    - quote: 1 item
    - cycle: 3-5 items
    - thanks: 0 items

    Returns
    - A string containing the final task result (including the PPTX URL when available),
      or an error/timeout message.
    """
    endpoint = "/presentation/generate/slide-by-slide"
    status_endpoint_base = "/task_status"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    # Basic validation
    if not isinstance(slides, list) or len(slides) == 0:
        return "Parameter 'slides' must be a non-empty list of slide objects."

    payload: dict[str, Any] = {
        "template": template,
        "slides": slides,
    }
    if language:
        payload["language"] = language
    if fetch_images is not None:
        payload["fetch_images"] = fetch_images

    # Step 1: Initiate slide-by-slide generation
    init_result = await _make_api_request("POST", endpoint, payload=payload, timeout=GENERATION_TIMEOUT)
    if not init_result:
        return "Failed to initiate slide-by-slide generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        return f"Failed to initiate slide-by-slide generation. API response did not contain a task ID. Response: {init_result}"

    logging.info(f"Slide-by-slide generation initiated. Task ID: {task_id}")

    # Step 2: Poll for the task status
    status_endpoint = f"{status_endpoint_base}/{task_id}"
    start_time = time.time()
    final_result: Optional[str] = None

    while time.time() - start_time < GENERATION_TIMEOUT:
        logging.debug(f"Polling status for task {task_id} (slide-by-slide)...")
        status_result = await _make_api_request("GET", status_endpoint, timeout=POLLING_TIMEOUT)

        if status_result:
            task_status = status_result.get("task_status")
            task_result = status_result.get("task_result")

            if task_status == "SUCCESS":
                logging.info(f"Task {task_id} completed successfully (slide-by-slide).")
                final_result = str(task_result) if task_result else str(status_result)
                final_result = (
                    f"Make sure to return the pptx url to the user if available. Here is the result: {final_result}"
                )
                break
            elif task_status == "FAILED":
                logging.error(f"Task {task_id} failed (slide-by-slide). Status response: {status_result}")
                error_message = (
                    task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                )
                final_result = f"Slide-by-slide generation failed for task {task_id}. Reason: {error_message}"
                break
            elif task_status in ("PENDING", "PROCESSING", "SENT"):
                logging.debug(f"Task {task_id} status: {task_status}. Waiting...")
            else:
                logging.warning(
                    f"Task {task_id} has unknown status: {task_status}. Response: {status_result}"
                )
        else:
            logging.warning(
                f"Failed to get status for task {task_id} during polling (slide-by-slide). Will retry."
            )

        await asyncio.sleep(POLLING_INTERVAL)

    if final_result:
        return final_result
    else:
        logging.warning(
            f"Timeout ({GENERATION_TIMEOUT}s) while waiting for slide-by-slide task {task_id}."
        )
        return (
            f"Timeout while waiting for slide-by-slide generation (Task ID: {task_id}). The task might still be running."
        )


if __name__ == "__main__":
    # Configure logging (optional but recommended)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Check for API Key at startup
    if not API_KEY:
       logging.critical("SLIDESPEAK_API_KEY is not set. The server cannot communicate with the backend API.")
       # Optionally exit here if the API key is absolutely required
       # import sys
       # sys.exit("API Key missing. Exiting.")

    # Initialize and run the server
    mcp.run(transport='stdio')