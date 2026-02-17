"""CLI entry point and orchestration (execute_router_plan, execute_action)."""

import datetime
import os
import traceback

from . import handlers
from .butler_writes_cache import record_butler_write
from .memory import get_vault_folder, is_safe_path, log_debug
from .reference_resolution import inject_reference_links
from .types import FICTION_PATH, get_setting, is_vault_path_protected


def execute_action(
    op_type,
    path,
    content,
    original_text,
    extra_paths=None,
    source_datetime=None,
    summary=None,
    resolved_refs=None,
    plan_operation_types=None,
):
    log_debug(f"Executing Operation: {op_type}")
    final_content = content if (content and len(content) > 10) else original_text
    dest_path = None
    if resolved_refs:
        dest_path = handlers.get_destination_path_for_operation(
            op_type, path, source_datetime
        )
        final_content = inject_reference_links(
            final_content, resolved_refs, dest_path or ""
        )
        # Content for main file / written body: original text with refs injected (so written files get links)
        content_for_written = inject_reference_links(
            original_text or "", resolved_refs, dest_path or ""
        )
    else:
        content_for_written = original_text or ""

    try:
        result = None

        if op_type == "use_zettel_append":
            result = handlers.handle_zettel_append(path, final_content)
            handlers.run_ai_observation_to_temporal_in_background(
                "Appended to existing zettel",
                content=final_content,
            )
            return result

        if op_type == "use_daily_journal":
            # Use final_content so when router set op.content (e.g. user segment for mixed notes), diary gets it
            content_for_daily = final_content
            result = handlers.handle_daily(
                content_for_daily, source_datetime=source_datetime
            )
            handlers.run_ai_observation_to_temporal_in_background(
                "Routed to daily journal", content=content_for_daily
            )
            return result

        if op_type == "use_idea_generator":
            result = handlers.handle_idea(final_content)
            handlers.run_ai_observation_to_temporal_in_background(
                "Captured new idea", content=final_content
            )
            return result

        if op_type == "use_experiment_create":
            result = handlers.handle_experiment_create(final_content)
            handlers.run_ai_observation_to_temporal_in_background(
                "Created new experiment tracking file", content=final_content
            )
            return result

        if op_type == "use_experiment_log":
            skip_diary_report_and_todos = (
                plan_operation_types is not None
                and "use_daily_journal" in plan_operation_types
            )
            result = handlers.handle_experiment_log(
                original_text,
                path,
                extra_paths or [],
                source_datetime=source_datetime,
                summary=summary,
                skip_diary_report_and_todos=skip_diary_report_and_todos,
            )
            if get_setting("add-context-to-report-summary", False):
                from .task_queue import enqueue_context_aware_report_summary

                enqueue_context_aware_report_summary(
                    op_type="use_experiment_log",
                    original_text=original_text,
                    path=path or "",
                    source_datetime=source_datetime,
                    event_description=f"Logged experiment observation to {os.path.basename(path) if path else 'experiment'}",
                )
            else:
                obs_content = (
                    (summary or original_text)
                    if get_setting("summarize-logs-for-ai", False)
                    and (summary or "").strip()
                    else original_text
                )
                handlers.run_ai_observation_to_temporal_in_background(
                    f"Logged experiment observation to {os.path.basename(path) if path else 'experiment'}",
                    content=obs_content,
                )
            return result

        if op_type == "use_dev_log":
            skip_diary_report_and_todos = (
                plan_operation_types is not None
                and "use_daily_journal" in plan_operation_types
            )
            result = handlers.handle_dev_log(
                content_for_written,
                path,
                source_datetime=source_datetime,
                summary=summary,
                skip_diary_report_and_todos=skip_diary_report_and_todos,
            )
            if get_setting("add-context-to-report-summary", False):
                from .task_queue import enqueue_context_aware_report_summary

                enqueue_context_aware_report_summary(
                    op_type="use_dev_log",
                    original_text=original_text,
                    path=path or "",
                    source_datetime=source_datetime,
                    event_description=f"Logged to devlog: {os.path.basename(path) if path else 'devlog'}",
                )
            else:
                obs_content = (
                    (summary or original_text)
                    if get_setting("summarize-logs-for-ai", False)
                    and (summary or "").strip()
                    else original_text
                )
                handlers.run_ai_observation_to_temporal_in_background(
                    f"Logged to devlog: {os.path.basename(path) if path else 'devlog'}",
                    content=obs_content,
                )
            return result

        if op_type == "use_dev_log_create":
            if get_setting("forbid-new-devlog-creation", False):
                # Only append to existing devlogs; route would-be new project to Ideas
                result = handlers.handle_idea(final_content)
                handlers.run_ai_observation_to_temporal_in_background(
                    "Captured new idea (devlog creation forbidden)",
                    content=final_content,
                )
                return result
            result = handlers.handle_dev_log_create(final_content)
            handlers.run_ai_observation_to_temporal_in_background(
                "Created new devlog project",
                content=final_content,
            )
            return result

        if op_type == "use_zettel_script":
            skip_diary_report_and_todos = (
                plan_operation_types is not None
                and "use_daily_journal" in plan_operation_types
            )
            result = handlers.handle_zettel(
                content_for_written,
                summary=summary,
                skip_diary_report_and_todos=skip_diary_report_and_todos,
            )
            if not get_setting("add-context-to-report-summary", False):
                obs_content = (
                    (summary or original_text)
                    if get_setting("summarize-logs-for-ai", False)
                    and (summary or "").strip()
                    else original_text
                )
                handlers.run_ai_observation_to_temporal_in_background(
                    "Created zettelkasten note for intellectual work",
                    content=obs_content,
                )
            return result

        if op_type == "use_apple_notes_general":
            result = handlers.handle_apple_notes_general(final_content)
            handlers.run_ai_observation_to_temporal_in_background(
                "Routed to Apple Notes for quick searchability",
                content=final_content,
            )
            return result

        if op_type == "use_fiction_append":
            if is_vault_path_protected(FICTION_PATH):
                log_debug(
                    f"❌ Block: cannot write to protected path (template/excalidraw): {FICTION_PATH}"
                )
                return "❌ Cannot modify template or excalidraw file"
            with open(FICTION_PATH, "a") as f:
                f.write(f"\n\n---\n## {datetime.date.today()}\n{final_content}")
            log_debug(f"💾 Action: Fiction Append -> {FICTION_PATH}")
            record_butler_write(FICTION_PATH)
            handlers.run_ai_observation_to_temporal_in_background(
                "Captured fiction/creative writing idea", content=final_content
            )
            return f"{get_vault_folder(FICTION_PATH)} | Fiction Log"

        if op_type in ["file_append", "file_create"] and path:
            if not is_safe_path(path):
                log_debug(f"❌ Security Block: {path}")
                return "❌ Unsafe Path"
            if is_vault_path_protected(path):
                log_debug(
                    f"❌ Block: cannot write to protected path (template/excalidraw): {path}"
                )
                return "❌ Cannot modify template or excalidraw file"
            mode = "a" if op_type == "file_append" else "w"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, mode, encoding="utf-8") as f:
                prefix = "\n\n" if mode == "a" and os.path.getsize(path) > 0 else ""
                f.write(prefix + final_content)

            log_debug(f"💾 Action: Generic {mode} -> {path}")
            record_butler_write(path)
            handlers.run_ai_observation_to_temporal_in_background(
                f"{'Appended to' if mode == 'a' else 'Created'} file: {os.path.basename(path)}",
                content=final_content,
            )
            return f"{get_vault_folder(path)} | {'Appended' if mode == 'a' else 'Created'}: {os.path.basename(path)}"

        # Router failure mode: unknown or unsupported operation -> always append to daily
        log_debug(f"⚠️ Unknown Operation '{op_type}'. Defaulting to Daily.")
        content_for_daily = (
            (original_text or "").strip()
            if (original_text and len((original_text or "").strip()) > 0)
            else final_content
        )
        return handlers.handle_daily(content_for_daily, source_datetime=source_datetime)

    except Exception as e:
        log_debug(f"❌ CRITICAL EXECUTION ERROR: {traceback.format_exc()}")
        raise e
