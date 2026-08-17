"""
Compara dos retratos de botones y enseña SOLO lo que ha cambiado.

Un diff de texto sobre dos ficheros JSON de 300 botones es ilegible: cambia el
orden de las claves, sobran las llaves y las comas, y lo importante —qué botón
dice ahora otra cosa— se pierde. Esto lo dice en una línea por botón.

    python tools/snapshot_diff.py /tmp/antes.json /tmp/despues.json

Sale con código 1 si hay diferencias, para poder encadenarlo, y con 0 cuando
los dos retratos son idénticos. Un retrato idéntico después de un cambio
grande es la mejor noticia posible: has movido código sin mover el producto.

La única regla al leer la lista: cada diferencia tiene que ser una que
esperabas. La que no esperabas es el fallo que ibas a desplegar.
"""

import json
import sys


def cargar(ruta):

    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


def resumir(entrada, limite=220):
    """Una línea legible de lo que produjo un botón."""

    if entrada is None:
        return "(no existía)"

    partes = []

    for salida in entrada.get("salida") or []:

        # (método, texto, teclado)
        texto = str(salida[1] if len(salida) > 1 else "").replace("\n", " ⏎ ")
        partes.append(f"{salida[0]}: {texto}")

    if not partes:
        return f"[{entrada.get('status', '?')}] (sin salida capturada)"

    linea = " | ".join(partes)

    return f"[{entrada.get('status', '?')}] {linea[:limite]}"


def main():

    if len(sys.argv) != 3:

        print(__doc__)

        return 2

    antes, despues = cargar(sys.argv[1]), cargar(sys.argv[2])

    claves = sorted(set(antes) | set(despues))
    distintos = [k for k in claves if antes.get(k) != despues.get(k)]

    nuevos = [k for k in distintos if k not in antes]
    perdidos = [k for k in distintos if k not in despues]
    cambiados = [k for k in distintos if k in antes and k in despues]

    print(f"botones: {len(claves)}   iguales: {len(claves) - len(distintos)}   "
          f"cambiados: {len(cambiados)}   nuevos: {len(nuevos)}   "
          f"desaparecidos: {len(perdidos)}")

    if not distintos:

        print()
        print("Retratos idénticos: el producto no se ha movido.")

        return 0


    for clave in cambiados:

        print()
        print(f"~ {clave}")
        print(f"    antes:  {resumir(antes[clave])}")
        print(f"    ahora:  {resumir(despues[clave])}")


    for clave in nuevos:

        print()
        print(f"+ {clave}")
        print(f"    ahora:  {resumir(despues[clave])}")


    for clave in perdidos:

        print()
        print(f"- {clave}  ← este botón ya no existe. ¿A propósito?")
        print(f"    antes:  {resumir(antes[clave])}")


    print()
    print("Cada diferencia tiene que ser una que esperabas.")

    return 1


if __name__ == "__main__":

    sys.exit(main())
