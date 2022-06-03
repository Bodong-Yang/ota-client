r"""Import extra modules path."""


def load_path():
    import sys
    from pathlib import Path

    _project_base = Path(__file__).parent.parent
    _app = _project_base / "app"

    sys.path.insert(0, str(_project_base))
    sys.path.insert(0, str(_app))


load_path()

del load_path
