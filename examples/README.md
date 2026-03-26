# Vit Examples

This directory contains example scripts and sample data for testing vit functionality.

## LLM Demo (`llm_demo.py`)

A standalone demo script that tests AI merge resolution with sample timeline data. No Resolve project or git repository needed.

### What it does

The demo simulates a realistic merge scenario:
- **BASE**: A timeline with an interview clip and B-roll
- **OURS (Editor)**: Trimmed the interview and added new B-roll footage
- **THEIRS (Colorist)**: Color graded the interview with warmer tones, adjusted audio

The LLM analyzes these changes and decides how to merge them.

### Supported LLM Providers

The demo works with any OpenAI-compatible API:

| Provider | URL Example | Notes |
|----------|-------------|-------|
| **Ollama** (local) | `http://localhost:11434/v1` | Free, runs locally |
| **OpenAI** | `https://api.openai.com/v1` | GPT-4, GPT-3.5 |
| **OpenRouter** | `https://openrouter.ai/api/v1` | Access many models |
| **Together AI** | `https://api.together.xyz/v1` | Various open models |
| **Groq** | `https://api.groq.com/openai/v1` | Fast inference |
| **Azure OpenAI** | `https://your-resource.openai.azure.com/openai/deployments/your-deployment` | Enterprise |

### Usage

#### With Ollama (Local)

1. Install Ollama: https://ollama.com

2. Pull a good coding model:
   ```bash
   ollama pull qwen2.5-coder:14b
   ```

3. Run the demo:
   ```bash
   export VIT_LLM_URL=http://localhost:11434/v1
   export VIT_LLM_MODEL=qwen2.5-coder:14b
   python examples/llm_demo.py
   ```

#### With OpenAI

```bash
export VIT_LLM_URL=https://api.openai.com/v1
export VIT_LLM_MODEL=gpt-4
export GEMINI_API_KEY=your_openai_key_here  # Reuses same env var for API key
python examples/llm_demo.py
```

#### With OpenRouter

```bash
export VIT_LLM_URL=https://openrouter.ai/api/v1
export VIT_LLM_MODEL=anthropic/claude-3.5-sonnet
export GEMINI_API_KEY=your_openrouter_key_here
python examples/llm_demo.py
```

#### With Gemini

```bash
export GEMINI_API_KEY=your_gemini_key_here
python examples/llm_demo.py
```

### Expected Output

The LLM will analyze the merge and output something like:

```
============================================================
AI MERGE ANALYSIS RESULT
============================================================

Summary: Editor trimmed clips and added B-roll; Colorist graded interview

Decisions:
  [✓] cuts: accept_ours
      Confidence: high
      Reasoning: Editor made structural changes to timeline
  
  [~] color: merge
      Confidence: medium
      Reasoning: Colorist graded item_001; editor's new clip item_003 has no grade
  
  [?] audio: needs_user_input
      Confidence: low
      Reasoning: Both branches modified audio (trim vs volume)
      Options:
        A) Keep ours: Trimmed audio to match video
        B) Keep theirs: Reduced volume with original length
        C) Merge: Apply both trim and volume reduction

Auto-resolved domains:
  - cuts
  - color

⚠ This merge requires user input for some decisions.
```

### Sample Data Structure

The demo uses the same JSON structure as real vit projects:

- `cuts.json` - Video clip placements, in/out points, transforms
- `color.json` - Color grades per clip
- `audio.json` - Audio levels and panning
- `markers.json` - Timeline markers
- `metadata.json` - Project settings

See `docs/JSON_SCHEMAS.md` for full schema documentation.
