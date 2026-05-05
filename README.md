# 🎬 PROJECT MONTAGE
### AI-Powered Animated Video Generation System

> Transform a text prompt into a fully animated, narrated video — autonomously, in under two minutes.

---

## 📌 Overview

**Project AI-Powered Animated Video Generation System** is an end-to-end autonomous video generation pipeline that converts textual narratives or screenplays into fully animated videos with synchronized audio and cinematic visual effects.

The system operates across **four sequential phases**:

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Story Generation | Converts user input into structured scene manifest & character database via a multi-agent LangGraph pipeline |
| 2 | Audio Synthesis | Synthesizes per-scene WAV audio tracks with frame-accurate timing using Microsoft Edge TTS |
| 3 | Video Generation | Generates per-character images & animated clips via Alibaba DashScope APIs, then composites the final MP4 |
| 4 | Edit & Undo | Natural language post-production editing with full SQLite-backed version history and one-click revert |

A **Human-in-the-Loop (HITL)** checkpoint is embedded in Phase 1 so users can review and approve the generated story before any media is produced.

---

## 🛠️ Technology Stack

### Core AI & Orchestration
| Tool | Version | Purpose |
|------|---------|---------|
| [LangGraph](https://github.com/langchain-ai/langgraph) | `>= 0.2.0` | Multi-agent pipeline orchestration |
| [Groq](https://groq.com) | `>= 0.5.0` | Low-latency LLM inference (scriptwriting, intent classification) |
| [LangChain Chroma](https://python.langchain.com/docs/integrations/vectorstores/chroma/) | `>= 0.1.0` | Semantic vector search over character/scene data |
| [LangChain HuggingFace](https://python.langchain.com/docs/integrations/text_embedding/huggingfacehub/) | `>= 0.0.3` | Embedding generation for retrieval |

### Image & Video Generation
| Tool | Version | Purpose |
|------|---------|---------|
| [DashScope](https://dashscope.aliyun.com) | `>= 1.14.0` | Alibaba multimodal APIs — `wan2.5` (text-to-image), `wan2.7` (image-to-video) |
| [MoviePy](https://zulko.github.io/moviepy/) | `1.0.3` | Video composition, scene merging, transitions |
| [Pillow](https://python-pillow.org) | `>= 10.0.0` | Image resizing, filtering, and manipulation |
| [imageio](https://imageio.readthedocs.io) | `>= 2.34.0` | Frame-level image I/O |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | `>= 0.4.9` | FFmpeg backend for video encoding |

### Audio & TTS
| Tool | Version | Purpose |
|------|---------|---------|
| [edge-tts](https://github.com/rany2/edge-tts) | `>= 6.1.9` | Microsoft Edge neural TTS — multi-voice, multi-character dialogue synthesis |

### UI & State Management
| Tool | Version | Purpose |
|------|---------|---------|
| React + Fast API | Built-in | Web GUI with 4-tab navigation |
| SQLite3 | Built-in | Append-only version history storage for state & asset backups |
| [gradio_client](https://www.gradio.app) | `>= 0.15.0` | Optional web-based client integration |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | `>= 1.0.0` | API key and environment variable management |

---

## 📁 Project Structure

```
project-montage/
│
├── main.py                  # Main Web GUI — Phase 1 & 2 panels (993 lines)
├── phase3_panel.py          # Phase 3 panel — 6-stage video generation pipeline
├── edit_panel.py            # Phase 4 panel — Edit & Undo with version history UI
├── state_manager.py         # SQLite versioning, asset backup & restoration
│
├── state.py                 # Phase 1 LangGraph TypedDict state model
├── state2.py                # Phase 2 LangGraph TypedDict state model
├── state3.py                # Phase 3 LangGraph TypedDict state model
│
├── graph.py                 # Phase 1 LangGraph pipeline definition
├── graph2.py                # Phase 2 LangGraph pipeline definition
├── graph3.py                # Phase 3 LangGraph pipeline definition
│
├── llm.py                   # Groq LLM endpoint configuration
├── requirements.txt         # Python dependency declarations
│
├── agents/                  # Phase 1 AI agents (Scriptwriter, Validator, Character Designer)
├── agents2/                 # Phase 2 AI agents (Scene Parser, Voice Synthesis)
├── agents3/                 # Phase 3 AI agents (Image Gen, Video Gen, Compositor)
├── mcp/                     # Model Context Protocol integration
├── memory/                  # Long-context memory management for agents
├── utils/                   # Shared utilities — JSON helpers, state helpers
│
└── outputs/                 # Runtime output directory (auto-created)
    ├── audio/               # scene_{id}.wav — per-scene audio tracks
    ├── images/characters/   # {scene_id}_{char}.png — generated character images
    ├── clips/               # {scene_id}_{char}.mp4 — per-character animated clips
    ├── video/
    │   ├── scenes/          # {scene_id}.mp4 — composited scene videos
    │   ├── final_output.mp4 # Final assembled video
    │   └── subtitles.srt    # Optional subtitle file
    ├── logs/                # Execution logs
    └── versions.db          # SQLite version history database
```

---

## ⚙️ Setup Instructions

### Prerequisites

- Python **3.10+**
- `ffmpeg` installed and available on your system PATH
- API keys for **Groq** and **Alibaba DashScope**

#### Install ffmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows — download from https://ffmpeg.org/download.html
```

### 1. Clone the Repository

```bash
git clone https://github.com/ambreenarshad/AI-Powered-Animated-Video-Generation-System.git
cd AI-Powered-Animated-Video-Generation-System
```

### 2. Create a Virtual Environment

```bash
python -m venv venv

# Activate on macOS/Linux
source venv/bin/activate

# Activate on Windows
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API Keys

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
DASHSCOPE_API_KEY=your_dashscope_api_key_here
```

> 💡 Get your **Groq** key at [console.groq.com](https://console.groq.com)  
> 💡 Get your **DashScope** key at [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com)

---

## 🚀 Running the Application

```bash
uvicorn api:app --reload --port 8000
cd frontend
npm install (for first time)
npm run dev
```

The GUI will launch with four tabs corresponding to the four pipeline phases.

---

## 🎮 Execution Steps

### Step 1 — Story Generation (Phase 1 Tab)

1. Enter your prompt in one of three supported formats:
   - **Plain text**: e.g., *"A detective and a ghost solve a mystery in 1920s Paris"*
   - **Raw screenplay**: formatted with Scene / Speaker / Visual Cue sections
   - **Structured JSON**: a manually authored scene manifest
2. Click **Generate Story**.
3. Review the generated script in the HITL checkpoint panel.
4. **Approve** to proceed, or provide feedback and **Regenerate**.

> Outputs: `outputs/scene_manifest.json`, `outputs/character_db.json`

---

### Step 2 — Audio Synthesis (Phase 2 Tab)

1. Ensure Phase 1 has completed successfully (manifest files present).
2. Click **Synthesize Audio**.
3. The pipeline processes all scenes in parallel — progress is shown in the log panel.

> Outputs: `outputs/audio/scene_{id}.wav`, `outputs/timing_manifest.json`, `outputs/phase2_manifest.json`

---

### Step 3 — Video Generation (Phase 3 Tab)

1. Ensure Phase 2 has completed successfully.
2. Click **Generate Video**.
3. The 6-stage pipeline runs automatically:
   - Manifest loading → Image generation → Video generation → A/V sync → Scene merge → Final composition
4. Progress is tracked per stage in real time.

> Outputs: `outputs/video/final_output.mp4`, `outputs/video/subtitles.srt`

---

### Step 4 — Edit & Undo (Phase 4 Tab)

1. Type a natural language edit query, for example:
   - *"Make scene 2 feel darker and more dramatic"*
   - *"Change Alice's voice to a British accent"*
   - *"Add a transition effect between scenes 1 and 3"*
2. Click **Apply Edit**.
3. Use the **Version History** panel to view all prior states.
4. Click **Revert** on any version to restore it completely, including all asset files.

---

## ⏱️ Expected Performance

For a representative **3-scene video with 2 characters per scene**:

| Phase | Expected Duration |
|-------|-------------------|
| Phase 1: Story Generation | ~12 seconds |
| Phase 2: Audio Synthesis | ~9 seconds |
| Phase 3: Video Generation | ~95 seconds |
| Phase 4: Edit Apply | < 1 second |
| **Total** | **~116 seconds** |

> Primary bottleneck is DashScope API rate limits during image and video generation.

---

## 🗺️ Roadmap

- [ ] Lip synchronization via **Wav2Lip**
- [ ] Expressive facial animation via **SadTalker**
- [ ] Background stock footage via **Pexels API**
- [ ] High-fidelity TTS via **ElevenLabs**
- [ ] Web-based UI via **Gradio / FastAPI**
- [ ] Multi-language support
- [ ] Real-time multi-user collaboration via WebSockets
- [ ] Advanced cinematic color grading in the compositor

---

## ⚠️ Known Limitations

- Single-user desktop application — no web or multi-user support yet
- DashScope API rate limits cap concurrent scene generation throughput
- API keys must be configured manually via `.env` — no GUI credential manager
- Lip-sync requires additional model setup (not included in base install)
- English-language content only in current release

---

## 📄 License

This project is confidential. All rights reserved — May 2026.

---

*Built with using LangGraph · Groq · Alibaba DashScope · Microsoft Edge TTS · MoviePy*
