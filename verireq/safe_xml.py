"""Parse untrusted XML without external entities or entity expansion bombs.

ReqIF and JUnit uploads are attacker-controlled. The standard library parser
is not a safe default for that, so every untrusted parse goes through defusedxml.
"""
from __future__ import annotations

from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import fromstring as _fromstring
from defusedxml.common import DefusedXmlException


def parse_xml(data: bytes):
    if not isinstance(data, (bytes, bytearray)):
        data = str(data).encode("utf-8")
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("XML is larger than 15 MB.")
    try:
        return _fromstring(data)
    except (DefusedXmlException, ParseError) as exc:
        raise ValueError("XML was rejected.") from exc
