<div align="center">
  <img src="Auto_Use/logo/auto_use.png" alt="Auto Use Logo" width="120"/>

  # Auto Use

  <a href="https://autouse.netlify.app/">
    <img src="https://img.shields.io/badge/⬇️%20Download%20One--Click%20Setup-2563EB?style=for-the-badge&logoColor=white" alt="Download One-Click Setup" height="44"/>
  </a>

  **🤖 Computer Use Framework for macOS & Windows**

  Let AI drive your computer — **Autouse AI — Computer Use**, now with both the macOS and Windows builds combined in a single repository. Control your entire OS with natural language. Browser automation, coding tasks, file management — all powered by vision-language models.

  [Features](#-features) • [Example Tasks](#-example-tasks) • [Providers](#-supported-providers) • [Setup](#-setup) • [Author](#-author)
</div>

---

## ✨ Features

- GUI-based automation
- Multi-agent system
- Web agent
- CLI agent
- AppScript
- Secure sandbox

---

## 🎯 Example Tasks

Just describe what you want — Auto Use picks the right tool for the job.

### 🖥️ GUI Task
```
"Open Chrome, go to YouTube, and search for Python tutorials"
```

### 👨‍💻 Coding Task
```
"Create a Python Flask API with user authentication"
```

### 🌐 Web Search Task
```
"Find the latest NVIDIA stock price and quarterly revenue"
```

### 💻 CLI Task
```
"Check disk space and clean up temp files"
```

### 🍎 AppScript Task
```
"Send an iMessage to John saying I'll be 10 minutes late"
```

---

## 🎯 What Can Auto Use Do?

| Category | Examples |
|----------|----------|
| **Browser** | Fill forms, extract data, navigate sites, download files |
| **Productivity** | Create documents, manage spreadsheets, organize files |
| **Development** | Write code, debug errors, run tests, manage git |
| **System** | Install software, configure settings, manage processes |
| **Research** | Search web, compile information, generate reports |

---

## 🧠 Supported Providers

Auto Use supports **6 LLM providers**:

- **Anthropic**
- **Google**
- **Groq**
- **OpenAI**
- **OpenRouter**
- **Perplexity**

---

## 📋 Requirements

- **macOS** (Apple Silicon or Intel) **or** **Windows 10/11**
- **API Key** from any supported provider

---

## 🚀 Setup

> 💡 **Recommended for most users:** We strongly encourage installing the **latest binary build** from our [official website](https://autouse.netlify.app/) for a fully seamless installation and the complete UI experience — no manual setup required.
>
> The steps below are for developers who want to run Auto Use directly from source.

### 🍎 macOS

1. **Run the setup script**

   ```bash
   bash MacOS_setup.sh
   ```

2. **Add your API key(s)**

   Copy the example env file and fill in your keys:

   ```bash
   cp .env.example .env
   ```

   Then open `.env` and add the API key for whichever provider(s) you want to use.

3. **Run Auto Use**

   ```bash
   python main.py
   ```

### 🪟 Windows

1. **Run the setup script**

   ```bat
   windows_setup.bat
   ```

2. **Add your API key(s)**

   Copy the example env file and fill in your keys:

   ```bat
   copy .env.example .env
   ```

   Then open `.env` and add the API key for whichever provider(s) you want to use.

3. **Run Auto Use**

   ```bat
   python main.py
   ```

> **Note:** On Windows, Python **3.13.3** is the preferred version for best compatibility.

---

## 🛡️ Safety

- **Sandbox Isolation** — Code runs in a protected environment
- **No System Modification** — Won't delete files or run destructive commands without permission
- **Permission Awareness** — Asks for confirmation before accepting elevation prompts
- **Path Protection** — Blocks access to critical system folders

---

## 🌟 Why Auto Use?

| Feature | Auto Use | Others |
|---------|----------|--------|
| Multi-agent system | ✅ | ❌ |
| Domain knowledge injection | ✅ | ❌ |
| Multi-provider LLM support | ✅ | Limited |
| Vision-based automation | ✅ | ✅ |
| Coding agent | ✅ | ❌ |
| Web search integration | ✅ | ❌ |
| Secure sandbox | ✅ | ❌ |

---

## 💻 OS Support

This repository supports **both macOS and Windows** — the two platform builds live side-by-side in the same repo:

- **macOS** — `Auto_Use/macOS_use`
- **Windows** — `Auto_Use/windows_use`

---

## 👤 Author

**Ashish Yadav** — founder of [Autouse AI](https://github.com/auto-use)

---

## 📄 License & Attribution

Licensed under the **Apache License 2.0** — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

If you use, fork, reference, or derive from this project, you must:

1. Preserve the copyright notice and the `NOTICE` file.
2. Credit **Ashish Yadav (Autouse AI)** as the original author.
3. Link back to the project: https://github.com/auto-use

### How to cite

> Yadav, Ashish. *Autouse AI — Computer Use.* Autouse AI, 2026. https://github.com/auto-use
