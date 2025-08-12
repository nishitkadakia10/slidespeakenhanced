from typing import Any, Optional, Literal, List, Dict
import httpx
import os
import time
import asyncio
import logging
import warnings
from mcp.server.fastmcp import FastMCP
from pydantic import Field

# Suppress deprecation warnings from websockets and uvicorn
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")

# --- Configuration & Constants ---

# Initialize FastMCP server
mcp = FastMCP("slidespeak")

# API Configuration
API_BASE = "https://api.slidespeak.co/api/v1"
USER_AGENT = "slidespeak-mcp/0.0.3"
API_KEY = os.environ.get('SLIDESPEAK_API_KEY')

# Railway-specific environment detection
PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if PUBLIC_DOMAIN:
    BASE_URL = f"https://{PUBLIC_DOMAIN}"
else:
    BASE_URL = "http://localhost:8080"

# Port configuration
PORT = int(os.environ.get("PORT", 8080))

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
    """
    Get all available presentation templates/themes.
    
    Returns a list of all available templates that can be used for presentation generation.
    Each template includes name and preview image URLs.
    """
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
async def get_themes() -> str:
    """
    Get all available presentation themes.
    
    This endpoint returns all available themes that can be used in the template parameter
    when generating presentations. Use this to see what themes are available.
    """
    themes_endpoint = "/presentation/themes"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    themes_data = await _make_api_request("GET", themes_endpoint)

    if not themes_data:
        return "Unable to fetch themes due to an API error. Check server logs."

    if isinstance(themes_data, list):
        formatted_themes = "Available themes:\n"
        for theme in themes_data:
            if isinstance(theme, dict):
                name = theme.get("name", "unknown")
                theme_id = theme.get("id", "")
                description = theme.get("description", "")
                formatted_themes += f"- {name}"
                if theme_id:
                    formatted_themes += f" (ID: {theme_id})"
                if description:
                    formatted_themes += f"\n  Description: {description}"
                formatted_themes += "\n"
            else:
                formatted_themes += f"- {theme}\n"
        return formatted_themes.strip()
    else:
        return f"Themes data: {themes_data}"

@mcp.tool()
async def generate_powerpoint(
    plain_text: str = Field(description="The text content to generate a presentation about"),
    length: int = Field(description="The number of slides to generate (typically 5-20)"),
    template: str = Field(default="default", description="The template/theme name or custom template ID. Use 'default' or get options from get_themes()"),
    language: Optional[str] = Field(default="ORIGINAL", description="Language code for the presentation (e.g., 'ENGLISH', 'SPANISH', 'FRENCH', 'GERMAN', 'ITALIAN', 'PORTUGUESE', 'ORIGINAL')"),
    fetch_images: Optional[bool] = Field(default=True, description="Whether to include stock images in the presentation"),
    tone: Optional[str] = Field(default="default", description="The tone to use for the text (e.g., 'default', 'professional', 'casual', 'formal', 'creative')"),
    verbosity: Optional[str] = Field(default="standard", description="Content verbosity level: 'concise', 'standard', or 'detailed'"),
    custom_user_instructions: Optional[str] = Field(default=None, description="Custom instructions to follow when generating the presentation")
) -> str:
    """
    Generate a PowerPoint presentation from text with advanced customization options.
    
    Creates a presentation based on the provided text, with control over length, template,
    language, tone, verbosity, and custom instructions. Supports custom templates via template ID.
    Returns a task ID that can be used to check status and download the presentation.
    """
    generation_endpoint = "/presentation/generate"
    status_endpoint_base = "/task_status"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    # Prepare the JSON body for the generation request
    payload = {
        "plain_text": plain_text,
        "length": length,
        "template": template,
        "language": language,
        "fetch_images": fetch_images,
        "tone": tone,
        "verbosity": verbosity
    }
    
    # Only add custom instructions if provided
    if custom_user_instructions:
        payload["custom_user_instructions"] = custom_user_instructions

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
            task_result = status_result.get("task_result")

            if task_status == "SUCCESS":
                logging.info(f"Task {task_id} completed successfully.")
                final_result = str(task_result) if task_result else str(status_result)
                final_result = f"Presentation generated successfully! Task ID: {task_id}\n\nResult: {final_result}\n\nMake sure to provide the PPTX download URL to the user."
                break
            elif task_status == "FAILED":
                logging.error(f"Task {task_id} failed. Status response: {status_result}")
                error_message = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                final_result = f"PowerPoint generation failed for task {task_id}. Reason: {error_message}"
                break
            elif task_status in ("PENDING", "PROCESSING", "SENT"):
                logging.debug(f"Task {task_id} status: {task_status}. Waiting...")
            else:
                logging.warning(f"Task {task_id} has unknown status: {task_status}. Response: {status_result}")

        else:
            logging.warning(f"Failed to get status for task {task_id} during polling. Will retry.")

        await asyncio.sleep(POLLING_INTERVAL)

    if final_result:
        return final_result
    else:
        logging.warning(f"Timeout ({GENERATION_TIMEOUT}s) while waiting for PowerPoint generation task {task_id}.")
        return f"Timeout while waiting for PowerPoint generation (Task ID: {task_id}). The task might still be running. You can check the status using get_task_status('{task_id}')"

@mcp.tool()
async def generate_slide_by_slide(
    template: str = Field(description="The template name or custom template ID to use"),
    slides: List[Dict[str, Any]] = Field(description="List of slide objects, each with: title, layout, item_amount (optional), and content"),
    language: Optional[str] = Field(default="ORIGINAL", description="Language code like 'ENGLISH', 'SPANISH', 'FRENCH', 'GERMAN', 'ITALIAN', 'PORTUGUESE', or 'ORIGINAL'"),
    fetch_images: Optional[bool] = Field(default=True, description="Whether to fetch and include images"),
    include_cover: Optional[bool] = Field(default=True, description="Whether to include a cover slide"),
    include_table_of_contents: Optional[bool] = Field(default=False, description="Whether to include table of contents slides")
) -> str:
    """
    Generate a PowerPoint presentation with fine-grained control over each slide.
    
    This advanced method allows you to specify exact content for each slide, including
    the layout type and content structure. Perfect for creating highly customized presentations.
    
    Slide object structure:
    - title: The title of the slide
    - layout: Layout type (see available layouts below)
    - item_amount: Number of items (required for certain layouts)
    - content: The content for the slide
    
    Available layouts:
    - items: 1-5 items (requires item_amount)
    - steps: 3-5 items (requires item_amount)
    - summary: 1-5 items (requires item_amount)
    - comparison: exactly 2 items
    - big-number: 1-5 items (requires item_amount)
    - milestone: 3-5 items (requires item_amount)
    - pestel: exactly 6 items
    - swot: exactly 4 items
    - pyramid: 1-5 items (requires item_amount)
    - timeline: 3-5 items (requires item_amount)
    - funnel: 3-5 items (requires item_amount)
    - quote: 1 item
    - cycle: 3-5 items (requires item_amount)
    - thanks: 0 items (no content needed)
    
    Example slide object:
    {
        "title": "Key Benefits",
        "layout": "items",
        "item_amount": 3,
        "content": "Benefit 1: Increased efficiency\nBenefit 2: Cost reduction\nBenefit 3: Better quality"
    }
    """
    endpoint = "/presentation/generate/slide-by-slide"
    status_endpoint_base = "/task_status"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    # Basic validation
    if not isinstance(slides, list) or len(slides) == 0:
        return "Parameter 'slides' must be a non-empty list of slide objects."

    payload: Dict[str, Any] = {
        "template": template,
        "slides": slides,
        "language": language,
        "fetch_images": fetch_images,
        "include_cover": include_cover,
        "include_table_of_contents": include_table_of_contents
    }

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
                final_result = f"Slide-by-slide presentation generated successfully! Task ID: {task_id}\n\nResult: {final_result}\n\nMake sure to provide the PPTX download URL to the user."
                break
            elif task_status == "FAILED":
                logging.error(f"Task {task_id} failed (slide-by-slide). Status response: {status_result}")
                error_message = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                final_result = f"Slide-by-slide generation failed for task {task_id}. Reason: {error_message}"
                break
            elif task_status in ("PENDING", "PROCESSING", "SENT"):
                logging.debug(f"Task {task_id} status: {task_status}. Waiting...")
            else:
                logging.warning(f"Task {task_id} has unknown status: {task_status}. Response: {status_result}")
        else:
            logging.warning(f"Failed to get status for task {task_id} during polling (slide-by-slide). Will retry.")

        await asyncio.sleep(POLLING_INTERVAL)

    if final_result:
        return final_result
    else:
        logging.warning(f"Timeout ({GENERATION_TIMEOUT}s) while waiting for slide-by-slide task {task_id}.")
        return f"Timeout while waiting for slide-by-slide generation (Task ID: {task_id}). The task might still be running. You can check the status using get_task_status('{task_id}')"

@mcp.tool()
async def get_task_status(task_id: str = Field(description="The task ID returned from a generation request")) -> str:
    """
    Check the status of an asynchronous task.
    
    Use this to check the progress of presentation generation or other long-running tasks.
    Returns the current status (PENDING, PROCESSING, SUCCESS, FAILED) and result if available.
    
    Status values:
    - PENDING: Task is queued but not started
    - PROCESSING/SENT: Task is currently being processed
    - SUCCESS: Task completed successfully (includes download URL)
    - FAILED: Task failed (includes error message)
    """
    status_endpoint = f"/task_status/{task_id}"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    status_result = await _make_api_request("GET", status_endpoint, timeout=DEFAULT_TIMEOUT)

    if not status_result:
        return f"Failed to get status for task {task_id}. Check server logs."

    task_status = status_result.get("task_status", "UNKNOWN")
    task_result = status_result.get("task_result")
    task_info = status_result.get("task_info")

    formatted_status = f"Task ID: {task_id}\nStatus: {task_status}\n"

    if task_status == "SUCCESS":
        if task_result:
            formatted_status += f"\nResult: {task_result}"
            if isinstance(task_result, dict) and "url" in task_result:
                formatted_status += f"\n\nDownload URL: {task_result['url']}"
        if task_info:
            formatted_status += f"\nAdditional Info: {task_info}"
    elif task_status == "FAILED":
        if task_result:
            error_msg = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else str(task_result)
            formatted_status += f"\nError: {error_msg}"
    elif task_status in ("PENDING", "PROCESSING", "SENT"):
        formatted_status += "\nThe task is still being processed. Please check again later."
        if task_info:
            formatted_status += f"\nProgress Info: {task_info}"

    return formatted_status

@mcp.tool()
async def create_slide_example() -> str:
    """
    Get an example of how to structure slides for the generate_slide_by_slide tool.
    
    Returns a complete example showing how to format the slides parameter with
    different layout types and proper structure.
    """
    example = """
Example slides structure for generate_slide_by_slide:

[
    {
        "title": "Introduction to AI",
        "layout": "items",
        "item_amount": 3,
        "content": "Machine Learning fundamentals\nNeural Networks and Deep Learning\nPractical Applications in Business"
    },
    {
        "title": "Implementation Steps",
        "layout": "steps",
        "item_amount": 4,
        "content": "Step 1: Assess current infrastructure\nStep 2: Define use cases\nStep 3: Build pilot project\nStep 4: Scale and optimize"
    },
    {
        "title": "Comparison",
        "layout": "comparison",
        "item_amount": 2,
        "content": "Traditional Approach: Manual processes, Time-consuming, Error-prone\nAI-Powered Approach: Automated workflows, Real-time processing, High accuracy"
    },
    {
        "title": "Key Metrics",
        "layout": "big-number",
        "item_amount": 3,
        "content": "85% - Accuracy improvement\n60% - Time saved\n3.2x - ROI increase"
    },
    {
        "title": "SWOT Analysis",
        "layout": "swot",
        "content": "Strengths: Innovation capability, Strong team\nWeaknesses: Limited resources, Technical debt\nOpportunities: Market growth, New partnerships\nThreats: Competition, Regulatory changes"
    },
    {
        "title": "Project Timeline",
        "layout": "timeline",
        "item_amount": 5,
        "content": "Q1 2024: Planning phase\nQ2 2024: Development\nQ3 2024: Testing\nQ4 2024: Deployment\nQ1 2025: Optimization"
    },
    {
        "title": "Success Quote",
        "layout": "quote",
        "content": "Innovation distinguishes between a leader and a follower. - Steve Jobs"
    },
    {
        "title": "Thank You",
        "layout": "thanks",
        "content": ""
    }
]

Available layouts and their constraints:
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

Languages available: ENGLISH, SPANISH, FRENCH, GERMAN, ITALIAN, PORTUGUESE, CHINESE, JAPANESE, KOREAN, RUSSIAN, ARABIC, HINDI, ORIGINAL
Tones available: default, professional, casual, formal, creative, educational, persuasive
Verbosity levels: concise, standard, detailed
"""
    return example

@mcp.resource("health://status")
def health_status() -> str:
    """Health check endpoint"""
    import json
    from datetime import datetime, timezone
    return json.dumps({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transport": "streamable-http",
        "server": "slidespeak-mcp",
        "version": "0.0.3",
        "api_key_configured": bool(API_KEY)
    }, indent=2)

@mcp.resource("info://capabilities")
def server_capabilities() -> str:
    """Get information about server capabilities"""
    import json
    return json.dumps({
        "server": "SlideSpeak MCP Server",
        "version": "0.0.3",
        "capabilities": {
            "presentation_generation": {
                "from_text": True,
                "slide_by_slide": True,
                "custom_templates": True,
                "languages": ["ENGLISH", "SPANISH", "FRENCH", "GERMAN", "ITALIAN", "PORTUGUESE", "CHINESE", "JAPANESE", "KOREAN", "RUSSIAN", "ARABIC", "HINDI", "ORIGINAL"],
                "tones": ["default", "professional", "casual", "formal", "creative", "educational", "persuasive"],
                "verbosity_levels": ["concise", "standard", "detailed"],
                "layouts": ["items", "steps", "summary", "comparison", "big-number", "milestone", "pestel", "swot", "pyramid", "timeline", "funnel", "quote", "cycle", "thanks"]
            },
            "async_processing": True,
            "task_status_checking": True,
            "template_listing": True
        },
        "api_base": API_BASE,
        "transport": "streamable-http",
        "deployment_url": BASE_URL if PUBLIC_DOMAIN else "http://localhost:8080"
    }, indent=2)

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # Check for API Key at startup
    if not API_KEY:
       logging.critical("SLIDESPEAK_API_KEY is not set. The server cannot communicate with the backend API.")
       logging.info("Get your API key at: https://slidespeak.co/slidespeak-api/")

    # Log startup information
    logger.info(f"Starting SlideSpeak MCP Server v0.0.3")
    logger.info(f"Transport: streamable-http")
    logger.info(f"Port: {PORT}")
    if PUBLIC_DOMAIN:
        logger.info(f"Public URL: {BASE_URL}/mcp")
    
    # Initialize and run the server with streamable-http transport
    # The MCP library reads PORT from environment automatically for streamable-http
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    
    # For streamable-http, the library typically handles host/port from env vars
    mcp.run(transport="streamable-http")
