from __future__ import annotations

from parser_worker import app as worker


def test_capabilities_do_not_claim_uninstalled_backends(monkeypatch):
    modules = {"raganything": True, "docling": False, "paddleocr": False, "pypdfium2": False}
    monkeypatch.setattr(worker, "_module_available", lambda name: modules.get(name, False))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/mineru" if name == "mineru" else None)

    profiles = {item["id"]: item for item in worker.capabilities()["profiles"]}

    assert profiles["mineru"]["available"] is True
    assert profiles["docling"]["available"] is False
    assert profiles["docling"]["reason"] == "docling Python package is not installed"
    assert profiles["paddleocr"]["available"] is False
    assert profiles["paddleocr"]["reason"]


def test_missing_raganything_disables_every_profile(monkeypatch):
    monkeypatch.setattr(worker, "_module_available", lambda _name: False)
    monkeypatch.setattr(worker.shutil, "which", lambda _name: None)

    result = worker.profile_availability()

    assert all(not item["available"] for item in result.values())
    assert {item["reason"] for item in result.values()} == {"raganything is not installed"}
