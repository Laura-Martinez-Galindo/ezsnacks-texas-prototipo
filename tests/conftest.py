"""Las pruebas usan una base de datos temporal y vacia cada una, nunca la de la aplicacion."""
import os
import tempfile

import pytest

os.environ.pop("DATABASE_URL", None)
os.environ["DATOS_DIR"] = tempfile.mkdtemp(prefix="ezsnack_pruebas_")


@pytest.fixture(autouse=True)
def base_limpia(tmp_path, monkeypatch):
    from ezsnack import almacen
    monkeypatch.setenv("DATOS_DIR", str(tmp_path / "datos"))
    almacen.reiniciar()
    yield
    almacen.reiniciar()
