from langgraph.graph import StateGraph, END
from agent.state import VaultLearnState
from agent.nodes import study_session_node 

graph = StateGraph(VaultLearnState)


def should_end(state:VaultLearnState) -> str:
    if state["user_input"].lower().strip() == "end session":
        return "end"
    return "continue"


graph.add_node("study_session", study_session_node)
graph.set_entry_point("study_session")
graph.add_conditional_edges(
    "study_session",
    should_end,
    {"end":END,"continue":END}
)



session_app = graph.compile()