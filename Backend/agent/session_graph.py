from langgraph.graph import StateGraph, END
from agent.state import VaultLearnState
from agent.nodes import (study_session_node, write_notes_node, read_vault_node,
                         choose_action_node, generate_quiz_node, grade_quiz_node)

graph = StateGraph(VaultLearnState)


def route_action(state: VaultLearnState) -> str:
    return state["action"]


graph.add_node("study_session", study_session_node)
graph.add_node("write_notes",write_notes_node)
graph.add_node("read_vault", read_vault_node)
graph.add_node("choose_action", choose_action_node)
graph.add_node("generate_quiz", generate_quiz_node)
graph.add_node("grade_quiz", grade_quiz_node)
graph.set_entry_point("read_vault")
graph.add_edge("read_vault", "choose_action")
graph.add_conditional_edges(
    "choose_action", route_action,
    {"end": "write_notes", "answer": "study_session", "quiz": "generate_quiz", "grade": "grade_quiz"}
)
graph.add_edge("study_session", END)
graph.add_edge("generate_quiz", END)
graph.add_edge("grade_quiz", END)
graph.add_edge("write_notes", END)


session_app = graph.compile()
