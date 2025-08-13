#!/usr/bin/env python3
"""
SlideSpeak MCP Server - FastMCP Implementation with Streamable HTTP
Deployable on Railway for remote access via Claude Desktop
"""

from typing import Any, Optional, Literal, Dict, List
import httpx
import os
import time
import asyncio
import logging
import json
import warnings
from datetime import datetime, timezone
from pydantic import Field

# Suppress deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# --- Configuration & Logging ---

# Configure comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('slidespeak_server')

# --- API Configuration ---
API_BASE = "https://api.slidespeak.co/api/v1"
USER_AGENT = "slidespeak-mcp/0.0.3"

# Default Timeouts
DEFAULT_TIMEOUT = 30.0
GENERATION_TIMEOUT = 90.0  # Total time allowed for generation + polling
POLLING_INTERVAL = 2.0  # Seconds between status checks
POLLING_TIMEOUT = 10.0  # Timeout for each individual status check request

# Get server URL from environment (Railway provides RAILWAY_PUBLIC_DOMAIN)
public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if public_domain:
    base_url = f"https://{public_domain}"
else:
    # Fallback for local development
    base_url = f"http://localhost:{os.environ.get('PORT', '8080')}"

logger.info("=" * 60)
logger.info("🚀 SlideSpeak MCP Server Starting")
logger.info(f"📍 Base URL: {base_url}")
logger.info("=" * 60)

# Initialize FastMCP server without authentication for now
mcp = FastMCP(
    name="SlideSpeak MCP Server",
    description="Create professional presentations using AI through SlideSpeak API"
)

# Check for API key
API_KEY = os.environ.get('SLIDESPEAK_API_KEY')
if not API_KEY:
    logger.warning("⚠️  SLIDESPEAK_API_KEY environment variable not set.")
    logger.warning("⚠️  Server will start but API calls will fail without a valid key.")
else:
    logger.info("✅ SlideSpeak API key configured")

# --- Helper Functions ---

async def _make_api_request(
    method: Literal["GET", "POST"],
    endpoint: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT
) -> Optional[dict[str, Any]]:
    """
    Makes an HTTP request to the SlideSpeak API with comprehensive logging.

    Args:
        method: HTTP method ('GET' or 'POST').
        endpoint: API endpoint path (e.g., '/presentation/templates').
        payload: JSON payload for POST requests. Ignored for GET.
        timeout: Request timeout in seconds.

    Returns:
        The parsed JSON response as a dictionary on success, None on failure.
    """
    if not API_KEY:
        logger.error("❌ API Key is missing. Cannot make API request.")
        return None

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": API_KEY,
    }

    # Construct full URL
    url = f"{API_BASE}{endpoint}"
    
    logger.info(f"🔄 Making {method} request to: {endpoint}")
    if payload:
        logger.debug(f"📤 Request payload: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            else:  # Default to GET
                response = await client.get(url, headers=headers, timeout=timeout)

            logger.info(f"📥 Response status: {response.status_code}")
            
            response.raise_for_status()  # Raise exception for 4xx or 5xx status codes
            
            result = response.json()
            logger.debug(f"📦 Response data: {json.dumps(result, indent=2)[:500]}...")  # Log first 500 chars
            
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP error calling {method} {url}: {e.response.status_code}")
            logger.error(f"❌ Response text: {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"❌ Request error calling {method} {url}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error calling {method} {url}: {str(e)}")
            return None

# --- Health Check Resources ---

@mcp.resource("health://status")
def health_status() -> str:
    """MCP health check endpoint for monitoring"""
    status = {
        "status": "healthy",
        "service": "SlideSpeak MCP Server",
        "version": "1.0.0",
        "api_configured": API_KEY is not None,
        "api_base": API_BASE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoints": {
            "templates": "/presentation/templates",
            "generate": "/presentation/generate",
            "slide_by_slide": "/presentation/generate/slide-by-slide",
            "task_status": "/task_status/{task_id}",
            "me": "/me",
            "upload": "/document/upload"
        }
    }
    logger.info("🏥 Health check requested")
    return json.dumps(status, indent=2)

# --- MCP Tools ---

@mcp.tool()
async def get_available_templates() -> str:
    """
    Get all available presentation templates from SlideSpeak.
    
    Returns a formatted list of templates with their cover and content image URLs.
    This is typically the first command to run to see what templates are available.
    """
    logger.info("🎨 Fetching available templates")
    templates_endpoint = "/presentation/templates"

    if not API_KEY:
        logger.error("❌ API Key missing for get_available_templates")
        return "API Key is missing. Cannot process any requests."

    templates_data = await _make_api_request("GET", templates_endpoint)

    if not templates_data:
        logger.error("❌ Failed to fetch templates")
        return "Unable to fetch templates due to an API error. Check server logs."

    if not isinstance(templates_data, list):
        logger.warning(f"⚠️  Unexpected response format for templates: {type(templates_data).__name__}")
        return f"Unexpected response format received for templates: {type(templates_data).__name__}"

    if not templates_data:
        logger.info("ℹ️  No templates available")
        return "No templates available."

    formatted_templates = "Available templates:\n"
    template_count = 0
    for template in templates_data:
        template_count += 1
        # Add more robust checking for expected keys
        name = template.get("name", "default")
        images = template.get("images", {})
        cover = images.get("cover", "No cover image URL")
        content = images.get("content", "No content image URL")
        formatted_templates += f"- {name}\n  Cover: {cover}\n  Content: {content}\n\n"
        logger.debug(f"📋 Template {template_count}: {name}")

    logger.info(f"✅ Successfully fetched {template_count} templates")
    return formatted_templates.strip()

@mcp.tool()
async def get_me() -> str:
    """
    Get details about the current API key (user_name and remaining credits).
    
    Returns information about the authenticated user including credit balance.
    Note: Generating slides costs 1 credit per slide.
    """
    logger.info("👤 Fetching user details")
    
    if not API_KEY:
        logger.error("❌ API Key missing for get_me")
        return "API Key is missing. Cannot process any requests."

    result = await _make_api_request("GET", "/me")
    if not result:
        logger.error("❌ Failed to fetch user details")
        return "Failed to fetch current user details."
    
    logger.info(f"✅ User details fetched successfully")
    if 'credits' in result:
        logger.info(f"💳 Credits remaining: {result.get('credits', 'Unknown')}")
    
    return json.dumps(result, indent=2) + "\n\nNote: Generating slides costs 1 credit per slide"

@mcp.tool()
async def generate_powerpoint(
    plain_text: str = Field(description="The text content to generate presentation from"),
    length: int = Field(description="Number of slides to generate (costs 1 credit per slide)"),
    template: str = Field(description="Template name to use (get available templates first)"),
    document_uuids: Optional[list[str]] = Field(default=None, description="Optional document UUIDs to include"),
) -> str:
    """
    Generate a PowerPoint presentation based on text, length, and template.
    
    This initiates presentation generation and polls for completion.
    The function will wait up to 90 seconds for the result.
    
    Args:
        plain_text: The text content to base the presentation on
        length: Number of slides to generate (each costs 1 credit)
        template: Name of the template to use
        document_uuids: Optional list of document UUIDs to incorporate
    
    Returns:
        URL to download the generated PPTX file or error message
    """
    logger.info("🎯 Starting PowerPoint generation")
    logger.info(f"📝 Text length: {len(plain_text)} chars")
    logger.info(f"📊 Slides requested: {length}")
    logger.info(f"🎨 Template: {template}")
    
    generation_endpoint = "/presentation/generate"
    status_endpoint_base = "/task_status"

    if not API_KEY:
        logger.error("❌ API Key missing for generate_powerpoint")
        return "API Key is missing. Cannot process any requests."

    # Prepare the JSON body for the generation request
    payload: dict[str, Any] = {
        "plain_text": plain_text,
        "length": length,
        "template": template
    }
    if document_uuids:
        payload["document_uuids"] = document_uuids
        logger.info(f"📎 Including {len(document_uuids)} document(s)")

    # Step 1: Initiate generation (POST request)
    logger.info("🚀 Initiating PowerPoint generation...")
    init_result = await _make_api_request("POST", generation_endpoint, payload=payload, timeout=GENERATION_TIMEOUT)

    if not init_result:
        logger.error("❌ Failed to initiate generation")
        return "Failed to initiate PowerPoint generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        logger.error(f"❌ No task ID in response: {init_result}")
        return f"Failed to initiate PowerPoint generation. API response did not contain a task ID. Response: {init_result}"

    logger.info(f"✅ PowerPoint generation initiated. Task ID: {task_id}")

    # Step 2: Poll for the task status
    status_endpoint = f"{status_endpoint_base}/{task_id}"
    start_time = time.time()
    final_result = None
    poll_count = 0

    while time.time() - start_time < GENERATION_TIMEOUT:
        poll_count += 1
        logger.debug(f"🔄 Polling status for task {task_id} (attempt {poll_count})...")
        status_result = await _make_api_request("GET", status_endpoint, timeout=POLLING_TIMEOUT)

        if status_result:
            task_status = status_result.get("task_status")
            task_result = status_result.get("task_result")
            
            logger.info(f"📊 Task status: {task_status}")

            if task_status == "SUCCESS":
                logger.info(f"🎉 Task {task_id} completed successfully!")
                final_result = str(task_result) if task_result else str(status_result)
                final_result = f"✅ Presentation generated successfully!\n\n{final_result}\n\nMake sure to return the PPTX URL to the user if available."
                break
            elif task_status == "FAILED":
                logger.error(f"❌ Task {task_id} failed. Response: {status_result}")
                error_message = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                final_result = f"❌ PowerPoint generation failed for task {task_id}.\nReason: {error_message}"
                break
            elif task_status in ["PENDING", "PROCESSING", "SENT"]:
                logger.debug(f"⏳ Task {task_id} status: {task_status}. Waiting...")
            else:
                logger.warning(f"⚠️  Task {task_id} has unknown status: {task_status}")

        else:
            logger.warning(f"⚠️  Failed to get status for task {task_id} during polling. Will retry.")

        await asyncio.sleep(POLLING_INTERVAL)

    # After loop: check if we got a result or timed out
    if final_result:
        return final_result
    else:
        elapsed = time.time() - start_time
        logger.warning(f"⏱️  Timeout after {elapsed:.1f}s while waiting for task {task_id}")
        return f"⏱️  Timeout while waiting for PowerPoint generation (Task ID: {task_id}).\nThe task might still be running. You can check status using get_task_status."

@mcp.tool()
async def generate_slide_by_slide(
    template: str = Field(description="Template name or custom template ID"),
    slides: list[dict[str, Any]] = Field(description="List of slide definitions with title, layout, item_amount, and content"),
    language: Optional[str] = Field(default=None, description="Language code like 'ENGLISH' or 'ORIGINAL'"),
    fetch_images: Optional[bool] = Field(default=True, description="Whether to fetch images for slides"),
) -> str:
    """
    Generate a PowerPoint presentation using Slide-by-Slide input for precise control.

    This gives you complete control over each slide's content and layout.

    Parameters:
        template: The name of the template or custom template ID
        language: Optional language code
        slides: List of slide dictionaries, each containing:
            - title: The slide title
            - layout: Layout type (see available layouts below)
            - item_amount: Number of items (must match layout constraints)
            - content: The slide content

    Available Layouts:
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

    Returns:
        URL to download the generated PPTX file or error message
    """
    logger.info("🎯 Starting slide-by-slide generation")
    logger.info(f"📊 Number of slides: {len(slides)}")
    logger.info(f"🎨 Template: {template}")
    if language:
        logger.info(f"🌍 Language: {language}")
    
    endpoint = "/presentation/generate/slide-by-slide"
    status_endpoint_base = "/task_status"

    if not API_KEY:
        logger.error("❌ API Key missing for generate_slide_by_slide")
        return "API Key is missing. Cannot process any requests."

    # Basic validation
    if not isinstance(slides, list) or len(slides) == 0:
        logger.error("❌ Invalid slides parameter")
        return "Parameter 'slides' must be a non-empty list of slide objects."

    # Log slide details
    for i, slide in enumerate(slides, 1):
        logger.debug(f"Slide {i}: {slide.get('title', 'Untitled')} - Layout: {slide.get('layout', 'Unknown')}")

    payload: dict[str, Any] = {
        "template": template,
        "slides": slides,
    }
    if language:
        payload["language"] = language
    if fetch_images is not None:
        payload["fetch_images"] = fetch_images

    # Step 1: Initiate slide-by-slide generation
    logger.info("🚀 Initiating slide-by-slide generation...")
    init_result = await _make_api_request("POST", endpoint, payload=payload, timeout=GENERATION_TIMEOUT)
    
    if not init_result:
        logger.error("❌ Failed to initiate slide-by-slide generation")
        return "Failed to initiate slide-by-slide generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        logger.error(f"❌ No task ID in response: {init_result}")
        return f"Failed to initiate slide-by-slide generation. API response did not contain a task ID. Response: {init_result}"

    logger.info(f"✅ Slide-by-slide generation initiated. Task ID: {task_id}")

    # Step 2: Poll for the task status
    status_endpoint = f"{status_endpoint_base}/{task_id}"
    start_time = time.time()
    final_result: Optional[str] = None
    poll_count = 0

    while time.time() - start_time < GENERATION_TIMEOUT:
        poll_count += 1
        logger.debug(f"🔄 Polling status for task {task_id} (attempt {poll_count})...")
        status_result = await _make_api_request("GET", status_endpoint, timeout=POLLING_TIMEOUT)

        if status_result:
            task_status = status_result.get("task_status")
            task_result = status_result.get("task_result")
            
            logger.info(f"📊 Task status: {task_status}")

            if task_status == "SUCCESS":
                logger.info(f"🎉 Task {task_id} completed successfully!")
                final_result = str(task_result) if task_result else str(status_result)
                final_result = f"✅ Slide-by-slide presentation generated successfully!\n\n{final_result}\n\nMake sure to return the PPTX URL to the user if available."
                break
            elif task_status == "FAILED":
                logger.error(f"❌ Task {task_id} failed. Response: {status_result}")
                error_message = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                final_result = f"❌ Slide-by-slide generation failed for task {task_id}.\nReason: {error_message}"
                break
            elif task_status in ("PENDING", "PROCESSING", "SENT"):
                logger.debug(f"⏳ Task {task_id} status: {task_status}. Waiting...")
            else:
                logger.warning(f"⚠️  Task {task_id} has unknown status: {task_status}")
        else:
            logger.warning(f"⚠️  Failed to get status for task {task_id} during polling. Will retry.")

        await asyncio.sleep(POLLING_INTERVAL)

    if final_result:
        return final_result
    else:
        elapsed = time.time() - start_time
        logger.warning(f"⏱️  Timeout after {elapsed:.1f}s while waiting for task {task_id}")
        return f"⏱️  Timeout while waiting for slide-by-slide generation (Task ID: {task_id}).\nThe task might still be running. You can check status using get_task_status."

@mcp.tool()
async def get_task_status(
    task_id: str = Field(description="The task ID to check status for")
) -> str:
    """
    Get the current task status and result by task_id.
    
    Use this to check on long-running tasks or tasks that timed out.
    
    Args:
        task_id: The task ID returned from generation endpoints
        
    Returns:
        Current status and result of the task
    """
    logger.info(f"📊 Checking status for task: {task_id}")
    
    if not API_KEY:
        logger.error("❌ API Key missing for get_task_status")
        return "API Key is missing. Cannot process any requests."
    
    status = await _make_api_request("GET", f"/task_status/{task_id}", timeout=POLLING_TIMEOUT)
    
    if not status:
        logger.error(f"❌ Failed to fetch status for task {task_id}")
        return f"Failed to fetch status for task {task_id}."
    
    task_status = status.get("task_status", "Unknown")
    logger.info(f"✅ Task {task_id} status: {task_status}")
    
    return json.dumps(status, indent=2)

@mcp.tool()
async def upload_document(
    file_path: str = Field(description="Path to the document file to upload")
) -> str:
    """
    Upload a document file and return the task_id for processing.
    
    Supported file types: .pptx, .ppt, .docx, .doc, .xlsx, .pdf
    
    Args:
        file_path: Path to the file to upload
        
    Returns:
        Task ID and document UUID for the uploaded file
    """
    logger.info(f"📤 Uploading document: {file_path}")
    
    if not API_KEY:
        logger.error("❌ API Key missing for upload_document")
        return "API Key is missing. Cannot process any requests."

    url = f"{API_BASE}/document/upload"
    headers = {
        "User-Agent": USER_AGENT,
        "X-API-Key": API_KEY,
    }

    # Validate path
    if not os.path.isfile(file_path):
        logger.error(f"❌ File not found: {file_path}")
        return f"File not found: {file_path}"

    file_size = os.path.getsize(file_path)
    logger.info(f"📁 File size: {file_size / 1024:.2f} KB")

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f)}
                logger.info("⬆️  Uploading file...")
                response = await client.post(url, headers=headers, files=files)
                
                logger.info(f"📥 Upload response status: {response.status_code}")
                response.raise_for_status()
                
                data = response.json()
                logger.info(f"✅ Document uploaded successfully")
                if 'task_id' in data:
                    logger.info(f"📋 Task ID: {data['task_id']}")
                if 'document_uuid' in data:
                    logger.info(f"🆔 Document UUID: {data['document_uuid']}")
                    
                return json.dumps(data, indent=2)
                
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP error uploading document: {e.response.status_code}")
        logger.error(f"❌ Response: {e.response.text}")
        return f"Upload failed: {e.response.status_code} {e.response.text}"
    except Exception as e:
        logger.error(f"❌ Unexpected error uploading document: {str(e)}")
        return f"Upload failed: {str(e)}"

# --- MCP Resources ---

@mcp.resource("templates://list")
def templates_resource() -> str:
    """Resource endpoint to get template information"""
    logger.info("📋 Templates resource accessed")
    return """
    SlideSpeak Templates Resource
    
    Use get_available_templates() to fetch the current list of templates.
    Each template includes:
    - Name: Template identifier
    - Cover image URL: Preview of the cover slide
    - Content image URL: Preview of content slides
    
    Templates are regularly updated, so always fetch the latest list before generating.
    """

@mcp.resource("api://documentation")
def api_documentation() -> str:
    """API documentation and usage guide"""
    logger.info("📚 API documentation resource accessed")
    return """
    SlideSpeak MCP API Documentation
    
    ## Authentication
    Set SLIDESPEAK_API_KEY environment variable with your API key.
    
    ## Available Tools
    
    1. get_available_templates()
       - Fetches list of presentation templates
       - No parameters required
    
    2. get_me()
       - Returns user info and credit balance
       - Credits are consumed at 1 per slide
    
    3. generate_powerpoint(plain_text, length, template, document_uuids?)
       - Generates presentation from text
       - Returns download URL for PPTX file
    
    4. generate_slide_by_slide(template, slides, language?, fetch_images?)
       - Precise control over each slide
       - Define layout and content per slide
    
    5. get_task_status(task_id)
       - Check status of generation tasks
       - Useful for long-running operations
    
    6. upload_document(file_path)
       - Upload documents to incorporate
       - Returns document UUID for use in generation
    
    ## Rate Limits
    - Standard API rate limits apply
    - Generation tasks may take 30-90 seconds
    
    ## Credits
    - Each slide costs 1 credit
    - Check balance with get_me()
    """

# --- MCP Prompts ---

@mcp.prompt("slidespeak_workflow")
def slidespeak_workflow() -> str:
    """Recommended workflow for using SlideSpeak"""
    logger.info("💡 Workflow prompt accessed")
    return """
    SlideSpeak Presentation Generation Workflow
    
    1. **Check your credits:**
       - Run get_me() to see your credit balance
       - Remember: 1 credit = 1 slide
    
    2. **Choose a template:**
       - Run get_available_templates() to see options
       - Note the template name you want to use
    
    3. **Prepare your content:**
       - For text-based: Write or paste your content
       - For documents: Upload them first with upload_document()
    
    4. **Generate presentation:**
       
       Option A - Simple generation:
       ```
       generate_powerpoint(
           plain_text="Your content here",
           length=10,  # Number of slides
           template="modern"
       )
       ```
       
       Option B - Slide-by-slide control:
       ```
       generate_slide_by_slide(
           template="modern",
           slides=[
               {
                   "title": "Introduction",
                   "layout": "items",
                   "item_amount": 3,
                   "content": "Point 1|Point 2|Point 3"
               },
               # More slides...
           ]
       )
       ```
    
    5. **Monitor progress:**
       - Generation typically takes 30-90 seconds
       - If it times out, use get_task_status(task_id)
    
    6. **Download result:**
       - The response includes a PPTX download URL
       - Share this URL with the user
    """

@mcp.prompt("slide_layouts")
def slide_layouts_guide() -> str:
    """Guide for available slide layouts"""
    logger.info("📐 Slide layouts prompt accessed")
    return """
    SlideSpeak Slide Layouts Guide
    
    When using generate_slide_by_slide(), you can choose from these layouts:
    
    ## Flexible Layouts (1-5 items)
    - **items**: Bullet points or list items
    - **summary**: Key takeaways or overview
    - **big-number**: Statistics or KPIs
    - **pyramid**: Hierarchical information
    
    ## Fixed Range Layouts (3-5 items)
    - **steps**: Process or procedure steps
    - **milestone**: Timeline events
    - **timeline**: Chronological sequence
    - **funnel**: Sales or conversion funnel
    - **cycle**: Circular process
    
    ## Fixed Count Layouts
    - **comparison**: Exactly 2 items (A vs B)
    - **swot**: Exactly 4 items (Strengths, Weaknesses, Opportunities, Threats)
    - **pestel**: Exactly 6 items (Political, Economic, Social, Technological, Environmental, Legal)
    - **quote**: Exactly 1 item (quotation)
    - **thanks**: 0 items (closing slide)
    
    ## Content Format
    Separate items with pipe character (|):
    "Item 1|Item 2|Item 3"
    
    Make sure item_amount matches the actual number of items!
    """

# --- Main Execution ---

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    # Log server configuration
    logger.info("=" * 60)
    logger.info("🚀 Starting SlideSpeak MCP Server")
    logger.info(f"📍 Port: {port}")
    logger.info(f"🌐 Base URL: {base_url}")
    logger.info(f"🔧 API Base: {API_BASE}")
    logger.info(f"⏱️  Generation Timeout: {GENERATION_TIMEOUT}s")
    logger.info(f"🔄 Polling Interval: {POLLING_INTERVAL}s")
    logger.info("=" * 60)
    
    if API_KEY:
        logger.info("✅ API Key configured")
        logger.info(f"🔑 Key prefix: {API_KEY[:8]}...")
    else:
        logger.warning("⚠️  No API key configured")
        logger.warning("⚠️  Set SLIDESPEAK_API_KEY environment variable")
    
    logger.info("=" * 60)
    logger.info("📡 Server endpoints:")
    logger.info(f"  Health: {base_url}/health/status")
    logger.info(f"  MCP: {base_url}/mcp")
    logger.info("=" * 60)
    
    # Run FastMCP server with streamable-http transport for Railway deployment
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",  # Bind to all interfaces for cloud deployment
        port=port
    )
