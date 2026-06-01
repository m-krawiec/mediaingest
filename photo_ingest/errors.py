from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    USAGE_ERROR = 10
    SOURCE_ERROR = 11
    DEST_ERROR = 12
    CONFLICT = 13
    COPY_ERROR = 20
    VERIFY_ERROR = 21
    INTERRUPTED = 30


class IngestError(Exception):
    def __init__(self, message: str, exit_code: ExitCode = ExitCode.USAGE_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(IngestError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.USAGE_ERROR)


class SourceError(IngestError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.SOURCE_ERROR)


class DestError(IngestError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.DEST_ERROR)


class ConflictError(IngestError):
    def __init__(self, import_id: str) -> None:
        super().__init__(
            f"import_id '{import_id}' already exists. "
            "Use --resume to continue a partial copy, or --auto-seq for a new id.",
            ExitCode.CONFLICT,
        )
        self.import_id = import_id


class CopyError(IngestError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.COPY_ERROR)


class VerifyError(IngestError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.VERIFY_ERROR)
