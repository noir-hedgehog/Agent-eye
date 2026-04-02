# Agent-Eye

面向 **计算机使用型智能体（CUA）** 与 **OpenClaw** 等场景的增强版截屏与帧流服务：Rust 服务端环形缓冲 + Python 采集端，支持网格/鼠标叠加、多显示器、每帧 **vision 元数据**，并可对齐 **阿里云百炼 Qwen3.5** 等多模态 API 的像素与消息格式。

本仓库是 **[the-eyes](https://github.com/nullvoider07/the-eyes)**（作者 Kartik / [nullvoider07](https://github.com/nullvoider07)）的 **GPL 衍生 fork**，仅按 **GPL-3.0-or-later** 分发，详见根目录 [`LICENSE`](LICENSE)。

---

## 架构

| 组件 | 说明 |
|------|------|
| **eye-server**（Rust） | HTTP 服务：接收帧、`/health`、`/snapshot.png`、`/frames` 列表与下载、1:1 Agent 连接等 |
| **Python Agent** | 跨平台截屏（mss / 系统工具）、编码上传、CLI `eye` |
| **vision_meta** | 与图像一并上传的 JSON，服务端在 `GET /frames` 的每条记录中解析为 **`vision`** 字段 |

---

## 功能概览

- **全屏 / 区域**采集，`--region x,y,w,h`
- **多显示器**（mss）：`--monitor`（0=虚拟整屏，1=主屏，以此类推）
- **最长边缩放**：`--max-dimension`，减轻视觉模型与带宽压力
- **每帧视觉上下文**：分辨率、采集耗时、可选前台窗口标题、屏幕坐标鼠标、相对上一帧的 **变化分数**（`frame_change_score`）
- **网格与鼠标**：`--grid`、`--mouse` 便于坐标类自动化
- **Qwen / DashScope 预设**：`--vision-preset qwen35-plus` 时按百炼默认 `max_pixels` 对齐约 **1619px** 最长边，并在元数据中附带 API 说明字段
- **多格式**：PNG、JPEG、WebP 等（见 Agent 参数）

详细命令说明还可参考仓库内 [`the-eyes.md`](the-eyes.md)（上游文档衍生，已标注本 fork）。

---

## 快速开始

### 1. 编译并启动服务端

```bash
cargo build --release -p eye-server
./target/release/eye-server --port 8080
```

常用环境变量：`EYE_PORT`、`EYE_AUTH_TOKEN`、`EYE_MAX_FRAMES`（环形缓冲条数，默认 100）。

### 2. 安装 Python 依赖并启动 Agent

依赖：`mss`、`Pillow`、`requests`、`click`、`pyyaml`（与 `setup.py` 中一致）。

```bash
pip install mss pillow requests click pyyaml
export PYTHONPATH="/path/to/Agent-eye/crates"   # 指向仓库内的 crates 目录
```

在已配置 `PYTHONPATH` 的前提下，可直接用模块方式运行（不依赖全局安装 `eye` 命令）：

```bash
python -m eye.cli agent start --server http://localhost:8080 --token YOUR_TOKEN
```

若已通过 `pip install -e .`（在仓库根目录、且 `setup.py` 能正确发现 `eye` 包）安装 **eye-capture**，则也可使用：

```bash
eye agent start --server http://localhost:8080 --token YOUR_TOKEN
```

带视觉元数据与网格示例：

```bash
eye agent start --server http://localhost:8080 \
  --grid 100 --mouse --vision-meta \
  --monitor 1 --max-dimension 1280
```

**对接 Qwen3.5 / 百炼多模态（推荐参数）**：

```bash
eye agent start --server http://localhost:8080 \
  --vision-preset qwen35-plus --format jpeg --quality 85
```

在代码中引用（需 `PYTHONPATH=.../crates` 或已安装 `eye-capture`）：

```python
from eye.agent import Agent

agent = Agent(
    server_url="http://localhost:8080",
    interval=1.5,
    grid_size=100,
    show_mouse=True,
    region="0,0,1200,900",   # 可选
    monitor_index=1,
    max_dimension=1280,
    vision_context=True,
    vision_preset="qwen35-plus",  # 可选
)
agent.run()
```

将截图拼成 OpenAI 兼容 **user 多模态消息**（供 DashScope 等使用）：

```python
from eye.utils.qwen_vision import build_openai_user_multimodal_message

msg = build_openai_user_multimodal_message(
    "请描述当前界面",
    image_bytes,
    "image/jpeg",
)
```

---

## 常用 CLI 选项（`eye agent start`）

| 选项 | 说明 |
|------|------|
| `--server` | 服务端 URL（必填） |
| `--token` | Bearer Token（与 `EYE_AUTH_TOKEN` 一致） |
| `--interval` | 截屏间隔（秒） |
| `--format` | `png` / `jpeg` / `webp` 等 |
| `--quality` | JPEG 等质量 1–100 |
| `--grid` | 网格像素步长，0 关闭 |
| `--mouse` / `--no-mouse` | 鼠标十字与坐标 |
| `--region` | `x,y,w,h` |
| `--monitor` | mss 显示器索引 |
| `--max-dimension` | 最长边像素上限 |
| `--vision-meta` / `--no-vision-meta` | 是否上传 vision_meta |
| `--window-title` / `--no-window-title` | 元数据中是否含前台窗口标题 |
| `--vision-preset` | `none` 或 `qwen35-plus` |

完整列表：`eye agent start --help`。

---

## HTTP API（节选）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查与帧数量等 |
| POST | `/connect` | Agent 占用连接槽（1:1） |
| POST | `/disconnect` | 释放连接槽 |
| POST | `/upload` | multipart：图像 + `frame_id`、`format`、可选 **`vision_meta`**（JSON 字符串） |
| GET | `/snapshot.png` | 最新一帧图像 |
| GET | `/frames` | 缓冲区内帧的元数据列表；含 **`vision`**（当上传时带 `vision_meta`） |
| GET | `/frames/:id` | 按 ID 下载单帧 |
| GET | `/debug` | 调试信息 |

---

## 与 Qwen 3.5 / DashScope 对齐（摘要）

百炼 **OpenAI 兼容 Chat Completions** 下，多模态消息使用 `content` 数组 + `image_url`（支持 HTTPS 或 `data:image/...;base64,...`）。图像可配置 **`min_pixels` / `max_pixels`**；Qwen3.5 默认 `max_pixels` 为 **2_621_440**，本仓库 `qwen35-plus` 预设将最长边约 **1619px** 与文档对齐。

官方文档：

- [通过 OpenAI 接口使用通义千问](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [图像与视频理解](https://help.aliyun.com/zh/model-studio/vision)

---

## 上游与 fork

| 项目 | 链接 |
|------|------|
| 上游 | [nullvoider07/the-eyes](https://github.com/nullvoider07/the-eyes) |
| 本 fork | [noir-hedgehog/Agent-eye](https://github.com/noir-hedgehog/Agent-eye) |

安装脚本与 CLI 中若仍指向上游 Release，以代码注释为准；上游二进制同样受 GPLv3 约束。

---

## 许可

GNU General Public License **v3.0 or later** — 见 [`LICENSE`](LICENSE)。
