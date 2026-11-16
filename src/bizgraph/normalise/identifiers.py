"""Identifier validators. A checksum-valid identifier is the only thing the
exact path is allowed to trust; anything else falls to the name paths."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from bizgraph.domain.models import IdScheme, Identifier

_NON_DIGIT = re.compile(r"\D")
_NON_ALNUM = re.compile(r"[^0-9A-Z]")


class IdentifierValidator(ABC):
    scheme: IdScheme

    @abstractmethod
    def normalise(self, raw: str) -> str: ...

    @abstractmethod
    def is_valid(self, value: str) -> bool: ...

    def parse(self, raw: str | None) -> Identifier | None:
        """Normalise and validate; return None when absent or invalid."""
        if not raw:
            return None
        value = self.normalise(raw)
        return Identifier(self.scheme, value) if self.is_valid(value) else None


class AbnValidator(IdentifierValidator):
    """ABN: 11 digits. Subtract 1 from the first digit, weight, sum mod 89 == 0."""

    scheme = IdScheme.ABN
    _weights = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)

    def normalise(self, raw: str) -> str:
        return _NON_DIGIT.sub("", raw)

    def is_valid(self, value: str) -> bool:
        if len(value) != 11 or not value.isdigit() or value[0] == "0":
            return False
        digits = [int(c) for c in value]
        digits[0] -= 1
        return sum(d * w for d, w in zip(digits, self._weights)) % 89 == 0


class AcnValidator(IdentifierValidator):
    """ACN (also ARBN): 9 digits, weights 8..1 on the first 8, complement mod 10 is the check digit."""

    scheme = IdScheme.ACN
    _weights = (8, 7, 6, 5, 4, 3, 2, 1)

    def normalise(self, raw: str) -> str:
        return _NON_DIGIT.sub("", raw)

    def is_valid(self, value: str) -> bool:
        if len(value) != 9 or not value.isdigit():
            return False
        total = sum(int(c) * w for c, w in zip(value[:8], self._weights))
        return (10 - total % 10) % 10 == int(value[8])

    @staticmethod
    def from_abn(abn: str) -> str | None:
        """For companies, the last 9 digits of the ABN are the ACN. Only trust this if it validates."""
        candidate = abn[2:] if len(abn) == 11 else ""
        return candidate if AcnValidator().is_valid(candidate) else None


class LeiValidator(IdentifierValidator):
    """LEI (ISO 17442): 20 alphanumerics, ISO 7064 mod 97-10 check == 1."""

    scheme = IdScheme.LEI

    def normalise(self, raw: str) -> str:
        return _NON_ALNUM.sub("", raw.upper())

    def is_valid(self, value: str) -> bool:
        if len(value) != 20 or not value.isalnum():
            return False
        numeric = "".join(str(int(c, 36)) for c in value)
        return int(numeric) % 97 == 1


class LicenceNumberValidator(IdentifierValidator):
    """AFSL / ACL numbers: digits only, no public checksum, so format check only."""

    def __init__(self, scheme: IdScheme) -> None:
        self.scheme = scheme

    def normalise(self, raw: str) -> str:
        return _NON_DIGIT.sub("", raw).lstrip("0")

    def is_valid(self, value: str) -> bool:
        return value.isdigit() and 1 <= len(value) <= 9


_VALIDATORS: dict[IdScheme, IdentifierValidator] = {
    IdScheme.ABN: AbnValidator(),
    IdScheme.ACN: AcnValidator(),
    IdScheme.ARBN: AcnValidator(),
    IdScheme.ARSN: AcnValidator(),
    IdScheme.LEI: LeiValidator(),
    IdScheme.AFSL: LicenceNumberValidator(IdScheme.AFSL),
    IdScheme.ACL: LicenceNumberValidator(IdScheme.ACL),
}


def validator_for(scheme: IdScheme) -> IdentifierValidator:
    return _VALIDATORS[scheme]
