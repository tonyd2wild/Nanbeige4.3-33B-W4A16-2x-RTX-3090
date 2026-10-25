#!/usr/bin/env python3
"""Concurrency sweep bench: c1..c6 x {code,json,prose,math,narrative}.

Per cell: N parallel streamed chat completions (temp 0, 400-token budget).
Reports per-stream median TTFT and decode tok/s, plus aggregate tok/s.
Separate prefill pass: one ~15K-token prompt per type at c1, prefill tok/s =
prompt_tokens / TTFT (upper bound incl. queueing, same metric the lane's older
benches used). Usage:
  python3 bench_exl3_sweep.py [base_url] [model] [out.md]
"""
import json, sys, time, threading, statistics, urllib.request, datetime

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/v1"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen3.8-flash-next"
OUT = sys.argv[3] if len(sys.argv) > 3 else "bench_exl3_results.md"
MAXTOK = 400

PROMPTS = {
    "code": "Write a Python class implementing an LRU cache with O(1) get/put using a doubly linked list and dict. Include type hints and a small usage example.",
    "json": "Produce a JSON object describing a fictional e-commerce order: 6 line items (sku, name, qty, unit_price), shipping address, totals with tax breakdown, and an ISO-8601 timestamp. JSON only, no prose.",
    "prose": "Explain how tensor parallelism and expert parallelism differ when serving a large mixture-of-experts language model, for a technically literate reader. Flowing prose, no lists.",
    "math": "A tank holds 2400 L. Pipe A fills at 40 L/min, pipe B fills at 60 L/min, and drain C empties at 25 L/min. A opens at t=0, B at t=10 min, C at t=20 min. Work through, step by step, exactly when the tank is full.",
    "narrative": "Write the opening scene of a mystery novel set in a data center at 3 a.m.: a night-shift engineer notices one rack's fans spin down moments before the badge-access logs delete themselves. Atmospheric, third person.",
}

def one_stream(ptype, idx, results):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPTS[ptype] + f"\n(variant {idx})"}],
        "max_tokens": MAXTOK, "temperature": 0, "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(BASE + "/chat/completions", body, {"Content-Type": "application/json"})
    t0 = time.time(); ttft = None; tlast = None; ntok = None; ptok = None
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            for line in resp:
                if not line.startswith(b"data:"): continue
                payload = line[5:].strip()
                if payload == b"[DONE]": break
                d = json.loads(payload)
                if d.get("usage"):
                    ntok = d["usage"].get("completion_tokens"); ptok = d["usage"].get("prompt_tokens")
                ch = d.get("choices") or []
                if ch and (ch[0].get("delta") or {}).get("content"):
                    now = time.time()
                    if ttft is None: ttft = now - t0
                    tlast = now
    except Exception as e:
        results.append({"err": str(e)[:120]}); return
    if ttft is None or ntok is None or tlast is None or tlast <= t0 + ttft:
        results.append({"err": "no usable stream timing"}); return
    results.append({"ttft": ttft, "decode": (ntok - 1) / (tlast - (t0 + ttft)), "ntok": ntok, "ptok": ptok, "wall": tlast - t0})

def cell(ptype, conc):
    results, threads = [], []
    t0 = time.time()
    for i in range(conc):
        th = threading.Thread(target=one_stream, args=(ptype, i, results)); th.start(); threads.append(th)
    for th in threads: th.join()
    wall = time.time() - t0
    ok = [r for r in results if "err" not in r]
    errs = [r["err"] for r in results if "err" in r]
    if not ok: return {"err": "; ".join(errs[:2]) or "all failed"}
    return {
        "ttft_med": statistics.median(r["ttft"] for r in ok),
        "decode_med": statistics.median(r["decode"] for r in ok),
        "agg": sum(r["ntok"] for r in ok) / wall,
        "n_ok": len(ok), "n_err": len(errs),
    }

def prefill_test(ptype):
    filler = ("The quarterly engineering review covered capacity planning, incident retrospectives, "
              "and the migration roadmap in considerable detail. ") * 850  # ~15-16K tokens
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": filler + "\n\nNow: " + PROMPTS[ptype]}],
        "max_tokens": 32, "temperature": 0, "stream": True, "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(BASE + "/chat/completions", body, {"Content-Type": "application/json"})
    t0 = time.time(); ttft = None; ptok = None
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            for line in resp:
                if not line.startswith(b"data:"): continue
                payload = line[5:].strip()
                if payload == b"[DONE]": break
                d = json.loads(payload)
                if d.get("usage"): ptok = d["usage"].get("prompt_tokens")
                ch = d.get("choices") or []
                if ch and (ch[0].get("delta") or {}).get("content") and ttft is None:
                    ttft = time.time() - t0
    except Exception as e:
        return {"err": str(e)[:120]}
    if ttft is None or not ptok: return {"err": "no timing"}
    return {"ptok": ptok, "ttft": ttft, "prefill": ptok / ttft}

def main():
    print(f"bench vs {BASE} model={MODEL} @ {datetime.datetime.now():%Y-%m-%d %H:%M}")
    # warmup
    r = []; one_stream("prose", 999, r)
    print("warmup:", r[0] if r else "?")
    lines = [f"# Nanbeige int4 bench - {MODEL} @ {BASE}", f"Date: {datetime.datetime.now():%Y-%m-%d %H:%M} · temp 0 · {MAXTOK}-token budget · streamed",
             "", "## Decode / TTFT sweep (per-stream medians; agg = cell total tok/s)", ""]
    header = "| type | " + " | ".join(f"c{c}" for c in range(1, 7)) + " |"
    lines += [header, "|---" * 7 + "|"]
    for ptype in PROMPTS:
        row = [ptype]
        for c in range(1, 7):
            res = cell(ptype, c)
            if "err" in res:
                row.append("ERR"); print(f"{ptype} c{c}: ERROR {res['err']}")
            else:
                row.append(f"{res['decode_med']:.1f} t/s · ttft {res['ttft_med']:.2f}s · agg {res['agg']:.0f}")
                print(f"{ptype} c{c}: decode {res['decode_med']:.1f} tok/s  ttft {res['ttft_med']:.2f}s  agg {res['agg']:.0f} tok/s  ok={res['n_ok']} err={res['n_err']}")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Prefill (~15K-token prompt, c1; prefill = prompt_tokens / TTFT)", "", "| type | prompt tok | TTFT | prefill tok/s |", "|---|---|---|---|"]
    for ptype in PROMPTS:
        res = prefill_test(ptype)
        if "err" in res:
            lines.append(f"| {ptype} | ERR | - | - |"); print(f"prefill {ptype}: ERROR {res['err']}")
        else:
            lines.append(f"| {ptype} | {res['ptok']} | {res['ttft']:.2f}s | {res['prefill']:.0f} |")
            print(f"prefill {ptype}: {res['ptok']} tok in {res['ttft']:.2f}s = {res['prefill']:.0f} tok/s")
    with open(OUT, "w") as f: f.write("\n".join(lines) + "\n")
    print("wrote", OUT)

if __name__ == "__main__":
    main()
