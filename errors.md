# Errors Log

Read this file at the start of every session before writing any code.

## Format

`Date | Error | Root cause | Solution`

---

<!-- Add entries below as errors are encountered and resolved -->

**2026-04-28 | anthropic==0.25.0 TypeError: Client.__init__() got an unexpected keyword argument 'proxies'**
Root cause: anthropic==0.25.0 requires httpx<0.25.0 but supabase==2.28.3 requires httpx>=0.26, causing a version conflict. The proxies argument was removed in newer httpx versions.
Solution: upgraded anthropic from 0.25.0 to 0.97.0 which supports httpx>=0.25.0, compatible with supabase's requirements. Updated requirements.txt accordingly.

**2026-05-06 | FutureWarning: sns.boxplot with all-NaN column and pandas 2.2**
Root cause: seaborn internals emit a FutureWarning when sns.boxplot receives a column that is entirely NaN values, triggered by pandas 2.2 internal behavior change. The except block in generate_boxplot catches this safely and returns None without crashing.
Solution: already handled gracefully by the try/except pattern in viz_tools.py. No code change needed. Be aware this warning may appear in logs when datasets have all-NaN numeric columns after cleaning.
