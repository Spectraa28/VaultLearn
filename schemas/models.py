from pydantic import BaseModel , Field

class UrlResponse(BaseModel):
    url:str=Field(description="This is the url for the input technology")
    
class Topic(BaseModel):
    topic_number:int=Field(description="This is the topic no. given by LLM to the particular topic")
    title:str=Field(description="This is the title of the topic")
    source_url:str=Field(description="this is the source url for the Topic")
    skills_acquired:list[str]=Field(description="this is the skills that the student aquired after doing these topics")

class Module(BaseModel):
    module_number:int=Field(description="This is the module no. which enables easy retrieval and relevent chunks to llm")
    title:str=Field(description="This is the module title that is given by the llm")
    estimated_hours:float=Field(description="THis is the estimated hours calculated by llm that will be required for the module")
    priority:str=Field(description="This is the priority of different modules classified as HIGH, LOW, MEDIUM")
    estimated_refined:bool=Field(default=False,description="This is the estimated hours that is required to complete the module but this time we have to content of the pages so it will be lil bit accurate")
    disclaimer:str=Field(description="This is a warning that the earlier estimated_hours is calculated on the basis of title only ")
    topics :list[Topic]=Field(description="THis is the list of sub topics under the each module")

class StudyPlan(BaseModel):
    title:str=Field(description="This is the title of the main topic that the user is learning")
    total_estimated_hours:float=Field(description="This is the total time that will be required to complete the full study plan")
    skills_acquired:list[str]=Field(description="This is the comprehensive list of all the skills aquired after completing the study plan")
    disclaimer:str=Field(description="This is the disclaimer that tells that the estimated times are depended on the user speed.")
    modules: list[Module]=Field(description="This is the list of modules under the study plan")