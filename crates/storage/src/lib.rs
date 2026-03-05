// crates/storage/src/lib.rs
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::fs;
use tokio::sync::RwLock;

// Data structure representing a stored frame
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Frame {
    pub id: i64,
    pub data: Vec<u8>,
    pub timestamp: DateTime<Utc>,
    pub metadata: HashMap<String, String>,
}

// Storage modes
#[derive(Debug, Clone)]
pub enum StorageMode {
    Memory,
    Disk,
    Hybrid,
}

// Memory Store
pub struct MemoryStore {
    frames: Arc<RwLock<Vec<Frame>>>,
    max_frames: usize,
    current: Arc<RwLock<usize>>,
}

// Implementation of MemoryStore
impl MemoryStore {
    pub fn new(max_frames: usize) -> Self {
        Self {
            frames: Arc::new(RwLock::new(Vec::with_capacity(max_frames))),
            max_frames,
            current: Arc::new(RwLock::new(0)),
        }
    }

    // Store a frame in memory
    pub async fn store(&self, frame: Frame) -> Result<()> {
        let mut frames = self.frames.write().await;
        let mut current = self.current.write().await;

        if frames.len() < self.max_frames {
            frames.push(frame);
        } else {
            frames[*current] = frame;
            *current = (*current + 1) % self.max_frames;
        }

        Ok(())
    }

    // Retrieve the latest frame (by timestamp)
    pub async fn get_latest(&self) -> Result<Frame> {
        let frames = self.frames.read().await;

        if frames.is_empty() {
            anyhow::bail!("no frames available");
        }

        // Find the frame with the latest timestamp
        let latest_frame = frames
            .iter()
            .max_by_key(|f| f.timestamp)
            .unwrap();

        Ok(latest_frame.clone())
    }

    // Retrieve the latest frame (by buffer position - legacy behavior)
    pub async fn get_latest_by_position(&self) -> Result<Frame> {
        let frames = self.frames.read().await;
        let current = self.current.read().await;

        if frames.is_empty() {
            anyhow::bail!("no frames available");
        }

        let frame = if frames.len() < self.max_frames {
            frames.last().unwrap()
        } else {
            let idx = (*current + self.max_frames - 1) % self.max_frames;
            &frames[idx]
        };

        Ok(frame.clone())
    }

    // Retrieve a single frame by its ID
    pub async fn get_by_id(&self, id: i64) -> Result<Frame> {
        let frames = self.frames.read().await;

        frames
            .iter()
            .find(|f| f.id == id)
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("frame {} not found", id))
    }

    // Retrieve all frames whose timestamp falls within [from, to] (inclusive)
    pub async fn get_in_range(
        &self,
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Vec<Frame> {
        let frames = self.frames.read().await;

        frames
            .iter()
            .filter(|f| f.timestamp >= from && f.timestamp <= to)
            .cloned()
            .collect()
    }

    // List all stored frames
    pub async fn list(&self) -> Vec<Frame> {
        let frames = self.frames.read().await;
        frames.clone()
    }
}

// Disk Store
pub struct DiskStore {
    base_path: PathBuf,
}

// Implementation of DiskStore
impl DiskStore {
    pub async fn new(base_path: PathBuf) -> Result<Self> {
        fs::create_dir_all(&base_path)
            .await
            .context("Failed to create storage directory")?;

        Ok(Self { base_path })
    }

    // Store a frame on disk
    pub async fn store(&self, frame: &Frame) -> Result<()> {
        let filename = format!("frame_{}_{}.png", frame.id, frame.timestamp.timestamp());
        let filepath = self.base_path.join(filename);

        fs::write(&filepath, &frame.data)
            .await
            .context("Failed to write frame to disk")?;

        Ok(())
    }

    // Retrieve the latest frame from disk (not implemented)
    pub async fn get_latest(&self) -> Result<Frame> {
        anyhow::bail!("not implemented")
    }
}

// Storage Manager
pub struct Manager {
    memory: MemoryStore,
    disk: Option<DiskStore>,
    mode: StorageMode,
}

// Implementation of Storage Manager
impl Manager {
    pub async fn new(
        mode: StorageMode,
        memory_size: usize,
        disk_path: Option<PathBuf>,
    ) -> Result<Self> {
        let memory = MemoryStore::new(memory_size);

        let disk = match &mode {
            StorageMode::Disk | StorageMode::Hybrid => {
                let path = disk_path.context("Disk path required for disk/hybrid mode")?;
                Some(DiskStore::new(path).await?)
            }
            _ => None,
        };

        Ok(Self { memory, disk, mode })
    }

    // Store a frame based on the storage mode
    pub async fn store(&self, frame: Frame) -> Result<()> {
        match self.mode {
            StorageMode::Memory | StorageMode::Hybrid => {
                self.memory.store(frame.clone()).await?;
            }
            _ => {}
        }

        match (&self.mode, &self.disk) {
            (StorageMode::Disk, Some(disk)) | (StorageMode::Hybrid, Some(disk)) => {
                disk.store(&frame).await?;
            }
            _ => {}
        }

        Ok(())
    }

    // Retrieve the latest frame from memory
    pub async fn get_latest(&self) -> Result<Frame> {
        self.memory.get_latest().await
    }

    pub async fn list(&self) -> Vec<Frame> {
        self.memory.list().await
    }
}

// Unit tests
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_memory_store() {
        let store = MemoryStore::new(10);

        let frame = Frame {
            id: 1,
            data: vec![1, 2, 3],
            timestamp: Utc::now(),
            metadata: HashMap::new(),
        };

        store.store(frame.clone()).await.unwrap();
        let retrieved = store.get_latest().await.unwrap();
        assert_eq!(retrieved.id, frame.id);
    }

    #[tokio::test]
    async fn test_get_by_id() {
        let store = MemoryStore::new(10);

        for i in 1..=3i64 {
            store.store(Frame {
                id: i,
                data: vec![i as u8],
                timestamp: Utc::now(),
                metadata: HashMap::new(),
            }).await.unwrap();
        }

        let frame = store.get_by_id(2).await.unwrap();
        assert_eq!(frame.id, 2);

        assert!(store.get_by_id(99).await.is_err());
    }

    #[tokio::test]
    async fn test_get_in_range() {
        use chrono::Duration;

        let store = MemoryStore::new(10);
        let base = Utc::now();

        for i in 0..5i64 {
            store.store(Frame {
                id: i,
                data: vec![i as u8],
                timestamp: base + Duration::seconds(i * 10),
                metadata: HashMap::new(),
            }).await.unwrap();
        }

        // Frames at t+10s, t+20s, t+30s — IDs 1, 2, 3
        let from = base + Duration::seconds(10);
        let to   = base + Duration::seconds(30);
        let results = store.get_in_range(from, to).await;

        assert_eq!(results.len(), 3);
        assert!(results.iter().all(|f| f.id >= 1 && f.id <= 3));
    }
}