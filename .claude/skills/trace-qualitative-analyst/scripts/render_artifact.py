#!/usr/bin/env python3
"""
render_artifact.py
==================

Take an annotated trajectory JSON and produce the final interactive HTML
artifact. The annotation step (assigning quote-grounded codebook tags to each
thought) is done by Claude beforehand; this script handles everything else
deterministically: validation, pie-chart generation, template fill-in, output.

USAGE
-----

    python render_artifact.py <annotated.json> [--output <path>]

If --output is not given, writes to ./<instance_id>-trajectory-analysis.html
in the current directory.

INPUT JSON SCHEMA
-----------------

{
  "instance_id": "pylint-dev/pylint-5859",     # required
  "model": "SWE-agent w/ GPT-4 Turbo",         # required
  "outcome": "resolved" | "unresolved",        # required
  "issue_text": "...full issue body...",       # required, plain text
  "summary": "...4-8 sentence narrative...",   # required, may contain inline HTML
  "quote_target": "thought" | "action",        # optional, default "thought"
                                               # "thought": quotes are substrings of t.thought
                                               #            (SWE-agent style — annotate reasoning)
                                               # "action":  quotes are substrings of t.action
                                               #            (multi-agent dialog style — annotate
                                               #            the action surface only: code lines,
                                               #            output tokens, protocol prose)
                                               # "both":    each quote carries its own "target"
                                               #            ("thought" | "action") naming the host
                                               #            field; both blocks render with their
                                               #            respective highlights (Planner-Executor
                                               #            hybrids, HyperAgent, etc.)
  "findings": [                                # optional, 0-4 items
    {"title": "...", "body": "..."},
    ...
  ],
  "segments": [                                # optional, 0-N narrative sub-sequences
    {"start": 1, "end": 5,                     #   inclusive turn-n bounds
     "title": "First investigation cycle",     #   short label (optional)
     "summary": "Localize → reproduce → ..."   #   1-3 sentence prose, inline HTML allowed
                                               #   (rendered in the right panel only)
    },
    ...
  ],
  "turns": [
    {
      "n": 1,                                  # turn number, 1-indexed
      "phase": "reproduce",                    # one of: reproduce | localize |
                                               #   edit | recover | verify |
                                               #   submit | other
      "phase_label": "Reproduction",           # display label for the phase pill
      "headline": "Create the empty test file.",   # one-line summary
      "obs": "...",                            # observation text
      "thought": "...",                        # VERBATIM thought from trajectory.
                                               # In quote_target="action" mode, this is
                                               # context-only (rendered without highlights).
      "action": "create test.py",              # action / command. In quote_target="action"
                                               # mode this should be the VERBATIM action
                                               # surface (multi-line code blocks, stdout
                                               # tokens, protocol message), not a one-line
                                               # summary, since quotes match against it.
      "quotes": [                              # quote-grounded annotations
        {
          "quote": "first try to replicate the bug",  # MUST be a substring of the host field
                                                      # (thought OR action, per quote_target)
          "grp":   "Planning",                        # one of the 10 groups
          "sub":   "Decompose a task into subtasks",
          "leaf":  "Subgoal with executable success-condition"
        },
        ...
      ],
      "insight": "..."                         # optional, displayed as callout
    },
    ...
  ]
}

The renderer validates that every quote is actually a substring of its host
field (thought or action, depending on quote_target); if not, it prints a
warning and the quote will simply not be highlighted (but the annotation row
will still appear).
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

# ============ GROUP COLOUR PALETTE ============
# Must match the CSS variables in the template.
# 10-category v4.2 codebook (3-level hierarchy: action → sub-action → leaf, aligned with arXiv:2605.13625v1).
GROUP_COLOURS = {
    "Retrieval":  "#6b5b3a",
    "Memory":     "#6a5a3a",
    "Planning":   "#2d4a6a",
    "Reasoning":  "#5b4a8a",
    "Evaluate":   "#1a5878",
    "Deciding":   "#4a4a5a",
    "Grounding":  "#8a4a6a",
    "Executing":  "#2d5a3d",
    "Learning":   "#8a3a4a",
    "Reflection": "#b8451a",
}

# Group keys are now their own display names; no rewriting needed.
GROUP_DISPLAY_NAMES = {}

VALID_PHASES = {"reproduce", "localize", "edit", "recover", "verify", "submit", "other"}
VALID_QUOTE_TARGETS = {"thought", "action", "both"}

# ============ VALIDATION ============

def validate_data(data):
    """Validate the input JSON structure. Raises ValueError on missing fields."""
    required_top = ["instance_id", "model", "outcome", "issue_text", "summary", "turns"]
    for field in required_top:
        if field not in data:
            raise ValueError(f"Missing required top-level field: {field}")

    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise ValueError("summary must be a non-empty string (4-8 sentence narrative of the run)")

    if data["outcome"] not in ("resolved", "unresolved"):
        raise ValueError(f"outcome must be 'resolved' or 'unresolved', got: {data['outcome']}")

    if not isinstance(data["turns"], list) or len(data["turns"]) == 0:
        raise ValueError("turns must be a non-empty list")

    # quote_target defaults to "thought" for backwards compatibility
    quote_target = data.get("quote_target", "thought")
    if quote_target not in VALID_QUOTE_TARGETS:
        raise ValueError(
            f"quote_target must be one of {sorted(VALID_QUOTE_TARGETS)}, got: {quote_target!r}"
        )
    data["quote_target"] = quote_target  # normalise

    warnings = []
    for i, t in enumerate(data["turns"]):
        for f in ("n", "obs", "thought", "action"):
            if f not in t:
                raise ValueError(f"Turn {i}: missing field '{f}'")

        # quotes is optional but must validate if present
        if "quotes" not in t:
            t["quotes"] = []

        # phase defaulting
        if "phase" not in t:
            t["phase"] = "other"
        if t["phase"] not in VALID_PHASES:
            warnings.append(f"Turn {t['n']}: unknown phase '{t['phase']}' — using 'other'")
            t["phase"] = "other"
        if "phase_label" not in t:
            t["phase_label"] = "Step"

        # validate each quote is actually in the host field (thought or action).
        # In "both" mode, each quote carries its own target field that picks the host.
        for j, q in enumerate(t["quotes"]):
            for f in ("quote", "grp", "sub", "leaf"):
                if f not in q:
                    raise ValueError(f"Turn {t['n']}, quote {j}: missing field '{f}'")
            if q["grp"] not in GROUP_COLOURS:
                warnings.append(f"Turn {t['n']}, quote {j}: unknown group '{q['grp']}'")

            if quote_target == "both":
                q_target = q.get("target", "action")
                if q_target not in ("thought", "action"):
                    warnings.append(
                        f"Turn {t['n']}, quote {j}: invalid target {q_target!r}; "
                        "must be 'thought' or 'action' in both-mode"
                    )
                    q_target = "action"
                q["target"] = q_target  # normalise
                host_field = q_target
            else:
                host_field = quote_target  # "thought" | "action"
            host_text = t[host_field]
            if q["quote"] not in host_text:
                warnings.append(
                    f"Turn {t['n']}, quote {j}: quote not found in {host_field} verbatim. "
                    f"Quote: {q['quote'][:60]!r}"
                )

    return warnings


# ============ BAR CHART (SVG) ============

def make_bar_chart(group_counts, total, width=300):
    """
    Build a horizontal SVG bar chart, one bar per codebook group, ordered
    descending by count.

    Returns (svg_string, summary_html). The summary_html slot carries a
    one-line total ("N tags across G groups") and is shown above the bars
    in place of the legend (bars carry the per-group info themselves).

    Each bar is wrapped in a <g class="pie-slice" data-grp="..."> so the
    existing template CSS hover state and JS click handler keep working
    without modification.

    group_counts: list of (group_name, count) sorted descending by count
    total: sum of all counts
    """
    if total == 0:
        return ('<div style="color: var(--ink-mute); font-style: italic;">No annotations to chart.</div>',
                '')

    nonzero = [(g, c) for g, c in group_counts if c > 0]
    if not nonzero:
        return ('', '')

    # Layout
    row_h = 22                      # vertical pitch per bar
    label_w = 96                    # right-aligned group label column
    count_w = 28                    # right-aligned count column
    gap = 6                         # padding between label/bar and bar/count
    bar_x = label_w + gap
    bar_max_w = width - label_w - count_w - 2 * gap
    top_pad = 4
    bottom_pad = 4
    height = top_pad + row_h * len(nonzero) + bottom_pad

    max_count = max(c for _, c in nonzero)

    rows_svg = []
    for i, (grp_name, count) in enumerate(nonzero):
        y = top_pad + i * row_h
        bar_y = y + 5
        bar_h = row_h - 10
        bar_w = (count / max_count) * bar_max_w
        frac_overall = count / total
        colour = GROUP_COLOURS.get(grp_name, "#888")
        display = GROUP_DISPLAY_NAMES.get(grp_name, grp_name)
        rows_svg.append(
            f'<g class="pie-slice" data-grp="{grp_name}" style="cursor: pointer;">'
            f'<title>{display}: {count} ({frac_overall*100:.0f}%)</title>'
            # transparent hit-rect spanning the full row so the whole row is clickable
            f'<rect x="0" y="{y}" width="{width}" height="{row_h}" fill="transparent"/>'
            # group name, right-aligned in the label column
            f'<text x="{label_w}" y="{y + row_h/2 + 3.5}" text-anchor="end" '
            f'font-family="Inter, sans-serif" font-size="11" font-weight="500" fill="#1a1a1a">{display}</text>'
            # bar track (light) + filled bar (group colour)
            f'<rect x="{bar_x}" y="{bar_y}" width="{bar_max_w:.1f}" height="{bar_h}" fill="#efefef" rx="2"/>'
            f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w:.1f}" height="{bar_h}" fill="{colour}" rx="2"/>'
            # count, right-aligned at the far right
            f'<text x="{width - 2}" y="{y + row_h/2 + 3.5}" text-anchor="end" '
            f'font-family="JetBrains Mono, monospace" font-size="10" fill="#888888">{count}</text>'
            f'</g>'
        )

    svg = (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display: block; margin: 0 auto;">'
        f'{"".join(rows_svg)}'
        f'</svg>'
    )

    # Header line in place of the old legend block: total count + group count
    summary_html = (
        f'<div style="font-family: \'JetBrains Mono\', monospace; font-size: 10px; '
        f'color: var(--ink-mute); letter-spacing: 0.08em; text-transform: uppercase; '
        f'text-align: center; margin-bottom: 10px;">'
        f'{total} tags across {len(nonzero)} groups'
        f'</div>'
    )
    return svg, summary_html


def aggregate_groups(turns):
    """Count quotes per group, return list sorted descending by count."""
    counts = {}
    for t in turns:
        for q in t.get("quotes", []):
            counts[q["grp"]] = counts.get(q["grp"], 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


# ============ FINDINGS HTML ============

def render_findings(findings):
    if not findings:
        # default catch-all if user provided no findings
        return (
            '<div class="finding"><strong>No findings provided</strong>'
            '<span>Add a "findings" array to the input JSON to populate this section.</span></div>'
        )
    rows = []
    for f in findings:
        title = escape_html(f.get("title", ""))
        body = f.get("body", "")  # body may contain inline <em> or <strong>; pass through
        rows.append(f'<div class="finding"><strong>{title}</strong><span>{body}</span></div>')
    return "".join(rows)


# ============ HELPERS ============

def escape_html(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def turns_to_js_payload(turns):
    """
    Convert turns into the exact JS-side shape:
      [{ n, phase, phaseLabel, headline, obs, thought, action, quotes: [...], insight }]
    """
    out = []
    for t in turns:
        out.append({
            "n": t["n"],
            "phase": t.get("phase", "other"),
            "phaseLabel": t.get("phase_label", "Step"),
            "headline": t.get("headline", ""),
            "obs": t["obs"],
            "thought": t["thought"],
            "action": t["action"],
            "quotes": t.get("quotes", []),
            "insight": t.get("insight", ""),
        })
    return out


def render_memory_queries(mq, turns_by_n=None):
    """Render the 'How the harness reacted to memory queries' section.

    `mq` is an optional dict: {title?, overview?, items:[...]}. Each item:
      trap_id, inserted_after_turn?, query (the memory check text),
      expected (list of tokens)?, reaction ("PASS"|"FAIL"),
      behavior (e.g. "COMPLY"|"REFLECT+FIX"|"DETECT+REJECT"|"IGNORE")?,
      source_turn?, probe_turn?, components_at_probe?, recall_mode?, why?.
    When `turns_by_n` is given, the probe turn's codebook quotes are joined in as
    a 'Cognitive moves @ probe' column — fusing memory-handling with the annotation.
    Returns "" when absent/empty so the section is simply omitted.
    """
    turns_by_n = turns_by_n or {}
    if not mq:
        return ""
    items = mq.get("items") or []
    if not items:
        return ""
    title = escape_html(mq.get("title", "How the harness reacted to memory queries"))
    overview = mq.get("overview", "")
    n_pass = sum(1 for it in items if str(it.get("reaction", "")).upper() == "PASS")
    # aggregate codebook groups over the distinct probe turns
    probe_ns = sorted({it.get("probe_turn") for it in items if it.get("probe_turn")})
    probe_grp = Counter()
    for n in probe_ns:
        for q in (turns_by_n.get(n, {}).get("quotes") or []):
            probe_grp[q.get("grp")] += 1
    rows = []
    for i, it in enumerate(items):
        reaction = str(it.get("reaction", "")).upper()
        pill_bg = "#2d5a3d" if reaction == "PASS" else "#8a2d2d"
        pill_txt = "credited ✓" if reaction == "PASS" else "not credited ✗"
        beh = it.get("behavior", "")
        beh_html = (f'<span style="display:inline-block;padding:1px 6px;border-radius:4px;'
                    f'background:#2d2d38;color:#d8d2c2;font-size:11px;font-weight:600;'
                    f'letter-spacing:.3px">{escape_html(beh)}</span>') if beh else ""
        exp = it.get("expected") or []
        exp_html = " ".join(
            f'<code style="background:#201d28;color:#b8a888;padding:0 4px;border-radius:3px;'
            f'font-size:11px">{escape_html(str(e))}</code>' for e in exp)
        after = it.get("inserted_after_turn")
        aturn = it.get("agent_turn")
        loc = []
        if after is not None:
            loc.append(f"after T{escape_html(str(after))}")
        if aturn is not None:
            loc.append(f"surfaced T{escape_html(str(aturn))}")
        loc_html = (" · ".join(loc))
        evidence = escape_html(it.get("agent_evidence", ""))
        why = escape_html(it.get("why", ""))
        trap = escape_html(str(it.get("trap_id", "")))
        probe_html = _probe_cell(it)
        pt = it.get("probe_turn")
        moves_html = _codebook_chips((turns_by_n.get(pt, {}).get("quotes") if pt else None))
        rows.append(f"""
        <tr style="border-top:1px solid #2a2730;vertical-align:top">
          <td style="padding:7px 8px;color:#8a8478;font-size:11px;white-space:nowrap">{i+1}. <strong style="color:#b8a888">{trap}</strong><br><span style="font-size:10px">{loc_html}</span></td>
          <td style="padding:7px 8px;font-size:12.5px;color:#d8d2c2">{escape_html(it.get('query',''))}{('<br>'+exp_html) if exp_html else ''}</td>
          <td style="padding:7px 8px;white-space:nowrap"><span style="display:inline-block;padding:1px 7px;border-radius:4px;background:{pill_bg};color:#fff;font-size:11px;font-weight:600">{pill_txt}</span>{('<br>'+beh_html) if beh_html else ''}</td>
          <td style="padding:7px 8px">{probe_html}</td>
          <td style="padding:7px 8px">{moves_html}</td>
          <td style="padding:7px 8px;font-size:12px;color:#aba596">{('<em style=\"color:#8a8478\">agent:</em> '+evidence) if evidence else ''}{('<br><em style=\"color:#8a8478\">validator:</em> '+why) if why else ''}</td>
        </tr>""")
    overview_html = (f'<div style="color:#aba596;font-size:12.5px;margin:4px 0 6px">'
                     f'{escape_html(overview)}</div>') if overview else ""
    agg_html = ""
    if probe_grp:
        chips = "".join(
            f'<span style="display:inline-block;padding:1px 7px;border-radius:4px;background:{GROUP_COLOURS.get(g,"#4a4a5a")};'
            f'color:#fff;font-size:10.5px;margin:1px 3px 1px 0">{escape_html(g)}×{c}</span>'
            for g, c in probe_grp.most_common())
        agg_html = (f'<div style="margin:2px 0 10px;font-size:11.5px;color:#8a8478">'
                    f'Codebook moves concentrated on the {len(probe_ns)} probe turn(s): {chips}</div>')
    return f"""
<div class="section-label">memory-query reactions · {n_pass}/{len(items)} credited</div>
<div style="background:#16141c;border:1px solid #2a2730;border-radius:8px;padding:12px 14px;margin-bottom:18px">
  <div style="font-weight:700;color:#e8e2d2;font-size:14px;margin-bottom:2px">{title}</div>
  {overview_html}{agg_html}
  <table style="width:100%;border-collapse:collapse">
    <thead><tr style="text-align:left;color:#8a8478;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px">
      <th style="padding:4px 8px">Trap / position</th><th style="padding:4px 8px">Memory query &amp; expected tokens</th><th style="padding:4px 8px">Harness reaction</th><th style="padding:4px 8px">Components @ probe</th><th style="padding:4px 8px">Cognitive moves @ probe</th><th style="padding:4px 8px">Evidence</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""


def _codebook_chips(quotes):
    """Colored chips for a turn's codebook quotes (Group · Subgroup, leaf in tooltip)."""
    if not quotes:
        return '<span style="color:#8a8478;font-size:11px">—</span>'
    chips = []
    for q in quotes:
        grp = q.get("grp", "")
        c = GROUP_COLOURS.get(grp, "#4a4a5a")
        tip = escape_html(f'{grp} › {q.get("sub","")} › {q.get("leaf","")}')
        chips.append(f'<span title="{tip}" style="display:inline-block;padding:1px 6px;border-radius:4px;'
                     f'background:{c};color:#fff;font-size:10.5px;margin:1px 2px 1px 0">'
                     f'<strong style="font-variant:small-caps">{escape_html(grp)}</strong>'
                     f'<span style="opacity:.85"> · {escape_html(q.get("sub",""))}</span></span>')
    return "".join(chips)


# Component-kind → colour (shared by probe cells and the component timeline)
KIND_COLORS = {
    "retrieval": "#6b5b3a", "mutate": "#8a3a4a", "compute": "#2d4a6a",
    "other": "#4a4a5a", "skill": "#6a5a3a",
}


def _kind_chips(kinds, skill_calls=0):
    chips = []
    for k, n in sorted((kinds or {}).items(), key=lambda kv: -kv[1]):
        c = KIND_COLORS.get(k, "#4a4a5a")
        chips.append(f'<span style="display:inline-block;padding:1px 6px;border-radius:4px;'
                     f'background:{c};color:#fff;font-size:10.5px;margin:1px 2px 1px 0">{escape_html(k)}×{n}</span>')
    if skill_calls:
        chips.append(f'<span style="display:inline-block;padding:1px 6px;border-radius:4px;'
                     f'background:{KIND_COLORS["skill"]};color:#fff;font-size:10.5px;margin:1px 2px 1px 0">skill×{skill_calls}</span>')
    return "".join(chips) or '<span style="color:#8a8478;font-size:11px">—</span>'


def _probe_cell(it):
    """Render the 'Components @ probe' cell for one memory-query item."""
    pt = it.get("probe_turn")
    src = it.get("source_turn")
    rm = it.get("recall_mode", "")
    kinds = it.get("components_at_probe")
    if pt is None and not rm and not kinds:
        return '<span style="color:#8a8478;font-size:11px">—</span>'
    # recall-mode pill colour: green = genuine memory, olive = re-retrieved
    is_recall = rm.startswith("pure recall") or rm.startswith("recall + action")
    rm_bg = "#2d5a3d" if is_recall else "#6b5b3a"
    if pt is not None and src is not None:
        head = f'<span style="color:#8a8478;font-size:11px">T{escape_html(str(src))}→T{escape_html(str(pt))}</span> '
    elif pt is not None:
        head = f'<span style="color:#8a8478;font-size:11px">T{escape_html(str(pt))}</span> '
    else:
        head = ""
    rm_html = (f'<span style="display:inline-block;padding:1px 6px;border-radius:4px;background:{rm_bg};'
               f'color:#fff;font-size:10.5px;font-weight:600">{escape_html(rm)}</span>') if rm else ""
    chips = f'<div style="margin-top:3px">{_kind_chips(kinds)}</div>' if kinds else ""
    return f"{head}{rm_html}{chips}"


def render_component_timeline(ct, turns_by_n=None):
    """Render a compact per-turn component-call timeline.

    `ct` is an optional dict {title?, overview?, turns:[{n, probe?, label?, kinds, skill_calls?,
    recall_mode?, note?}]}. Memory-probe turns are flagged. When `turns_by_n` is given, each
    row also shows that turn's codebook moves — fusing components with the annotation.
    Returns "" when absent.
    """
    turns_by_n = turns_by_n or {}
    if not ct:
        return ""
    turns = ct.get("turns") or []
    if not turns:
        return ""
    title = escape_html(ct.get("title", "Component-call timeline (before / at / after memory probes)"))
    overview = ct.get("overview", "")
    rows = []
    for t in turns:
        probe = bool(t.get("probe"))
        flag = ('<span style="display:inline-block;padding:0 6px;border-radius:4px;background:#8a4a6a;'
                'color:#fff;font-size:10px;font-weight:700;letter-spacing:.4px">MEMORY&nbsp;PROBE</span>') if probe else ""
        rm = t.get("recall_mode", "")
        rm_html = f'<span style="color:#aba596;font-size:11px">{escape_html(rm)}</span>' if (probe and rm) else ""
        note = f'<span style="color:#8a8478;font-size:11px"> · {escape_html(t.get("note",""))}</span>' if t.get("note") else ""
        bg = "#1b1622" if probe else "transparent"
        moves = _codebook_chips(turns_by_n.get(t.get("n"), {}).get("quotes"))
        rows.append(f"""
        <tr style="border-top:1px solid #241f2b;background:{bg};vertical-align:top">
          <td style="padding:5px 8px;color:#b8a888;font-size:11px;white-space:nowrap;font-weight:600">T{t.get('n')}</td>
          <td style="padding:5px 8px;white-space:nowrap">{flag}</td>
          <td style="padding:5px 8px">{_kind_chips(t.get('kinds'), t.get('skill_calls',0))}</td>
          <td style="padding:5px 8px">{moves}</td>
          <td style="padding:5px 8px">{rm_html}{note}</td>
        </tr>""")
    overview_html = (f'<div style="color:#aba596;font-size:12.5px;margin:4px 0 10px">{escape_html(overview)}</div>'
                     if overview else "")
    return f"""
<div class="section-label">component-call timeline</div>
<div style="background:#16141c;border:1px solid #2a2730;border-radius:8px;padding:12px 14px;margin-bottom:18px">
  <div style="font-weight:700;color:#e8e2d2;font-size:14px;margin-bottom:2px">{title}</div>
  {overview_html}
  <table style="width:100%;border-collapse:collapse">
    <thead><tr style="text-align:left;color:#8a8478;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px">
      <th style="padding:4px 8px">Turn</th><th style="padding:4px 8px"></th><th style="padding:4px 8px">Components called</th><th style="padding:4px 8px">Cognitive moves</th><th style="padding:4px 8px">Recall mode / note</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""


# ============ MAIN ============
def main():
    parser = argparse.ArgumentParser(description="Render an annotated SWE-agent trajectory into an interactive HTML artifact.")
    parser.add_argument("input_json", type=Path, help="Path to annotated trajectory JSON")
    parser.add_argument("--output", type=Path, default=None, help="Output HTML path")
    parser.add_argument("--template", type=Path, default=None, help="Override template path (default: assets/template.html next to this script)")
    args = parser.parse_args()

    # Locate template
    if args.template:
        template_path = args.template
    else:
        template_path = Path(__file__).parent.parent / "assets" / "template.html"
    if not template_path.exists():
        print(f"ERROR: template not found at {template_path}", file=sys.stderr)
        sys.exit(1)

    # Load and validate input
    with open(args.input_json) as f:
        data = json.load(f)

    warnings = validate_data(data)
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)

    # Aggregate
    group_counts = aggregate_groups(data["turns"])
    total_annot = sum(c for _, c in group_counts)

    # Bar chart + summary header
    pie_svg, pie_legend = make_bar_chart(group_counts, total_annot)

    # Findings
    findings_html = render_findings(data.get("findings", []))

    # map turn number -> turn, for joining codebook quotes into the memory sections
    _turns_by_n = {t["n"]: t for t in data["turns"]}

    # JS payload
    turns_js = turns_to_js_payload(data["turns"])

    # Outcome label
    outcome_class = data["outcome"]  # "resolved" | "unresolved"
    outcome_label = "RESOLVED ✓" if outcome_class == "resolved" else "UNRESOLVED ✗"

    # Method note copy varies by quote_target — when annotating action surface,
    # the reading instructions need to point readers at the action block.
    if data["quote_target"] == "action":
        method_note_html = (
            "<strong>How to read this.</strong> Each turn shows the verbatim "
            "<em>action surface</em> — the actual code, output token, or peer "
            "message the agent emitted — with codebook tags grounded to specific "
            "quoted phrases inside it. Underlined phrases inside the <em>Action</em> "
            "block (not the Thought block) are <em>linguistic evidence</em> for a "
            "codebook label; the surrounding Thought is shown as context only. "
            "Below each action, the annotation table reads <code>\"quote\" → Group › "
            "Subgroup › Action</code>, one row per phrase. Click any phrase, any row, "
            "or any codebook entry — they highlight bidirectionally without scrolling."
        )
    elif data["quote_target"] == "both":
        method_note_html = (
            "<strong>How to read this.</strong> Each turn shows two annotated surfaces. "
            "<em>Thought</em> annotations capture <em>meta moves</em> — phase pivots, "
            "hypothesis formation, recovery cognition, design judgments, verification "
            "decisions — phrases that tell you <em>why</em> the agent chose this action. "
            "<em>Action</em> annotations capture the executable surface — commands, code "
            "lines, edit directives — phrases that tell you <em>what</em> was done. "
            "The two are designed to be complementary: thought rarely repeats what action "
            "already shows, so most procedural turns carry only action quotes, while "
            "phase-boundary turns carry both. Click any underlined phrase, annotation row, "
            "or codebook entry to highlight bidirectionally."
        )
    else:
        method_note_html = (
            "<strong>How to read this.</strong> Each turn shows the verbatim "
            "<em>thought</em> from the trajectory. Inside, underlined phrases are "
            "<em>linguistic evidence</em> for a codebook label — the colour matches "
            "the codebook group on the right. Below each thought, the annotation "
            "table reads <code>\"quote\" → Group › Subgroup › Action</code>, one row "
            "per phrase. Click any phrase, any row, or any codebook entry — they "
            "highlight bidirectionally without scrolling."
        )

    # Optional `segments`: list of {start, end, title, summary} dicts that
    # group turns into named sub-sequences. Rendered as inline header cards
    # above the first turn of each segment in the main trajectory column.
    segments = data.get("segments", []) or []
    for s in segments:
        for f in ("start", "end"):
            if f not in s:
                raise ValueError(f"Segment missing field {f}: {s}")

    # Load template & substitute
    template = template_path.read_text()
    replacements = {
        "{{INSTANCE_ID}}": escape_html(data["instance_id"]),
        "{{MODEL}}": escape_html(data["model"]),
        "{{TURN_COUNT}}": str(len(data["turns"])),
        "{{OUTCOME_CLASS}}": outcome_class,
        "{{OUTCOME_LABEL}}": outcome_label,
        "{{ANNOTATION_COUNT}}": str(total_annot),
        "{{ISSUE_TEXT}}": escape_html(data["issue_text"]),
        "{{SUMMARY_HTML}}": data["summary"],
        "{{PIE_SVG}}": pie_svg,
        "{{PIE_LEGEND}}": pie_legend,
        "{{FINDINGS_HTML}}": findings_html,
        "{{MEMORY_QUERIES_HTML}}": render_memory_queries(data.get("memory_queries"), _turns_by_n),
        "{{COMPONENT_TIMELINE_HTML}}": render_component_timeline(data.get("component_timeline"), _turns_by_n),
        "{{QUOTE_TARGET}}": data["quote_target"],
        "{{METHOD_NOTE}}": method_note_html,
        "{{TURNS_JSON}}": json.dumps(turns_js, ensure_ascii=False),
        "{{SEGMENTS_JSON}}": json.dumps(segments, ensure_ascii=False),
    }
    for k, v in replacements.items():
        template = template.replace(k, v)

    # Output path
    if args.output:
        output_path = args.output
    else:
        # sanitise instance_id for filename
        slug = data["instance_id"].replace("/", "-").replace("__", "-").replace(" ", "-")
        output_path = Path(f"{slug}-trajectory-analysis.html")

    output_path.write_text(template)
    print(f"✓ Wrote artifact: {output_path}")
    print(f"  · {len(data['turns'])} turns")
    print(f"  · {total_annot} quote-level annotations")
    print(f"  · {len(group_counts)} codebook groups represented")


if __name__ == "__main__":
    main()
