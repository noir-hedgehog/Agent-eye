"""
Enhanced capture utilities for The Eyes
Features: grid overlay, mouse coordinates, window/region capture
"""

import subprocess
import platform
import os
import tempfile
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont


def get_mouse_position() -> Optional[Tuple[int, int]]:
    """
    Get current mouse cursor position.
    Returns (x, y) or None if failed.
    """
    os_type = platform.system()
    
    try:
        if os_type == "Darwin":  # macOS
            # Use AppleScript to get mouse position
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get {x position, y position} of (process "System Events")'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                coords = result.stdout.strip().split(", ")
                return (int(coords[0]), int(coords[1]))
        elif os_type == "Linux":
            # Use xdotool or python-evdev
            result = subprocess.run(
                ["xdotool", "getmouselocation"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # Output: x:1234 y:5678 screen:0
                parts = result.stdout.strip().split()
                x = int(parts[0].split(":")[1])
                y = int(parts[1].split(":")[1])
                return (x, y)
        elif os_type == "Windows":
            # Use pygetwindow or ctypes
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return (pt.x, pt.y)
    except Exception:
        pass
    
    return None


def add_grid_overlay(img: Image.Image, grid_size: int = 100, color: Tuple[int, int, int] = (128, 128, 128)) -> Image.Image:
    """
    Add grid overlay to image.
    
    Args:
        img: PIL Image
        grid_size: Grid cell size in pixels (default 100)
        color: RGB color for grid lines
    
    Returns:
        Image with grid overlay
    """
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    # Draw vertical lines
    for x in range(0, width, grid_size):
        draw.line([(x, 0), (x, height)], color, 1)
    
    # Draw horizontal lines
    for y in range(0, height, grid_size):
        draw.line([(0, y), (width, y)], color, 1)
    
    return img


def add_mouse_coordinates(img: Image.Image, mouse_pos: Optional[Tuple[int, int]] = None, 
                          show_label: bool = True, show_crosshair: bool = True) -> Image.Image:
    """
    Add mouse position indicator to image.
    
    Args:
        img: PIL Image
        mouse_pos: Mouse (x, y) position. If None, will try to get current position.
        show_label: Show coordinate label
        show_crosshair: Show crosshair at position
    
    Returns:
        Image with mouse coordinates overlay
    """
    if mouse_pos is None:
        mouse_pos = get_mouse_position()
    
    if mouse_pos is None:
        return img  # No position available
    
    x, y = mouse_pos
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    # Clamp to image bounds
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    
    # Crosshair settings
    crosshair_color = (255, 0, 0)  # Red
    crosshair_size = 15
    
    if show_crosshair:
        # Draw crosshair
        # Horizontal line
        draw.line([(x - crosshair_size, y), (x + crosshair_size, y)], crosshair_color, 2)
        # Vertical line
        draw.line([(x, y - crosshair_size), (x, y + crosshair_size)], crosshair_color, 2)
        # Circle
        draw.ellipse([x-8, y-8, x+8, y+8], outline=crosshair_color, width=2)
    
    if show_label:
        # Draw coordinate label
        label_text = f"({x}, {y})"
        
        # Try to use a font, fallback to default
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except:
            font = ImageFont.load_default()
        
        # Get text size
        bbox = draw.textbbox((0, 0), label_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Label position (avoid going off screen)
        label_x = x + 20
        label_y = y - 30
        if label_x + text_width + 10 > width:
            label_x = x - text_width - 30
        if label_y < 0:
            label_y = y + 20
        
        # Draw background rectangle
        padding = 6
        bg_box = [
            label_x - padding,
            label_y - padding,
            label_x + text_width + padding,
            label_y + text_height + padding
        ]
        draw.rectangle(bg_box, fill=(0, 0, 0, 200))  # Semi-transparent black
        
        # Draw text
        draw.text((label_x, label_y), label_text, fill=(255, 255, 0), font=font)  # Yellow
    
    return img


def capture_region(x: int, y: int, width: int, height: int) -> bytes:
    """
    Capture a specific region of the screen.
    
    Args:
        x: Left coordinate
        y: Top coordinate
        width: Region width
        height: Region height
    
    Returns:
        Image bytes
    """
    os_type = platform.system()
    
    try:
        if os_type == "Darwin":
            temp_file = tempfile.mktemp(suffix=".png")
            subprocess.run(
                ["screencapture", "-R", f"{x},{y},{width},{height}", "-x", temp_file],
                check=True, timeout=5
            )
            img = Image.open(temp_file)
            os.remove(temp_file)
            return img
        elif os_type == "Linux":
            # Use import from ImageMagick
            temp_file = tempfile.mktemp(suffix=".png")
            subprocess.run(
                ["import", "-window", "root", "-crop", f"{width}x{height}+{x}+{y}", temp_file],
                check=True, timeout=5
            )
            img = Image.open(temp_file)
            os.remove(temp_file)
            return img
    except Exception as e:
        print(f"[WARN] Region capture failed: {e}")
    
    return None


def list_windows() -> list:
    """
    List available windows on the system.
    Returns list of window info dicts.
    """
    os_type = platform.system()
    windows = []
    
    try:
        if os_type == "Darwin":
            # Use AppleScript to get window list
            script = '''
            tell application "System Events"
                set windowList to {}
                repeat with p in (every process whose background only is false)
                    try
                        set processName to name of p
                        repeat with w in (every window of p)
                            set windowName to name of w
                            set windowPos to position of w
                            set windowSize to size of w
                            set end of windowList to {processName, windowName, item 1 of windowPos, item 2 of windowPos, item 1 of windowSize, item 2 of windowSize}
                        end repeat
                    end try
                end repeat
                return windowList
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(", ")
                        if len(parts) >= 6:
                            windows.append({
                                "app": parts[0],
                                "title": parts[1],
                                "x": int(parts[2]),
                                "y": int(parts[3]),
                                "width": int(parts[4]),
                                "height": int(parts[5])
                            })
        elif os_type == "Linux":
            # Use wmctrl
            result = subprocess.run(
                ["wmctrl", "-l", "-G"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 7:
                        windows.append({
                            "app": parts[[-1]],
                            "title": " ".join(parts[4:-1]),
                            "x": int(parts[2]),
                            "y": int(parts[3]),
                            "width": int(parts[4]),
                            "height": int(parts[5])
                        })
    except Exception as e:
        print(f"[WARN] Window list failed: {e}")
    
    return windows
