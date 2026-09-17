from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
#from langchain_ollama import ChatOllama

from ase.agent.models import (
    Diagnosis,
    Investigation,
    PatchProposal,
)
from ase.agent.prompts import (
    DIAGNOSIS_SYSTEM_PROMPT,
    INVESTIGATION_SYSTEM_PROMPT,
    PATCH_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    investigation_context,
    verification_context,
)
from ase.agent.schemas import (
    DiagnosisOutput,
    PatchOutput,
    RepairOutput,
)
from ase.agent.tooling import (
    build_repository_model_tools,
)
from ase.tools.repository import RepositoryTools
from ase.verifier.models import VerificationReport


from langchain_core.language_models.chat_models import (
    BaseChatModel,
)

from ase.providers.settings import (
    ModelSettings,
)

from ase.providers.errors import (
    ModelOutputError,
    ToolBudgetExceeded,
    raise_provider_error,
)

class ChatModelEngineeringAgent:
    def __init__(
        self,
        *,
        model: BaseChatModel,
        settings: ModelSettings,
    ) -> None:
        self._model = model
        self._settings = settings


    def investigate(
        self,
        ticket: str,
        tools: RepositoryTools,
    ) -> Investigation:
        bundle = build_repository_model_tools(
            tools
        )

        model_with_tools = (
            self._model.bind_tools(
                bundle.tools,
                strict=True,
            )
        )

        messages = [
            SystemMessage(
                content=INVESTIGATION_SYSTEM_PROMPT
            ),
            HumanMessage(
                content=(
                    "Investigate this engineering ticket.\n\n"
                    f"{ticket}"
                )
            ),
        ]

        tool_call_count = 0
        final_summary = ""

        while True:
            try:
                response = model_with_tools.invoke(
                    messages
                )
            except Exception as exc:
                raise_provider_error(
                    provider=self._settings.provider,
                    stage="investigation",
                    exc=exc,
                )
            messages.append(response)

            if not response.tool_calls:
                final_summary = str(
                    response.content
                ).strip()
                break

            for call in response.tool_calls:
                tool_call_count += 1

                if (
                    tool_call_count
                    > self._settings.max_tool_calls
                ):
                    raise ToolBudgetExceeded(
                        "investigation exceeded "
                        f"maximum tool calls "
                        f"({self._settings.max_tool_calls})"
                    )

                tool_name = call["name"]
                tool = bundle.by_name.get(
                    tool_name
                )

                if tool is None:
                    output = (
                        "ERROR: unknown tool "
                        f"{tool_name}"
                    )
                else:
                    try:
                        output = str(
                            tool.invoke(
                                call["args"]
                            )
                        )
                    except Exception as exc:
                        output = (
                            "ERROR: "
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )

                messages.append(
                    ToolMessage(
                        content=output,
                        tool_call_id=call["id"],
                    )
                )

        if not final_summary:
            final_summary = (
                "Investigation completed after "
                f"{tool_call_count} tool calls."
            )

        return Investigation(
            searches=tuple(bundle.searches),
            files=tuple(bundle.files),
            summary=final_summary,
            tool_events=tuple(bundle.events),
        )


    def diagnose(
        self,
        ticket: str,
        investigation: Investigation,
        tools: RepositoryTools,
    ) -> Diagnosis:
        del tools

        structured_model = (
            self._model.with_structured_output(
                DiagnosisOutput,
                method="json_schema",
            )
        )

        result = structured_model.invoke(
            [
                SystemMessage(
                    content=DIAGNOSIS_SYSTEM_PROMPT
                ),
                HumanMessage(
                    content=investigation_context(
                        ticket,
                        investigation,
                    )
                ),
            ]
        )

        if not isinstance(
            result,
            DiagnosisOutput,
        ):
            raise ModelOutputError(
                "diagnosis: provider returned "
                "an unexpected structured result"
            )


        return Diagnosis(
            root_cause=result.root_cause,
            evidence_paths=tuple(
                item.path
                for item in result.evidence
            ),
            affected_files=tuple(
                result.affected_files
            ),
            proposed_change=(
                result.proposed_change
            ),
            confidence=result.confidence,
        )

    def propose_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        tools: RepositoryTools,
    ) -> PatchProposal:
        del tools

        structured_model = (
            self._model.with_structured_output(
                PatchOutput,
                method="json_schema",
            )
        )

        context = "\n\n".join(
            [
                investigation_context(
                    ticket,
                    investigation,
                ),
                "",
                "DIAGNOSIS:",
                f"Root cause: {diagnosis.root_cause}",
                (
                    "Proposed change: "
                    f"{diagnosis.proposed_change}"
                ),
                (
                    "Affected files: "
                    f"{list(diagnosis.affected_files)}"
                ),
            ]
        )

        result = structured_model.invoke(
            [
                SystemMessage(
                    content=PATCH_SYSTEM_PROMPT
                ),
                HumanMessage(content=context),
            ]
        )

        if not isinstance(
            result,
            PatchOutput,
        ):
            raise ModelOutputError(
                "patch_proposal: provider returned "
                "an unexpected structured result"
            )

        return PatchProposal(
            summary=result.summary,
            diff=result.diff,
        )


    def repair_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        previous: PatchProposal,
        verification: VerificationReport,
        tools: RepositoryTools,
    ) -> PatchProposal:
        del tools

        structured_model = (
            self._model.with_structured_output(
                RepairOutput,
                method="json_schema",
            )
        )

        context = "\n\n".join(
            [
                investigation_context(
                    ticket,
                    investigation,
                ),
                "",
                "ORIGINAL DIAGNOSIS:",
                diagnosis.root_cause,
                "",
                "PREVIOUS PATCH:",
                previous.diff,
                "",
                "VISIBLE VERIFICATION FAILURES:",
                verification_context(
                    verification
                ),
                "",
                (
                    "The previous patch has already "
                    "been applied. Produce an "
                    "incremental diff against the "
                    "current workspace."
                ),
            ]
        )

        result = structured_model.invoke(
            [
                SystemMessage(
                    content=REPAIR_SYSTEM_PROMPT
                ),
                HumanMessage(content=context),
            ]
        )

        if not isinstance(
            result,
            RepairOutput,
        ):
            raise ModelOutputError(
                "repair_patch: provider returned "
                "an unexpected structured result"
            )

        return PatchProposal(
            summary=result.summary,
            diff=result.diff,
        )
