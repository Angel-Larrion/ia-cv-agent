import numpy as np

import rag


def test_proyectos_has_51_consecutive_chunks():
    fragmentos = rag.leer_fragmentos()
    assert len(fragmentos) == 51
    assert [f["id"] for f in fragmentos] == list(range(51))
    assert all(f["titulo"] and f["texto"] for f in fragmentos)


def test_index_matches_document_and_is_normalized():
    # cargar_indice raises if the model, dimensions or content hash do not match
    fragmentos, matriz = rag.cargar_indice()
    assert matriz.shape == (51, rag.DIMENSIONES)
    assert len(fragmentos) == 51
    assert np.allclose(np.linalg.norm(matriz, axis=1), 1.0, atol=1e-4)


def test_buscar_returns_k_chunks_best_first(monkeypatch):
    _, matriz = rag.cargar_indice()
    monkeypatch.setattr(rag, "embeber", lambda texto, tarea, rapido=False: matriz[3])
    resultado = rag.buscar("pregunta cualquiera")
    assert len(resultado) == rag.K
    assert resultado[0]["id"] == 3
    puntajes = [f["puntaje"] for f in resultado]
    assert puntajes == sorted(puntajes, reverse=True)


def test_buscar_uses_up_to_three_query_vectors(monkeypatch):
    _, matriz = rag.cargar_indice()
    textos = []

    def falso(texto, tarea, rapido=False):
        textos.append((texto, tarea, rapido))
        return matriz[0]

    monkeypatch.setattr(rag, "embeber", falso)
    rag.buscar("Cuéntame más", [])
    assert len(textos) == 1
    textos.clear()
    rag.buscar("Cuéntame más", ["uno", "dos", "tres"])
    assert len(textos) == 3
    assert all(t[1] == "RETRIEVAL_QUERY" and t[2] is True for t in textos)
    assert {t[0] for t in textos} == {"Cuéntame más", "tres Cuéntame más", "dos tres Cuéntame más"}
