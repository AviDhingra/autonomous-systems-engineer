from jev_agent.models import STEP_ORDER, Checkpoint, CheckpointPhase, StepName


def determine_resume_step(checkpoints: list[Checkpoint], attempt: int) -> StepName | None:
    """Return the step a job's given attempt should (re)run next, or None if
    that attempt's steps are all done.

    Checkpoints are scoped by attempt: a retry restarts from `PROPOSE`, so an
    earlier attempt's completed steps must never be mistaken for the current
    attempt's progress. Only checkpoints matching `attempt` are consulted;
    earlier attempts' checkpoints remain in the store as history but are
    ignored here.

    Within the matched attempt, a step counts as durably completed only if
    it has an `after` checkpoint. A step with only a `before` checkpoint was
    interrupted mid-step and is re-entered from scratch — it is not treated
    as completed. Steps are resumed in the fixed PROPOSE -> APPLY -> VERIFY
    order; the first step without an `after` checkpoint is where the job
    resumes.
    """
    completed_steps = {
        checkpoint.step
        for checkpoint in checkpoints
        if checkpoint.phase is CheckpointPhase.AFTER and checkpoint.attempt == attempt
    }

    for step in STEP_ORDER:
        if step not in completed_steps:
            return step

    return None
