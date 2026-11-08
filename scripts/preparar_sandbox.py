"""Deja el sandbox de QuickBooks con datos de EzSnack (lo mismo que la pestaña "Preparar sandbox" de la app).

Uso, desde la carpeta del proyecto y despues de conectarse en la app:
    python scripts/preparar_sandbox.py --limpiar              # solo MUESTRA que se borraria
    python scripts/preparar_sandbox.py --limpiar --confirmar  # borra (pide escribir BORRAR)
    python scripts/preparar_sandbox.py --cargar               # crea cuentas, productos, proveedores y cliente

La limpieza borra las transacciones de ejemplo del sandbox y marca como inactivos los clientes,
proveedores y productos de ejemplo. No se puede deshacer. Solo funciona en el sandbox.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ezsnack.preparar import cargar_datos, ejecutar_limpieza, es_sandbox, plan_limpieza, resumen_plan  # noqa: E402
from ezsnack.qbo import QBO  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limpiar", action="store_true")
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--cargar", action="store_true")
    args = ap.parse_args()
    if not (args.limpiar or args.cargar):
        ap.print_help()
        return
    qbo = QBO()
    if args.limpiar:
        if not es_sandbox():
            sys.exit("Por seguridad, la limpieza solo funciona con QBO_ENVIRONMENT=sandbox.")
        empresa = qbo.info_empresa().get("CompanyName")
        plan = plan_limpieza(qbo)
        print(f"Empresa: {empresa}")
        for f in resumen_plan(plan):
            print(f"  {f['accion']:10s} {f['tipo']:15s} {f['cantidad']}")
        if not args.confirmar:
            print("No se cambio nada. Para ejecutar: agregue --confirmar")
        elif input(f"Esto borra datos de '{empresa}' y NO se puede deshacer. Escriba BORRAR: ").strip() == "BORRAR":
            errores = ejecutar_limpieza(qbo, plan)
            print(f"Limpieza terminada. Errores: {len(errores)}")
            for e in errores:
                print("  ", e)
        else:
            print("Cancelado. No se cambio nada.")
    if args.cargar:
        for linea in cargar_datos(qbo):
            print(linea)


if __name__ == "__main__":
    main()
