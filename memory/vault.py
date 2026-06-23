import os
from pathlib import Path
from datetime import date ,timedelta
from schemas.models import StudyPlan
from langchain_groq import ChatGroq
from langchain_core.messages import  SystemMessage,HumanMessage

def write_note(file_name: str, content:str):
    os.makedirs("vault",exist_ok=True)
    with open(f"vault/{file_name}.md","w",encoding="utf-8")  as file:
        file.write(content)
        
def read_note(file_name: str) -> str:
    file_name = f"vault/{file_name}.md"
    if not os.path.exists(file_name):
        return None
    with open(file_name, "r",encoding="utf-8")  as file:
        return file.read()
    
def list_notes() -> list[str]:
    if not os.path.exists("vault"):
        return []
    return [f.name for f in Path("vault").iterdir() if f.is_file()]

async def generate_session_note(study_plan: StudyPlan, messages: list, module_number: int) -> str:
    title = study_plan.title
    dates = date.today()
    module = next((m for m in study_plan.modules if m.module_number == module_number), None)
    module_title = module.title if module else "Unknown"
    module_covered = f"{module_number}. {module_title}"
    takeaways = await extract_key_takeaways(messages, title)
    takeaways_md = "\n".join(f"- {t}" for t in takeaways)
    return f"""# Session Note

        **Topic:** {title}
        **Date:** {dates}
        **Module Covered:** {module_covered}
        **Messages Exchanged:** {len(messages or [])}
        
        **Key Takeaways:**
        {takeaways_md}
        """

def generate_struggle_note(struggle_signals: dict, topic: str) -> str:
    struggled_list = "\n".join(f"- **{q}**: {r}" for q, r in struggle_signals.items())
    flagged = len(struggle_signals) > 0
    return f"""# Struggle Note
        **Topic:** {topic}
        **Date:** {date.today()}
        **Struggled with :** {struggled_list}
        **Flaggged for review :** {flagged}
            """
            
def generate_review_schedule(struggle_signals: dict, topic: str) -> str:
    struggle_score = min(len(struggle_signals) / 10, 1.0)

    if struggle_score > 0.5:
        days = 1
    elif struggle_score > 0.2:
        days = 3
    else:
        days = 7

    next_review = date.today() + timedelta(days=days)
    
    return f"""# Review Schedule
            **Topic: ** {topic}
            **score: ** {struggle_score}
            **Next review date**:{next_review}
            """

async def extract_key_takeaways(messages: list, topic: str) -> list[str]:
    model = ChatGroq(model="llama-3.1-8b-instant")
    conversation = "\n".join([
        f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}"
        for m in (messages or [])
    ])
    response = await model.ainvoke([
        SystemMessage("Extract 3-5 key learning points from this study session as a bullet list. Return only the points, no preamble."),
        HumanMessage(f"Topic: {topic}\n\nConversation:\n{conversation}")
    ])
    points = [line.strip("- ").strip() for line in response.content.splitlines() if line.strip()]
    return points