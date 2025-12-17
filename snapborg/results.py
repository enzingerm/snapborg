import enum
from typing import Callable, Optional, Sequence, Self


class ResultStatus(enum.Enum):
    OK = 0
    WARN = 1
    ERR = 2


class CommandResult:
    def __init__(
        self,
        message: Optional[str] = None,
        children: Sequence[Self] = [],
        status: Optional[ResultStatus] = None,
        task_description: Optional[str] = None,
    ):
        self.message = message
        self.children = children
        self._status = status
        self.task_description = task_description

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
        if self.task_description:
            output = f"{self.status.name.ljust(5)} {self.task_description}\n"
            if self.message:
                output += f"       ↳ {self.message}\n"
        else:
            output = self.status.name.ljust(5) + (f" {self.message}" if self.message else "") + "\n"
        output += "\n".join(
            [f"  {line}" for child in self.children for line in child.get_output().splitlines()]
        )
        return output

    @classmethod
    def ok(cls, message: Optional[str] = None, children: Sequence[Self] = []) -> Self:
        return cls(message, children=children, status=ResultStatus.OK)

    @classmethod
    def warn(cls, message: Optional[str] = None, children: Sequence[Self] = []) -> Self:
        return cls(message, children=children, status=ResultStatus.WARN)

    @classmethod
    def err(cls, message: Optional[str] = None, children: Sequence[Self] = []) -> Self:
        return cls(message, children=children, status=ResultStatus.ERR)

    @classmethod
    def from_children(
        cls,
        children: Sequence[Self],
        message: Optional[str] = None,
        task_description: Optional[str] = None,
    ):
        return cls(message, children, task_description=task_description)


class Command:
    def __init__(self, task: str, executor: Callable[[], CommandResult]):
        self.task = task
        self.executor = executor

    def __call__(self, *args, **kwds) -> CommandResult:
        result = self.executor()
        result.task_description = self.task
        return result
