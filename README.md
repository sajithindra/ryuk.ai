# Agentic AI Real-Time Safety Intelligence System

**Team Name:** Palantir  
**Team Members:** Sajith Surendran, Jobin Mathew  

---

## Overview

Our platform is an agentic AI-powered real-time safety intelligence system built to protect people at scale. It integrates CCTV networks, drone feeds, and live video streams to detect and identify individuals who appear on authorized watchlists such as repeat offenders or organized fraud networks.

What makes the system agentic is not just recognition, but autonomous coordination. The AI continuously observes multiple camera feeds, links identities across locations, tracks movement patterns, builds situational timelines, and generates structured intelligence reports without waiting for step-by-step human commands. It determines when to escalate, when to continue monitoring, and when to request operator validation. The system operates as a goal-driven security agent: prevent harm, minimize response time, and maintain traceable documentation.

This platform is built for dense residential communities, apartments, campuses, enterprises, and child-focused institutions. In India alone, millions live in gated communities and high-density housing clusters where shared spaces increase exposure risk.

---

## Repository Structure

This repository contains the core software stack for our safety intelligence platform, comprising the AI-driven analytics backend, real-time video processing workers, and an interactive desktop dashboard. Below is an overview of the key directories and files:

### Application Entry
- **`main.py`**  
  The primary entry point of the application. It initializes the system, starts the background FastAPI server for live stream ingestion, and launches the PyQt6 desktop dashboard (`ui/dashboard.py`).

### Core Logic (`core/`)
Contains the central business logic and agentic frameworks:
- **`server.py`**: FastAPI WebSocket server customized to receive and buffer high-speed camera frames from edge devices and mobile clients.
- **`agent.py`**: The autonomous agent logic that coordinates tracking, links identities across time and space, and decides escalation protocols based on observed threats.
- **`ai_processor.py`**: The AI vision engine, utilizing state-of-the-art models for robust facial recognition, bounding box tracking, and keypoint detection.
- **`watchdog_indexer.py`**: Continuous monitoring service that catalogs observed events, generates situational timelines, and triggers real-time alerts.
- **`database.py`**: Manages data persistence for individuals on watchlists, observed events, timelines, and system logs.
- **`state.py`**: Centralized state management for tracking in-memory video sessions and overall system status.

### User Interface (`ui/` & `components/`)
- **`ui/dashboard.py`**: A comprehensive PyQt6 dashboard providing operators with a real-time command center view of camera feeds, AI analytics, and threat alerts.
- **`components/video_worker.py`**: Modular PyQt6 worker threads that offload heavy video stream decoding and ML inference from the main UI thread, ensuring smooth UI performance.

### Data & Documentation
- **`data/`**: Used for persisting local configuration, model weights, local databases, or cached facial embeddings required by the AI processor.
- **`mobile_integration.md`**: Provides instructions and API documentation for connecting mobile clients (iOS/Android) or external cameras to our WebSocket server for video ingestion.

### Environment Requirements
- **`requirements.txt`**: Standard Python dependencies needed to run the platform.

---

## Getting Started

1. **Environment Setup**: Python 3.8+ (Tested on 3.12) is recommended.
2. **Install Dependencies**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Run the Platform**:
   ```bash
   python main.py
   ```
   The platform will start the WebSocket server and launch the desktop dashboard, ready to receive incoming video streams.

---
