"""Explicit, checkpointable LangGraph orchestration for Agent import Cases."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from app.agent_import.case_service import CaseRecord, CaseService
from app.agent_import.states import CaseStatus
from app.agent_import.workflow import AgentImportWorkflow


class AgentImportGraphState(TypedDict):
    case_id: str
    status: str
    context_revision: int
    stop_requested: bool
    last_error_code: str | None
    resumed: NotRequired[bool]


class AgentImportGraphRunner:
    """Run small graph states while business payloads remain in Case tables."""

    def __init__(
        self,
        *,
        service: CaseService,
        workflow: AgentImportWorkflow,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        checkpoint_connection: Any | None = None,
    ) -> None:
        self.service = service
        self.workflow = workflow
        self.checkpointer = checkpointer or InMemorySaver()
        self.checkpoint_connection = checkpoint_connection
        self.graph = build_agent_import_graph(
            service=service,
            workflow=workflow,
            checkpointer=self.checkpointer,
        )

    @classmethod
    def for_workflow(
        cls,
        *,
        service: CaseService,
        workflow: AgentImportWorkflow,
    ) -> "AgentImportGraphRunner":
        if service.engine.dialect.name != "postgresql":
            return cls(service=service, workflow=workflow, checkpointer=InMemorySaver())
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver

        dsn = service.engine.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )
        connection = psycopg.connect(dsn, autocommit=True, prepare_threshold=0)
        checkpointer = PostgresSaver(connection)
        checkpointer.setup()
        return cls(
            service=service,
            workflow=workflow,
            checkpointer=checkpointer,
            checkpoint_connection=connection,
        )

    def close(self) -> None:
        if self.checkpoint_connection is not None:
            self.checkpoint_connection.close()
            self.checkpoint_connection = None

    def run_case(self, case_id: str) -> CaseRecord:
        config = {"configurable": {"thread_id": case_id}}
        case = self.service.get_case(case_id)
        snapshot = self.graph.get_state(config)
        has_interrupt = any(getattr(task, "interrupts", ()) for task in snapshot.tasks)
        if has_interrupt and case.status == CaseStatus.ANALYZING:
            self.graph.invoke(
                Command(resume={"context_revision": case.context_revision}),
                config=config,
            )
        elif case.status != CaseStatus.NEEDS_USER:
            self.graph.invoke(_state(case), config=config)
        return self.service.get_case(case_id)


def build_agent_import_graph(
    *,
    service: CaseService,
    workflow: AgentImportWorkflow,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> Any:
    def refresh(state: AgentImportGraphState) -> AgentImportGraphState:
        case = service.get_case(state["case_id"])
        if case.status == CaseStatus.STOPPING:
            case = service.finish_stopping(case.case_id)
        return _state(case, resumed=state.get("resumed"))

    def analyze(state: AgentImportGraphState) -> AgentImportGraphState:
        return _run_phase(state, workflow.run_analysis_phase)

    def build_candidate(state: AgentImportGraphState) -> AgentImportGraphState:
        return _run_phase(state, workflow.run_candidate_phase)

    def review_candidate(state: AgentImportGraphState) -> AgentImportGraphState:
        return _run_phase(state, workflow.run_review_phase)

    def execute_staging(state: AgentImportGraphState) -> AgentImportGraphState:
        return _run_phase(state, workflow.run_execution_phase)

    def wait_for_user(state: AgentImportGraphState) -> AgentImportGraphState:
        resume = interrupt(
            {
                "case_id": state["case_id"],
                "context_revision": state["context_revision"],
                "status": CaseStatus.NEEDS_USER.value,
            }
        )
        case = service.get_case(state["case_id"])
        if case.status != CaseStatus.ANALYZING:
            raise RuntimeError("Agent Case was resumed without a committed user answer")
        return _state(case, resumed=bool(resume))

    def _run_phase(state: AgentImportGraphState, phase: Any) -> AgentImportGraphState:
        try:
            case = phase(state["case_id"])
        except Exception as exc:  # noqa: BLE001 - graph failures are persisted as business state
            case = workflow.handle_failure(state["case_id"], exc)
        return _state(case, resumed=state.get("resumed"))

    graph = StateGraph(AgentImportGraphState)
    graph.add_node("refresh_case", refresh)
    graph.add_node("analyze_source", analyze)
    graph.add_node("build_candidate", build_candidate)
    graph.add_node("review_candidate", review_candidate)
    graph.add_node("execute_staging", execute_staging)
    graph.add_node("wait_for_user", wait_for_user)
    graph.set_entry_point("refresh_case")
    graph.add_conditional_edges(
        "refresh_case",
        _route,
        {
            "analyze_source": "analyze_source",
            "build_candidate": "build_candidate",
            "review_candidate": "review_candidate",
            "execute_staging": "execute_staging",
            "wait_for_user": "wait_for_user",
            "end": END,
        },
    )
    for node in ("analyze_source", "build_candidate", "review_candidate", "execute_staging", "wait_for_user"):
        graph.add_edge(node, "refresh_case")
    return graph.compile(checkpointer=checkpointer)


def _route(state: AgentImportGraphState) -> str:
    status = CaseStatus(state["status"])
    if status in {CaseStatus.CREATED, CaseStatus.ANALYZING}:
        return "analyze_source"
    if status == CaseStatus.STRATEGY_READY:
        return "build_candidate"
    if status == CaseStatus.BUILDING:
        return "review_candidate"
    if status == CaseStatus.VERIFYING:
        return "execute_staging"
    if status == CaseStatus.NEEDS_USER:
        return "wait_for_user"
    return "end"


def _state(case: CaseRecord, *, resumed: bool | None = None) -> AgentImportGraphState:
    verification = case.verification_payload or {}
    state: AgentImportGraphState = {
        "case_id": case.case_id,
        "status": case.status.value,
        "context_revision": case.context_revision,
        "stop_requested": case.stop_requested_at is not None,
        "last_error_code": (
            str(verification.get("failure_code"))
            if verification.get("failure_code") is not None
            else None
        ),
    }
    if resumed is not None:
        state["resumed"] = resumed
    return state
