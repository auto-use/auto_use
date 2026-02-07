<div align="center">
  <img src="auto_use.png" alt="Auto Use Logo" width="120"/>

  # Auto Use

  **One Click. Millions of Possibilities.**

  [Features](#-features) • [Agents](#-agents) • [Models](#-supported-models) • [Requirements](#-requirements)
</div>

---

## 🎬 Demo

<img src="demo.gif" alt="Auto Use Demo" width="100%"/>

<p align="center">
  <strong>👇 Click here to watch full video demos</strong>
</p>

<p align="center">
  <a href="https://drive.google.com/file/d/13FrZzM-dsyxSxlFZwmbfMnHmmpOp3jxx/view?usp=sharing"><img src="https://img.shields.io/badge/▶_OS_+_Coding_Demo-4285F4?style=for-the-badge&logo=google-drive&logoColor=white" alt="OS + Coding Demo"/></a>
  &nbsp;&nbsp;
  <a href="https://drive.google.com/file/d/1cPFu5SHA0udp9ErLandowRcaYIqfM30H/view?usp=sharing"><img src="https://img.shields.io/badge/▶_Coding_Task_Demo-34A853?style=for-the-badge&logo=google-drive&logoColor=white" alt="Coding Task Demo"/></a>
</p>

---

## ✨ Features

### 🔍 Vision-Based Automation

Auto Use sees your screen like a human does. It captures screenshots, identifies UI elements with orange bounding boxes, and understands exactly where to click, type, or scroll.

### 🧠 Multi-Agent System

Four specialized agents working together — GUI automation, CLI commands, web search, and coding tasks. Each agent is optimized for its domain.

### 📚 Knowledge System

Add your personal domain/application context easily. Smart reinforcement system to understand your domain/application better — fine-tune just with prompts.

### 🔒 Secure Sandbox Execution

All code execution happens in an isolated sandbox environment. Your system stays protected while the agent works.

### 💾 Intelligent Memory

3 state memory system for long running sessions. Maintains context across multi-step tasks and never loses track of complex workflows.

### ⚡ Multi-Provider Support

Choose from 16+ AI models across OpenRouter, Groq, and OpenAI. Switch providers based on speed, cost, or capability needs.

---

## 🤖 Agents

### 🖥️ GUI Agent

The main automation engine. Uses computer vision to interact with any Windows application.

- **See** — Captures annotated screenshots with element detection
- **Understand** — Analyzes UI using vision-language models
- **Act** — Clicks, types, scrolls, and uses keyboard shortcuts
- **Verify** — Confirms actions completed before moving on

```
"Open Chrome, go to YouTube, and search for Python tutorials"
```

### 💻 CLI Agent

PowerShell-powered terminal agent for command-line tasks.

- Execute shell commands
- Navigate file systems
- Run scripts and programs
- Manage system operations

```
"Check disk space and clean up temp files"
```

### 👨‍💻 Coding Agent

Your AI programming assistant that writes, edits, and debugs code.

- Create new files with proper structure
- Edit existing code with precision
- Debug and fix errors
- Run and test programs

```
"Create a Python Flask API with user authentication"
```

### 🌐 Web Agent

Real-time information retrieval from the internet.

- Search multiple sources automatically
- Extract and summarize data
- Save findings to milestones
- Integrate results into ongoing tasks

```
"Find the latest NVIDIA stock price and quarterly revenue"
```

---

## 🎯 What Can Auto Use Do?


| Category         | Examples                                                 |
| ---------------- | -------------------------------------------------------- |
| **Browser**      | Fill forms, extract data, navigate sites, download files |
| **Productivity** | Create documents, manage spreadsheets, organize files    |
| **Development**  | Write code, debug errors, run tests, manage git          |
| **System**       | Install software, configure settings, manage processes   |
| **Research**     | Search web, compile information, generate reports        |


---

## 🧠 Supported Models

Auto Use supports **16+ vision-language models** across 3 providers.

### OpenRouter

Access multiple AI providers through a single API.


| Model                    | API Name / Short Name           | Reasoning |
| ------------------------ | ------------------------------- | --------- |
| **Gemini 2.5 Pro**       | `google/gemini-2.5-pro`         | ✅         |
| **Gemini 2.5 Flash**     | `google/gemini-2.5-flash`       | ✅         |
| **Gemini 2.5 Flash Lite**| `google/gemini-2.5-flash-lite`  | ✅         |
| **Gemini 3 Pro Preview** | `google/gemini-3-pro-preview`   | ✅         |
| **Gemini 3 Flash Preview**| `google/gemini-3-flash-preview` | ✅         |
| **GPT-5.1**              | `openai/gpt-5.1`                | ✅         |
| **GPT-5.2**              | `openai/gpt-5.2`                | ✅         |
| **GPT-5 Pro**            | `openai/gpt-5-pro`              | ❌         |
| **Claude Sonnet 4.5**    | `anthropic/claude-sonnet-4.5`   | ✅         |
| **Grok 4 Fast**          | `x-ai/grok-4-fast`              | ✅         |
| **Grok 4.1 Fast**        | `x-ai/grok-4.1-fast`            | ✅         |
| **Kimi K2.5**            | `moonshotai/kimi-k2.5`          | ✅         |


🔗 **Get API Key:** [openrouter.ai/keys](https://openrouter.ai/keys)

---

### Groq

Ultra-fast inference with open-source models.


| Model                    | API Name / Short Name                            | Vision |
| ------------------------ | ------------------------------------------------- | ------ |
| **Llama 4 Maverick 17B** | `meta-llama/llama-4-maverick-17b-128e-instruct`  | ✅      |
| **Llama 4 Scout 17B**    | `meta-llama/llama-4-scout-17b-16e-instruct`      | ✅      |


🔗 **Get API Key:** [console.groq.com/keys](https://console.groq.com/keys)

---

### OpenAI Direct

Direct access to OpenAI's latest models.


| Model       | API Name   | Reasoning |
| ----------- | ---------- | --------- |
| **GPT-5.1** | `gpt-5.1`  | ✅         |
| **GPT-5.2** | `gpt-5.2`  | ✅         |


🔗 **Get API Key:** [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

---

## 🎮 Model Selection Guide


| Use Case         | Recommended Model                | Why                                   |
| ---------------- | -------------------------------- | ------------------------------------- |
| **Fast & Cheap** | `gemini-3-flash`                 | Great balance of speed and capability |
| **Most Capable** | `claude-sonnet-4.5/gemini-3-pro` | Best reasoning for complex tasks      |
| **Ultra-Fast**   | `llama-4-maverick` (Groq)        | Lowest latency                        |
| **Best Vision**  | `claude-sonnet-4.5`              | Excellent UI understanding            |


---

## 📋 Requirements

- **Windows 10/11** (64-bit)
- **API Key** from any supported provider

---

## 🛡️ Safety

- **Sandbox Isolation** — Code runs in a protected environment
- **No System Modification** — Won't delete files or run destructive commands without permission
- **UAC Awareness** — Asks for confirmation before accepting elevation prompts
- **Path Protection** — Blocks access to critical system folders

---

## 🌟 Why Auto Use?


| Feature                    | Auto Use | Others  |
| -------------------------- | -------- | ------- |
| Multi-agent system         | ✅        | ❌       |
| Domain knowledge injection | ✅        | ❌       |
| 16+ model support          | ✅        | Limited |
| Vision-based automation    | ✅        | ✅       |
| Coding agent               | ✅        | ❌       |
| Web search integration     | ✅        | ❌       |
| Secure sandbox             | ✅        | ❌       |


---

## 💻 OS Support


| Operating System | Status         |
| ---------------- | -------------- |
| **Windows**      | ✅ Supported    |
| **macOS**        | 🚧 Coming Soon |
| **Linux**        | 🚧 Coming Soon |


