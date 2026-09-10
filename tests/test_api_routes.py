"""Tests for the Evaluator AI REST API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gemini_act.chat.app import app

client = TestClient(app)


def test_healthz_endpoint() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "model" in data


def test_ui_endpoint_returns_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Evaluator AI" in response.text
    # Verificăm că se servește index.html din React (are div id=root)
    assert '<div id="root">' in response.text


def test_get_demo_audit() -> None:
    response = client.get("/api/audit/demo")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "date_audit" in data
    assert "data" in data
    assert "pdf_url" in data
    assert "pdf_download_url" in data
    audit = data["data"]
    assert audit["complex_name"] == "Aviatiei Park"
    assert audit["scor_general"] == 8.8
    assert "audit_electrocasnice" in audit
    assert "evaluare_anevar" in audit
    assert "audit_targetare" in audit


def test_generate_audit_demo_mode() -> None:
    # Test cu alias-uri folosite de frontend: url și is_demo
    response = client.post(
        "/api/audit/generate",
        json={"url": "https://www.imobiliare.ro/oferta/demo", "is_demo": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data
    assert "date_audit" in data
    assert "pdf_url" in data
    assert "pdf_download_url" in data
    assert data["pdf_download_url"].startswith("/api/audit/pdf/")

    # Verificăm că PDF-ul generat poate fi descărcat
    filename = data["pdf_url"].replace("/api/audit/pdf/", "")
    pdf_resp = client.get(f"/api/audit/pdf/{filename}")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers.get("content-type") == "application/pdf"
    assert len(pdf_resp.content) > 1000


def test_download_pdf_security_traversal() -> None:
    # Test directory traversal attack
    response = client.get("/api/audit/pdf/../../etc/passwd")
    assert response.status_code in (400, 404)

    # Test non-pdf file
    response = client.get("/api/audit/pdf/malicious.sh")
    assert response.status_code == 400


def test_demo_audit_carries_a_location_block() -> None:
    """The web report's map, Street View and amenity list all hang off this."""
    response = client.get("/api/audit/demo")
    audit = response.json()["data"]

    assert "locatie" in audit
    locatie = audit["locatie"]
    # Without a Maps key configured (as in CI) this degrades rather than fails.
    assert locatie["status"] in {"success", "indisponibil"}
    if locatie["status"] == "success":
        assert locatie["harta"]["raza_m"] == 500
        assert locatie["harta"]["url"].startswith("/api/audit/imagery/roadmap")
        assert locatie["satelit"]["url"].startswith("/api/audit/imagery/aerial")


def test_demo_audit_includes_the_full_report_chapters() -> None:
    """The web report renders these sections; a missing key silently hides one."""
    audit = client.get("/api/audit/demo").json()["data"]

    for chapter in (
        "rezumat_executiv",
        "puncte_forte",
        "puncte_slabe",
        "metodologie",
        "ipoteze_limitative",
        "analiza_piata",
        "riscuri",
        "costuri_detinere",
        "esg",
    ):
        assert audit.get(chapter), f"lipsește capitolul {chapter}"

    evaluare = audit["evaluare_anevar"]
    for block in ("abordare_venit", "abordare_cost", "reconciliere", "senzitivitate"):
        assert evaluare.get(block), f"lipsește {block}"
    assert all(comp.get("ajustari") for comp in evaluare["comparabile_utilizate"])


def test_imagery_endpoints_reject_out_of_range_geometry() -> None:
    """Static Maps caps a side at 640; asking for more would 400 upstream."""
    too_wide = client.get("/api/audit/imagery/roadmap?lat=44.5&lon=26.1&w=2000&h=480")
    assert too_wide.status_code == 422
    assert client.get("/api/audit/imagery/roadmap?lat=44.5&lon=26.1&zoom=30").status_code == 422
    assert (
        client.get("/api/audit/imagery/streetview?lat=44.5&lon=26.1&heading=400").status_code == 422
    )


def test_location_endpoint_accepts_explicit_coordinates() -> None:
    response = client.get("/api/audit/location?adresa=test&lat=44.5&lon=26.1&raza_m=500")
    assert response.status_code == 200
    assert response.json()["status"] in {"success", "indisponibil"}
