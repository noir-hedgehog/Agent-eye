// crates/agent/src/main.rs
// SPDX-License-Identifier: GPL-3.0-or-later
// Derivative of https://github.com/nullvoider07/the-eyes — fork: https://github.com/noir-hedgehog/Agent-eye

use anyhow::{Context, Result};
use capture::{Config as CaptureConfig, Engine};
use image::ImageFormat;
use std::env;
use std::time::Duration;
use tokio::signal;
use tokio::time::interval;
use tracing::{error, info, warn};
use transport::Client;

// Agent structure encapsulating capture and upload logic
struct Agent {
    engine: Engine,
    client: Client,
    interval: Duration,
    frame_id: i64,
    running: bool,
}

// Implementation of Agent
impl Agent {
    fn new(server_url: String, token: String, capture_interval: Duration) -> Self {
        let engine = Engine::new(CaptureConfig {
            interval: capture_interval,
            format: ImageFormat::Png,
        });

        let client = Client::new(server_url, token);

        Self {
            engine,
            client,
            interval: capture_interval,
            frame_id: 0,
            running: false,
        }
    }

    // Wait for the server to be ready
    async fn wait_for_server(&self, timeout: Duration) -> Result<()> {
        info!("Waiting for server...");
        let start = tokio::time::Instant::now();
        let mut ticker = interval(Duration::from_secs(2));

        loop {
            ticker.tick().await;

            if self.client.health_check().await.is_ok() {
                info!("Server ready! Registering agent...");

                // Claim the server's single connection slot.
                // Returns an error if another agent is already connected.
                self.client
                    .connect()
                    .await
                    .context("Failed to register with server")?;

                info!("Agent registered — connection established (1:1)");
                return Ok(());
            }

            if start.elapsed() > timeout {
                anyhow::bail!("Server timeout");
            }
        }
    }

    // Capture a frame and upload it to the server
    async fn capture_and_upload(&mut self) -> Result<()> {
        let frame = self.engine.capture_frame(self.frame_id)
            .context("Failed to capture frame")?;

        let response = self.client.upload_frame(frame.id, frame.data).await
            .context("Failed to upload frame")?;

        let size_kb = frame.size_bytes as f64 / 1024.0;
        info!("Frame #{} uploaded ({:.1} KB)", frame.id, size_kb);

        // Handle dynamic config updates from server
        if let Some(config) = response.get("config") {
            if let Some(interval) = config.get("interval").and_then(|v| v.as_f64()) {
                let new_interval = Duration::from_secs_f64(interval);
                if new_interval != self.interval {
                    info!("Interval update: {:?} -> {:?}", self.interval, new_interval);
                    self.interval = new_interval;
                }
            }
        }

        self.frame_id += 1;
        Ok(())
    }

    // Start the agent's capture and upload loop
    async fn start(&mut self) -> Result<()> {
        self.wait_for_server(Duration::from_secs(30)).await?;

        self.running = true;
        info!("Starting capture loop...");

        let mut ticker = interval(self.interval);
        let ctrl_c = signal::ctrl_c();
        tokio::pin!(ctrl_c);

        loop {
            tokio::select! {
                _ = ticker.tick() => {
                    if let Err(e) = self.capture_and_upload().await {
                        error!("Error: {}", e);
                    }
                }
                _ = &mut ctrl_c => {
                    info!("Stop signal received — disconnecting...");
                    self.running = false;
                    break;
                }
            }
        }

        if let Err(e) = self.client.disconnect().await {
            warn!("Failed to disconnect cleanly: {}. \
                The server slot will remain occupied until the server is restarted.", e);
        } else {
            info!("Disconnected from server");
        }

        Ok(())
    }
}

// Main function to start the agent
#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.contains(&"--version".to_string()) {
        const VERSION: &str = env!("CARGO_PKG_VERSION");
        println!("eye-agent v{}", VERSION);
        return Ok(());
    }
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing::Level::INFO.into()),
        )
        .init();

    // Get configuration from environment
    let server_url = env::var("EYE_SERVER_URL")
        .context("EYE_SERVER_URL required")?;

    let token = env::var("EYE_AUTH_TOKEN")
        .unwrap_or_default();

    let interval = Duration::from_millis(1500);

    info!("Server: {}", server_url);
    info!("Interval: {:.1}s", interval.as_secs_f64());

    let mut agent = Agent::new(server_url, token, interval);
    agent.start().await?;

    Ok(())
}

// Unit tests for the agent
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_agent_creation() {
        let agent = Agent::new(
            "http://localhost:8080".to_string(),
            "test-token".to_string(),
            Duration::from_secs(1),
        );
        assert_eq!(agent.frame_id, 0);
    }
}