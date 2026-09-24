import fluon
import fluon._native


def test_import() -> None:
    assert fluon.__name__ == "fluon"
    assert fluon._native.__name__ == "fluon._native"
