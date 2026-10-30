"""The node pack README and per-node DESCRIPTION must cover every registered node."""
import ast
from pathlib import Path

PACK = Path(__file__).resolve().parents[1] / "custom_nodes" / "opensoul_nodes"


def _classes_with_description():
    tree = ast.parse((PACK / "nodes.py").read_text())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(getattr(t, "id", "") == "DESCRIPTION" for t in stmt.targets):
                    out[node.name] = ast.literal_eval(stmt.value)
    return out


def _display_names():
    tree = ast.parse((PACK / "nodes.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "NODE_DISPLAY_NAME_MAPPINGS":
            return ast.literal_eval(node.value)
    raise AssertionError("NODE_DISPLAY_NAME_MAPPINGS not found")


def test_every_node_has_description_and_readme_entry():
    names = _display_names()
    descs = _classes_with_description()
    readme = (PACK / "README.md").read_text()
    for cls, display in names.items():
        assert descs.get(cls), f"{cls} has no DESCRIPTION"
        assert display in readme, f"README does not document {display}"


def test_readme_lists_every_env_var():
    doc = (PACK / "nodes.py").read_text().split('"""')[1]
    readme = (PACK / "README.md").read_text()
    for var in [w for w in doc.split() if w.startswith("OPENSOUL_")]:
        assert f"`{var}`" in readme, f"README missing {var}"
