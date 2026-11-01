"""Extract per-turn component (tool) usage from a harness trace_*.json.

Each trace turn carries `steps[]`, each step = {tool, tool_input_args, tool_output,
agent_thought, skill_calls}. This classifies every tool call into a KIND so a report
can show WHICH components were called on each turn — in particular, whether a
memory-probe turn was answered purely from working memory (no retrieval) or by
re-invoking a retrieval component (DB query / file read).

Usage:
    python extract_components.py --trace <trace_*.json> --out <components.json>

Output schema (also returned by extract()):
{
  "turns": [
    {"n": 1, "n_steps": 10, "skill_calls": 0,
     "kinds": {"retrieval": 7, "compute": 2, "mutate": 1},
     "tools": [{"tool": "read_file", "kind": "retrieval"}, ...],
     "recall_mode": "re-retrieved"|"pure recall (no tools)"|"recall + action (no re-retrieval)"}
  ]
}

KIND taxonomy (documented in SKILL.md):
  retrieval  — reads state: read_file/grep/search/list_dir, or a terminal command that
               queries data (select/sqlite/.db/.load()/pragma/fetch/get_/cat/head/read)
  mutate     — changes state: write/edit/apply_patch, or a terminal command that writes
               (update/insert/cancel/book/delete/save/commit/patch)
  compute    — any other terminal command (install, calc, generic python)
  other      — anything else
"""
import argparse, glob, json, os, re, sys
from collections import Counter

_RETRIEVE_CMD = re.compile(
    r"\bselect\b|sqlite3|\.db\b|\.load\(\)|pragma|fetchone|fetchall|get_[a-z_]+|\bcat \b|\bhead \b|\bread\b|grep", re.I)
_MUTATE_CMD = re.compile(r"\bupdate\b|\binsert\b|cancel|book|\bwrite\b|delete|\bsave\b|commit|apply_patch|\bpatch\b", re.I)
# read-state tools across harnesses (grok/goose/mistral-vibe/kilocode)
_RETRIEVE_TOOLS = {"read_file", "grep", "codebase_search", "list_dir", "glob_file_search", "search",
                   "read", "glob", "file_system.read_file", "search_tool_functions"}
# write-state tools across harnesses
_MUTATE_TOOLS = {"write", "edit_file", "apply_patch", "create_file", "delete_file",
                 "edit", "search_replace", "file_system.write"}
# terminal / shell tools whose kind depends on the command text
_TERMINAL_TOOLS = {"run_terminal_command", "shell", "bash", "file_system.bash", "execute_command"}
# skill-loading / planning scaffolding tools -> "other" (not a data component)
_OTHER_TOOLS = {"load_skill", "skill", "skill.read", "todo_write", "todowrite", "vibe.todo", "todo"}


def classify(tool, args):
    a = " ".join(str(x.get("value", "")) for x in (args or [])).lower()
    if tool in _OTHER_TOOLS:
        return "other"
    if tool in _RETRIEVE_TOOLS:
        return "retrieval"
    if tool in _MUTATE_TOOLS:
        return "mutate"
    if tool in _TERMINAL_TOOLS:
        # order matters: a write command wins over an incidental read token
        if _MUTATE_CMD.search(a):
            return "mutate"
        if _RETRIEVE_CMD.search(a):
            return "retrieval"
        return "compute"
    return "other"


def recall_mode(kinds, n_steps):
    if n_steps == 0:
        return "pure recall (no tools)"
    if kinds.get("retrieval", 0) == 0:
        return "recall + action (no re-retrieval)"
    return f"re-retrieved ({kinds['retrieval']} retrieval call{'s' if kinds['retrieval'] != 1 else ''})"


def extract(trace_path):
    d = json.load(open(trace_path))
    out = []
    for i, t in enumerate(d["turns"]):
        steps = t.get("steps") or []
        tools = [{"tool": s.get("tool"), "kind": classify(s.get("tool"), s.get("tool_input_args"))}
                 for s in steps]
        kinds = dict(Counter(x["kind"] for x in tools))
        sk = sum(len(s.get("skill_calls") or []) for s in steps)
        out.append({
            "n": i + 1,
            "n_steps": len(steps),
            "skill_calls": sk,
            "kinds": kinds,
            "tools": tools,
            "recall_mode": recall_mode(kinds, len(steps)),
        })
    return {"turns": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", required=True, help="path to trace_*.json (or a glob/dir)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    tp = args.trace
    if os.path.isdir(tp):
        tp = glob.glob(os.path.join(tp, "trace_*.json"))[0]
    elif "*" in tp:
        tp = glob.glob(tp)[0]
    res = extract(tp)
    json.dump(res, open(args.out, "w"), indent=1, ensure_ascii=False)
    print(f"✓ {args.out}: {len(res['turns'])} turns")


if __name__ == "__main__":
    main()
