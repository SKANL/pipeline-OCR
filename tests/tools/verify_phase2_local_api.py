"""Prueba de contrato HTTP en proceso sobre fixtures locales; sin servidor."""
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.tools.phase2_evidence import QUERIES


def main():
    parsed = urlsplit(get_settings().mongodb_uri)
    if parsed.scheme != "mongodb" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or "," in parsed.netloc:
        raise SystemExit("La verificación exige MongoDB loopback")
    client = TestClient(app)
    for name, queries in QUERIES.items():
        total = 0
        for number, query in queries:
            response = client.get(f"/api/v1/ref/{name}/pagina/{number}", params={"q": query})
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["motor"] == "pypdfium2"
            assert page["imagen_url"].startswith("/media/")
            assert page["coincidencias"]
            assert not page["coincidencias_truncadas"]
            assert "posiciones" not in page
            for match in page["coincidencias"]:
                assert match["precision"] == "exacta" and match["rects"]
                assert 0 <= match["inicio"] < match["fin"] <= len(page["texto"])
            total += len(page["coincidencias"])
            image = client.get(f"/api/v1/pages/{name}/pagina/{number}/imagen")
            assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        print(name, total, "coincidencias exactas; API q e imagen original correctas")


if __name__ == "__main__":
    main()
