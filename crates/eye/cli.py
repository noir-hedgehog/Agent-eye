# SPDX-License-Identifier: GPL-3.0-or-later
# Derivative of https://github.com/nullvoider07/the-eyes — see fork: https://github.com/noir-hedgehog/Agent-eye

import click
import yaml
import os
import subprocess
import requests
import sys
import platform
import tempfile
import shutil
import stat
import zipfile
from datetime import datetime
from pathlib import Path
from eye.agent import Agent

# Define configuration paths
CONFIG_DIR = Path.home() / ".eye"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# Version - Update with each release
__version__ = "0.2.2"

# GitHub repository
REPO = "nullvoider07/the-eyes"

# Helpers
def _auth_headers(token):
    """Return Bearer auth headers if a token was provided."""
    return {"Authorization": f"Bearer {token}"} if token else {}

def _parse_datetime(value: str) -> datetime:
    """
    Parse a human-readable datetime string into a datetime object.
    Accepted formats:
        2025-03-01 14:30:00
        2025-03-01T14:30:00
        2025-03-01 14:30
        2025-03-01
    """
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise click.BadParameter(
        f"Cannot parse '{value}'. Use YYYY-MM-DD HH:MM:SS (or YYYY-MM-DD)."
    )

# CLI root
@click.group()
@click.version_option(version=__version__, prog_name="Eye Vision Capture Tool")
def cli():
    """Eye - Vision capture tool"""
    pass

# server commands
@cli.group()
def server():
    """Manage server"""
    pass

@server.command(name='start')
@click.option('--port', default=8080, help='Server port')
@click.option('--token', help='Auth token')
def start_server(port, token):
    """Start Rust server"""
    click.echo(f"[START] Starting Eye Server (Rust) on port {port}")

    env = os.environ.copy()
    env['EYE_PORT'] = str(port)
    if token:
        env['EYE_AUTH_TOKEN'] = token

    server_bin = None
    possible_locations = [
        "./bin/eye-server",
        "./target/release/eye-server",
        str(Path.home() / ".local" / "bin" / "eye-server"),
        "/usr/local/bin/eye-server",
        "eye-server",
    ]

    for location in possible_locations:
        if os.path.exists(location):
            server_bin = location
            click.echo(f"[INFO] Found server binary at: {location}")
            break

    if not server_bin:
        server_bin = "eye-server"

    try:
        click.echo(f"[INFO] Starting server: {server_bin}")
        subprocess.run([server_bin], env=env, check=True)
    except FileNotFoundError:
        click.echo("[ERROR] 'eye-server' binary not found!", err=True)
        click.echo("", err=True)
        click.echo("Build the Rust server with:", err=True)
        click.echo("  cd /path/to/the-eyes", err=True)
        click.echo("  cargo build --release -p eye-server", err=True)
        click.echo("", err=True)
        click.echo("Or install system-wide with:", err=True)
        click.echo("  make install", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\n[INFO] Server stopped")

# agent commands
@cli.group()
def agent():
    """Manage agent"""
    pass

@agent.command(name='start')
@click.option('--server', required=True, help='Server URL (e.g. http://localhost:8080)')
@click.option('--token', help='Auth token')
@click.option('--interval', type=float, default=1.5, help='Capture interval (seconds)')
@click.option('--format', type=click.Choice(['png', 'jpeg', 'webp', 'bmp', 'tiff']), default='png', help='Image format')
@click.option('--quality', type=int, default=95, help='Compression quality (1-100)')
@click.option('--duration', type=int, help='Auto-stop after N seconds')
@click.option('--max-frames', type=int, help='Auto-stop after N frames')
@click.option('--notify/--no-notify', default=True, help='Show or hide desktop notifications')
@click.option('--grid', 'grid_size', type=int, default=0, help='Grid overlay size in pixels (0=disabled, 100=100px grid)')
@click.option('--mouse/--no-mouse', default=False, help='Show mouse coordinates overlay')
@click.option('--region', type=str, default=None, help='Capture region: x,y,width,height (e.g., "0,0,800,600")')
def start_agent(server, token, interval, format, quality, duration, max_frames, notify, grid_size, mouse, region):
    """Start Python capture agent (compatible with Rust server)"""

    try:
        import mss
        from PIL import Image
    except ImportError:
        click.echo("Missing dependencies. Run: pip install mss pillow requests", err=True)
        sys.exit(1)

    click.echo(f"[START] Starting Eye Agent (Python) -> {server}")
    click.echo(f"   Format: {format.upper()}")
    if format == 'jpeg':
        click.echo(f"   Quality: {quality}/100")
    click.echo(f"   Interval: {interval}s")
    if duration:
        click.echo(f"   Duration: {duration}s (auto-stop)")
    if max_frames:
        click.echo(f"   Max frames: {max_frames} (auto-stop)")
    if grid_size > 0:
        click.echo(f"   Grid: {grid_size}px")
    if mouse:
        click.echo(f"   Mouse: enabled")
    if region:
        click.echo(f"   Region: {region}")
    click.echo(f"   Server: Rust-based Eye Server")

    try:
        bot = Agent(
            server_url=server,
            token=token,
            interval=interval,
            format=format,
            quality=quality,
            duration=duration,
            max_frames=max_frames,
            notify=notify,
            grid_size=grid_size,
            show_mouse=mouse,
            region=region
        )
        bot.run()
    except KeyboardInterrupt:
        click.echo("\nStopping...")

# snapshot commands
@cli.group()
def snapshot():
    """Download frames from the server"""
    pass

@snapshot.command(name='download')
@click.option('--server', 'server_url', default='http://localhost:8080',
              show_default=True, help='Server URL')
@click.option('--token', default=None, help='Auth token')
@click.option('--output', '-o', default='.', show_default=True,
              help='Directory (or file path) to save the image to')
def snapshot_download(server_url, token, output):
    """
    Download the latest frame from the server.

    The file is saved with a timestamp-based name that matches the moment
    the screenshot was taken, e.g. frame_2025-03-01T14-32-10.123Z.png.
    The format matches whatever the agent is currently streaming — no
    conversion is applied.

    \b
    Examples:
      eye snapshot download
      eye snapshot download --server http://192.168.1.10:8080 --token secret
      eye snapshot download -o ~/screenshots
    """
    server_url = server_url.rstrip('/')
    output_path = Path(output)

    try:
        response = requests.get(
            f"{server_url}/snapshot.png",
            headers=_auth_headers(token),
            timeout=10,
            stream=True,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        click.echo(f"[ERROR] Could not reach server: {e}", err=True)
        sys.exit(1)

    # Derive filename from the x-frame-timestamp header if present,
    # otherwise fall back to the current time.
    raw_ts = response.headers.get("x-frame-timestamp")
    if raw_ts:
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            ts_str = ts.strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"
        except ValueError:
            ts_str = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"
    else:
        ts_str = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"

    # Determine file extension from Content-Type header
    content_type = response.headers.get("content-type", "image/png")
    ext = content_type.split("/")[-1]
    if ext == "jpeg":
        ext = "jpeg"

    filename = f"frame_{ts_str}.{ext}"

    # If output is a directory, place the file inside it
    if output_path.is_dir():
        dest = output_path / filename
    else:
        # Treat as an explicit file path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dest = output_path

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    size_kb = dest.stat().st_size / 1024
    click.echo(f"[OK] Saved: {dest}  ({size_kb:.1f} KB)")

@snapshot.command(name='list')
@click.option('--server', 'server_url', default='http://localhost:8080',
              show_default=True, help='Server URL')
@click.option('--token', default=None, help='Auth token')
def snapshot_list(server_url, token):
    """
    List all frames currently held in the server's ring buffer.

    Shows each frame's ID, capture timestamp, size, and format so you can
    decide which frames to download with 'fetch' or 'range'.

    \b
    Examples:
      eye snapshot list
      eye snapshot list --server http://192.168.1.10:8080
    """
    server_url = server_url.rstrip('/')

    try:
        response = requests.get(
            f"{server_url}/frames",
            headers=_auth_headers(token),
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        click.echo(f"[ERROR] Could not reach server: {e}", err=True)
        sys.exit(1)

    data = response.json()
    frames = data.get("frames", [])
    count = data.get("count", 0)

    if count == 0:
        click.echo("[INFO] No frames in buffer.")
        return

    click.echo(f"\n  {'ID':>6}  {'Timestamp':<32}  {'Size':>9}  {'Format'}")
    click.echo(f"  {'──────':>6}  {'──────────────────────────────':32}  {'─────────':>9}  {'──────'}")

    for f in frames:
        click.echo(
            f"  {f['id']:>6}  {f['timestamp']:<32}  {f['size_kb']:>8.1f}K  {f['format']}"
        )

    click.echo(f"\n  {count} frame(s) in buffer.\n")

@snapshot.command(name='fetch')
@click.option('--server', 'server_url', default='http://localhost:8080',
              show_default=True, help='Server URL')
@click.option('--token', default=None, help='Auth token')
@click.option('--id', 'frame_id', required=True, type=int, help='Frame ID to download')
@click.option('--output', '-o', default='.', show_default=True,
              help='Directory (or file path) to save the image to')
def snapshot_fetch(server_url, token, frame_id, output):
    """
    Download a specific frame from the ring buffer by its ID.

    Use 'eye snapshot list' first to see which IDs are available.
    The file is saved with a timestamp-based name identical to the one
    the server would use, e.g. frame_2025-03-01T14-32-10.123Z.png.

    \b
    Examples:
      eye snapshot fetch --id 42
      eye snapshot fetch --id 42 -o ~/screenshots
      eye snapshot fetch --id 42 --server http://192.168.1.10:8080
    """
    server_url = server_url.rstrip('/')
    output_path = Path(output)

    try:
        response = requests.get(
            f"{server_url}/frames/{frame_id}",
            headers=_auth_headers(token),
            timeout=10,
            stream=True,
        )
        if response.status_code == 404:
            click.echo(
                f"[ERROR] Frame {frame_id} not found. "
                "Run 'eye snapshot list' to see available frames.",
                err=True,
            )
            sys.exit(1)
        response.raise_for_status()
    except requests.RequestException as e:
        click.echo(f"[ERROR] Could not reach server: {e}", err=True)
        sys.exit(1)

    # The server sets Content-Disposition with the correct filename —
    # use it if present, otherwise build one ourselves.
    disposition = response.headers.get("content-disposition", "")
    filename = None
    if 'filename="' in disposition:
        filename = disposition.split('filename="')[1].rstrip('"')

    if not filename:
        raw_ts = response.headers.get("x-frame-timestamp")
        if raw_ts:
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                ts_str = ts.strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"
            except ValueError:
                ts_str = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"
        else:
            ts_str = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"

        content_type = response.headers.get("content-type", "image/png")
        ext = content_type.split("/")[-1]
        filename = f"frame_{ts_str}.{ext}"

    if output_path.is_dir():
        dest = output_path / filename
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dest = output_path

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    size_kb = dest.stat().st_size / 1024
    click.echo(f"[OK] Frame #{frame_id} saved: {dest}  ({size_kb:.1f} KB)")

@snapshot.command(name='range')
@click.option('--server', 'server_url', default='http://localhost:8080',
              show_default=True, help='Server URL')
@click.option('--token', default=None, help='Auth token')
@click.option('--from', 'from_dt', required=True,
              help='Start of range  e.g. "2025-03-01 14:30:00"')
@click.option('--to', 'to_dt', required=True,
              help='End of range    e.g. "2025-03-01 14:35:00"')
@click.option('--output', '-o', default='.', show_default=True,
              help='Directory to extract frames into')
def snapshot_range(server_url, token, from_dt, to_dt, output):
    """
    Download all frames captured within a time window.

    The server returns a zip archive; this command extracts each image into
    the output directory automatically. Each filename contains the capture
    timestamp, e.g. frame_2025-03-01T14-32-10.123Z.png.

    Timestamps are interpreted as local time. The ring buffer holds up to
    100 frames by default (configurable via EYE_MAX_FRAMES on the server),
    so very old frames may have been evicted already.

    \b
    Examples:
      eye snapshot range --from "2025-03-01 14:30:00" --to "2025-03-01 14:35:00"
      eye snapshot range --from "2025-03-01 14:30" --to "2025-03-01 14:35" -o ~/frames
    """
    server_url = server_url.rstrip('/')
    output_path = Path(output)

    # Parse the human-readable strings into Unix timestamps
    try:
        from_datetime = _parse_datetime(from_dt)
        to_datetime   = _parse_datetime(to_dt)
    except click.BadParameter as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

    if from_datetime >= to_datetime:
        click.echo("[ERROR] --from must be earlier than --to.", err=True)
        sys.exit(1)

    from_unix = int(from_datetime.timestamp())
    to_unix   = int(to_datetime.timestamp())

    click.echo(
        f"[INFO] Requesting frames from {from_datetime} to {to_datetime}..."
    )

    try:
        response = requests.get(
            f"{server_url}/frames/range",
            headers=_auth_headers(token),
            params={"from": from_unix, "to": to_unix},
            timeout=30,
            stream=True,
        )
        if response.status_code == 404:
            click.echo(
                "[INFO] No frames found in that time window. "
                "Run 'eye snapshot list' to see what is available.",
                err=True,
            )
            sys.exit(1)
        response.raise_for_status()
    except requests.RequestException as e:
        click.echo(f"[ERROR] Could not reach server: {e}", err=True)
        sys.exit(1)

    # Save the zip to a temp file, then extract it
    output_path.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            names = zf.namelist()
            zf.extractall(output_path)
    finally:
        os.unlink(tmp_path)

    frame_count = response.headers.get("x-frame-count", str(len(names)))
    click.echo(
        f"[OK] {frame_count} frame(s) extracted to: {output_path.resolve()}"
    )
    for name in sorted(names):
        size_kb = (output_path / name).stat().st_size / 1024
        click.echo(f"     {name}  ({size_kb:.1f} KB)")

# other commands
@cli.command()
def debug():
    """Show debug info from Rust server"""
    try:
        r = requests.get('http://localhost:8080/debug', timeout=2)
        click.echo(yaml.dump(r.json()))
    except:
        click.echo("[ERROR] Server not running or unreachable", err=True)

@cli.command()
@click.option('--check-only', is_flag=True, help='Only check for updates without installing')
def update(check_only):
    """Check for updates and install the latest version (Rust binaries)"""

    click.echo("Checking for updates...")
    click.echo(f"Current version: v{__version__}")

    try:
        release_url = f"https://api.github.com/repos/{REPO}/releases/latest"
        response = requests.get(release_url, timeout=10)
        response.raise_for_status()

        latest_release = response.json()
        latest_tag = latest_release['tag_name']
        latest_version = latest_tag.lstrip('v')

        click.echo(f"Latest version: v{latest_version}")

        if latest_version == __version__:
            click.echo(click.style("[OK] You already have the latest version!", fg='green'))
            return

        click.echo(click.style(f"[UPDATE] New version available: v{latest_version}", fg='yellow'))

        if check_only:
            click.echo("\nTo install the update, run: eye update")
            return

        if not click.confirm('\nDo you want to update now?'):
            click.echo("Update cancelled.")
            return

        os_type = platform.system().lower()
        machine = platform.machine().lower()

        if os_type == 'darwin':
            os_name = 'osx'
        elif os_type == 'linux':
            os_name = 'linux'
        elif os_type == 'windows':
            os_name = 'win'
        else:
            click.echo(f"[ERROR] Unsupported OS: {os_type}", err=True)
            return

        if machine in ['x86_64', 'amd64']:
            arch = 'x64'
        elif machine in ['arm64', 'aarch64']:
            arch = 'arm64'
        elif machine in ['i386', 'i686']:
            arch = 'x86'
        else:
            click.echo(f"[ERROR] Unsupported architecture: {machine}", err=True)
            return

        if os_name == 'win':
            file_name = f"eye-{latest_version}-{os_name}-{arch}.zip"
        else:
            file_name = f"eye-{latest_version}-{os_name}-{arch}.tar.gz"

        download_url = f"https://github.com/{REPO}/releases/download/{latest_tag}/{file_name}"
        click.echo(f"\nDownloading {file_name}...")

        download_response = requests.get(download_url, stream=True, timeout=30)
        download_response.raise_for_status()

        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, file_name)

        with open(temp_file, 'wb') as f:
            for chunk in download_response.iter_content(chunk_size=8192):
                f.write(chunk)

        click.echo("[OK] Download complete")
        click.echo("Installing update...")

        if os_name == 'win':
            import zipfile as zf
            with zf.ZipFile(temp_file, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
        else:
            import tarfile
            with tarfile.open(temp_file, 'r:gz') as tar_ref:
                tar_ref.extractall(temp_dir)

        if os_name == 'win':
            install_dir = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Eye' / 'bin'
        else:
            install_dir = Path.home() / '.local' / 'bin'

        extracted_bin_dir = Path(temp_dir) / 'bin'
        if not extracted_bin_dir.exists():
            extracted_bin_dir = Path(temp_dir)

        install_dir.mkdir(parents=True, exist_ok=True)

        binaries = ['eye-server', 'eye']
        if os_name == 'win':
            binaries = [f"{b}.exe" for b in binaries]

        for binary in binaries:
            src = extracted_bin_dir / binary
            if src.exists():
                dst = install_dir / binary
                shutil.copy2(str(src), str(dst))
                if os_name != 'win':
                    dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                click.echo(f"  ✓ Installed: {dst}")

        shutil.rmtree(temp_dir, ignore_errors=True)
        click.echo(click.style(f"\n[OK] Updated to v{latest_version}!", fg='green'))

    except requests.RequestException as e:
        click.echo(f"[ERROR] Update failed: {e}", err=True)
        sys.exit(1)

@cli.command()
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--purge', is_flag=True, help='Also remove configuration and data files')
def uninstall(yes, purge):
    """Remove Eye binaries and optionally configuration files"""

    os_type = platform.system().lower()
    paths_to_remove = []

    if os_type == 'windows':
        binary_locations = [
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Eye' / 'bin',
        ]
        binary_names = ['eye.exe', 'eye-server.exe', 'eye-agent.exe']
    else:
        binary_locations = [
            Path('/usr/local/bin'),
            Path.home() / '.local' / 'bin',
            Path('./bin'),
            Path('./target/release'),
        ]
        binary_names = ['eye', 'eye-server', 'eye-agent']

    found_binaries = []
    for location in binary_locations:
        if location.exists():
            for binary in binary_names:
                binary_path = location / binary
                if binary_path.exists():
                    found_binaries.append(binary_path)
                    paths_to_remove.append(binary_path)
                old_binary = location / f"{binary}.old"
                if old_binary.exists():
                    paths_to_remove.append(old_binary)

    python_package_info = None
    try:
        from importlib.metadata import packages_distributions, metadata, PackageNotFoundError
        try:
            meta = metadata('eye-capture')
            python_package_info = {
                'name': meta['Name'],
                'version': meta['Version'],
                'location': '',   # importlib.metadata doesn't expose install path directly
            }
        except PackageNotFoundError:
            pass
    except Exception:
        pass

    config_paths = []
    if purge:
        config_dir = Path.home() / '.eye'
        if config_dir.exists():
            config_paths.append(config_dir)

    click.echo("The following components will be removed:")
    click.echo("")

    click.echo(click.style("Rust Binaries:", fg='yellow', bold=True))
    if found_binaries:
        for binary in found_binaries:
            click.echo(f"  - {binary}")
    else:
        click.echo("  - None found")
    click.echo("")

    click.echo(click.style("Python Package:", fg='yellow', bold=True))
    if python_package_info:
        click.echo(f"  - {python_package_info['name']} v{python_package_info['version']}")
        click.echo(f"    Location: {python_package_info['location']}")
    else:
        click.echo("  - Not installed via pip")
    click.echo("")

    if config_paths:
        click.echo(click.style("Configuration & Data:", fg='yellow', bold=True))
        for path in config_paths:
            click.echo(f"  - {path}")
        click.echo("")

    total_size = 0
    for path in paths_to_remove + config_paths:
        if path.exists():
            if path.is_file():
                total_size += path.stat().st_size
            elif path.is_dir():
                total_size += sum(f.stat().st_size for f in path.rglob('*') if f.is_file())

    if total_size > 0:
        size_mb = total_size / (1024 * 1024)
        click.echo(f"Total disk space to be freed: {size_mb:.2f} MB")
        click.echo("")

    if not found_binaries and not python_package_info and not config_paths:
        click.echo(click.style("✓ Eye is not installed on this system", fg='green'))
        return

    if not yes:
        click.echo(click.style("⚠ This action cannot be undone!", fg='red', bold=True))
        if not click.confirm('Do you want to continue?'):
            click.echo("\nUninstall cancelled.")
            return

    click.echo("")
    click.echo("Uninstalling...")
    click.echo("")

    removed = []
    failed = []

    for binary_path in paths_to_remove:
        try:
            if binary_path.exists():
                binary_path.unlink()
                removed.append(str(binary_path))
                click.echo(f"  ✓ Removed: {binary_path}")
        except PermissionError:
            if os_type == 'windows':
                try:
                    temp_path = binary_path.with_suffix('.delete_me')
                    if temp_path.exists():
                        try: temp_path.unlink()
                        except: pass
                    binary_path.rename(temp_path)
                    cmd = f'cmd /c ping 127.0.0.1 -n 3 > nul & del "{temp_path}"'
                    subprocess.Popen(
                        cmd, shell=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    removed.append(str(binary_path))
                    click.echo(f"  ✓ Removed: {binary_path} (Scheduled for deletion)")
                    continue
                except Exception:
                    pass
            failed.append((str(binary_path), "Permission denied (File in use)"))
            click.echo(click.style(f"  ✗ Failed: {binary_path} (File in use)", fg='red'))
        except Exception as e:
            failed.append((str(binary_path), str(e)))
            click.echo(click.style(f"  ✗ Failed: {binary_path} ({e})", fg='red'))

    if python_package_info:
        try:
            click.echo(f"\n  Uninstalling Python package: {python_package_info['name']}...")
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'uninstall', '-y', 'eye-capture'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                removed.append(f"Python package: {python_package_info['name']}")
                click.echo("  ✓ Uninstalled Python package")
            else:
                failed.append(("Python package", result.stderr))
                click.echo(click.style("  ✗ Failed to uninstall Python package", fg='red'))
        except Exception as e:
            failed.append(("Python package", str(e)))
            click.echo(click.style(f"  ✗ Failed: {e}", fg='red'))

    if config_paths:
        click.echo("")
        for config_path in config_paths:
            try:
                if config_path.exists():
                    if config_path.is_dir():
                        shutil.rmtree(config_path)
                    else:
                        config_path.unlink()
                    removed.append(str(config_path))
                    click.echo(f"  ✓ Removed: {config_path}")
            except Exception as e:
                failed.append((str(config_path), str(e)))
                click.echo(click.style(f"  ✗ Failed: {config_path} ({e})", fg='red'))

    if os_type == 'windows':
        eye_dir = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Eye'
        try:
            if eye_dir.exists() and not any(eye_dir.iterdir()):
                eye_dir.rmdir()
                click.echo(f"  ✓ Removed empty directory: {eye_dir}")
        except Exception:
            pass

    click.echo("")
    if removed:
        click.echo(click.style(f"✓ Uninstall complete — {len(removed)} item(s) removed.", fg='green'))
    if failed:
        click.echo(click.style(f"✗ {len(failed)} item(s) could not be removed:", fg='red'))
        for path, reason in failed:
            click.echo(f"  - {path}: {reason}")

def main():
    cli()

if __name__ == '__main__':
    main()