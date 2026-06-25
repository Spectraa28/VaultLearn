from langgraph.graph import StateGraph, END
from agent.state import VaultLearnState
from agent.nodes import study_session_node ,write_notes_node,read_vault_node

graph = StateGraph(VaultLearnState)


def should_end(state:VaultLearnState) -> str:
    if state["user_input"].lower().strip() == "end session":
        return "end"
    return "continue"


graph.add_node("study_session", study_session_node)
graph.add_node("write_notes",write_notes_node)
graph.add_node("read_vault", read_vault_node)
graph.set_entry_point("read_vault")
graph.add_edge("read_vault", "study_session")
graph.add_conditional_edges(
    "study_session",
    should_end,
    {"end":"write_notes","continue":END}
)
graph.add_edge("write_notes", END)


session_app = graph.compile()