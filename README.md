# EzSnack Impuestos

Prototipo para EzSnack Texas, una empresa de máquinas expendedoras en Houston. Cada mes el gerente declara y paga el impuesto a las ventas ante el Texas Comptroller. Para hacerlo descarga los reportes de cuatro lectores de tarjeta distintos (Nayax, AV360, XMAI y Qingo), le pide a ChatGPT que los una, revisa duplicados, y en Excel le resta las devoluciones, el agua, que no paga impuesto, y los productos que compró por fuera con el impuesto ya pagado. Después filtra a mano las máquinas de Houston y las de Bellaire, Katy y Spring para calcular los impuestos locales. Este proceso le toma alrededor de una hora cada mes y depende de que ChatGPT sume bien. El prototipo hace todo el cálculo a partir de los mismos archivos y deja un Excel de respaldo para una auditoría del estado.

## Cómo funciona

La página sigue el orden del cierre del mes y está en español, aunque los reportes de los lectores vienen en inglés.

En el primer paso se suben el vendor list de la empresa, los reportes de ventas de los lectores y, si se quiere, un Excel con una sola columna llamada Product con lo que se compró ese mes en Walmart u otra tienda pagando impuesto. El programa reconoce cada reporte por sus columnas, sin importar el nombre del archivo. De Nayax toma cada transacción y descarta las rechazadas, que quedan con valor cero, y la fila de total. De AV360, XMAI y Qingo toma una fila por máquina y producto. Las ventas de XMAI y Qingo cuentan como tarjeta, porque esas máquinas no reciben efectivo. Cada venta se asocia a su máquina por el número que aparece en el nombre ("EzSnack 146"), y de la máquina se toma la ciudad y el socio del vendor list. Las filas del vendor list marcadas como old son ubicaciones anteriores y no se usan.

En el segundo paso se confirman los productos exentos y los comprados con impuesto pagado. El programa propone como exenta el agua sin endulzar, es decir, los productos que dicen water o agua, salvo los que llevan azúcar, como Vitamin Water o el agua de coco. La lista de compras se cruza con los productos vendidos. Si un renglón dice el tamaño, por ejemplo Sunkist 16 oz, solo se marcan los productos de ese tamaño, con una onza de tolerancia. Si el nombre vendido no dice el tamaño, queda para que el usuario decida. Un producto que ya es exento no se descuenta dos veces.

En el tercer paso aparece la declaración en el mismo orden del formulario del Comptroller. Las ventas totales son el efectivo más la tarjeta, menos un tres por ciento de devoluciones a clientes, como hace hoy la empresa. A eso se le restan el agua y los productos ya pagados para llegar a las ventas gravables, sobre las que se calcula el 6.25 % del estado. Para los impuestos locales se hace el mismo cálculo solo con las máquinas de cada jurisdicción: las de Houston van a HOUSTON-CITY (2101017) y las de Bellaire, Katy y Spring a HOUSTON MTA (3101990), las dos al 1 %. Al final se resta el descuento del 0.5 % por presentar a tiempo. Al hacer clic en un valor se copia para pegarlo en la página del Comptroller.

En el cuarto paso se calculan las comisiones. A ProCity se le paga el 10 % de las ventas de cada máquina que consiguió, solo si esa máquina vendió más de 300 dólares en el mes. A North American University se le paga el 10 % de las ventas netas de sus máquinas, descontando el 5.95 % de lo vendido con tarjeta y 15 dólares al mes por cada lector. VMS y MR aparecen en el vendor list, pero sus reglas no se explicaron, así que quedan por confirmar. Las reglas se pueden cambiar en la página.

En el quinto paso se descarga el Excel del cierre, con las ventas integradas, el resumen por máquina, la declaración, las comisiones y el detalle de qué filas de cada archivo se usaron. Si se conecta QuickBooks, también se registra el cierre como dos tipos de facturas por pagar: una al Texas Comptroller por el impuesto, con vencimiento el 20 del mes siguiente, y una por la comisión de cada socio.

## Por qué una aplicación propia y para qué QuickBooks

Ningún sistema que ya tiene la empresa hace este cálculo completo. Cada lector calcula un impuesto de referencia solo para sus propias máquinas y con una tasa fija del 6.25 %, sin las tasas locales ni las devoluciones. QuickBooks podría calcular el impuesto por dirección, pero exige registrar cada venta como una transacción y la empresa no usa ese módulo. Además, el gerente piensa cambiarse a Zoho Books porque QuickBooks le resulta costoso. El Comptroller solo recibe los totales. Por eso el prototipo no reemplaza ningún sistema. Se integra con los que ya existen: lee los archivos que exportan los cuatro lectores y el vendor list tal como salen, entrega las cifras en el formato del Comptroller y registra el resultado en el sistema contable por su API.

El cálculo no necesita QuickBooks. La conexión es opcional y sirve para que el impuesto por pagar y las comisiones queden en la contabilidad. Hoy se conecta con QuickBooks Online porque es el sistema que la empresa usa. Si la empresa se pasa a Zoho Books, basta con cambiar el archivo ezsnack/contabilidad.py por uno que cree las mismas facturas de proveedor con la API de Zoho, que está disponible en los planes pagos de Zoho Books.

## Verificación con septiembre de 2026

Con los archivos reales de septiembre, el programa cuadra al centavo con el total que cada lector trae en su propio reporte. El Excel que se armó con ChatGPT suma unos dólares menos en efectivo y tarjeta que los reportes originales. Las ventas de las máquinas de Bellaire, Katy y Spring dan igual que en el Excel del gerente.

Las diferencias que quedan vienen de valores que el gerente sacó filtrando a mano: el total de agua, la lista de productos comprados con impuesto pagado ese mes y la lista de máquinas de Houston. Las cifras que pagó en el Comptroller tampoco salen de las fórmulas de su Excel, así que falta que él confirme cuáles fueron los valores de agua, compras y máquinas que usó ese mes. La página muestra esta comparación renglón por renglón cuando se suben los archivos de septiembre y la instalación tiene las cifras de referencia, que se cargan en la variable VERIFICACION_JSON y no están en el repositorio.

Los archivos reales de la empresa no se publican en este repositorio. La carpeta datos_prueba tiene archivos con el mismo formato, pero con máquinas y ventas inventadas, y se generan con scripts/generar_datos_prueba.py.

## Publicarla en internet

La aplicación está publicada en Render, en https://ezsnack-impuestos.onrender.com. Los archivos que se suben se leen en memoria y se borran a las tres horas, no se guardan en disco. Para publicarla de nuevo se entra a render.com con la cuenta de GitHub, se crea un Blueprint con este repositorio y se completan el Client ID, el Client Secret y la dirección de regreso de la aplicación de Intuit, que es la dirección que asigna Render seguida de /auth/callback. Esa misma dirección se agrega en developer.intuit.com, en Settings, Redirect URIs. Sin esos valores la página funciona igual, solo que sin el registro en QuickBooks.

## Correrla en un computador

Se necesita Python 3.11 o superior. Dentro de la carpeta del proyecto se copia el archivo .env.example con el nombre .env, se completan sus valores si se quiere conectar QuickBooks y se ejecuta:

```
pip install -r requirements.txt
uvicorn web.main:app --port 8000
```

La página queda en http://localhost:8000.

## Organización del código

La carpeta ezsnack contiene la lógica. lectores.py reconoce y lee los reportes de cada lector, maquinas.py lee el vendor list, productos.py reconoce el agua y cruza la lista de compras, cierre.py hace el cálculo de la declaración y de las comisiones, libro.py arma el Excel del cierre, contabilidad.py registra el cierre en QuickBooks y qbo.py maneja la conexión con Intuit. Las tasas, las jurisdicciones y las reglas de comisión están en config/reglas.json. La carpeta web tiene el servidor y la página. Las pruebas automáticas están en tests y se ejecutan con python -m pytest.

## Lo que falta confirmar con la empresa

Falta que el gerente confirme las reglas de comisión de VMS y MR y si el porcentaje de North American University es 10 % o 12 %. También falta definir si los cupones que compran las empresas para sus empleados deben sumarse como ventas, porque hoy no se suman. También conviene revisar con el contador dos puntos. El primero es que la tasa de Houston de 8.25 % incluye el 1 % de la ciudad y el 1 % del MTA, mientras que hoy al MTA solo se le declaran las máquinas de Bellaire, Katy y Spring. El segundo es que lo comprado con impuesto pagado se descuenta por su valor de venta y no por su costo.
