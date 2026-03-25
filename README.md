# Agent-Eye

Enhanced screen capture and streaming for AI agents. This repository is a **fork** of **[the-eyes](https://github.com/nullvoider07/the-eyes)** by Kartik (NullVoider / [nullvoider07](https://github.com/nullvoider07)), extended for **OpenClaw** and related workflows (extra capture options, automation-oriented UX, and local integration needs).

The upstream project is licensed under the **GNU General Public License v3.0**. This fork is distributed **only** under **GPL-3.0-or-later** as well; see the [`LICENSE`](LICENSE) file in this repository.

## Features

- **Screenshot capture**: Full screen or specific regions
- **100px grid overlay**: Visual grid for coordinate-based automation
- **Mouse coordinates**: Real-time cursor overlay with crosshair
- **Region capture**: e.g. `--region 0,0,1200,900`
- **Web dashboard**: View captured frames in the browser
- **Multiple formats**: PNG, JPEG, and others as supported by the agent

## Quick Start

### Server

```bash
cargo build --release -p eye-server
./target/release/eye-server --port 8080
```

### Agent (Python)

```bash
pip install -r crates/eye/requirements.txt
cd crates/eye
python -c "
from agent import Agent
agent = Agent(server_url='http://localhost:8080', interval=1.5)
agent.run()
"
```

## Configuration

### Server options

| Option | Description | Default |
|--------|-------------|---------|
| `--port` | Server port | 8080 |
| `--region` | Capture region (x,y,w,h) | Fullscreen |
| `--max-frames` | Frame buffer size | 100 |

### Agent options

```python
agent = Agent(
    server_url='http://localhost:8080',
    interval=1.5,
    grid_size=100,
    show_mouse=True,
    region='0,0,1200,900',
)
```

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /snapshot.png` | Latest frame |
| `GET /frames` | Frames in buffer |
| `GET /frames/:id` | Frame by id |
| `GET /health` | Health status |

## Upstream and this fork

- **Upstream repository**: [nullvoider07/the-eyes](https://github.com/nullvoider07/the-eyes) (GPLv3).
- **This fork**: [noir-hedgehog/Agent-eye](https://github.com/noir-hedgehog/Agent-eye) — changes here build on upstream; see git history for concrete edits.

### Enhancements in this fork (examples)

- Frame buffer handling improvements (timestamp-based latest frame selection)
- Region capture with coordinate handling
- Grid overlay (e.g. 100px cells) and mouse overlay for UI automation
- Orientation toward OpenClaw / agent automation use cases

Install scripts and CLI helpers may still reference upstream release URLs where noted in code; binaries obtained from upstream remain subject to GPLv3.

## License

GNU General Public License v3.0 or later — see [`LICENSE`](LICENSE).
