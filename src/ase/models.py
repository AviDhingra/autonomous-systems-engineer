from pydantic import BaseModel


class FixProposal(BaseModel):
    file_path: str
    explanation: str
    new_content: str
