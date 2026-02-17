"""Routing logic: get_router_plan, get_rules, and prompt construction."""

import os
import re
import sys

from pydantic import ValidationError

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from prompt_loader import load_prompt

from . import memory
from .llm_client import call_llm_structured
from .llm_models import RouterPlan, RoutingOperation
from .routing_keywords_cache import apply_category_limits, match_keywords_in_content
from .types import (
    DEVLOG_DIR,
    EXPERIMENT_DIR,
    MODEL_MED,
    ROUTER_TOOLS_DESCRIPTION,
    get_router_tools_description,
    RULES_CACHE,
    RULES_FILE,
    MODEL_SMART_MakeInstructions,
    MODEL_SMART_MakeRouterDecisions,
    get_setting,
)


def scan_recent_notes(root_path, limit=10):
    memory.log_debug(f"Scanning for context in: {os.path.basename(root_path)}")
    if not os.path.exists(root_path):
        memory.log_debug("⚠️ Context path not found.")
        return ""
    found = []
    for dp, _, filenames in os.walk(root_path):
        for f in filenames:
            if f.endswith(".md"):
                fp = os.path.join(dp, f)
                try:
                    found.append((os.path.getmtime(fp), f, fp))
                except Exception:
                    continue
    found.sort(key=lambda x: x[0], reverse=True)

    context_list = [f"- FILE: {item[1]}\n  PATH: {item[2]}" for item in found[:limit]]
    memory.log_debug(f"Found {len(context_list)} recent experiment notes.")
    return "\n".join(context_list) if context_list else "None"


def _parse_devlog_frontmatter(raw):
    """Parse butler_summary and butler_keywords from YAML frontmatter. Returns (summary_str, keywords_str)."""
    summary_str = "none"
    keywords_str = "none"
    if not raw or "---" not in raw:
        return summary_str, keywords_str
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return summary_str, keywords_str
    fm = parts[1].strip()
    m = re.search(r"butler_summary:\s*(.+?)(?=\n\w|\n---|\Z)", fm, re.DOTALL)
    if m:
        summary_str = m.group(1).strip().strip("\"'")
    m = re.search(r"butler_keywords:\s*(.+?)(?=\n\w|\n---|\Z)", fm, re.DOTALL)
    if m:
        kw = m.group(1).strip()
        if kw.startswith("["):
            keywords_str = kw
        else:
            keywords_str = kw.strip("\"'")
    return summary_str, keywords_str


def _build_devlog_context_for_paths(paths, path_to_matched_keywords=None):
    """Build context string for given devlog paths. Optional path_to_matched_keywords adds 'Matched:' line."""
    context_list = []
    for fpath in paths:
        if not os.path.isfile(fpath):
            continue
        fname = os.path.basename(fpath)
        summary_str = "none"
        keywords_str = "none"
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                head = f.read(8192)
            summary_str, keywords_str = _parse_devlog_frontmatter(head)
        except Exception:
            pass
        line = f"- FILE: {fname}\n  PATH: {fpath}\n  BUTLER_SUMMARY: {summary_str}\n  KEYWORDS: {keywords_str}"
        if path_to_matched_keywords and fpath in path_to_matched_keywords:
            kws = path_to_matched_keywords[fpath]
            quoted = ", ".join(f'"{k}"' for k in kws[:5])
            line += f"\n  Matched: content mentions {quoted}"
        context_list.append(line)
    return "\n".join(context_list) if context_list else ""


def _build_experiment_context_for_paths(paths, path_to_matched_keywords=None):
    """Build context string for given experiment paths. Optional path_to_matched_keywords adds 'Matched:' line."""
    context_list = []
    for fpath in paths:
        if not os.path.isfile(fpath):
            continue
        fname = os.path.basename(fpath)
        line = f"- FILE: {fname}\n  PATH: {fpath}"
        if path_to_matched_keywords and fpath in path_to_matched_keywords:
            kws = path_to_matched_keywords[fpath]
            quoted = ", ".join(f'"{k}"' for k in kws[:5])
            line += f"\n  Matched: content mentions {quoted}"
        context_list.append(line)
    return "\n".join(context_list) if context_list else ""


def scan_recent_devlog_notes(limit=10, exclude_paths=None):
    """Scan DEVLOG_DIR for recent .md files; return context string with FILE, PATH, BUTLER_SUMMARY, KEYWORDS."""
    memory.log_debug(f"Scanning for context in: {os.path.basename(DEVLOG_DIR)}")
    if not os.path.exists(DEVLOG_DIR):
        memory.log_debug("⚠️ Devlog context path not found.")
        return "None"
    found = []
    for dp, _, filenames in os.walk(DEVLOG_DIR):
        for f in filenames:
            if f.endswith(".md"):
                fp = os.path.join(dp, f)
                try:
                    found.append((os.path.getmtime(fp), f, fp))
                except Exception:
                    continue
    found.sort(key=lambda x: x[0], reverse=True)
    exclude = set(exclude_paths or [])
    context_list = []
    for mtime, fname, fpath in found[: limit + len(exclude)]:
        if fpath in exclude:
            continue
        if len(context_list) >= limit:
            break
        summary_str = "none"
        keywords_str = "none"
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                head = f.read(8192)
            summary_str, keywords_str = _parse_devlog_frontmatter(head)
        except Exception:
            pass
        context_list.append(
            f"- FILE: {fname}\n  PATH: {fpath}\n  BUTLER_SUMMARY: {summary_str}\n  KEYWORDS: {keywords_str}"
        )
    memory.log_debug(f"Found {len(context_list)} recent devlog notes.")
    return "\n".join(context_list) if context_list else "None"


def scan_recent_notes_for_experiments(root_path, limit=10, exclude_paths=None):
    """Scan root for recent .md; return context. Exclude_paths: paths already in keyword-matched set."""
    if not os.path.exists(root_path):
        return ""
    found = []
    for dp, _, filenames in os.walk(root_path):
        for f in filenames:
            if f.endswith(".md"):
                fp = os.path.join(dp, f)
                try:
                    found.append((os.path.getmtime(fp), f, fp))
                except Exception:
                    continue
    found.sort(key=lambda x: x[0], reverse=True)
    exclude = set(exclude_paths or [])
    context_list = []
    for _, fname, fp in found:
        if fp in exclude:
            continue
        if len(context_list) >= limit:
            break
        context_list.append(f"- FILE: {fname}\n  PATH: {fp}")
    return "\n".join(context_list) if context_list else "None"


REPORT_OPS = {
    "use_zettel_script",
    "use_zettel_append",
    "use_experiment_log",
    "use_dev_log",
}


def consolidate_router_plan(plan: RouterPlan) -> RouterPlan:
    """
    Deduplicate operations: when report ops (devlog/experiment/zettel) are present,
    drop use_daily_journal only when it has no meaningful content (redundant with
    report handler's diary write). If use_daily_journal has non-empty content, keep
    it so the diary receives the user-focused segment; the report handler still
    writes project-mention + one-liner to the diary.
    When forbid-new-devlog-creation is true, replace use_dev_log_create with
    use_idea_generator so content is routed to Ideas instead of creating a new devlog.
    """
    ops = plan.operations
    # Forbid new devlog: replace create with idea so we only append to existing devlogs
    if get_setting("forbid-new-devlog-creation", False):
        ops = [
            RoutingOperation(
                type="use_idea_generator",
                path=op.path or "",
                content=op.content or "",
                extra_paths=op.extra_paths,
                summary=op.summary,
            )
            if op.type == "use_dev_log_create"
            else op
            for op in ops
        ]
    has_report = any(op.type in REPORT_OPS for op in ops)
    has_daily = any(op.type == "use_daily_journal" for op in ops)
    if has_report and has_daily:
        # Keep use_daily_journal when it has meaningful content (user segment for mixed notes)
        ops = [
            op
            for op in ops
            if op.type != "use_daily_journal"
            or (op.content and len((op.content or "").strip()) > 10)
        ]
    return RouterPlan(
        operations=ops, referring_to_other_notes=plan.referring_to_other_notes
    )


def _strip_dev_log_create_from_prompt(system: str) -> str:
    """Remove use_dev_log_create and any instructions to use it from the routing prompt."""
    lines = system.split("\n")
    out = []
    for line in lines:
        # Drop the bullet that instructs when to use use_dev_log_create
        if line.strip().startswith("- IF ") and "use_dev_log_create" in line:
            continue
        out.append(line)
    system = "\n".join(out)
    # Remove the OUTPUT line clause about use_dev_log_create
    system = re.sub(
        r"\s*For use_dev_log_create,[^.]*\.\s*",
        " ",
        system,
        flags=re.IGNORECASE,
    )
    return system


def get_rules():
    if not os.path.exists(RULES_FILE):
        memory.log_debug("⚠️ Rules file missing, using defaults.")
        return "Default Rules."

    src_mtime = os.path.getmtime(RULES_FILE)
    cache_mtime = os.path.getmtime(RULES_CACHE) if os.path.exists(RULES_CACHE) else 0

    if cache_mtime > src_mtime:
        memory.log_debug("💾 Loaded Rules from Cache.")
        with open(RULES_CACHE, "r") as f:
            return f.read()

    memory.log_debug("Rules outdated/uncached. Re-processing with AI...")
    with open(RULES_FILE, "r") as f:
        raw = f.read()
    rules_prompt = load_prompt(
        "01-routing/03-rules_instructions",
        variables={"router_tools_description": ROUTER_TOOLS_DESCRIPTION},
    )
    processed = memory.call_llm(rules_prompt, raw, MODEL_SMART_MakeInstructions) or raw
    with open(RULES_CACHE, "w") as f:
        f.write(processed)
    return processed


def get_router_plan(content):
    memory.log_debug("Generating Router Plan...")

    rules = get_rules()

    # Keyword cache: boost matched devlogs/experiments into context
    matched_devlogs, matched_experiments, _ = match_keywords_in_content(content)
    limited_devlogs, limited_experiments, _ = apply_category_limits(
        matched_devlogs, matched_experiments, {}
    )

    keyword_devlog_paths = list(limited_devlogs.keys())
    keyword_experiment_paths = list(limited_experiments.keys())

    devlog_keyword_ctx = _build_devlog_context_for_paths(
        keyword_devlog_paths, limited_devlogs
    )
    devlog_recent_ctx = scan_recent_devlog_notes(
        10, exclude_paths=set(keyword_devlog_paths)
    )
    context_devlog = devlog_keyword_ctx
    if devlog_recent_ctx and devlog_recent_ctx != "None":
        context_devlog = (
            (context_devlog + "\n" + devlog_recent_ctx)
            if context_devlog
            else devlog_recent_ctx
        )
    if not context_devlog:
        context_devlog = "None"

    exp_keyword_ctx = _build_experiment_context_for_paths(
        keyword_experiment_paths, limited_experiments
    )
    exp_recent_ctx = scan_recent_notes_for_experiments(
        EXPERIMENT_DIR, 10, exclude_paths=set(keyword_experiment_paths)
    )
    context_experiments = exp_keyword_ctx
    if exp_recent_ctx and exp_recent_ctx != "None":
        context_experiments = (
            (context_experiments + "\n" + exp_recent_ctx)
            if context_experiments
            else exp_recent_ctx
        )
    if not context_experiments:
        context_experiments = "None"

    matched_hint = ""
    if keyword_devlog_paths or keyword_experiment_paths:
        matched_hint = "Items marked 'Matched: content mentions X' are prioritized because the user's content mentioned those keywords.\n\n"

    forbid_new_devlog = get_setting("forbid-new-devlog-creation", False)
    system = load_prompt(
        "01-routing/02-vault_os_system",
        variables={
            "router_tools_description": get_router_tools_description(forbid_new_devlog_creation=forbid_new_devlog),
            "rules": rules,
            "context_experiments": context_experiments,
            "context_devlog": context_devlog,
            "matched_hint": matched_hint,
        },
    )
    if forbid_new_devlog:
        system = _strip_dev_log_create_from_prompt(system)

    user = f"CONTENT: {content[:4000]}"

    # 1. Attempt fast model with structured output (instructor + Pydantic)
    try:
        plan = call_llm_structured(
            system=system,
            user=user,
            model=MODEL_MED,
            response_model=RouterPlan,
            max_retries=2,
        )
        memory.log_debug(f"🎯 Router Decision: {[op.type for op in plan.operations]}")
        memory.log_debug(
            f'[Router] "{memory.snippet(content, 80)}" → {[op.type for op in plan.operations]}'
        )
        return plan
    except (ValidationError, Exception) as e:
        memory.log_debug(
            f"Med Speed Model ({MODEL_MED}) failed: {e}. Retrying with Smart Model ({MODEL_SMART_MakeRouterDecisions})..."
        )

    # 2. Fallback to smart model
    try:
        plan = call_llm_structured(
            system=system,
            user=user,
            model=MODEL_SMART_MakeRouterDecisions,
            response_model=RouterPlan,
            max_retries=3,
        )
        memory.log_debug(f"🎯 Router Decision: {[op.type for op in plan.operations]}")
        memory.log_debug(
            f'[Router] "{memory.snippet(content, 80)}" → {[op.type for op in plan.operations]}'
        )
        return plan
    except Exception as e2:
        memory.log_debug(f"All routers failed: {e2}. Defaulting to Daily.")
        plan = RouterPlan(
            operations=[RoutingOperation(type="use_daily_journal", path="", content="")]
        )
        memory.log_debug(
            f'[Router] "{memory.snippet(content, 80)}" → {[op.type for op in plan.operations]}'
        )
        return plan
