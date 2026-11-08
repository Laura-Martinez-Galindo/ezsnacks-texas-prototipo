# EzSnack Impuestos

Módulo externo que se conecta a **QuickBooks Online** por su API oficial para:

1. **Unir las ventas** de los lectores (Nayax, AB360 y otros) con el vendor list y enviarlas a QuickBooks como recibos de venta por máquina. Cada recibo lleva la **dirección de la máquina** (`ShipFromAddr`), así que QuickBooks calcula solo el impuesto de Texas, la ciudad de Houston o MTA. Los productos exentos (agua) se marcan en QuickBooks.
2. **Revisar los recibos** de compras en Walmart, Restaurant Depot y H-E-B que ya se guardaron en QuickBooks. Compara cada renglón con los productos registrados, separa el renglón de impuesto y avisa lo que no reconoce.
3. **Calcular y registrar las comisiones** de los socios que consiguen locaciones (por ejemplo, 10 %).

QuickBooks sigue siendo el sistema contable. El módulo no borra nada en QuickBooks y no duplica un mes que ya se envió.

## Estructura

| Carpeta / archivo | Qué es |
|---|---|
| `app.py` | La interfaz para Humberto (Streamlit) |
| `ezsnack/qbo.py` | Conexión OAuth 2.0 con QuickBooks, tokens y renovación |
| `ezsnack/consolidar.py` | Lectura y unión de los Excel de los lectores y el vendor list |
| `ezsnack/emparejar.py` | Reconoce productos por nombre y detecta renglones de impuesto |
| `ezsnack/servicios.py` | Envía ventas, revisa recibos y registra comisiones en QuickBooks |
| `config/columnas.json` | Qué columna de cada Excel es cada dato. **Ajustar con los archivos reales** |
| `config/catalogo.json` | Productos, proveedores, socios y cuentas de prueba |
| `config/alias.json` | Equivalencias aprendidas ("DORITOS NCH 1OZ" = "Doritos Nacho Cheese 1 oz") |
| `scripts/preparar_sandbox.py` | Limpia los datos de ejemplo del sandbox y carga los de EzSnack |
| `scripts/generar_datos_prueba.py` | Crea Excel de prueba en `datos_prueba/` |
| `tests/` | Pruebas sin conexión (`python -m pytest -q`) |

## Puesta en marcha (computador del equipo o de Humberto)

1. Instalar Python 3.11 o superior (python.org; en Windows marcar "Add Python to PATH").
2. Copiar `.env.example` como `.env` y pegar el Client ID y el Client Secret de la app de Intuit
   (developer.intuit.com > su app > Keys & credentials). **No compartir ni subir `.env`.**
3. En la app de Intuit, agregar la Redirect URI `http://localhost:8501/`.
4. Windows: doble clic en `iniciar.bat`. Mac/Linux:
   ```
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   streamlit run app.py
   ```
5. En la página que se abre, clic en **Conectar con QuickBooks** y autorizar la empresa sandbox.
6. Solo la primera vez, preparar el sandbox:
   ```
   python scripts/preparar_sandbox.py --limpiar              # muestra qué se borraría, no cambia nada
   python scripts/preparar_sandbox.py --limpiar --confirmar  # borra (pide escribir BORRAR)
   python scripts/preparar_sandbox.py --cargar               # crea productos, proveedores y cuentas de EzSnack
   ```

## Despliegue

| Opción | Costo | Para qué sirve | Ojo |
|---|---|---|---|
| **Computador local** (`iniciar.bat`) | Gratis | Demo del 24 de noviembre y primeras pruebas de Humberto | Solo funciona en ese computador |
| **Streamlit Community Cloud** | Gratis | Que Humberto lo use desde un enlace, sin instalar nada | Permite una sola app privada por cuenta; los secretos van en *Settings > Secrets*; la Redirect URI debe ser la URL `https://...streamlit.app/`; si la app se reinicia hay que volver a conectar |

Para usarlo con la empresa **real** de Humberto falta pasar la **revisión de la app de Intuit** (llaves de producción: cuestionario de seguridad y 1 a 2 semanas de espera) y cambiar `QBO_ENVIRONMENT=production`.

## Supuestos que hay que confirmar con datos reales

- Las columnas de los Excel de Nayax y AB360 (`config/columnas.json`). Solo "Machine" y "Product" se vieron en las capturas del taller.
- Que los montos de los reportes no incluyan el impuesto. Si lo incluyen, hay que descontarlo antes de enviar.
- Las direcciones exactas de cada máquina en el vendor list.
