"""MCP Server application for Wayland interactions.
This module provides core functionality for the Wayland MCP server including:
- Screenshot capture with various backends
- Vision-Language Model (VLM) integration for image analysis
- Mouse control utilities
- Environment configuration for optimal capture performance
"""
import os
import shutil
import subprocess
import time
import logging
import base64
import requests
def configure_environment():
    """Set up optimized capture environment"""
    env = os.environ.copy()
    env.update(
        {
            "LD_LIBRARY_PATH": "/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu",
            "GTK_PATH": "",
            "GST_PLUGIN_SYSTEM_PATH": "/usr/lib/x86_64-linux-gnu/gstreamer-1.0",
            "PULSE_PROP_OVERRIDE": "filter.want=echo-cancel",
        }
    )
    # Ensure silent sound theme exists in system or user location
    system_sound_dir = "/usr/share/sounds/silent/stereo"
    user_sound_dir = os.path.expanduser("~/.local/share/sounds/silent/stereo")
    # Try system location first
    if not os.path.exists(system_sound_dir):
        os.makedirs(user_sound_dir, exist_ok=True)
        sound_dir = user_sound_dir
    else:
        sound_dir = system_sound_dir
    # Create silent sound file if needed
    sound_file = os.path.join(sound_dir, "screen-capture.oga")
    if not os.path.exists(sound_file):
        # Create an empty file using 'with' to ensure it's closed
        with open(sound_file, "w", encoding="utf-8") as _:  # Use _ for unused variable
            pass  # Just create the file
    env["SOUND_THEME"] = "silent"
    return env
def minimize_effects():
    """Reduce visual and sound effects"""
    try:
        # Reduce animations (minimizes flash)
        subprocess.run(
            [
                "gsettings",
                "set",
                "org.gnome.desktop.interface",
                "enable-animations",
                "false",
            ],
            check=True,
        )
        # Disable event sounds
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.sound", "event-sounds", "false"],
            check=True,
        )
        time.sleep(0.3)  # Allow settings to apply
    except subprocess.CalledProcessError as e:
        logging.error("Error minimizing effects: %s", e)
def restore_effects():
    """Restore original system settings"""
    try:
        subprocess.run(
            [
                "gsettings",
                "set",
                "org.gnome.desktop.interface",
                "enable-animations",
                "true",
            ],
            check=True,
        )
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.sound", "event-sounds", "true"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logging.error("Error restoring effects: %s", e)
from enum import Enum
from typing import Optional, Dict, Any

class CaptureMode(Enum):
    """Enumeration for capture modes to improve type safety and readability."""
    AUTO = "auto"
    REGION = "region"
    WINDOW = "window"

def _select_region(tool: str) -> Optional[str]:
    """Helper to select region using the specified tool, returning geometry or None."""
    if tool == "slurp" and shutil.which("slurp"):
        try:
            result = subprocess.run(
                ["slurp"], capture_output=True, text=True, timeout=10, check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logging.warning("slurp region selection timed out")
    elif tool == "xrandr" and shutil.which("xrandr"):
        try:
            result = subprocess.run(
                ["sh", "-c", "xrandr | grep ' connected'"],
                capture_output=True, text=True, timeout=10, check=False
            )
            if result.returncode == 0:
                # Parse basic geometry (implement full parsing if needed)
                # Placeholder: Assume first connected display
                # In production, expand to parse actual geometry from output
                return "0,0,1920,1080"  # Example fallback; replace with real parsing
        except subprocess.TimeoutExpired:
            logging.warning("xrandr region selection timed out")
    return None

def _try_ksnip(output_path: str, include_mouse: bool, env: Dict[str, str]) -> bool:
    """Attempt capture with ksnip (prioritized for stability)."""
    if not shutil.which("ksnip"):
        return False
    cmd = ["ksnip", "-f", output_path, "-m"]  # -m for silent mode
    if include_mouse:
        cmd.append("-c")  # Include cursor
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, timeout=15, check=False
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logging.error("ksnip timed out")
        return False

def _try_gnome_screenshot(output_path: str, include_mouse: bool, env: Dict[str, str]) -> bool:
    """Attempt capture with gnome-screenshot (fallback for GNOME)."""
    if not shutil.which("gnome-screenshot"):
        return False
    cmd = ["gnome-screenshot", "-f", output_path]
    if include_mouse:
        cmd.append("--include-pointer")
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, timeout=20, check=False
        )  # Reduced timeout for efficiency
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logging.error("gnome-screenshot timed out")
        return False

def _try_spectacle(output_path: str, env: Dict[str, str]) -> bool:
    """Attempt capture with spectacle (KDE-oriented)."""
    if not shutil.which("spectacle"):
        return False
    cmd = ["spectacle", "--fullscreen", "--background", "--nonotify", "--output", output_path]
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, timeout=20, check=False
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logging.error("spectacle timed out")
        return False

def _try_grim(output_path: str, mode: CaptureMode, geometry: Optional[str], include_mouse: bool, env: Dict[str, str]) -> bool:
    """Attempt capture with grim (Wayland-specific)."""
    if not (os.environ.get("WAYLAND_DISPLAY") and shutil.which("grim")):
        return False
    if include_mouse:
        logging.warning("Grim does not support cursor capture; mouse will not be visible")
    cmd = ["grim", output_path]
    if mode == CaptureMode.REGION and geometry:
        cmd = ["grim", "-g", geometry, output_path]
    elif mode == CaptureMode.REGION and not geometry:
        logging.error("Region mode requires geometry for grim")
        return False
    try:
        subprocess.run(cmd, env=env, timeout=15, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logging.error("Grim capture failed: %s", e)
        return False

def minimize_effects() -> None:
    """Reduce visual and sound effects (unchanged but made into standalone function)."""
    try:
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.interface", "enable-animations", "false"],
            check=True
        )
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.sound", "event-sounds", "false"],
            check=True
        )
        time.sleep(0.3)  # Allow settings to apply
    except subprocess.CalledProcessError as e:
        logging.error("Error minimizing effects: %s", e)

def restore_effects() -> None:
    """Restore original system settings (unchanged but made into standalone function)."""
    try:
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.interface", "enable-animations", "true"],
            check=True
        )
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.sound", "event-sounds", "true"],
            check=True
        )
    except subprocess.CalledProcessError as e:
        logging.error("Error restoring effects: %s", e)

# pylint: disable=too-many-branches
def capture_screenshot(
    output_path: str = None,
    mode: str = "auto",
    geometry: str = None,
    include_mouse: bool = True
) -> Dict[str, Any]:
    """
    Capture screenshot with optional region selection and mouse cursor.

    Args:
        output_path: Output file path (default: screenshot.png).
        mode: Capture mode ('auto', 'region', 'window').
        geometry: Optional pre-defined geometry (x,y,w,h) for region mode.
        include_mouse: Whether to include mouse cursor (default: True).

    Returns:
        Dict with 'success': bool, 'filename': str (on success), 'error': str (on failure).
    """
    if output_path is None:
        output_path = os.path.abspath("screenshot.png")
    # Validate and convert mode early
    try:
        capture_mode = CaptureMode(mode)
    except ValueError:
        return {"success": False, "error": f"Invalid mode: {mode}"}
    # Pre-check: Ensure output path is writable
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'wb') as _:
            pass  # Create/overwrite to test write access
    except (OSError, ValueError) as e:
        return {"success": False, "error": f"Invalid output path: {e}"}

    logging.info("Starting screenshot capture in mode: %s", capture_mode.value)
    env = configure_environment()
    # Define capture methods in priority order (e.g., prioritize commonly available tools)
    capture_methods = [
        (_try_ksnip, "ksnip"),
        (_try_gnome_screenshot, "gnome-screenshot"),
        (_try_spectacle, "spectacle"),
        (_try_grim, "grim"),
    ]
    success = False
    error = "All capture methods failed"

    try:
        minimize_effects()
        # Force mute as backup
        subprocess.run(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            env=env, check=False
        )
        # Handle region selection early if needed
        resolved_geometry = geometry
        if capture_mode == CaptureMode.REGION and not resolved_geometry:
            resolved_geometry = _select_region("slurp") or _select_region("xrandr") or None
            if not resolved_geometry:
                error = "Region selection failed; no geometry obtained"
            else:
                logging.info("Selected region geometry: %s", resolved_geometry)
        # Attempt captures in order
        for method_func, method_name in capture_methods:
            # Adjust parameters based on method (grim needs mode and geometry)
            if method_name == "grim":
                if method_func(output_path, capture_mode, resolved_geometry, include_mouse, env):
                    logging.info("Capture succeeded with %s", method_name)
                    success = True
                    break
            else:
                if method_func(output_path, include_mouse, env):
                    logging.info("Capture succeeded with %s", method_name)
                    success = True
                    break
        # Note: Window mode is not implemented per original code; skip for now
        if success:
            return {"success": True, "filename": output_path}
        return {"success": False, "error": error}
    except Exception as e:
        logging.error("Unexpected error during capture: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        restore_effects()
        subprocess.run(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
            env=env, check=False
        )
class VLMAgent:
    """Agent for interacting with Vision-Language Models (VLMs).
    Handles image analysis and comparison using VLM APIs.
    Requires an API key for authentication.
    """
    def __init__(self, api_key=None):
        """Initialize with API key validation"""
        self.api_key = api_key
        if not api_key:
            logging.warning("VLMAgent initialized without API key!")
        else:
            logging.info("VLMAgent initialized with valid API key")
    def compare_images(
        self,
        img1_path: str,
        img2_path: str,
    ) -> str:
        """Compare two images using VLM analysis"""
        if not self.api_key:
            logging.error("No API key configured for VLMAgent")
            return "Error: No API key configured for VLMAgent"
        # Verify both images exist
        for img_path in [img1_path, img2_path]:
            if not os.path.exists(img_path):
                logging.error("Image file not found: %s", img_path)
                return f"Error: Image file not found - {img_path}"
        # Encode both images
        encoded_images = []
        for img_path in [img1_path, img2_path]:
            try:
                with open(img_path, "rb") as image_file:
                    encoded_images.append(
                        base64.b64encode(image_file.read()).decode("utf-8")
                    )
            except (IOError, OSError) as e:
                logging.error("Failed to encode image %s: %s", img_path, str(e))
                return f"Error: Failed to process image {img_path} - {str(e)}"
        # Prepare request matching test script
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/your-repo",
            "X-Title": "Wayland MCP"
        }
        # Match the toy script's prompt structure exactly
        payload = {
            "model": "qwen/qwen2.5-vl-72b-instruct:free",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Compare these two screenshots in detail."},
                        {"type": "text", "text": "Focus on:"},
                        {"type": "text", "text": "1. Application windows and their content"},
                        {"type": "text", "text": "2. Layout and positioning differences"},
                        {"type": "text", "text": "3. Any visual changes between them"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encoded_images[0]}",
                                "detail": "high"
                            }
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encoded_images[1]}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 2000
        }
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return (
                f"API error: {response.status_code} - "
                f"{response.text}"
            )
        except requests.exceptions.RequestException as e:
            return f"Request failed: {str(e)}"
    def analyze_image(self, image_path: str, prompt: str) -> str:
        """Analyze a single image using VLM analysis"""
        return self.analyze_screenshot(image_path, prompt)
# pylint: disable=too-many-locals
    def analyze_screenshot(self, image_path: str, prompt: str) -> str:
        """Analyze screenshot using Kimi-VL model
        Args:
            image_path: Path to image file
            prompt: Text prompt for analysis
        Returns:
            str: Analysis result or error message
        """
        # Validate inputs
        if not self.api_key or not os.path.exists(image_path):
            if not self.api_key:
                error_msg = "Error: No API key configured for VLMAgent"
            else:
                error_msg = f"Error: Image file not found - {image_path}"
            logging.error(error_msg)
            return error_msg
        # Encode image
        try:
            with open(image_path, "rb") as image_file:
                file_size = os.path.getsize(image_path)
                logging.info("Processing image: %s (%d bytes)", image_path, file_size)
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
                logging.info("Image encoded successfully (%d chars)", len(encoded_image))
        except (IOError, OSError) as e:
            error_msg = f"Error: Failed to process image - {str(e)}"
            logging.error(error_msg)
            return error_msg
        # Break long dictionary assignment
        auth_header = f"Bearer {self.api_key.strip()}"
        headers = {
            "Authorization": auth_header,
            "HTTP-Referer": "https://github.com/your-repo",  # Keep this line short
            "X-Title": "Wayland MCP",
            "Content-Type": "application/json",
        }
        logging.info("Using API key starting with: %s...", self.api_key[:8])
        payload = {
            "model": os.environ.get(
                "VLM_MODEL", "moonshotai/kimi-vl-a3b-thinking:free"
            ),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            # Break long line
                            "image_url": f"data:image/png;base64,{encoded_image}",
                        },
                    ],
                }
            ],
            "max_tokens": 1000,
        }
        logging.info("Sending VLM request with prompt: %s", prompt)
        try:
            start_time = time.time()
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            elapsed = time.time() - start_time
            logging.info("VLM request completed in %.2fs", elapsed)
            if response.status_code == 200:
                try:
                    result = response.json()["choices"][0]["message"]["content"]
                    logging.info("VLM analysis result: %.200s...", result)
                    return result
                except KeyError as e:
                    error_msg = (f"VLM API response format error: {str(e)}. "
                               f"Full response: {response.text}")
                    if "quota" in response.text.lower():
                        error_msg = ("API quota exceeded. Please switch to "
                                   "a different API key or wait until quota resets.")
                    logging.error(error_msg)
                    return error_msg
            # Handle API errors with more specific messages
            error_msg = f"VLM API error {response.status_code}"
            if response.status_code == 429:
                error_msg = ("API quota exceeded. Please switch to "
                           "a different API key or wait until quota resets.")
            elif "quota" in response.text.lower():
                error_msg = ("API quota exceeded. Please switch to "
                           "a different API key or wait until quota resets.")
            logging.error("%s: %s", error_msg, response.text)
            return (f"{error_msg}\n"
                   f"Response details: {response.text}")
        except requests.exceptions.RequestException as e:
            logging.error("VLM request failed: %s", str(e))
            # Return f-string directly to reduce local variables
            return f"VLM request failed: {str(e)}"
