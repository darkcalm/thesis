# Browser Automation Status & Implementation Guide

## Current Status (2026-01-29)

### ✅ Disabled: agent-browser
**Reason:** Even advanced browser agents haven't solved academic paper downloading cheaply and reliably.

**Issues found:**
- Multi-stage workflow too complex
- Cannot solve Cloudflare/CAPTCHA challenges
- Requires manual element identification
- Failed on item001 (stuck at Cloudflare challenge)

**Status:** Implementation kept but disabled via `AGENT_BROWSER_ENABLED = False`

### 🎯 Recommended: browser-use

**Why browser-use?**
- Solved item001 without any manual stages
- Autonomous LLM-powered navigation
- Handles Cloudflare, CAPTCHAs, dynamic content
- Simple prompt-based interface

**Status:** Stub implemented, ready for integration

## Implementation Guide: browser-use

### 1. Installation

```bash
# Install browser-use
pip install browser-use

# Install Playwright browsers
playwright install chromium
```

### 2. Basic Usage Example

```python
from browser_use import Browser
import asyncio

async def download_pdf(url, output_path):
    """Download PDF using browser-use autonomous navigation."""
    browser = Browser()

    # Simple prompt - browser-use figures out the rest
    prompt = f"""
    Go to {url}
    Find and download the PDF of the academic paper
    Save it to {output_path}
    """

    result = await browser.run(prompt)

    return result.success, result.message
```

### 3. Implementation Steps for download_sources.py

#### Step 1: Add browser-use import

```python
# At top of file (after existing imports)
try:
    import browser_use
    from browser_use import Browser
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False
```

#### Step 2: Implement try_browser_use_download()

Replace the stub function (line ~1400) with:

```python
def try_browser_use_download(url, output_path, timeout=30):
    """
    Use browser-use for autonomous browser automation.

    Returns:
        (success: bool, message: str, furthest_screenshot: Path | None, stage: str)
    """
    if not BROWSER_USE_AVAILABLE:
        return False, "browser-use not installed (pip install browser-use)", None, "not_available"

    import asyncio
    from browser_use import Browser

    # Create screenshots directory for debugging
    output_dir = output_path.parent
    item_num = output_path.stem.split('_')[0].replace('item', '')
    screenshots_dir = output_dir / f"item{item_num}_screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    async def download_task():
        try:
            browser = Browser(headless=True)

            # Simple, autonomous prompt
            prompt = f"""
            Navigate to {url}
            This is an academic paper page.
            Find the PDF download button/link and download the paper.
            Save the PDF to {output_path}

            Handle any popups, cookie consents, or access dialogs appropriately.
            If you encounter Cloudflare or CAPTCHA, wait for it to complete.
            """

            result = await browser.run(prompt, timeout=timeout)

            # Save final screenshot for debugging
            if hasattr(result, 'screenshot'):
                final_screenshot = screenshots_dir / "browser_use_final.png"
                with open(final_screenshot, 'wb') as f:
                    f.write(result.screenshot)

            # Check if download succeeded
            if output_path.exists() and is_valid_pdf(output_path):
                return True, "browser-use autonomous download", None, "success"
            else:
                return False, f"browser-use: {result.message}", None, "failed"

        except Exception as e:
            return False, f"browser-use error: {str(e)[:100]}", None, "error"

    # Run async task
    return asyncio.run(download_task())
```

#### Step 3: Enable browser-use

Set in configuration section (line ~130):

```python
BROWSER_USE_ENABLED = True  # Enable browser-use
AGENT_BROWSER_ENABLED = False  # Keep agent-browser disabled
```

### 4. Advanced Configuration

#### Option 1: Add retry logic

```python
# In try_browser_use_download()
MAX_RETRIES = 2
for attempt in range(MAX_RETRIES):
    success, message, screenshot, stage = await download_with_browser_use(url, output_path)
    if success:
        return success, message, screenshot, stage
    thread_print(f"  [BrowserUse] Attempt {attempt+1} failed, retrying...")
```

#### Option 2: Add cost tracking

```python
# browser-use uses LLM API calls - track costs
from browser_use import Browser

browser = Browser(
    model="gpt-4o-mini",  # Cheaper model
    max_tokens=500,  # Limit token usage
)
```

#### Option 3: Take progressive screenshots

```python
# Configure browser-use to save screenshots at each step
browser = Browser(
    screenshot_on_action=True,
    screenshot_dir=str(screenshots_dir)
)
```

## Testing Plan

### Phase 1: Single Item Test
```bash
python download_sources.py sourcing_checklist.md --start 1 --end 1
```

Expected: Should solve Cloudflare challenge and download PDF

### Phase 2: Batch Test (10 items)
```bash
python download_sources.py sourcing_checklist.md --start 1 --end 10
```

Track success rate vs. fast methods

### Phase 3: Cost Analysis
Monitor LLM API costs per download:
- Acceptable: < $0.10 per paper
- Target: < $0.05 per paper (using gpt-4o-mini)

## Comparison Matrix

| Feature | browser-use | agent-browser | Legacy Playwright |
|---------|-------------|---------------|-------------------|
| **Autonomy** | ✅ Full (LLM-driven) | ❌ Manual stages | ❌ Manual scoring |
| **Cloudflare** | ✅ Can solve | ❌ Fails | ❌ Fails |
| **CAPTCHA** | ✅ Can solve | ❌ Fails | ❌ Fails |
| **Setup Complexity** | ⭐ Simple prompt | ⭐⭐⭐ Multi-stage | ⭐⭐⭐⭐⭐ 1000+ lines |
| **Cost** | 💰 ~$0.05/paper | 💰 Free | 💰 Free |
| **Speed** | ⚡ Medium (LLM calls) | ⚡⚡ Fast | ⚡⚡ Fast |
| **Reliability** | ✅ High | ⭐⭐ Medium | ⭐⭐ Medium |
| **Maintenance** | ✅ Low | ⭐⭐⭐ Medium | ❌ Very High |

## Decision Matrix

**Use browser-use when:**
- Fast methods (OpenAlex, Unpaywall, Sci-Hub) fail
- Paper is behind Cloudflare/CAPTCHA
- Cost of $0.05-0.10 per paper is acceptable
- High success rate needed

**Skip browser automation when:**
- Fast methods succeed (75-85% of papers)
- Budget constraints are tight
- Paper is known to be impossible (hard paywall)

## References

- browser-use docs: https://docs.browser-use.com/quickstart
- browser-use GitHub: https://github.com/browser-use/browser-use
- Cost calculator: https://openai.com/api/pricing/ (gpt-4o-mini)

## Notes

- Agent-browser implementation retained in codebase for reference
- Progressive screenshot feature can be adapted to browser-use
- Vision analysis integration possible with browser-use screenshots
- Consider implementing both methods with fallback chain:
  1. Fast methods (OpenAlex, etc.)
  2. browser-use (autonomous)
  3. agent-browser (manual fallback)
