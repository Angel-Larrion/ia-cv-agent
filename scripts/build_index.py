import json
import time
from datetime import date

from rag import DATA, DIMENSIONES, MODELO_EMBED, embeber, hash_fragmentos, leer_fragmentos

ESPERADOS = 51
DESTINO = DATA / "index.json"
PAUSA = 0.7  # seconds between calls; the limit is 100 per minute


def main():
    """Compute every chunk's embedding and write data/index.json."""
    fragmentos = leer_fragmentos()
    # Stops here if an edit broke a heading
    assert len(fragmentos) == ESPERADOS, (
        f"Se esperaban {ESPERADOS} fragmentos y salieron {len(fragmentos)}"
    )

    for i, f in enumerate(fragmentos, 1):
        v = embeber(f["titulo"] + "\n" + f["texto"], "RETRIEVAL_DOCUMENT")
        assert len(v) == DIMENSIONES
        f["vector"] = [round(float(x), 6) for x in v]
        print(f"{i}/{len(fragmentos)}  {f['titulo'][:60]}")
        time.sleep(PAUSA)

    indice = {
        "modelo": MODELO_EMBED,
        "dimensiones": DIMENSIONES,
        "fecha": date.today().isoformat(),
        "hash": hash_fragmentos(fragmentos),
        "fragmentos": fragmentos,
    }
    # Saved only at the end: no half-built index if it fails
    DESTINO.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {len(fragmentos)} fragmentos en {DESTINO.name} ({DESTINO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
