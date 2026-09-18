"""Compatibility entry points and grounded study-plan construction."""

from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq

from observability import PLAN_MODEL, tracked_invoke
from rag.crawler import crawl_js_sidebar, crawl_sidebar, crawl_structure
from rag.discovery import find_docs_link, is_docs_page, resolve_url
from schemas.models import Module, PlannedStudyPlan, StudyPlan, Topic


async def generate_study_plan(pages: list[dict], topic: str) -> StudyPlan:
    if not pages:
        raise ValueError("Cannot generate a study plan without documentation pages")
    selected_pages = pages[:30]
    page_choices = [{"index": index, "title": page.get("title", "")}
                    for index, page in enumerate(selected_pages)]
    model = ChatGroq(model=PLAN_MODEL).with_structured_output(PlannedStudyPlan, include_raw=True)
    planned = await tracked_invoke(model, [SystemMessage(f"""Create a structured learning plan for {topic}.
Use only these documentation page indexes and titles: {page_choices}
Return modules with page_indexes from the list. Do not invent URLs. Group related pages.
Priority must be RED (core), YELLOW (important), or BLUE (optional).
""")], model=PLAN_MODEL, operation="generate_plan")

    modules = []
    used = set()
    for proposal in planned.modules:
        topics = []
        for page_index in proposal.page_indexes:
            if page_index < 0 or page_index >= len(selected_pages) or page_index in used:
                continue
            page = selected_pages[page_index]
            used.add(page_index)
            topics.append(Topic(topic_number=len(topics) + 1, title=page["title"],
                                source_url=page["url"], skills_acquired=proposal.skills_acquired))
        if topics:
            modules.append(Module(module_number=len(modules) + 1, title=proposal.title,
                                  estimated_hours=proposal.estimated_hours, priority=proposal.priority,
                                  estimated_refined=False,
                                  disclaimer="Estimate based on documentation page titles only", topics=topics))
    missing = [page for index, page in enumerate(selected_pages) if index not in used]
    if missing:
        topics = [Topic(topic_number=index + 1, title=page["title"], source_url=page["url"],
                        skills_acquired=[]) for index, page in enumerate(missing)]
        modules.append(Module(module_number=len(modules) + 1, title="Additional Documentation",
                              estimated_hours=max(1, round(len(topics) * 0.5)), priority="BLUE",
                              estimated_refined=False, disclaimer="Pages not assigned by planner", topics=topics))
    return StudyPlan(title=planned.title or topic, total_estimated_hours=planned.total_estimated_hours,
                     skills_acquired=planned.skills_acquired,
                     disclaimer=planned.disclaimer or "Estimates depend on learner speed.", modules=modules)
