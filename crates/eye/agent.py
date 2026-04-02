import json
import time
import requests
import os
import sys
import tempfile
import subprocess
import socket
import struct
import platform
import signal
from io import BytesIO
from PIL import Image
from typing import Any, Dict, Optional

from .utils.qwen_vision import (
    QWEN35_RECOMMENDED_MAX_LONGEST_EDGE,
    merge_vision_meta,
)
from datetime import datetime, timedelta
from PIL import ImageDraw, ImageFont

# Enhanced capture functions (inline)
def _get_mouse_position():
    """Get current mouse cursor position."""
    os_type = platform.system()
    try:
        if os_type == "Darwin":
            # Use Quartz for reliable mouse position
            import Quartz
            pos = Quartz.NSEvent.mouseLocation()
            height = Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID())
            x = int(pos.x)
            y = int(height - pos.y)
            return (x, y)
        elif os_type == "Linux":
            result = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                x = int(parts[0].split(":")[1])
                y = int(parts[1].split(":")[1])
                return (x, y)
        elif os_type == "Windows":
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return (pt.x, pt.y)
    except Exception as e:
        print(f"[WARN] Get mouse position failed: {e}")
    return None

def _add_grid_overlay(img, grid_size=100, color=(128, 128, 128)):
    """Add grid overlay to image."""
    draw = ImageDraw.Draw(img)
    width, height = img.size
    for x in range(0, width, grid_size):
        draw.line([(x, 0), (x, height)], color, 1)
    for y in range(0, height, grid_size):
        draw.line([(0, y), (width, y)], color, 1)
    return img

def _add_mouse_coordinates(img, mouse_pos=None, show_label=True, show_crosshair=True):
    """Add mouse position indicator to image."""
    if mouse_pos is None:
        mouse_pos = _get_mouse_position()
    if mouse_pos is None:
        return img
    
    x, y = mouse_pos
    draw = ImageDraw.Draw(img)
    width, height = img.size
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    
    if show_crosshair:
        crosshair_color = (255, 0, 0)
        draw.line([(x - 15, y), (x + 15, y)], crosshair_color, 2)
        draw.line([(x, y - 15), (x, y + 15)], crosshair_color, 2)
        draw.ellipse([x-8, y-8, x+8, y+8], outline=crosshair_color, width=2)
    
    if show_label:
        label_text = f"({x}, {y})"
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except:
            font = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), label_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        label_x, label_y = x + 20, y - 30
        if label_x + text_width + 10 > width:
            label_x = x - text_width - 30
        if label_y < 0:
            label_y = y + 20
        
        padding = 6
        draw.rectangle([label_x - padding, label_y - padding, label_x + text_width + padding, label_y + text_height + padding], fill=(0, 0, 0, 200))
        draw.text((label_x, label_y), label_text, fill=(255, 255, 0), font=font)
    
    return img


def _get_active_window_title() -> Optional[str]:
    """Best-effort foreground window / app title (helps LLM agents with UI context)."""
    os_type = platform.system()
    try:
        if os_type == "Darwin":
            script = (
                'tell application "System Events" to get name of first application process '
                "whose frontmost is true"
            )
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=0.85,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()[:240]
        elif os_type == "Windows":
            import ctypes

            u32 = ctypes.windll.user32
            hwnd = u32.GetForegroundWindow()
            if not hwnd:
                return None
            ln = u32.GetWindowTextLengthW(hwnd)
            if ln <= 0:
                return None
            buf = ctypes.create_unicode_buffer(ln + 1)
            u32.GetWindowTextW(hwnd, buf, ln + 1)
            return (buf.value or "")[:240] or None
        elif os_type == "Linux":
            r = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=0.85,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()[:240]
    except Exception:
        pass
    return None


def _resize_max_dimension(img: Image.Image, max_dim: int) -> Image.Image:
    """Scale down so the longest edge is at most max_dim (aspect preserved)."""
    max_dim = max(32, int(max_dim))
    w, h = img.size
    longest = max(w, h)
    if longest <= max_dim:
        return img
    ratio = max_dim / float(longest)
    nw = max(1, int(w * ratio))
    nh = max(1, int(h * ratio))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


ENHANCED_CAPTURE_AVAILABLE = True

# Check for MSS availability
try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    print("[WARN] mss not installed. Install with: pip install mss")

# Universal Capture Agent (Linux, Windows, macOS).
class Agent:
    """
    Universal Capture Agent (Linux, Windows, macOS).
    Now with: format control, quality settings, duration/frame limits
    Enhanced: grid overlay, mouse coordinates, window/region capture
    """
    
    # Initialization
    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        interval: float = 1.5,
        format: str = "png",
        quality: int = 95,
        duration: Optional[int] = None,
        max_frames: Optional[int] = None,
        notify: bool = True,
        # Enhanced capture options
        grid_size: int = 0,  # 0 = disabled, >0 = grid cell size
        show_mouse: bool = False,  # Show mouse coordinates overlay
        region: Optional[str] = None,  # "x,y,width,height" or None for fullscreen
        # Vision / agent integration
        monitor_index: int = 1,  # mss monitor index: 0=all virtual, 1=primary, …
        max_dimension: Optional[int] = None,  # scale down longest edge (e.g. 1280 for vision APIs)
        vision_context: bool = True,  # attach JSON vision_meta to each upload
        window_title: bool = True,  # include active window title when vision_context (best-effort)
        vision_preset: Optional[str] = None,  # e.g. "qwen35-plus" — align capture + meta for Qwen/DashScope
    ):
        self.interval = interval
        self.format = format.lower()
        self.quality = max(1, min(100, quality))
        self.duration = duration
        self.max_frames = max_frames
        self.notify = notify
        
        # Enhanced options
        self.grid_size = grid_size
        self.show_mouse = show_mouse
        self.region = region
        if region:
            parts = region.split(",")
            if len(parts) == 4:
                self.region_rect = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
            else:
                self.region_rect = None
        else:
            self.region_rect = None

        self.monitor_index = max(0, int(monitor_index))
        vp = (vision_preset or "").strip().lower()
        self.vision_preset = vp if vp and vp != "none" else None
        # Qwen3.5 / DashScope: default max_pixels 2_621_440 → ~1619px longest edge if unset
        if max_dimension is None and self.vision_preset in (
            "qwen35-plus",
            "qwen3.5-plus",
            "dashscope-qwen35",
        ):
            self.max_dimension = QWEN35_RECOMMENDED_MAX_LONGEST_EDGE
        else:
            self.max_dimension = max_dimension
        self.vision_context = vision_context
        self.window_title = window_title
        self._prev_frame_pix: Optional[list] = None
        self._pending_vision: Optional[Dict[str, Any]] = None
        
        self.frame_id = 0
        self.retry_delay = 1
        self.token = token
        self.os_type = platform.system()
        self.running = False
        self.start_time = None
        self.stop_time = None
        
        # Validate format
        if self.format not in ['png', 'jpeg', 'jpg', 'webp', 'bmp', 'tiff']:
            raise ValueError(f"Unsupported format: {format}. Use 'png' or 'jpeg'")
        if self.format == 'jpg':
            self.format = 'jpeg'
        
        # Resolve Server URL
        if server_url:
            self.server_url = server_url.rstrip('/')
            print(f"[INFO] Server URL set via CLI: {self.server_url}")
        else:
            self.server_url = self.detect_mediator()
            
        self.upload_endpoint = f"{self.server_url}/upload"
        self.connect_endpoint = f"{self.server_url}/connect"
        self.disconnect_endpoint = f"{self.server_url}/disconnect"
        
        print(f"[INFO] Eye Agent initializing on {self.os_type}...")
        print(f"[INFO] Target: {self.upload_endpoint}")
        print(f"[INFO] Format: {self.format.upper()}")
        if self.format == 'jpeg':
            print(f"[INFO] Quality: {self.quality}/100")
        print(f"[INFO] Interval: {self.interval}s")
        if self.duration:
            print(f"[INFO] Duration: {self.duration}s (auto-stop)")
        if self.max_frames:
            print(f"[INFO] Max frames: {self.max_frames} (auto-stop)")
        if not self.region_rect:
            print(f"[INFO] Monitor index (mss): {self.monitor_index}")
        if self.max_dimension:
            print(f"[INFO] Max dimension (longest edge): {self.max_dimension}px")
        print(f"[INFO] Vision meta JSON: {'on' if self.vision_context else 'off'}")
        
        # 2. Detect Capture Method
        self.capture_method = self._detect_capture_method()
        print(f"[INFO] Capture Strategy: {self.capture_method}")
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # Signal Handler
    def _signal_handler(self, signum, frame):
        """Handle stop signals gracefully"""
        print("\n[INFO] Stop signal received...")
        self.stop()
    
    def _auth_headers(self) -> dict:
        """Return authorization headers if a token is set"""
        if self.token:
            return {'Authorization': f'Bearer {self.token}'}
        return {}
    
    # Mediator Detection
    def detect_mediator(self) -> str:
        """Robust discovery strategy"""
        env_url = os.environ.get("MEDIATOR_URL")
        if env_url:
            return env_url.rstrip('/')

        print("[*] Auto-detecting Server...")
        candidates = [
            "http://localhost:8080",
            "http://mediator:8080",
            "http://host.docker.internal:8080"
        ]

        # Linux-specific Gateway Detection
        if self.os_type == "Linux":
            try:
                with open("/proc/net/route") as fh:
                    for line in fh:
                        fields = line.strip().split()
                        if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                            continue
                        gateway_ip = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
                        candidates.append(f"http://{gateway_ip}:8080")
                        break
            except Exception:
                pass

        for url in candidates:
            try:
                requests.get(f"{url}/health", timeout=1)
                print(f"[*] Found server at: {url}")
                return url
            except:
                continue

        return "http://localhost:8080"
    
    # Capture Method Detection
    def _detect_capture_method(self) -> str:
        """Determine best capture method based on OS"""
        
        # Linux Wayland Check (Needs external tools)
        if self.os_type == "Linux":
            if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
                return "linux_system"
        
        # Cross-Platform MSS (Best for Win/Mac/Linux X11)
        if MSS_AVAILABLE:
            try:
                from mss import mss 
                with mss() as sct:
                    sct.monitors
                return "mss"
            except Exception:
                pass
        
        # OS-Specific Fallbacks
        if self.os_type == "Darwin":
            return "macos_screencapture"
        elif self.os_type == "Linux":
            return "linux_system"
            
        return "test_pattern"

    # Wait for Server
    def wait_for_server(self, timeout: Optional[int] = None) -> bool:
        """Block until server is healthy"""
        print("[INFO] Waiting for server...")
        attempt = 0
        start_time = time.time()
        while True:
            if timeout and (time.time() - start_time > timeout):
                print("[ERROR] Server not reachable (Timeout).")
                return False
            attempt += 1
            try:
                response = requests.get(f"{self.server_url}/health", timeout=2)
                if response.status_code == 200:
                    print(f"[INFO] Server ready! (Connected on attempt {attempt})")
                    return True
            except Exception:
                pass
            if attempt % 10 == 0:
                print(f"[INFO] Still waiting for server... (Attempt {attempt})")
                time.sleep(2)
    
    # Connect to Server
    def connect_to_server(self) -> bool:
        """
        Claim the server's single connection slot.
        Returns False if another agent is already connected (HTTP 409).
        """
        try:
            response = requests.post(
                self.connect_endpoint,
                headers=self._auth_headers(),
                timeout=5
            )
            if response.status_code == 409:
                print(
                    "[ERROR] Another agent is already connected to this server.\n"
                    "[ERROR] This server operates in 1:1 mode. "
                    "Stop the existing agent before starting a new one."
                )
                return False
            if response.status_code != 200:
                print(f"[ERROR] Connect failed: HTTP {response.status_code}: {response.text}")
                return False
            print("[INFO] Agent registered with server (1:1 connection established)")
            return True
        except Exception as e:
            print(f"[ERROR] Could not reach connect endpoint: {e}")
            return False
    
    # Get Server URL
    def disconnect_from_server(self):
        """
        Release the server's connection slot.
        Best-effort — a warning is printed on failure.
        """
        try:
            response = requests.post(
                self.disconnect_endpoint,
                headers=self._auth_headers(),
                timeout=5
            )
            if response.status_code == 200:
                print("[INFO] Disconnected from server — slot is now free")
            else:
                print(f"[WARN] Disconnect returned HTTP {response.status_code}. "
                    "The server slot may remain occupied.")
        except Exception as e:
            print(f"[WARN] Failed to disconnect cleanly: {e}. "
                "The server slot may remain occupied until the server restarts.")
        
    # Auto-Stop Check
    def _should_stop(self) -> bool:
        """Check if agent should stop based on limits"""
        if not self.running:
            return True
        
        # Duration limit
        if self.duration and self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            if elapsed >= self.duration:
                print(f"\n[INFO] Duration limit reached ({self.duration}s)")
                return True
        
        # Frame limit
        if self.max_frames and self.frame_id >= self.max_frames:
            print(f"\n[INFO] Frame limit reached ({self.max_frames} frames)")
            return True
        
        return False
    
    # Screen Capture
    def capture_screen(self) -> bytes:
        """Capture and encode in configured format"""
        t0 = time.time()
        self._pending_vision = None

        # Handle region capture
        if self.region_rect:
            x, y, w, h = self.region_rect
            img = self._capture_region(x, y, w, h)
            if img is None:
                return self._generate_test_pattern()
        else:
            # Normal capture
            if self.capture_method == "mss":
                img = self._capture_mss_image()
            elif self.capture_method == "linux_system":
                img_bytes = self._capture_linux_fallback()
                img = Image.open(BytesIO(img_bytes))
            elif self.capture_method == "macos_screencapture":
                img_bytes = self._capture_macos()
                img = Image.open(BytesIO(img_bytes))
            else:
                img_bytes = self._generate_test_pattern()
                img = Image.open(BytesIO(img_bytes))
        
        # Apply enhanced overlays
        img = self._apply_enhancements(img)

        if self.max_dimension:
            img = _resize_max_dimension(img, self.max_dimension)

        elapsed = time.time() - t0
        change_score: Optional[float] = None
        if self.vision_context:
            change_score = self._compute_frame_change_score(img)
            self._pending_vision = self._build_vision_context(img, elapsed, change_score)

        # Encode to configured format
        return self._encode_image(img)
    
    def _capture_region(self, x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """Capture a specific region of the screen"""
        os_type = platform.system()
        temp_file = tempfile.mktemp(suffix=".png")
        
        try:
            if os_type == "Darwin":
                subprocess.run(
                    ["/usr/sbin/screencapture", "-R", f"{x},{y},{width},{height}", "-x", temp_file],
                    check=True, timeout=5
                )
            elif os_type == "Linux":
                subprocess.run(
                    ["import", "-window", "root", "-crop", f"{width}x{height}+{x}+{y}", temp_file],
                    check=True, timeout=5
                )
            else:
                return None
            
            img = Image.open(temp_file)
            os.remove(temp_file)
            return img
        except Exception as e:
            print(f"[WARN] Region capture failed: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return None
    
    def _apply_enhancements(self, img: Image.Image) -> Image.Image:
        """Apply grid and mouse coordinate overlays"""
        # Get mouse position (relative to captured region if using region capture)
        mouse_pos = None
        if self.show_mouse:
            screen_pos = _get_mouse_position()
            if screen_pos and self.region_rect:
                # Convert screen coordinates to region-relative coordinates
                reg_x, reg_y, reg_w, reg_h = self.region_rect
                rel_x = screen_pos[0] - reg_x
                rel_y = screen_pos[1] - reg_y
                # Only show if within region bounds
                if 0 <= rel_x < reg_w and 0 <= rel_y < reg_h:
                    mouse_pos = (rel_x, rel_y)
            elif screen_pos:
                mouse_pos = screen_pos
        
        # Add grid overlay
        if self.grid_size > 0:
            img = _add_grid_overlay(img, grid_size=self.grid_size)
        
        # Add mouse coordinates (relative to captured region)
        if self.show_mouse and mouse_pos:
            img = _add_mouse_coordinates(img, mouse_pos=mouse_pos)
        
        return img

    def _compute_frame_change_score(self, img: Image.Image) -> Optional[float]:
        """
        Normalized 0..1 score vs previous frame (64×64 luminance).
        First frame returns None.
        """
        small = img.convert("L").resize((64, 64), Image.Resampling.LANCZOS)
        pix = list(small.getdata())
        if self._prev_frame_pix is None:
            self._prev_frame_pix = pix
            return None
        n = len(pix)
        total = sum(abs(a - b) for a, b in zip(pix, self._prev_frame_pix))
        self._prev_frame_pix = pix
        return round((total / float(n * 255)), 4)

    def _build_vision_context(
        self,
        img: Image.Image,
        capture_seconds: float,
        change_score: Optional[float],
    ) -> Dict[str, Any]:
        w, h = img.size
        ctx: Dict[str, Any] = {
            "width": w,
            "height": h,
            "platform": self.os_type,
            "capture_latency_ms": round(capture_seconds * 1000.0, 2),
        }
        if not self.region_rect:
            ctx["monitor_index"] = self.monitor_index
        else:
            rx, ry, rw, rh = self.region_rect
            ctx["region"] = {"x": rx, "y": ry, "w": rw, "h": rh}
        if self.max_dimension:
            ctx["max_dimension_applied"] = self.max_dimension
        if change_score is not None:
            ctx["frame_change_score"] = change_score
        mp = _get_mouse_position()
        if mp:
            ctx["mouse_screen"] = {"x": mp[0], "y": mp[1]}
        if self.window_title:
            title = _get_active_window_title()
            if title:
                ctx["active_window_title"] = title
        return merge_vision_meta(ctx, self.vision_preset)

    # Encode Image
    def _encode_image(self, img: Image.Image) -> bytes:
        """Encode image in configured format and quality"""
        buffer = BytesIO()
        fmt = self.format.upper()
        
        if self.format == 'png':
            img.save(buffer, format='PNG', optimize=True)
        elif fmt == 'WEBP':
            img.save(buffer, format='WEBP', quality=self.quality, lossless=(self.quality == 100))
        elif fmt == 'BMP':
            img.save(buffer, format='BMP')
        elif fmt == 'TIFF':
            img.save(buffer, format='TIFF')
        else:
            if img.mode == 'RGBA':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[3])
                img = rgb_img
            img.save(buffer, format='JPEG', quality=self.quality, optimize=True)
        
        return buffer.getvalue()

    # MSS Capture → PIL (monitor_index: 0 = all monitors virtual, 1+ = specific display)
    def _capture_mss_image(self) -> Image.Image:
        try:
            from mss import mss

            with mss() as sct:
                n = len(sct.monitors)
                idx = min(self.monitor_index, n - 1)
                monitor = sct.monitors[idx]
                screenshot = sct.grab(monitor)
                return Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        except Exception:
            if self.os_type == "Linux":
                return Image.open(BytesIO(self._capture_linux_fallback()))
            elif self.os_type == "Darwin":
                return Image.open(BytesIO(self._capture_macos()))
            return Image.open(BytesIO(self._generate_test_pattern()))
    
    # Linux Fallback Capture
    def _capture_linux_fallback(self) -> bytes:
        """
        Linux Fallback: Standard execution with minimal environment cleanup.
        Removes LD_LIBRARY_PATH/LD_PRELOAD to fix Snap/VS Code compatibility issues
        """
        temp_file = tempfile.mktemp(suffix=".png")
        
        # 1. Sanitize Environment
        clean_env = os.environ.copy()
        clean_env.pop('LD_LIBRARY_PATH', None)
        clean_env.pop('LD_PRELOAD', None)

        if 'XDG_CURRENT_DESKTOP' not in clean_env:
            clean_env['XDG_CURRENT_DESKTOP'] = 'GNOME'

        flameshot_cmd = ["flameshot", "full", "-p", temp_file]
        if not self.notify:
            flameshot_cmd.insert(2, "-n")

        # 2. Try Standard Tools
        commands = [
            flameshot_cmd,
            ["gnome-screenshot", "-f", temp_file],
        ]
        
        for cmd in commands:
            try:
                subprocess.run(
                    cmd, 
                    env=clean_env, 
                    capture_output=True, 
                    timeout=10
                )
                
                if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                    # Load and re-encode in configured format
                    img = Image.open(temp_file)
                    os.remove(temp_file)
                    return self._encode_image(img)
            except Exception:
                continue
        
        return self._generate_test_pattern()

    # macOS Capture
    def _capture_macos(self) -> bytes:
        """macOS: Uses native screencapture tool"""
        temp_file = tempfile.mktemp(suffix=".png")
        try:
            subprocess.run(["/usr/sbin/screencapture", "-x", "-C", temp_file], check=True, timeout=5)
            
            # Load and re-encode in configured format
            img = Image.open(temp_file)
            os.remove(temp_file)
            return self._encode_image(img)
        except Exception:
            return self._generate_test_pattern()
    
    # Test Pattern Generation
    def _generate_test_pattern(self) -> bytes:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1920, 1080), color='#c0392b')
        d = ImageDraw.Draw(img)
        d.text((50, 50), f"CAPTURE FAILED - {self.os_type}\nFrame {self.frame_id}\nFormat: {self.format.upper()}", fill='white')
        return self._encode_image(img)

    def upload_frame(self, image_data: bytes) -> bool:
        try:
            mime_type = f"image/{self.format}"
            filename = f"frame.{self.format}"
            
            files = {'image': (filename, image_data, mime_type)}
            data = {
                'frame_id': str(self.frame_id),
                'timestamp': str(int(time.time())),
                'format': self.format,
            }
            if self.vision_context and self._pending_vision:
                data['vision_meta'] = json.dumps(self._pending_vision, ensure_ascii=False)
            
            response = requests.post(
                self.upload_endpoint,
                files=files,
                data=data,
                headers=self._auth_headers(),
                timeout=5
            )
            
            if response.status_code == 200:
                self.retry_delay = 1
                result = response.json()

                if 'config' in result:
                    remote = result['config']
                    
                    # 1. Update Interval
                    new_interval = float(remote.get('interval', self.interval))
                    if new_interval != self.interval:
                        print(f"\n[CMD] Interval update: {self.interval}s -> {new_interval}s")
                        self.interval = new_interval
                        
                    # 2. Update Format
                    new_format = remote.get('format', self.format).lower()
                    if new_format != self.format:
                        print(f"\n[CMD] Format update: {self.format} -> {new_format}")
                        self.format = new_format
                        
                    # 3. Update Quality
                    new_quality = int(remote.get('quality', self.quality))
                    if new_quality != self.quality:
                        print(f"\n[CMD] Quality update: {self.quality} -> {new_quality}")
                        self.quality = new_quality

                size_kb = result.get('size_kb', len(image_data) / 1024)
                print(f"\r[OK] Frame #{self.frame_id}: {size_kb:.1f} KB ({self.format.upper()})", end="", flush=True)
                return True
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            if self.retry_delay < 10:
                print(f"\n[!] Upload Failed: {e}. Backing off {self.retry_delay}s...")
            time.sleep(self.retry_delay)
            self.retry_delay = min(self.retry_delay * 2, 30)
            return False

    # Start Agent
    def start(self):
        """Start the agent"""
        if not self.wait_for_server():
            return False
        
        if not self.connect_to_server():
            return False
        
        self.running = True
        self.start_time = datetime.now()
        
        if self.duration:
            self.stop_time = self.start_time + timedelta(seconds=self.duration)
            print(f"[INFO] Will stop at: {self.stop_time.strftime('%H:%M:%S')}")
        
        print("[INFO] Agent Active.")
        return True
    
    # Stop Agent
    def stop(self):
        """Stop the agent"""
        if self.running:
            self.running = False
            elapsed = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
            print(f"\n[INFO] Agent stopped")
            print(f"[INFO] Captured {self.frame_id} frames in {elapsed:.1f}s")
            self.disconnect_from_server()

    # Main Loop
    def run(self):
        """Main loop with auto-stop support"""
        if not self.start():
            sys.exit(1)
        
        try:
            while not self._should_stop():
                loop_start = time.time()
                
                try:
                    data = self.capture_screen()
                    if self.upload_frame(data):
                        self.frame_id += 1
                except Exception as e:
                    print(f"\n[ERROR] Loop Error: {e}")
                    time.sleep(2)
                
                elapsed = time.time() - loop_start
                sleep_time = max(0, self.interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()