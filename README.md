# Agent-Eye 🎯

Enhanced screen capture and streaming service for AI agents.

## Features

- **Screenshot Capture**: Capture full screen or specific regions
- **100px Grid Overlay**: Visual reference grid for coordinate-based automation
- **Mouse Coordinates**: Real-time mouse position overlay with crosshair
- **Region Capture**: Capture specific screen regions (e.g., `--region 0,0,1200,900`)
- **Web Dashboard**: View captured frames via web interface
- **Multiple Format Support**: PNG, JPEG output

## Quick Start

### Server

```bash
# Build from source
cargo build --release -p eye-server

# Run server
./target/release/eye-server --port 8080
```

### Agent (Python)

```bash
# Install dependencies
pip install -r crates/eye/requirements.txt

# Run agent
cd crates/eye
python -c "
from agent import Agent
agent = Agent(server_url='http://localhost:8080', interval=1.5)
agent.run()
"
```

## Configuration

### Server Options

| Option | Description | Default |
|--------|-------------|---------|
| `--port` | Server port | 8080 |
| `--region` | Capture region (x,y,w,h) | Fullscreen |
| `--max-frames` | Frame buffer size | 100 |

### Agent Options

```python
agent = Agent(
    server_url='http://localhost:8080',
    interval=1.5,           # Capture interval in seconds
    grid_size=100,          # Grid cell size in pixels
    show_mouse=True,        # Show mouse coordinates
    region='0,0,1200,900'   # Capture region
)
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /snapshot.png` | Get latest frame as PNG |
| `GET /frames` | List all frames in buffer |
| `GET /frames/:id` | Get specific frame by ID |
| `GET /health` | Server health status |

## Acknowledgments

This project is a fork of [The-Eye](https://github.com/noir-hedgehog/the-eye), originally created by [noir-hedgehog](https://github.com/noir-hedgehog).

### Enhancements in This Fork

- Fixed frame buffer management (timestamp-based latest frame selection)
- Added region capture support with proper coordinate handling
- Enhanced grid overlay with 100px cells
- Mouse position tracking with crosshair visualization
- Optimized for UI automation workflows

## License

MIT
