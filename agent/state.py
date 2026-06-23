from typing import TypedDict, List , Optional
from langchain_core.messages import BaseMessage
from schemas.models import StudyPlan

class VaultLearnState(TypedDict):
    user_input: str
    resolved_url: Optional[str]
    pages: Optional[list]
    study_plan: Optional[StudyPlan]
    current_module_number: Optional[int]
    module_ready: Optional[bool]
    messages: Optional[list[BaseMessage]]
    session_active: Optional[bool]
    struggle_signals: Optional[dict]
    struggle_scores: Optional[dict]
    notes_written: Optional[bool]
    collection: Optional[object]