import enum
from typing import Optional, Sequence, Self, List

class ResultStatus(enum.Enum):
    OK = 0
    WARN = 1
    ERR = 2

class CommandResult:
    def __init__(self, message: str, children: Sequence[Self] = [], status: Optional[ResultStatus] = None):
        self.message = message
        self.children = children
        self._status = status
    
    @property
    def status(self) -> ResultStatus:
        if self._status != None:
            return self._status

        if all(it.status == ResultStatus.OK for it in self.children):
            return ResultStatus.OK
        elif any(it.status == ResultStatus.ERR for it in self.children):
            return ResultStatus.ERR
        else:
            return ResultStatus.WARN

    @status.setter
    def set_status(self, value: ResultStatus):
        self._status = value
    
    def get_output(self) -> str:
        return f"{self.status.name.ljust(5)} {self.message}\n" + \
            "\n".join([ f"  {line}" for child in self.children for line in child.get_output().splitlines()])
    
    @classmethod
    def ok(cls, message, children: Sequence[Self] = []) -> Self:
        return cls(message, children=children,status=ResultStatus.OK)

    @classmethod
    def warn(cls, message, children: Sequence[Self] = []) -> Self:
        return cls(message, children=children, status=ResultStatus.WARN)

    @classmethod
    def err(cls, message, children: Sequence[Self] = []) -> Self:
        return cls(message, children=children, status=ResultStatus.ERR)
    
    @classmethod
    def from_children(cls, children: Sequence[Self], message: str = ""):
        return cls(message, children)
