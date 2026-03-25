// crates/server/src/main.rs
// SPDX-License-Identifier: GPL-3.0-or-later
// Derivative of https://github.com/nullvoider07/the-eyes — fork: https://github.com/noir-hedgehog/Agent-eye

use anyhow::{Context, Result};
use axum::{
    extract::{DefaultBodyLimit, Multipart, Path, Query, Request, State},
    http::{StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Json, Response},
    routing::{get, post},
    Router,
};
use chrono::{DateTime, Local, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::env;
use std::io::Write;
use std::sync::Arc;
use std::time::Instant;
use storage::{Frame, MemoryStore};
use tokio::sync::RwLock;
use tracing::info;

// Configuration structure for the agent
#[derive(Debug, Clone, Serialize, Deserialize)]
struct AgentConfig {
    interval: f64,
    format: String,
    quality: i32,
}

// Default configuration values
impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            interval: 1.5,
            format: "png".to_string(),
            quality: 95,
        }
    }
}

// Application state shared across handlers
#[derive(Clone)]
struct AppState {
    store: Arc<MemoryStore>,
    start_time: Instant,
    config: Arc<RwLock<AgentConfig>>,
    /// True when an agent has claimed the connection slot.
    /// Only one agent may be connected at a time (1:1 model).
    agent_connected: Arc<RwLock<bool>>,
}

impl AppState {
    fn new(max_frames: usize) -> Self {
        Self {
            store: Arc::new(MemoryStore::new(max_frames)),
            start_time: Instant::now(),
            config: Arc::new(RwLock::new(AgentConfig::default())),
            agent_connected: Arc::new(RwLock::new(false)),
        }
    }
}

// Query parameters accepted by GET /frames/range
#[derive(Debug, Deserialize)]
struct RangeQuery {
    /// Start of the window as a Unix timestamp (seconds, inclusive)
    from: i64,
    /// End of the window as a Unix timestamp (seconds, inclusive)
    to: i64,
}

// Logging middleware

async fn logging_middleware(req: Request, next: Next) -> Response {
    let method = req.method().clone();
    let uri = req.uri().clone();
    let start = Instant::now();

    let response = next.run(req).await;

    let latency = start.elapsed();
    let status = response.status();
    let status_code = status.as_u16();

    let status_str = match status_code {
        200..=299 => format!("\x1b[42;30m {:>3} \x1b[0m", status_code),
        400..=499 => format!("\x1b[43;30m {:>3} \x1b[0m", status_code),
        500..=599 => format!("\x1b[41;30m {:>3} \x1b[0m", status_code),
        _ => status_code.to_string(),
    };

    let method_str = match method.as_str() {
        "GET"    => format!("\x1b[44;30m {:<3} \x1b[0m", "GET"),
        "POST"   => format!("\x1b[46;30m {:<4} \x1b[0m", "POST"),
        "PUT"    => format!("\x1b[43;30m {:<3} \x1b[0m", "PUT"),
        "DELETE" => format!("\x1b[41;30m {:<6} \x1b[0m", "DELETE"),
        m => m.to_string(),
    };

    let timestamp = Local::now().format("%Y/%m/%d - %H:%M:%S");
    let latency_str = format!("{:?}", latency);
    let client_ip = "::1";

    println!(
        "[Eye] {} |{}| {:>13} |{:>15} | {} \"{}\"",
        timestamp, status_str, latency_str, client_ip, method_str, uri
    );

    response
}

// Health

async fn health_handler(State(state): State<AppState>) -> Json<serde_json::Value> {
    let uptime = state.start_time.elapsed().as_secs_f64();
    let frames = state.store.list().await;
    let agent_connected = *state.agent_connected.read().await;

    Json(json!({
        "status": "healthy",
        "uptime": format!("{:.2}s", uptime),
        "frame_count": frames.len(),
        "agent_connected": agent_connected,
    }))
}

// 1:1 Connection

// An agent calls this to claim the sole connection slot.
// Returns 409 Conflict if a different agent is already connected.
async fn connect_handler(
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let mut connected = state.agent_connected.write().await;

    if *connected {
        return Err((
            StatusCode::CONFLICT,
            "An agent is already connected to this server. \
             This server operates in 1:1 mode — disconnect the existing agent first."
                .to_string(),
        ));
    }

    *connected = true;
    info!("Agent connected");

    Ok(Json(json!({ "status": "connected" })))
}

// The agent calls this on clean shutdown to free the slot.
async fn disconnect_handler(State(state): State<AppState>) -> Json<serde_json::Value> {
    let mut connected = state.agent_connected.write().await;
    *connected = false;
    info!("Agent disconnected");
    Json(json!({ "status": "disconnected" }))
}

// Admin

async fn admin_config_handler(
    State(state): State<AppState>,
    Json(new_config): Json<AgentConfig>,
) -> Json<serde_json::Value> {
    let mut config = state.config.write().await;

    let mut validated = new_config;
    if validated.interval < 0.1 {
        validated.interval = 0.1;
    }
    if validated.quality < 1 || validated.quality > 100 {
        validated.quality = 75;
    }
    validated.format = validated.format.to_lowercase();
    const SUPPORTED_FORMATS: &[&str] = &["png", "jpeg", "jpg", "webp", "bmp", "tiff"];
    if !SUPPORTED_FORMATS.contains(&validated.format.as_str()) {
        info!("Invalid format '{}', defaulting to PNG", validated.format);
        validated.format = "png".to_string();
    }
    if validated.format == "jpg" {
        validated.format = "jpeg".to_string();
    }

    *config = validated.clone();
    info!("Config updated: {:?}", config);

    Json(json!({
        "message": "Configuration updated",
        "config": config.clone(),
    }))
}

// Upload

// Receives frames from the connected agent.
// Requires a prior POST /connect — rejects with 403 otherwise.
// Reads the "format" multipart field to store the real content-type instead
// of blindly assuming PNG.
async fn upload_handler(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    // Enforce 1:1 — reject uploads from agents that haven't registered
    {
        let connected = state.agent_connected.read().await;
        if !*connected {
            return Err((
                StatusCode::FORBIDDEN,
                "No agent is registered with this server. \
                 Call POST /connect before uploading frames."
                    .to_string(),
            ));
        }
    }

    let mut data: Option<Vec<u8>> = None;
    let mut frame_id = 0i64;
    // Default to png; overwritten if the agent sends a "format" field
    let mut format = "png".to_string();

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
    {
        let name = field.name().unwrap_or("").to_string();

        match name.as_str() {
            "image" => {
                data = Some(
                    field
                        .bytes()
                        .await
                        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
                        .to_vec(),
                );
            }
            "frame_id" => {
                let text = field
                    .text()
                    .await
                    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
                frame_id = text
                    .parse()
                    .map_err(|_| (StatusCode::BAD_REQUEST, "Invalid frame_id".to_string()))?;
            }
            "format" => {
                let text = field
                    .text()
                    .await
                    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
                // Normalise "jpg" → "jpeg" so content-type strings are consistent
                format = if text.to_lowercase() == "jpg" {
                    "jpeg".to_string()
                } else {
                    text.to_lowercase()
                };
            }
            _ => {}
        }
    }

    let data = data.ok_or((StatusCode::BAD_REQUEST, "No image file".to_string()))?;

    // Store the real format in frame metadata so download endpoints can serve
    // the correct Content-Type and file extension later.
    let mut metadata = HashMap::new();
    metadata.insert("content-type".to_string(), format!("image/{}", format));
    metadata.insert("format".to_string(), format.clone());

    let frame = Frame {
        id: frame_id,
        data: data.clone(),
        timestamp: Utc::now(),
        metadata,
    };

    state
        .store
        .store(frame)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    info!("Frame #{} stored ({} bytes, {})", frame_id, data.len(), format);

    let config = state.config.read().await.clone();

    Ok(Json(json!({
        "status": "ok",
        "frame_id": frame_id,
        "size_kb": data.len() as f64 / 1024.0,
        "config": config,
    })))
}

// Snapshot (legacy)

// Returns the latest frame as raw bytes. Kept for backwards compatibility.
// Content-Type now reflects the actual format rather than hardcoded image/png.
async fn snapshot_handler(
    State(state): State<AppState>,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    let frame = state
        .store
        .get_latest()
        .await
        .map_err(|_| (StatusCode::NOT_FOUND, "No frames available".to_string()))?;

    let content_type = frame
        .metadata
        .get("content-type")
        .cloned()
        .unwrap_or_else(|| "image/png".to_string());

    axum::response::Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, content_type)
        .header("x-frame-id", frame.id.to_string())
        .header("x-frame-timestamp", frame.timestamp.to_rfc3339())
        .body(axum::body::Body::from(frame.data))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

// GET /frames

// Returns JSON metadata for every frame currently in the ring buffer.
// No image data is included — just enough to decide what to download.
async fn frames_list_handler(State(state): State<AppState>) -> Json<serde_json::Value> {
    let frames = state.store.list().await;

    let index: Vec<serde_json::Value> = frames
        .iter()
        .map(|f| {
            let format = f
                .metadata
                .get("format")
                .cloned()
                .unwrap_or_else(|| "png".to_string());

            json!({
                "id":             f.id,
                "timestamp":      f.timestamp.to_rfc3339(),
                "timestamp_unix": f.timestamp.timestamp(),
                "size_bytes":     f.data.len(),
                "size_kb":        (f.data.len() as f64 / 1024.0 * 10.0).round() / 10.0,
                "format":         format,
            })
        })
        .collect();

    Json(json!({
        "count":  index.len(),
        "frames": index,
    }))
}

// GET /frames/:id

// Returns a single frame's raw image bytes.
// Content-Type reflects the actual format the agent sent.
// Content-Disposition carries a timestamp-based filename so curl / browsers
// save it with a meaningful name automatically.
async fn frame_by_id_handler(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    let frame = state
        .store
        .get_by_id(id)
        .await
        .map_err(|_| (StatusCode::NOT_FOUND, format!("Frame {} not found", id)))?;

    let content_type = frame
        .metadata
        .get("content-type")
        .cloned()
        .unwrap_or_else(|| "image/png".to_string());

    let format = frame
        .metadata
        .get("format")
        .cloned()
        .unwrap_or_else(|| "png".to_string());

    // e.g. "frame_2025-03-01T14-32-10.123Z.png"
    let ts = frame.timestamp.format("%Y-%m-%dT%H-%M-%S%.3fZ");
    let filename = format!("frame_{}.{}", ts, format);

    axum::response::Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, content_type)
        .header(
            header::CONTENT_DISPOSITION,
            format!("attachment; filename=\"{}\"", filename),
        )
        .header("x-frame-id", frame.id.to_string())
        .header("x-frame-timestamp", frame.timestamp.to_rfc3339())
        .body(axum::body::Body::from(frame.data))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

// GET /frames/range

// Returns all frames within [from, to] (Unix seconds) as a zip archive.
// Each file inside the zip is named with its capture timestamp and format
// extension. Stored compression is used since image formats are already
// compressed — applying deflate on top would waste CPU with no size benefit.
async fn frames_range_handler(
    State(state): State<AppState>,
    Query(params): Query<RangeQuery>,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    let from = DateTime::<Utc>::from_timestamp(params.from, 0)
        .ok_or((StatusCode::BAD_REQUEST, "Invalid 'from' timestamp".to_string()))?;
    let to = DateTime::<Utc>::from_timestamp(params.to, 0)
        .ok_or((StatusCode::BAD_REQUEST, "Invalid 'to' timestamp".to_string()))?;

    if from > to {
        return Err((
            StatusCode::BAD_REQUEST,
            "'from' must be before or equal to 'to'".to_string(),
        ));
    }

    let frames = state.store.get_in_range(from, to).await;

    if frames.is_empty() {
        return Err((
            StatusCode::NOT_FOUND,
            format!(
                "No frames found between {} and {}",
                from.to_rfc3339(),
                to.to_rfc3339()
            ),
        ));
    }

    // Build the zip in memory
    let mut zip_buf: Vec<u8> = Vec::new();
    {
        let cursor = std::io::Cursor::new(&mut zip_buf);
        let mut zip = zip::ZipWriter::new(cursor);

        // Stored (no compression) — image data is already compressed
        let options: zip::write::FileOptions<'_, ()> =
            zip::write::FileOptions::default()
                .compression_method(zip::CompressionMethod::Stored);

        for frame in &frames {
            let format = frame
                .metadata
                .get("format")
                .cloned()
                .unwrap_or_else(|| "png".to_string());

            let ts = frame.timestamp.format("%Y-%m-%dT%H-%M-%S%.3fZ");
            let filename = format!("frame_{}.{}", ts, format);

            zip.start_file(&filename, options)
                .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

            zip.write_all(&frame.data)
                .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        }

        zip.finish()
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    }

    let zip_filename = format!(
        "frames_{}_{}.zip",
        from.format("%Y-%m-%dT%H-%M-%SZ"),
        to.format("%Y-%m-%dT%H-%M-%SZ")
    );

    info!(
        "Range download: {} frames ({} → {})",
        frames.len(),
        from.to_rfc3339(),
        to.to_rfc3339()
    );

    axum::response::Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "application/zip")
        .header(
            header::CONTENT_DISPOSITION,
            format!("attachment; filename=\"{}\"", zip_filename),
        )
        .header("x-frame-count", frames.len().to_string())
        .body(axum::body::Body::from(zip_buf))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

// Debug

async fn debug_handler(State(state): State<AppState>) -> Json<serde_json::Value> {
    let uptime = state.start_time.elapsed().as_secs_f64();
    let frames = state.store.list().await;
    let config = state.config.read().await.clone();
    let agent_connected = *state.agent_connected.read().await;

    Json(json!({
        "uptime_sec":      uptime,
        "total_frames":    frames.len(),
        "current_config":  config,
        "agent_connected": agent_connected,
    }))
}

// Main

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.contains(&"--version".to_string()) {
        const VERSION: &str = env!("CARGO_PKG_VERSION");
        println!("eye-server v{}", VERSION);
        return Ok(());
    }

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing::Level::INFO.into()),
        )
        .with_target(false)
        .compact()
        .init();

    let port = env::var("EYE_PORT").unwrap_or_else(|_| "8080".to_string());
    let _auth_token = env::var("EYE_AUTH_TOKEN").ok();

    // Ring-buffer capacity — configurable via EYE_MAX_FRAMES, default 100
    let max_frames: usize = env::var("EYE_MAX_FRAMES")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(100);

    info!("Ring buffer: {} frames max", max_frames);

    let state = AppState::new(max_frames);

    let app = Router::new()
        // Status
        .route("/health",       get(health_handler))
        .route("/debug",        get(debug_handler))
        // 1:1 connection lifecycle
        .route("/connect",      post(connect_handler))
        .route("/disconnect",   post(disconnect_handler))
        // Agent upload
        .route("/upload",       post(upload_handler))
        // Admin
        .route("/admin/config", post(admin_config_handler))
        // Image retrieval
        // NOTE: /frames/range must be registered BEFORE /frames/:id so that
        // Axum does not try to parse "range" as an integer frame ID.
        .route("/snapshot.png",  get(snapshot_handler))
        .route("/frames",        get(frames_list_handler))
        .route("/frames/range",  get(frames_range_handler))
        .route("/frames/:id",    get(frame_by_id_handler))
        .layer(DefaultBodyLimit::max(50 * 1024 * 1024))
        .layer(middleware::from_fn(logging_middleware))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", port);
    info!("Eye Server starting on {} (1:1 agent mode)", addr);

    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .context("Failed to bind server")?;

    axum::serve(listener, app)
        .await
        .context("Server error")?;

    Ok(())
}

// Tests

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_app_state_creation() {
        let state = AppState::new(100);
        assert!(state.start_time.elapsed().as_secs() < 1);
    }

    #[test]
    fn test_default_config() {
        let config = AgentConfig::default();
        assert_eq!(config.interval, 1.5);
        assert_eq!(config.format, "png");
        assert_eq!(config.quality, 95);
    }

    #[tokio::test]
    async fn test_agent_connected_initial_false() {
        let state = AppState::new(100);
        let connected = state.agent_connected.read().await;
        assert!(!*connected);
    }
}