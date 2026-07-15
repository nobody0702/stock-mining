"""One-tap clipboard HTML for Streamlit (HTTP + iOS Safari friendly).

Uses a tiny iframe with a real <button> click handler so copy happens inside a
user gesture. Prefer this over mounting heavy components that remount on every
full-page Streamlit rerun — call sites should keep the iframe inside
``@st.fragment`` so disposition clicks only remount one card.
"""

from __future__ import annotations

import json
import re

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_]+")
_DEFAULT_LABEL = "复制 Prompt"
_COPIED_LABEL = "已复制 ✓"
_FALLBACK_LABEL = "请用下方文本框复制"
# Streamlit html component height; keep small to avoid layout thrash.
COPY_BUTTON_IFRAME_HEIGHT = 52


def sanitize_dom_id(element_key: str) -> str:
    """Turn a Streamlit widget key into a safe HTML id suffix."""
    text = (element_key or "btn").strip() or "btn"
    text = _SAFE_ID_RE.sub("_", text)
    if text[0].isdigit():
        text = f"id_{text}"
    return text[:120]


def _json_for_script(value: str) -> str:
    """JSON-encode ``value`` so it is safe inside an HTML ``<script>`` literal."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_copy_prompt_html(
    text: str,
    *,
    element_key: str,
    button_label: str = _DEFAULT_LABEL,
) -> str:
    """Build self-contained HTML that copies ``text`` on one tap.

    Works on:
    - remote HTTP (``document.execCommand('copy')`` fallback; Clipboard API needs HTTPS)
    - iPhone Safari (in-viewport hidden textarea + setSelectionRange inside click)
    """
    safe_id = sanitize_dom_id(element_key)
    # Escape <>& so a prompt containing </script> cannot break out of the HTML
    # <script> block (json.dumps alone is not HTML-script-safe).
    payload = _json_for_script(text)
    label = _json_for_script(button_label)
    copied = _json_for_script(_COPIED_LABEL)
    fallback = _json_for_script(_FALLBACK_LABEL)
    btn_id = f"copy_{safe_id}"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>
  html, body {{
    margin: 0; padding: 0; width: 100%; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: transparent;
  }}
  #{btn_id} {{
    width: 100%; box-sizing: border-box;
    min-height: 44px;
    padding: 0.55rem 0.75rem;
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 0.5rem;
    background: rgb(255, 255, 255);
    color: rgb(49, 51, 63);
    cursor: pointer;
    font-size: 1rem;
    -webkit-tap-highlight-color: rgba(0, 0, 0, 0.08);
    touch-action: manipulation;
  }}
  #{btn_id}:active {{ background: rgb(240, 242, 246); }}
</style></head><body>
<button id="{btn_id}" type="button">{button_label}</button>
<script>
(function() {{
  var btn = document.getElementById({json.dumps(btn_id)});
  var text = {payload};
  var label = {label};
  var copiedLabel = {copied};
  var fallbackLabel = {fallback};
  var busy = false;

  function copyViaExecCommand(value) {{
    var ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.setAttribute("aria-hidden", "true");
    // iOS Safari often fails when the node is far off-screen; keep it in-view + tiny.
    ta.style.position = "absolute";
    ta.style.left = "0";
    ta.style.top = "0";
    ta.style.width = "1px";
    ta.style.height = "1px";
    ta.style.padding = "0";
    ta.style.border = "none";
    ta.style.outline = "none";
    ta.style.boxShadow = "none";
    ta.style.background = "transparent";
    ta.style.opacity = "0";
    ta.style.fontSize = "16px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, value.length);
    var ok = false;
    try {{ ok = document.execCommand("copy"); }} catch (e) {{ ok = false; }}
    document.body.removeChild(ta);
    return ok;
  }}

  function setTempLabel(msg, ms) {{
    btn.innerText = msg;
    setTimeout(function() {{ btn.innerText = label; busy = false; }}, ms);
  }}

  function onCopied() {{ setTempLabel(copiedLabel, 2000); }}
  function onFailed() {{ setTempLabel(fallbackLabel, 2500); }}

  btn.addEventListener("click", function(e) {{
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;
    busy = true;
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(text).then(onCopied).catch(function() {{
        if (copyViaExecCommand(text)) onCopied();
        else onFailed();
      }});
      return;
    }}
    if (copyViaExecCommand(text)) onCopied();
    else onFailed();
  }});
}})();
</script>
</body></html>"""
