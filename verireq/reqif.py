"""ReqIF 1.x import and export.

The subset written here is the interchange shape common tools accept:
a header, string and XHTML datatypes, one specification object type,
parent and depends-on relations, and a specification hierarchy. Import also
reads looser files that only carry SPEC-OBJECTs. No tool-vendor schema is
copied. Attribute names are ordinary labels (ReqIF.Text, ReqIF.ForeignID,
Verification Method, Verification Status), not a vendor extension.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import List
from xml.etree import ElementTree as ET

from .safe_xml import parse_xml

from .brand import PRODUCT_NAME
from .models import Requirement

NS = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XHTML = "http://www.w3.org/1999/xhtml"
REQIF_VERSION = "1.1"

_PARENT_NAMES = {"parent", "parent requirement", "derived from", "satisfies"}
_DEPENDS_NAMES = {"depends on", "dependency", "depends", "refines"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag else ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def loads(data: bytes) -> List[Requirement]:
    root = parse_xml(data)
    attr_names = {}
    rel_types = {}
    for el in root.iter():
        kind = _local(el.tag)
        ident = el.get("IDENTIFIER")
        if not ident:
            continue
        if kind.startswith("ATTRIBUTE-DEFINITION-"):
            attr_names[ident] = el.get("LONG-NAME") or ""
        elif kind == "SPEC-RELATION-TYPE":
            rel_types[ident] = (el.get("LONG-NAME") or "").strip().lower()

    objects = {}
    order: List[Requirement] = []
    by_req_id = {}
    for obj in root.iter():
        if _local(obj.tag) != "SPEC-OBJECT":
            continue
        values = {}
        loose = []
        for node in obj.iter():
            kind = _local(node.tag)
            if kind not in {"ATTRIBUTE-VALUE-STRING", "ATTRIBUTE-VALUE-XHTML"}:
                continue
            if kind == "ATTRIBUTE-VALUE-STRING":
                val = node.get("THE-VALUE") or ""
            else:
                val = ""
                for child in node.iter():
                    if _local(child.tag) == "THE-VALUE":
                        val = _clean("".join(child.itertext()))
                        break
            def_id = _child_text(node, {"ATTRIBUTE-DEFINITION-STRING-REF", "ATTRIBUTE-DEFINITION-XHTML-REF"})
            name = (attr_names.get(def_id) or "").strip().lower()
            if name:
                values[name] = val
            if val:
                loose.append(val)
        text = _first(values, ("reqif.text", "text", "requirement", "requirement text"))
        if not text and loose:
            text = max(loose, key=len)
        rid = _first(values, ("reqif.foreignid", "foreign id", "foreignid", "id", "identifier"))
        rid = rid or obj.get("LONG-NAME") or ""
        gen = False
        if not rid:
            gen = True
            rid = f"AUTO-{len(order) + 1:03d}"
        parent = _first(values, ("parent", "parent id", "parent requirement"))
        depends = _split_ids(_first(values, ("depends on", "dependencies", "dependency")))
        status = _first(values, ("verification status",)) or "Not started"
        method = _first(values, ("verification method",))
        req = Requirement(
            id=rid.strip(), text=_clean(text), source="reqif", id_generated=gen,
            parent_id=parent.strip(), depends_on=depends,
            verification_status=status.strip() or "Not started",
            method_override=method.strip(),
        )
        objects[obj.get("IDENTIFIER")] = req
        order.append(req)
        by_req_id.setdefault(req.id, req)

    for rel in root.iter():
        if _local(rel.tag) != "SPEC-RELATION":
            continue
        type_id = _child_text(rel, {"SPEC-RELATION-TYPE-REF"})
        kind = rel_types.get(type_id, "")
        source = objects.get(_child_text(rel, {"SPEC-OBJECT-REF"}, under={"SOURCE"}))
        target = objects.get(_child_text(rel, {"SPEC-OBJECT-REF"}, under={"TARGET"}))
        if source is None or target is None or source is target:
            continue
        if kind in _DEPENDS_NAMES:
            if target.id not in source.depends_on:
                source.depends_on.append(target.id)
        else:
            # Parent, or an unnamed relation: source is the child.
            if not source.parent_id:
                source.parent_id = target.id

    _apply_hierarchy(root, objects)
    return order


def dumps(reqs: List[Requirement], title: str = "Requirements") -> bytes:
    ET.register_namespace("", NS)
    ET.register_namespace("xhtml", XHTML)
    stamp = _stamp()
    root = ET.Element(_q("REQ-IF"))
    header = ET.SubElement(root, _q("THE-HEADER"))
    hdr = ET.SubElement(header, _q("REQ-IF-HEADER"), {"IDENTIFIER": "_header"})
    _text(hdr, "COMMENT", f"{PRODUCT_NAME} interchange file. Advisory draft.")
    _text(hdr, "CREATION-TIME", stamp)
    _text(hdr, "REQ-IF-TOOL-ID", PRODUCT_NAME)
    _text(hdr, "REQ-IF-VERSION", REQIF_VERSION)
    _text(hdr, "SOURCE-TOOL-ID", PRODUCT_NAME)
    _text(hdr, "TITLE", title or "Requirements")

    content = ET.SubElement(ET.SubElement(root, _q("CORE-CONTENT")), _q("REQ-IF-CONTENT"))
    dts = ET.SubElement(content, _q("DATATYPES"))
    ET.SubElement(dts, _q("DATATYPE-DEFINITION-STRING"), {
        "IDENTIFIER": "_dt_string", "LONG-NAME": "String", "MAX-LENGTH": "32000", "LAST-CHANGE": stamp,
    })
    ET.SubElement(dts, _q("DATATYPE-DEFINITION-XHTML"), {
        "IDENTIFIER": "_dt_xhtml", "LONG-NAME": "XHTML", "LAST-CHANGE": stamp,
    })

    types = ET.SubElement(content, _q("SPEC-TYPES"))
    sot = ET.SubElement(types, _q("SPEC-OBJECT-TYPE"), {
        "IDENTIFIER": "_sot", "LONG-NAME": "Requirement", "LAST-CHANGE": stamp,
    })
    attrs = ET.SubElement(sot, _q("SPEC-ATTRIBUTES"))
    _attr_string(attrs, "_ad_id", "ReqIF.ForeignID", stamp)
    _attr_xhtml(attrs, "_ad_text", "ReqIF.Text", stamp)
    _attr_string(attrs, "_ad_method", "Verification Method", stamp)
    _attr_string(attrs, "_ad_status", "Verification Status", stamp)

    for ident, name in (("_rt_parent", "Parent"), ("_rt_depends", "Depends On")):
        rt = ET.SubElement(types, _q("SPEC-RELATION-TYPE"), {
            "IDENTIFIER": ident, "LONG-NAME": name, "LAST-CHANGE": stamp,
        })
        ET.SubElement(rt, _q("SPEC-ATTRIBUTES"))

    st = ET.SubElement(types, _q("SPECIFICATION-TYPE"), {
        "IDENTIFIER": "_st", "LONG-NAME": "Specification", "LAST-CHANGE": stamp,
    })
    ET.SubElement(st, _q("SPEC-ATTRIBUTES"))

    objects = ET.SubElement(content, _q("SPEC-OBJECTS"))
    id_to_spec = {}
    for i, req in enumerate(reqs):
        spec_id = f"_obj_{i}"
        id_to_spec[req.id] = spec_id
        obj = ET.SubElement(objects, _q("SPEC-OBJECT"), {
            "IDENTIFIER": spec_id, "LONG-NAME": req.id, "LAST-CHANGE": stamp,
        })
        tref = ET.SubElement(obj, _q("TYPE"))
        ET.SubElement(tref, _q("SPEC-OBJECT-TYPE-REF")).text = "_sot"
        values = ET.SubElement(obj, _q("VALUES"))
        _value_string(values, "_ad_id", req.id)
        _value_xhtml(values, "_ad_text", req.text)
        _value_string(values, "_ad_method", req.method_override or "")
        _value_string(values, "_ad_status", req.verification_status or "Not started")

    relations = ET.SubElement(content, _q("SPEC-RELATIONS"))
    rel_i = 0
    for req in reqs:
        if req.parent_id and req.parent_id in id_to_spec and req.parent_id != req.id:
            _relation(relations, rel_i, "_rt_parent", id_to_spec[req.id], id_to_spec[req.parent_id], stamp)
            rel_i += 1
        for dep in req.depends_on:
            if dep in id_to_spec and dep != req.id:
                _relation(relations, rel_i, "_rt_depends", id_to_spec[req.id], id_to_spec[dep], stamp)
                rel_i += 1

    specs = ET.SubElement(content, _q("SPECIFICATIONS"))
    spec = ET.SubElement(specs, _q("SPECIFICATION"), {
        "IDENTIFIER": "_spec", "LONG-NAME": title or "Requirements", "LAST-CHANGE": stamp,
    })
    tref = ET.SubElement(spec, _q("TYPE"))
    ET.SubElement(tref, _q("SPECIFICATION-TYPE-REF")).text = "_st"
    children = ET.SubElement(spec, _q("CHILDREN"))
    _write_hierarchy(children, reqs, id_to_spec)

    buf = io.BytesIO()
    tree = ET.ElementTree(root)
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _write_hierarchy(parent_el, reqs: List[Requirement], id_to_spec: dict) -> None:
    by_parent = {}
    for req in reqs:
        by_parent.setdefault(req.parent_id if req.parent_id in id_to_spec else "", []).append(req)
    seen = set()

    def emit(container, req, index):
        if req.id in seen:
            return
        seen.add(req.id)
        node = ET.SubElement(container, _q("SPEC-HIERARCHY"), {"IDENTIFIER": f"_h_{index[0]}"})
        index[0] += 1
        obj = ET.SubElement(node, _q("OBJECT"))
        ET.SubElement(obj, _q("SPEC-OBJECT-REF")).text = id_to_spec[req.id]
        kids = by_parent.get(req.id) or []
        if kids:
            box = ET.SubElement(node, _q("CHILDREN"))
            for kid in kids:
                emit(box, kid, index)

    index = [0]
    for req in by_parent.get("", []):
        emit(parent_el, req, index)
    for req in reqs:
        if req.id not in seen:
            emit(parent_el, req, index)


def _relation(parent, index, type_id, source_id, target_id, stamp):
    rel = ET.SubElement(parent, _q("SPEC-RELATION"), {
        "IDENTIFIER": f"_rel_{index}", "LAST-CHANGE": stamp,
    })
    typ = ET.SubElement(rel, _q("TYPE"))
    ET.SubElement(typ, _q("SPEC-RELATION-TYPE-REF")).text = type_id
    src = ET.SubElement(rel, _q("SOURCE"))
    ET.SubElement(src, _q("SPEC-OBJECT-REF")).text = source_id
    tgt = ET.SubElement(rel, _q("TARGET"))
    ET.SubElement(tgt, _q("SPEC-OBJECT-REF")).text = target_id


def _attr_string(parent, ident, name, stamp):
    el = ET.SubElement(parent, _q("ATTRIBUTE-DEFINITION-STRING"), {
        "IDENTIFIER": ident, "LONG-NAME": name, "LAST-CHANGE": stamp,
    })
    typ = ET.SubElement(el, _q("TYPE"))
    ET.SubElement(typ, _q("DATATYPE-DEFINITION-STRING-REF")).text = "_dt_string"


def _attr_xhtml(parent, ident, name, stamp):
    el = ET.SubElement(parent, _q("ATTRIBUTE-DEFINITION-XHTML"), {
        "IDENTIFIER": ident, "LONG-NAME": name, "LAST-CHANGE": stamp,
    })
    typ = ET.SubElement(el, _q("TYPE"))
    ET.SubElement(typ, _q("DATATYPE-DEFINITION-XHTML-REF")).text = "_dt_xhtml"


def _value_string(parent, def_id, value):
    el = ET.SubElement(parent, _q("ATTRIBUTE-VALUE-STRING"), {"THE-VALUE": value or ""})
    d = ET.SubElement(el, _q("DEFINITION"))
    ET.SubElement(d, _q("ATTRIBUTE-DEFINITION-STRING-REF")).text = def_id


def _value_xhtml(parent, def_id, value):
    el = ET.SubElement(parent, _q("ATTRIBUTE-VALUE-XHTML"))
    d = ET.SubElement(el, _q("DEFINITION"))
    ET.SubElement(d, _q("ATTRIBUTE-DEFINITION-XHTML-REF")).text = def_id
    body = ET.SubElement(el, _q("THE-VALUE"))
    div = ET.SubElement(body, f"{{{XHTML}}}div")
    div.text = value or ""


def _text(parent, tag, value):
    el = ET.SubElement(parent, _q(tag))
    el.text = value
    return el


def _first(values: dict, names) -> str:
    for name in names:
        if values.get(name):
            return values[name]
    return ""


def _split_ids(raw: str) -> list:
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]


def _child_text(node, names: set, under: set | None = None) -> str:
    for el in node.iter():
        if under is not None and _local(el.tag) not in under and el is not node:
            # Only search inside the requested wrapper elements.
            continue
        if under is not None and _local(el.tag) in under:
            for child in el.iter():
                if _local(child.tag) in names and (child.text or "").strip():
                    return child.text.strip()
            continue
        if _local(el.tag) in names and (el.text or "").strip() and el is not node:
            return el.text.strip()
    return ""


def _apply_hierarchy(root, objects: dict) -> None:
    def walk(node, parent_req):
        for child in list(node):
            if _local(child.tag) != "SPEC-HIERARCHY":
                walk(child, parent_req)
                continue
            ref = _child_text(child, {"SPEC-OBJECT-REF"}, under={"OBJECT"})
            req = objects.get(ref)
            if req is not None and parent_req is not None and not req.parent_id and req is not parent_req:
                req.parent_id = parent_req.id
            for box in list(child):
                if _local(box.tag) == "CHILDREN":
                    walk(box, req if req is not None else parent_req)

    for el in root.iter():
        if _local(el.tag) == "SPECIFICATION":
            for box in list(el):
                if _local(box.tag) == "CHILDREN":
                    walk(box, None)
