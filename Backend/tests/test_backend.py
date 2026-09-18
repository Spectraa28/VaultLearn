import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from schemas.models import Module, StudyPlan, Topic


class BackendPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "sessions.db")
        self.previous = os.environ.get("VAULTLEARN_DB_PATH")
        os.environ["VAULTLEARN_DB_PATH"] = self.path
        import storage
        storage.init_db()

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("VAULTLEARN_DB_PATH", None)
        else:
            os.environ["VAULTLEARN_DB_PATH"] = self.previous
        self.temp.cleanup()

    def test_session_turns_runs_and_usage_survive_new_connections(self):
        import storage
        storage.create_session("s1", "https://docs.example.com", "Example", "kb-s1", "{}")
        storage.save_turn("s1", "user", "What is a route?")
        storage.save_turn("s1", "assistant", "A route maps a path.", ["https://docs.example.com/routes"])
        storage.update_session("s1", 2, {"routing": "needs work"}, False,
                               {"question": "What is a route?"}, {"routing": 0.65})
        storage.start_run("r1", "session_turn", "s1")
        storage.add_event("r1", "s1", "agent.decision", "ok", 12.5, {"action": "quiz"})
        storage.add_usage("r1", "s1", "choose_action", "openai/gpt-oss-20b", "ok", 100, 20, 0.0000135, 100)
        storage.finish_run("r1", "completed")

        record = storage.get_session("s1")
        self.assertEqual(record["current_module_number"], 2)
        self.assertEqual(json.loads(record["mastery_scores_json"])["routing"], 0.65)
        self.assertEqual(len(storage.get_turns("s1")), 2)
        self.assertEqual(storage.get_trace("r1")["events"][0]["details"]["action"], "quiz")
        self.assertAlmostEqual(storage.get_usage("s1")["totals"]["estimated_cost_usd"], 0.0000135)

    def test_tracked_model_call_records_tokens_and_price(self):
        import observability
        import storage
        storage.start_run("r2", "setup")
        response = AIMessage(content="hello", usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        runnable = AsyncMock()
        runnable.ainvoke.return_value = response

        async def invoke():
            with observability.run_context("r2"):
                return await observability.tracked_invoke(runnable, ["prompt"], model="openai/gpt-oss-20b", operation="test")

        self.assertEqual(asyncio.run(invoke()).content, "hello")
        usage = storage.get_usage()["calls"][0]
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(usage["output_tokens"], 20)
        self.assertAlmostEqual(usage["estimated_cost_usd"], 0.0000135)

    def test_running_run_becomes_interrupted_on_restart(self):
        import storage
        storage.start_run("stale", "setup")
        storage.mark_abandoned_runs()
        self.assertEqual(storage.get_trace("stale")["run"]["status"], "interrupted")

    def test_api_turn_resume_and_trace(self):
        from api import main as api
        import storage
        plan = StudyPlan(title="Example", total_estimated_hours=2, skills_acquired=[], disclaimer="",
                         modules=[Module(module_number=n, title=f"Module {n}", estimated_hours=1, priority="RED",
                                         disclaimer="", topics=[Topic(topic_number=1, title="Routes", source_url="https://docs.example.com", skills_acquired=[])])
                                  for n in (1, 2)])
        storage.create_session("api-s1", "https://docs.example.com", "Example", "kb-api-s1", plan.model_dump_json())
        result = {"messages": [AIMessage(content="Module two answer")], "anchor_urls": ["https://docs.example.com/routes"],
                  "struggle_signals": {}, "notes_written": False, "pending_quiz": {}, "mastery_scores": {}}
        with patch("api.main.chroma_client.get_collection", return_value=object()), patch(
            "api.main.session_app.ainvoke", new_callable=AsyncMock, return_value=result
        ) as graph:
            response = asyncio.run(api.chat("api-s1", api.SessionRequest(message="What is a route?", current_module_number=2)))
            run_id = response["run_id"]
            self.assertEqual(graph.call_args.args[0]["current_module_number"], 2)
            resumed = api.resume("api-s1")
            self.assertEqual(resumed["current_module_number"], 2)
            self.assertEqual(len(resumed["messages"]), 2)
            self.assertEqual(api.trace(run_id)["run"]["status"], "completed")

    def test_setup_stream_persists_session_and_attaches_run(self):
        from api import main as api
        import storage
        plan = StudyPlan(title="Example", total_estimated_hours=1, skills_acquired=[], disclaimer="",
                         modules=[Module(module_number=1, title="Basics", estimated_hours=1, priority="RED",
                                         disclaimer="", topics=[])])

        async def consume():
            return [json.loads(item.removeprefix("data: ")) async for item in api.setup_stream("https://docs.example.com")]

        with patch("api.main.setup_graph.ainvoke", new_callable=AsyncMock,
                   return_value={"study_plan": plan, "resolved_url": "https://docs.example.com/guide"}):
            events = asyncio.run(consume())
        done = next(item for item in events if item["type"] == "done")
        self.assertEqual(storage.get_session(done["session_id"])["url"], "https://docs.example.com/guide")
        self.assertEqual(done["resolved_url"], "https://docs.example.com/guide")
        self.assertEqual(storage.get_trace(done["run_id"])["run"]["session_id"], done["session_id"])

    def test_setup_failure_exposes_actionable_code_and_trace(self):
        from api import main as api
        from agent.nodes import IndexCoverageError

        async def consume():
            return [json.loads(item.removeprefix("data: ")) async for item in api.setup_stream("https://docs.example.com")]

        with patch("api.main.setup_graph.ainvoke", new_callable=AsyncMock,
                   side_effect=IndexCoverageError("Only 1/5 pages indexed")):
            events = asyncio.run(consume())
        failure = next(item for item in events if item["type"] == "error")
        self.assertEqual(failure["code"], "insufficient_index_coverage")
        self.assertEqual(api.trace(failure["run_id"])["run"]["status"], "failed")


class AgentDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_quiz_routes_to_grading_without_model_call(self):
        from agent.nodes import choose_action_node
        state = {"user_input": "A route connects a URL to a function", "pending_quiz": {"question": "Explain routes"}}
        result = await choose_action_node(state)
        self.assertEqual(result["action"], "grade")

    async def test_explicit_quiz_request_routes_to_quiz(self):
        from agent.nodes import choose_action_node
        result = await choose_action_node({"user_input": "quiz me", "pending_quiz": {}})
        self.assertEqual(result["action"], "quiz")

    async def test_empty_retrieval_avoids_unsupported_llm_answer(self):
        from agent.nodes import study_session_node
        plan = StudyPlan(title="Example", total_estimated_hours=1, skills_acquired=[], disclaimer="",
                         modules=[Module(module_number=1, title="Basics", estimated_hours=1, priority="RED",
                                         disclaimer="", topics=[Topic(topic_number=1, title="Routes", source_url="https://docs.example.com", skills_acquired=[])])])
        state = {"user_input": "What is a route?", "collection": object(), "current_module_number": 1,
                 "study_plan": plan, "messages": [], "struggle_signals": {}, "anchor_urls": []}
        with patch("agent.nodes.asyncio.to_thread", new_callable=AsyncMock, return_value=[]):
            result = await study_session_node(state)
        self.assertIn("couldn't find relevant evidence", result["messages"][-1].content)

    async def test_grading_updates_mastery_and_struggle_checkpoint(self):
        from agent.nodes import grade_quiz_node
        from schemas.models import QuizEvaluation
        state = {"user_input": "I don't know", "pending_quiz": {
            "concept": "routes", "question": "What is a route?", "expected_answer": "A URL-to-handler mapping",
        }, "mastery_scores": {"routes": 0.5}, "struggle_signals": {}, "messages": []}
        with patch("agent.nodes.ChatGroq"), patch("agent.nodes.tracked_invoke", new_callable=AsyncMock,
                                                   return_value=QuizEvaluation(correct=False, feedback="Review path mapping", concept="routes")):
            result = await grade_quiz_node(state)
        self.assertEqual(result["mastery_scores"]["routes"], 0.35)
        self.assertEqual(result["pending_quiz"], {})
        self.assertIn("What is a route?", result["struggle_signals"])

    async def test_vault_memory_reaches_answer_prompt(self):
        from agent.nodes import study_session_node
        plan = StudyPlan(title="Example", total_estimated_hours=1, skills_acquired=[], disclaimer="",
                         modules=[Module(module_number=1, title="Basics", estimated_hours=1, priority="RED",
                                         disclaimer="", topics=[])])
        state = {"user_input": "What is a route?", "collection": object(), "current_module_number": 1,
                 "study_plan": plan, "messages": [HumanMessage(content="Earlier question")],
                 "struggle_signals": {}, "anchor_urls": [], "vault_context": "Routes were difficult last time"}
        chunks = [{"text": "A route maps a path to a handler.", "metadata": {"anchor_url": "https://docs.example.com/routes"}}]
        with patch("agent.nodes.asyncio.to_thread", new_callable=AsyncMock, return_value=chunks), patch(
            "agent.nodes.ChatGroq"
        ), patch("agent.nodes.tracked_invoke", new_callable=AsyncMock, return_value=AIMessage(content="A route maps a path.")) as invoke:
            result = await study_session_node(state)
        self.assertIn("Routes were difficult last time", invoke.call_args.args[1][1].content)
        self.assertEqual(result["anchor_urls"], ["https://docs.example.com/routes"])


class SafetyTests(unittest.TestCase):
    def test_private_and_malformed_urls_rejected(self):
        from rag.security import validate_public_url
        for url in ("file:///etc/passwd", "http://localhost:8000", "http://127.0.0.1", "https://user:pass@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url)

    def test_title_is_safe_vault_stem(self):
        from memory.vault import note_key
        self.assertEqual(note_key("C/C++: Basics"), "C-C- Basics")


if __name__ == "__main__":
    unittest.main()
