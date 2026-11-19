import json
import time
from datetime import date

from rag import DATA, DIMENSIONES, MODELO_EMBED, embeber, hash_fragmentos, leer_fragmentos

ESPERADOS = 51
DESTINO = DATA / "index.json"
PAUSA = 0.7  # segundos entre llamadas; el límite es de 100 por minuto


def main():
    fragmentos = leer_fragmentos()
    # Si una edición rompe un encabezado, el script se detiene aquí
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
    # Se guarda al final: si algo falla a la mitad, no queda un índice incompleto
    DESTINO.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {len(fragmentos)} fragmentos en {DESTINO.name} ({DESTINO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
