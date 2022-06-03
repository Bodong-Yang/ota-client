from enum import unique, Enum


class OtaError(Exception):
    ...


class OtaErrorBusy(OtaError):
    ...


class OtaErrorRecoverable(OtaError):
    ...


class OtaErrorUnrecoverable(OtaError):
    ...


@unique
class OtaClientFailureType(Enum):
    NO_FAILURE = 0
    RECOVERABLE = 1
    UNRECOVERABLE = 2
