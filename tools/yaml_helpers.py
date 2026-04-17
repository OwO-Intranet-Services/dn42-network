from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


class LenientSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that treats unknown tags like plain YAML values."""


def _construct_unknown_tag(loader: LenientSafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node)
    raise TypeError(f"Unsupported YAML node: {type(node)!r}")


LenientSafeLoader.add_constructor(None, _construct_unknown_tag)


def load_yaml_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.load(handle, Loader=LenientSafeLoader)
