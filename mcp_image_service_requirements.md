# 📋 Project Requirements: Image Generation MCP Server & Visual Dashboard for Claude Code

## 1. Project Overview
The objective of this project is to develop a locally running **Model Context Protocol (MCP) Server** that exposes an `generate_image` tool to AI clients (prioritizing **Claude Code**), empowering them with image generation capabilities. To lower configuration barriers and maximize controllability, the project must integrate a **Visual Web Dashboard**. This dashboard will allow users to visually switch between cloud-based APIs and locally deployed image inference models.

---

## 2. Core Requirements

### ⚙️ 1. MCP Server
*   **Communication Protocol**: Built upon the official MCP specification, natively supporting **Stdio (Standard Input/Output)** mode so it can be dynamically spawned as a subprocess by Claude Code. Optionally, it should support **SSE (Server-Sent Events)** mode to run as a persistent background service.
*   **Exposed Tools**:
    *   `generate_image(prompt: string, size: string, ...)`:
        *   **Function**: Receives textual prompts and dimensional parameters from the AI client, routes them to the active underlying model, and triggers image generation.
        *   **Return Format**: Supports returning an external image **URL** or converting the generated image directly into a **Base64 data string (ImageContent)**. This allows Claude Code to natively render and display the image right within the terminal/client.

### 🎨 2. Image Model Routing System
The server must implement a multi-backend router that dynamically routes generation requests based on a centralized configuration file:
1.  **Cloud API Mode**:
    *   Supports **OpenAI-compatible endpoints** (e.g., OpenAI DALL-E 3, or authorized third-party model proxy APIs).
    *   *(Optional)* Supports native API endpoints for Stability AI (Flux/SD3) or Midjourney third-party connectors.
2.  **Local Deployment Mode**:
    *   Supports connecting to a local **Stable Diffusion WebUI (A1111)** via the `/sdapi/v1/txt2img` endpoint.
    *   *(Optional)* Supports **ComfyUI** API/WebSocket workflows or **Ollama** visual models.

### 🖥️ 3. Web Dashboard (Graphical User Interface)
Provides a lightweight, intuitive local web interface to manage the MCP server configurations seamlessly.
*   **Provider Switching**: A simple drop-down menu or card interface to instantly switch the active backend ("Cloud API" vs. "Local Deployment").
*   **Cloud Parameter Config**: Visually inputs and persists the `API Base URL`, `API Key` (masked for privacy), and `Model Name`.
*   **Local Parameter Config**: Configures local API endpoints (e.g., `http://127.0.0.1:7860`), default sampling steps, aspect ratios, and resolutions.
*   **Status Indicator**: Displays real-time connectivity status tests for both local models and cloud endpoints.

---

## 3. Architecture & Lifecycle Design

Because Claude Code frequently spawns and tears down MCP processes during tool execution, the project must adhere to a **decoupled dual-track execution architecture**:
*   **Data Persistence**: All settings modified via the GUI must be written in real time to a local configuration file (e.g., `config.json` or `.env`).
*   **Lightweight Stdio Invocation**:
    *   When executed via `python main.py --gui`, the script boots up a persistent Web Server (e.g., FastAPI + Vite/Vue) for configuration.
    *   When executed via `python main.py` (no arguments) by Claude Code, **the script must not spin up any web server or bind to any port**. It should instantly read `config.json` and cleanly execute the Stdio pipeline to prevent port conflicts and performance overhead.

---

## 4. Recommended Technical Stack
*   **Backend Language**: Python 3.10+ (for deeper AI ecosystem compatibility) or Node.js (TypeScript).
*   **MCP Framework**: Official Python `mcp` SDK or Node.js `@modelcontextprotocol/sdk`.
*   **Web Framework**: FastAPI / Express (Backend) + Vue 3 / React + Tailwind CSS (Frontend).
*   **HTTP Client**: Httpx / Aiohttp (Python) or Axios (Node.js) to support asynchronous, high-concurrency requests.
