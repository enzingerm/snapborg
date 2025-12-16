class SnapborgBaseException(Exception):
    _description = "Error occured during snapborg execution"

    def __str__(self):
        cause = f": {self.__cause__}" if self.__cause__ else ""
        if len(self.args) > 0 and isinstance(self.args[0], str):
            return f"{self._description}: {self.args[0]}{cause}"
        return f"{self._description}{cause}"


class SnapperTooOldException(SnapborgBaseException): ...


class SnapperExecutionException(SnapborgBaseException):
    _description = "Error occured during snapper execution"


class BorgExecutionException(SnapborgBaseException):
    def __init__(self, returncode: int):
        self.returncode = returncode

    def __str__(self):
        return f"Error during borg execution, borg return code: {self.returncode}"


class InvalidParameterException(SnapborgBaseException):
    _description = "Invalid parameter value given to borg"


class ConfigError(SnapborgBaseException):
    _description = "Error in snapborg config"


class PermissionError(SnapborgBaseException):
    _description = "Permission error occured during snapborg execution"


class BindMountError(SnapborgBaseException):
    _description = (
        "An error occured while handling bind mounts (maybe you need to run this as root?)"
    )
