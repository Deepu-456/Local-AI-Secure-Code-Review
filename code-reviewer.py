#!/usr/bin/env python3
"""
AI Source Code Review Tool — uses local Ollama models via chat API.
Auto-selects best model based on available RAM.
"""

import argparse
import json
import os
import sys
import time
import fnmatch
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    print("Error: pip install requests"); sys.exit(1)


OLLAMA_URL = "http://localhost:11434"

SUPPORTED = {".py":"Python",".js":"JavaScript",".ts":"TypeScript",
  ".tsx":"TSX",".jsx":"JSX",".go":"Go",".rs":"Rust",".java":"Java",
  ".c":"C",".h":"C",".cpp":"C++",".cc":"C++",".hpp":"C++ Header",
  ".cs":"C#",".rb":"Ruby",".php":"PHP",".swift":"Swift",".kt":"Kotlin",
  ".sh":"Shell",".bash":"Bash",".pl":"Perl",".lua":"Lua",".sql":"SQL",
  ".yaml":"YAML",".yml":"YAML",".json":"JSON",".xml":"XML",
  ".html":"HTML",".css":"CSS",".vue":"Vue",".svelte":"Svelte",
  ".tf":"Terraform",".toml":"TOML",".ini":"INI",
  ".zig":"Zig",".ex":"Elixir",".erl":"Erlang",
  ".groovy":"Groovy",".gradle":"Gradle",
  ".makefile":"Makefile",".cmake":"CMake",
  ".ml":"OCaml",".fs":"F#",".hs":"Haskell"}

IGNORE = [".git","__pycache__","node_modules",".venv","venv","env",
  ".tox","dist","build",".next","target","bin","obj",".gradle",".idea",
  "*.pyc","*.pyo","*.so","*.dll","*.exe","*.class","*.jar",
  "*.zip","*.tar.gz","*.tgz","*.min.js","*.min.css","*.map",
  "*.png","*.jpg","*.gif","*.ico","*.svg",
  "*.pdf","*.doc","*.docx","*.o",".DS_Store","Thumbs.db"]


def mem_avail_kb():
    try:
        for l in open("/proc/meminfo"):
            if l.startswith("MemAvailable:"):
                return int(l.split()[1])
    except: pass
    return 0


def best_model(url):
    try:
        names = [m["name"] for m in requests.get(f"{url}/api/tags", timeout=5).json().get("models",[])]
    except: return "llama3.2:3b"
    mb = mem_avail_kb() / 1024
    for m in ["qwen3:8b","llama3:8b"]:
        if any(m in n for n in names) and mb > 4500: return m
    for m in ["llama3.2:3b","llama3.2:1b"]:
        if any(m in n for n in names): return m
    return names[0] if names else "llama3.2:3b"


def check(url, model):
    try:
        names = [m["name"] for m in requests.get(f"{url}/api/tags", timeout=5).json().get("models",[])]
        if not any(model in m for m in names):
            print(f"Model '{model}' not found. Available: {', '.join(names)}")
            return False
        return True
    except requests.ConnectionError:
        print(f"Cannot reach Ollama at {url}\n  Start: sudo systemctl start ollama")
        return False


def find_files(path, recursive=False):
    files = []
    if not path.is_dir(): return files
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d,p) for p in IGNORE)]
        for n in names:
            if any(fnmatch.fnmatch(n,p) for p in IGNORE): continue
            fp = Path(root) / n
            if fp.suffix.lower() in SUPPORTED: files.append(str(fp))
        if not recursive: break
    return sorted(files)


def review_file(fp, model, url, timeout=180):
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return {"error": str(e)}
    if not content.strip():
        return {"error": "empty file"}

    ext = Path(fp).suffix.lower()
    lang = SUPPORTED.get(ext, ext.lstrip(".").capitalize() or "code")
    lines = content.split("\n")
    nlines = len(lines)

    if nlines <= 300:
        r = _call(fp, content, lang, model, url, timeout)
        return _norm(r, fp, lang, nlines) if r else {"error":"no response"}

    chunks = []
    for i in range(0, nlines, 300):
        ct = "\n".join(lines[i:i+300])
        cn = i//300 + 1
        tt = (nlines + 299)//300
        r = _call(fp, ct, lang, model, url, timeout, cn, tt, nlines)
        if r: chunks.append(r)
    return _merge(fp, chunks, lang, nlines) if chunks else {"error":"no responses"}


def _call(fp, content, lang, model, url, timeout, chunk=1, total=1, all_lines=None):
    n = all_lines or len(content.split("\n"))
    partial = f" (chunk {chunk}/{total})" if total > 1 else ""
    tag = Path(fp).name

    lang_lower = lang.lower()
    sev_hints = {
        "py": "Python: eval/exec, pickle, SQL injection, cmd injection, path traversal, hardcoded secrets",
        "js": "JS: XSS, prototype pollution, innerHTML, eval, insecure crypto, nosql injection",
        "go": "Go: SQL via fmt.Sprintf, unsafe ptr, goroutine leaks, missing error handling",
        "rs": "Rust: unsafe blocks, unwrap, transmute, dangling refs",
        "java": "Java: SQL injection, deserialization, path traversal, hardcoded creds, MD5/SHA1",
        "c": "C: buffer overflow, format string, use-after-free, memory leak, strcpy/strcat",
        "php": "PHP: SQL injection, XSS, LFI/RFI, unserialize, type juggling",
    }
    hint = ""
    for ext, h in sev_hints.items():
        if ext in lang_lower:
            hint = h
            break

    system = (
        "You are an expert code reviewer. Return ONLY valid JSON with no extra text. "
        "JSON structure: "
        '{"issues":[{"severity":"critical|high|medium|low|info",'
        '"type":"bug|security|performance|quality","line":<int line_number>,'
        '"message":"short","detail":"explain","suggestion":"fix"}],'
        '"positives":["good points"],"score":100}. '
        "Score starts 100: critical=-25, high=-15, medium=-8, low=-3, info=-1. "
        "Only report real issues. No false positives. "
        "IMPORTANT: You MUST include the exact line number for every issue. "
        "The line number is REQUIRED, never null."
    )

    user = f"Review this {lang} code for bugs, security flaws, and quality problems{partial}:\n\n"
    if hint:
        user += f"Focus areas: {hint}\n\n"
    user += f"File: {tag} ({n} lines)\n\n"
    user += f"```{lang_lower}\n{content}\n```"

    for attempt in range(3):
        try:
            r = requests.post(f"{url}/api/chat", json={
                "model": model,
                "messages": [{"role":"system","content":system},{"role":"user","content":user}],
                "stream": False,
                "temperature": 0.1,
                "num_predict": 2048,
            }, timeout=timeout)
            if r.status_code == 500:
                time.sleep(5); continue
            r.raise_for_status()
            text = r.json().get("message",{}).get("content","")
            return _parse_json(text)
        except Exception:
            if attempt < 2: time.sleep(3)
            else: return None
    return None


def _parse_json(text):
    text = text.strip()
    for pfx in ["```json","```"]:
        if text.startswith(pfx): text = text.split("\n",1)[-1]
    if text.endswith("```"): text = text.rsplit("```",1)[0]
    text = text.strip()
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a: text = text[a:b+1]
    try:
        d = json.loads(text)
        if isinstance(d, list): d = {"issues":d,"positives":[],"score":50}
        d.setdefault("issues",[]); d.setdefault("positives",[]); d.setdefault("score",50)
        return d
    except: return None


def _extract_snippet(file_path, line_num, context=2):
    """Extract code snippet around a line number for POC evidence."""
    if not line_num: return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        total = len(all_lines)
        # If reported line is blank/import, scan forward for real code
        actual = line_num - 1
        if actual < total:
            raw = all_lines[actual].strip()
            if not raw or raw.startswith(("import ", "from ", "#", "/*", "*")):
                for offset in range(1, min(6, total - actual)):
                    test = all_lines[actual + offset].strip()
                    if test and not test.startswith(("import ", "from ", "#", "/*", "*")):
                        actual = actual + offset
                        break
        start = max(0, actual - context)
        end = min(total, actual + context + 1)
        snippet = ""
        for i in range(start, end):
            prefix = ">>>" if i == actual else "   "
            snippet += f"{prefix} {i+1:4d} | {all_lines[i].rstrip()}\n"
        return {"line": actual + 1, "snippet": snippet.rstrip()}
    except:
        return None


def _norm(r, fp, lang, nlines):
    s = {"critical":0,"high":0,"medium":0,"low":0,"info":0}
    for i in r.get("issues",[]):
        sv = i.get("severity","info").lower()
        if sv in s: s[sv] += 1
        ln = i.get("line")
        if ln:
            snippet = _extract_snippet(fp, ln)
            if snippet:
                i["line"] = snippet["line"]
                i["code"] = snippet["snippet"]
    return {"_file":fp,"_lang":lang,"_lines":nlines,
            "issues":r["issues"],"positives":r["positives"],
            "score":r["score"],"total":len(r["issues"]),**s}


def _merge(fp, chunks, lang, nlines):
    iss, pos, sc = [], [], []
    for c in chunks:
        if c is None: continue
        iss.extend(c.get("issues",[]))
        pos.extend(c.get("positives",[]))
        if c.get("score") is not None: sc.append(c["score"])
    scr = round(sum(sc)/len(sc)) if sc else 50
    s = {"critical":0,"high":0,"medium":0,"low":0,"info":0}
    for i in iss:
        sv = i.get("severity","info").lower()
        if sv in s: s[sv] += 1
        ln = i.get("line")
        if ln:
            snippet = _extract_snippet(fp, ln)
            if snippet:
                i["line"] = snippet["line"]
                i["code"] = snippet["snippet"]
    return {"_file":fp,"_lang":lang,"_lines":nlines,
            "issues":iss,"positives":list(set(pos)),
            "score":scr,"total":len(iss),**s}


def output(results, fmt, model):
    if fmt == "json": return _json(results, model)
    if fmt == "markdown": return _md(results, model)
    if fmt == "html": return _html(results, model)
    return _term(results, model)


def _term(results, model):
    g = {s:0 for s in ["critical","high","medium","low","info"]}
    ti, scs = 0, []
    lines = []
    for fp, r in sorted(results.items()):
        if "error" in r:
            lines.append(f"\n  ERROR {Path(fp).name}: {r['error']}")
            continue
        n = len(r.get("issues",[]))
        ti += n; scs.append(r.get("score",0))
        for s in g: g[s] += r.get(s,0)
        lines.append("")
        s = r.get("score",0)
        lines.append(f"  {'='*60}")
        lines.append(f"  {fp}")
        lines.append(f"  Lang: {r.get('_lang','?')}  |  Score: {s}/100  |  Issues: {n}  "
                     f"(C:{r.get('critical',0)} H:{r.get('high',0)} "
                     f"M:{r.get('medium',0)} L:{r.get('low',0)} I:{r.get('info',0)})")
        lines.append(f"  {'='*60}")
        for i in r.get("issues",[]):
            sv = i.get("severity","info").upper()
            ln = f":{i['line']}" if i.get("line") else ""
            tag = {"CRITICAL":"  !!","HIGH":"  !!" if sv=="HIGH" else False,
                   "MEDIUM":"  ~~","LOW":"  ..","INFO":"    "}.get(sv,"    ")
            lines.append(f"  [{sv:<5}] [{i.get('type','?')}] {i.get('message','?')}{ln}")
            code = i.get("code")
            if code:
                for cl in code.split("\n"):
                    lines.append(f"         {cl}")
        for p in r.get("positives",[]):
            lines.append(f"       + {p}")

    avg = round(sum(scs)/len(scs)) if scs else 0
    summary = [
        "",
        f"  {'='*60}",
        f"  SUMMARY  Model: {model}  Files: {len(results)}",
        f"  Issues: {ti}  C:{g['critical']} H:{g['high']} M:{g['medium']} L:{g['low']} I:{g['info']}",
        f"  Avg score: {avg}/100",
        f"  {'='*60}",
        "",
    ]
    return "\n".join(summary + lines)


def _md(results, model):
    lines = [f"# Code Review Report",
             f"**Model:** `{model}`  |  **Date:** {datetime.now():%Y-%m-%d %H:%M}",
             f"**Files:** {len(results)}", ""]
    g = {s: sum(r.get(s,0) for r in results.values() if "error" not in r)
         for s in ["critical","high","medium","low","info"]}
    lines.append("## Summary")
    lines.append(f"| Severity | Count |")
    lines.append(f"|---|--:|")
    for s in ["critical","high","medium","low","info"]:
        lines.append(f"| {s.capitalize()} | {g[s]} |")
    lines.append("")
    for fp, r in sorted(results.items()):
        if "error" in r:
            lines.append(f"\n## {Path(fp).name}\nError: {r['error']}\n"); continue
        if not r.get("issues") and not r.get("positives"): continue
        lines.append(f"---")
        lines.append(f"## {Path(fp).name}")
        lines.append(f"`{fp}`  |  Score: {r.get('score','?')}/100  |  "
                     f"Issues: C:{r.get('critical',0)} H:{r.get('high',0)}"
                     f" M:{r.get('medium',0)} L:{r.get('low',0)} I:{r.get('info',0)}")
        lines.append("")
        order = {"critical":0,"high":1,"medium":2,"low":3,"info":4}
        for i in sorted(r.get("issues",[]), key=lambda x:order.get(x.get("severity","info"),9)):
            sv = i.get("severity","info")
            icons = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🔵","info":"⚪"}
            ln = f" (line {i['line']})" if i.get("line") else ""
            lines.append(f"### {icons.get(sv,'⚪')} [{sv.upper()}] {i.get('type','general')}{ln}")
            lines.append(f"**{i.get('message','')}**")
            lines.append("")
            if i.get("detail"): lines.append(f"{i['detail']}\n")
            if i.get("suggestion"): lines.append(f"> **Suggestion:** {i['suggestion']}\n")
            code = i.get("code")
            if code:
                lines.append("```python")
                lines.append(code)
                lines.append("```\n")
        for p in r.get("positives",[]): lines.append(f"- ✅ {p}")
        lines.append("")
    return "\n".join(lines)


def _html(results, model):
    md = _md(results, model)
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><title>Code Review Report</title>
<style>
body {{ font:14px/1.6 -apple-system,sans-serif; max-width:960px; margin:2em auto; padding:0 1em; background:#f8f9fa; color:#1a1a2e; }}
h1 {{ color:#16213e; border-bottom:3px solid #0f3460; }} h2 {{ color:#0f3460; }} h3 {{ color:#533483; }}
table {{ border-collapse:collapse; }} th,td {{ border:1px solid #ddd; padding:6px 12px; }} th {{ background:#e8eaf6; }}
code {{ background:#eef; padding:2px 5px; border-radius:3px; }}
blockquote {{ border-left:4px solid #0f3460; margin:0.5em 0; padding:0.5em 1em; background:#f0f4ff; }}
hr {{ border:none; border-top:1px solid #ddd; }}
</style></head><body>
{md}</body></html>"""


def _json(results, model):
    return json.dumps({
        "model":model,"date":datetime.now().isoformat(),"files":len(results),
        "results":{k:v for k,v in sorted(results.items())},
    }, indent=2)


def main():
    ap = argparse.ArgumentParser(
        description="AI Code Review — local Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  code-reviewer.py file.py
  code-reviewer.py src/ -r
  code-reviewer.py a.js b.py -f html -o report.html
  code-reviewer.py . --exclude tests --model llama3.2:3b
""")
    ap.add_argument("paths", nargs="+", metavar="path")
    ap.add_argument("-r","--recursive", action="store_true", help="Scan dirs recursively")
    ap.add_argument("-m","--model", help="Model (default: auto-detect)")
    ap.add_argument("-u","--url", default=OLLAMA_URL, help="Ollama URL")
    ap.add_argument("-f","--format", choices=["terminal","markdown","json","html"], default="terminal")
    ap.add_argument("-o","--output", help="Save report to file")
    ap.add_argument("-t","--timeout", type=int, default=180, help="Timeout per request (s)")
    ap.add_argument("--exclude", nargs="*", default=[], help="Extra ignore patterns")
    ap.add_argument("--workers", type=int, default=2, help="Parallel files")
    ap.add_argument("-q","--quiet", action="store_true")
    args = ap.parse_args()

    for p in args.exclude: IGNORE.append(p)
    url = args.url.rstrip("/")
    model = args.model or best_model(url)

    if not args.quiet:
        print(f"Code Review Tool  model={model}  mem={mem_avail_kb()//1024}MB free")
        print()

    if not check(url, model): sys.exit(1)

    results = {}
    for rp in args.paths:
        p = os.path.abspath(rp)
        if os.path.isfile(p):
            if not args.quiet: print(f"  → {Path(p).name}")
            results[p] = review_file(p, model, url, args.timeout)
        elif os.path.isdir(p):
            files = find_files(Path(p), args.recursive)
            if not files:
                if not args.quiet: print(f"  No supported files in {p}")
                continue
            if not args.quiet: print(f"  Scanning {p} ({len(files)} files)...")
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                fm = {ex.submit(review_file,f,model,url,args.timeout):f for f in files}
                for fut in as_completed(fm):
                    f = fm[fut]
                    try:
                        r = fut.result(); results[f] = r
                        n = len(r.get("issues",[])) if "error" not in r else "ERR"
                        if not args.quiet: print(f"    {Path(f).name}: {n} issues")
                    except Exception as e:
                        results[f] = {"error":str(e)}
                        if not args.quiet: print(f"    {Path(f).name}: ERROR {e}")
        else: print(f"  Not found: {p}")

    if not results: print("Nothing reviewed."); sys.exit(0)

    report = output(results, args.format, model)
    if args.output:
        Path(args.output).write_text(report)
        if not args.quiet: print(f"\n  Saved: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
