from langgraph.graph import StateGraph, END
from agent.state import VaultLearnState
from agent.nodes import resolve_url_node, crawl_structure_node, generate_study_plan_node,build_collection_node, study_session_node

graph = StateGraph(VaultLearnState)
graph.add_node("resolve_url",resolve_url_node)
graph.add_node("crawl_structure",crawl_structure_node)
graph.add_node("generate_study_plan", generate_study_plan_node)
graph.add_node("build_collection",build_collection_node)
graph.add_node("Study_session",study_session_node)
graph.set_entry_point("resolve_url")
graph.add_edge("resolve_url", "crawl_structure")
graph.add_edge("crawl_structure","generate_study_plan")
graph.add_edge("generate_study_plan","build_collection")
graph.add_edge("build_collection",END)

app = graph.compile()