# EzSnack Impuestos

Prototipo para EzSnack Texas, una empresa de máquinas expendedoras en Houston. Cada mes, el gerente calcula a mano el impuesto a las ventas que le debe al estado de Texas: une los reportes de los lectores de tarjeta de sus máquinas, separa los productos que no pagan impuesto, descuenta lo que compró con impuesto ya pagado y reparte las ventas según la jurisdicción de cada máquina. Este proceso le toma entre tres y cinco días. El prototipo lo reduce a unos pocos pasos sobre el sistema contable que la empresa ya usa, QuickBooks Online.

## Cómo funciona

La página tiene tres pasos que siguen el orden del cierre del mes.

En el primero se suben la lista de máquinas y los reportes de ventas de cada lector, ya sea Nayax, AB360 u otro. El programa une todas las ventas por máquina y producto, separa el agua, que está exenta, y avisa si encuentra una máquina que no está en la lista o un producto que no reconoce. Cuando el usuario elige a qué producto corresponde un nombre desconocido, el programa lo recuerda para los meses siguientes. Al enviar, se crea en QuickBooks un recibo de venta por máquina con la dirección de esa máquina, y es QuickBooks quien calcula el impuesto del estado, de la ciudad de Houston o del área metropolitana que corresponda.

En el segundo se revisan las compras hechas en Walmart, Restaurant Depot o H-E-B, que ya pagaron impuesto en la caja. La foto del recibo se sube en QuickBooks, que la lee, y el programa compara cada renglón con los productos registrados, separa el valor del impuesto pagado y marca lo que no reconoce para que el usuario lo confirme.

En el tercero se calculan las comisiones de quienes le consiguen locaciones a la empresa, a partir de las ventas de sus máquinas, y se registran en QuickBooks como una factura a nombre de cada socio.

A la derecha, un tiquete parecido al de una máquina resume el mes: ventas, exentas, ventas gravables por jurisdicción, impuesto estimado, impuesto calculado por QuickBooks, impuesto ya pagado en compras y comisiones.

## Cómo se conecta con QuickBooks

QuickBooks Online no permite instalar módulos por dentro, así que el prototipo funciona como una aplicación externa conectada por la API oficial de Intuit. QuickBooks sigue siendo el sistema contable y el lugar donde se calcula el impuesto oficial. El programa solo hace lo que QuickBooks no hace por sí mismo: unir los reportes de los distintos lectores, reconocer los productos de los recibos y calcular las comisiones.

Cada persona que entra a la página conecta su propia empresa de QuickBooks. Esa conexión queda guardada de forma cifrada en su navegador y no en el servidor, de modo que nadie puede ver ni modificar una empresa que no haya autorizado. Mientras la aplicación use las llaves de desarrollo de Intuit, solo se puede conectar a empresas de prueba, llamadas sandbox. Para conectarla a la empresa real hace falta pasar la revisión de aplicaciones de Intuit, que incluye un cuestionario de seguridad y toma entre una y dos semanas.

## Probarla sin archivos propios

En el primer paso hay un enlace para probar con los datos de ejemplo de septiembre de 2026. Esos archivos están en la carpeta datos_prueba y son ficticios: los nombres de productos salen de las capturas del taller con la empresa, las máquinas 158 y 160 tienen sus direcciones reales y las demás usan edificios públicos de Houston, Bellaire y Katy como dirección de ejemplo. Los nombres de columnas de los reportes también son supuestos, porque en el taller solo se alcanzaron a ver las columnas Machine y Product. Cuando lleguen los reportes reales, basta con ajustar el archivo config/columnas.json, sin cambiar el código.

La sección Preparar el sandbox deja la empresa de prueba lista la primera vez. Primero quita los datos de ejemplo que trae Intuit, después carga los productos, proveedores y cuentas de EzSnack y, si se quiere, agrega dos compras de prueba para el segundo paso.

## Publicarla en internet

La aplicación está preparada para Render, que tiene un plan gratuito sin tarjeta de crédito. En ese plan la aplicación se duerme después de quince minutos sin uso y tarda cerca de un minuto en despertar con la siguiente visita.

Para publicarla, se entra a render.com con la cuenta de GitHub, se elige crear un Blueprint y se selecciona este repositorio. Render lee el archivo render.yaml y pide tres valores: el Client ID y el Client Secret de la aplicación de Intuit, y la dirección de regreso, que es la dirección que Render le asigna a la aplicación seguida de /auth/callback. Esa misma dirección de regreso se agrega en la configuración de la aplicación en developer.intuit.com, en Settings, Redirect URIs.

## Correrla en un computador

Se necesita Python 3.11 o superior. Dentro de la carpeta del proyecto se copia el archivo .env.example con el nombre .env, se completan sus valores y se ejecuta:

```
pip install -r requirements.txt
uvicorn web.main:app --port 8000
```

La página queda en http://localhost:8000. Para que la conexión con QuickBooks funcione en el computador, la dirección http://localhost:8000/auth/callback debe estar registrada en la aplicación de Intuit.

## Organización del código

La carpeta ezsnack contiene la lógica: qbo.py maneja la conexión con QuickBooks, consolidar.py une los reportes, emparejar.py reconoce productos por nombre, servicios.py envía ventas, revisa compras y registra comisiones, y preparar.py prepara el sandbox. La carpeta web contiene el servidor, en main.py, y la página, en static. La carpeta config guarda el catálogo de prueba, las columnas de cada reporte, las tarifas de referencia y las equivalencias de nombres aprendidas. Las pruebas automáticas están en tests y se ejecutan con python -m pytest.

## Lo que falta confirmar con la empresa

Falta recibir un reporte real de cada lector para ajustar las columnas, confirmar si los montos de los reportes ya incluyen el impuesto y completar la dirección exacta de cada máquina en la lista. También falta definir sobre qué base se calcula la comisión de cada socio y cada cuánto se paga.
