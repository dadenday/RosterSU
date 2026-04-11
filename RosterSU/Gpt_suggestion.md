Yeah — this is a known Android + Chrome limitation, not your fault.

What’s happening is:

> 🚫 Chrome on Android blocks or restricts file:// access to local HTML files



Especially when:

You open via file manager

The HTML tries to load JS/CSS/JSON

Cross-file access (file:// → file://) happens



---

🧠 Why your static HTML “feels blocked”

Common symptoms:

Blank page

JS not running

JSON not loading

CSS missing


👉 Root cause:

> Chrome treats local files as untrusted origin → restricts access




---

🚀 Best Solutions (No Server Needed)

🥇 Option 1 — Use a Different Browser (Easiest Fix)

Install:

Kiwi Browser

Firefox for Android


👉 These allow file:// access much better than Chrome

Result:

Open HTML directly

Works instantly

No server needed



---

🥈 Option 2 — Inline Everything (Most Robust)

👉 Make your HTML self-contained

Instead of:

<script src="data.js"></script>
<link rel="stylesheet" href="style.css">

👉 Do:

<style>
/* CSS here */
</style>

<script>
const DATA = {...}; // embedded JSON
</script>


---

Why this works:

No external file access

Chrome can't block anything

Opens like a pure document


👉 This is the best “instant UI” design


---

🥉 Option 3 — Use content:// instead of file://

Open via:

Google Files app

Or a file manager that uses content://


👉 Sometimes bypasses restrictions

(but inconsistent across devices)


---

⚡ Option 4 — Install as a Local App (Super Clean)

Wrap your HTML in a WebView:

Android app (tiny)

Loads local file


👉 Benefits:

Instant launch

No browser restrictions

Feels native



---

⚠️ Your Current Workaround (Localhost Server)

You said:

> “It works but I don’t want overhead”



You're right.

Even a tiny server:

adds startup delay

drains battery slightly

adds complexity


👉 Good fallback, but not ideal for your goal


---

🔥 Best Practical Setup (What I Recommend)

Step 1 — Generate SINGLE FILE

schedule.html

With:

inline CSS

inline JS

inline data



---

Step 2 — Open with:

👉 Kiwi Browser
or
👉 Firefox for Android


---

Step 3 — Optional Shortcut

Add to home screen

Opens like an app



---

🧠 Pro Trick (Very Useful)

“Self-contained HTML snapshot”

Your pipeline should output:

render_html(snapshot_json)

👉 Produces:

<!-- EVERYTHING inside -->

No dependencies. Zero runtime logic.


---

🚨 One Subtle Gotcha

If your HTML uses:

fetch("schedule.json")

👉 It WILL break on Chrome (file:// restriction)


---

Fix:

Replace with:

const data = {...}; // inline


---

🏁 Final Answer

👉 The cleanest solution is:

> Self-contained HTML + non-Chrome browser




---

🚀 If you want next step

I can generate for you:

✅ A single-file HTML template (ultra-fast)
✅ A Python exporter that embeds JSON into HTML
✅ A minimal Android WebView wrapper APK concept

Just tell me 👍
