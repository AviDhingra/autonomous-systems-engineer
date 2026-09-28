from jev_agent.models import STEP_ORDER, Checkpoint, CheckpointPhase, StepName


def determine_resume_step(checkpoints: list[Checkpoint]) -> StepName | None:
    """Return the step a job should (re)run next, or None if all steps are done.

    A step counts as durably completed only if it has an `after` checkpoint.
    A step with only a `before` checkpoint was interrupted mid-step and is
    re-entered from scratch — it is not treated as completed. Steps are
    resumed in the fixed PROPOSE -> APPLY -> VERIFY order; the first step
    without an `after` checkpoint is where the job resumes.
    """
    completed_steps = {
        checkpoint.step
        for checkpoint in checkpoints
        if checkpoint.phase is CheckpointPhase.AFTER
    }

    for step in STEP_ORDER:
        if step not in completed_steps:
            return step

    return None
