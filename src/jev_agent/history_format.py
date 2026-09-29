"""One-line, human-readable rendering of execution history for demos and the CLI."""

import json

from jev_agent.models import Escalation, EventType, HistoryEvent


def format_event(event: HistoryEvent) -> str:
    payload = event.payload
    match event.event_type:
        case EventType.STATUS_TRANSITION:
            detail = f"{payload['from']} -> {payload['to']} ({payload['reason']})"
        case EventType.JEV_JUDGMENT:
            detail = f"jev={json.dumps(payload['output'])} -> policy={payload['outcome']}"
        case EventType.RETRY:
            detail = (
                f"attempt {payload['from_attempt']} -> {payload['to_attempt']} "
                f"({payload['reason']})"
            )
        case EventType.ROLLBACK:
            detail = f"restored {payload['file_path']}"
        case EventType.ESCALATION:
            detail = f"reason={payload['reason']}"
        case EventType.ESCALATION_RESOLVED:
            note = payload.get("note")
            detail = f"escalation {payload['escalation_id']} resolved" + (
                f" ({note})" if note else ""
            )
        case EventType.STEP_ERROR:
            detail = f"{payload['step']} raised {payload['error_type']}: {payload['message']}"
    return f"- attempt {event.attempt} {event.event_type.value}: {detail}"


def format_history(events: list[HistoryEvent]) -> str:
    return "\n".join(format_event(event) for event in events)


def format_escalation(escalation: Escalation) -> str:
    context = escalation.context
    lines = [
        f"Escalation #{escalation.id}: {escalation.reason.value} "
        f"(attempt {escalation.attempt}, {escalation.resolution_state.value})",
        f"  retries: {context['retry_count']} of {context['max_retries']}",
        f"  elapsed: {context['elapsed_seconds']:.1f}s of {context['max_wall_clock_seconds']}s",
        f"  judgment: {json.dumps(context['judgment'])}",
    ]
    return "\n".join(lines)
