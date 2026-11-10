# EzSnack Impuestos

Prototipo para EzSnack Texas, una empresa de máquinas expendedoras en Houston.

Cada mes el gerente declara y paga el impuesto a las ventas ante el Texas Comptroller. Para hacerlo descarga los reportes de cuatro lectores de tarjeta distintos, le pide a ChatGPT que los una, revisa duplicados, y en Excel le resta las devoluciones, el agua, que no paga impuesto, y los productos que compró por fuera con el impuesto ya pagado. Después filtra a mano las máquinas de Houston y las de Bellaire, Katy y Spring para separar los impuestos locales. Le toma cerca de una hora y depende de que ChatGPT sume bien.

## Quién hace cada paso

| Paso | Antes | Ahora |
|---|---|---|
| Descargar los reportes de cada lector | El gerente | El gerente |
| Unir los cuatro reportes | ChatGPT | La aplicación |
| Revisar duplicados y nombres distintos | El gerente, a ojo | La aplicación |
| Separar el agua | Filtro en Excel | La aplicación |
| Separar lo comprado con impuesto pagado | Filtro en Excel | La aplicación |
| Separar cupones de venta y de devolución | Estimado del 3 % | La aplicación |
| Cruzar las máquinas de Houston y del MTA | Dos pantallas en paralelo | La aplicación |
| Calcular el impuesto | Tasa fija en Excel | QuickBooks |
| Guardar el respaldo para una auditoría | Excel a mano | La aplicación |
| Digitar y pagar en el Comptroller | El gerente | El gerente |

## Cómo funciona

La página está en español y tiene tres pasos. Los reportes de los lectores se suben tal como salen, en inglés.

En el primero se suben el vendor list, los reportes de ventas y un Excel con la columna Product con lo que se compró ese mes pagando impuesto. El programa reconoce cada reporte por sus columnas, descarta las transacciones rechazadas de Nayax y une todo por lector, máquina y producto. La ciudad de cada máquina sale del vendor list, por el número que aparece en su nombre.

En el segundo se confirma qué no paga impuesto. El agua sin endulzar es exenta. Los productos de la lista de compras se descuentan porque su impuesto ya se pagó en la caja: si la lista dice el tamaño, por ejemplo Sunkist 16 oz, solo se marcan los de ese tamaño. Y los cupones se separan en dos: los que una empresa compra cada mes para sus empleados son una venta y pagan impuesto, y los que se le mandan a quien reclama que la máquina no le entregó el producto son una devolución y se restan. Se distinguen por el monto del mes: en septiembre las dos máquinas de Hoerbiger suman 735.25 dólares en cupones y las demás no pasan de 25.

En el tercero aparece el resumen del mes, los valores que se digitan en la página del Comptroller, el Excel de respaldo y el envío a QuickBooks.

## Qué hace la aplicación y qué hace QuickBooks

La regla es usar lo que ya existe y construir solo lo que falta.

De QuickBooks usamos el módulo de **Sales Tax**, que calcula el impuesto de cada recibo y arma la declaración del periodo con su fecha de vencimiento; los **Sales Receipts**, que guardan un recibo por máquina; los **Items**, tres productos de servicio donde el de ventas gravables está marcado como gravable y los otros dos no; un **Customer** genérico, porque en una máquina no hay cliente con nombre; la cuenta de ingresos en **Accounts**; y las **tax agencies y tax rates**, donde viven el Texas Comptroller y las tasas.

La aplicación hace lo único que QuickBooks no puede hacer: leer los reportes de los cuatro lectores, unirlos, separar el agua, las compras con impuesto pagado y los cupones, y armar el Excel de respaldo.

## Cómo decide QuickBooks qué paga impuesto

Cada recibo lleva tres renglones. El de ventas gravables va marcado TAX y los de agua y de lo comprado con impuesto ya pagado van marcados NON. QuickBooks suma los TAX como *taxable sales*, los NON como *nontaxable sales*, y aplica sobre los primeros la tasa del recibo. En septiembre recibió 61,254.82 dólares como taxable sales y 2,160.95 como nontaxable sales, los mismos valores que calcula la aplicación.

## Las tasas

QuickBooks viene con impuesto automático, que cobra por la dirección exacta de cada venta. Con las direcciones reales de las máquinas terminaba aplicando también Stafford, Sugar Land, Missouri City, Tomball y varios distritos de emergencia del condado de Harris, y daba 4,699.22 dólares. EzSnack no declara así: declara el 6.25 % del estado, el 1 % de la ciudad de Houston y el 1 % del MTA para Bellaire, Katy y Spring.

Por eso la aplicación crea en la empresa tres tasas propias a nombre del Texas Comptroller y le dice a cada recibo cuál usar:

| Tasa | Se arma con | Se aplica a |
|---|---|---|
| EzSnack Houston | 6.25 % estado + 1 % HOUSTON-CITY | Houston |
| EzSnack Houston MTA | 6.25 % estado + 1 % HOUSTON MTA | Bellaire, Katy, Spring |
| EzSnack Solo estado | 6.25 % estado | Las demás ciudades |

Con eso QuickBooks da 4,340.46 dólares en septiembre, repartidos en esas tres líneas y en ninguna más. Las tres comparten la tasa del estado, que QuickBooks no deja repetir, así que se crea una sola vez y las otras dos la referencian por su id.

## La conexión

El servidor es Python con FastAPI. Los archivos se leen en memoria con pandas y openpyxl y se borran a las tres horas; no se guardan en disco.

La autorización es OAuth 2: la página manda al usuario a Intuit, Intuit devuelve un código y el servidor lo cambia por un token de acceso y uno de refresco. Los tokens quedan cifrados en una cookie del navegador de cada usuario, no en el servidor, así que cada quien ve solo la empresa que autorizó. El token de acceso dura una hora; cuando vence, el servidor lo renueva con el de refresco y vuelve a intentar la llamada.

Contra QuickBooks se usa la Accounting API v3: consultas con el lenguaje de Intuit y creación de los recibos en lotes de 25 con el endpoint batch. Mientras la aplicación use las llaves de desarrollo solo puede conectarse a empresas de prueba; para la empresa real hay que pasar la revisión de Intuit, que incluye un cuestionario de seguridad.

## Cómo quedó configurada la empresa de prueba

La empresa de prueba de QuickBooks viene con datos de ejemplo de Intuit. Desde la página, la sección que prepara el sandbox borra todas las transacciones de ejemplo, deja inactivos los productos, proveedores y clientes que no usa la integración, y pone el nombre y la dirección de EzSnack.

En QuickBooks, en Sales Tax, hubo que completar las agencias: venían Arizona y California, que se dejaron inactivas, y el Texas State Comptroller, al que se le puso frecuencia mensual desde el 1 de enero de 2026. Con eso la declaración de septiembre aparece en el centro de impuestos con vencimiento el 20 de octubre, la misma fecha del recibo real de la empresa.

## Mantenimiento

Las tasas y las reglas de impuestos las mantiene Intuit dentro de QuickBooks, así que no hay tablas de impuestos que actualizar en el código.

En la sección Reglas de la página se cambian las ciudades de cada jurisdicción y el monto desde el cual un mes de cupones se toma como venta a una empresa. Los cambios quedan guardados en el navegador.

Si llega un reporte de otro sistema, o un lector cambia el formato del suyo, la página reconoce las columnas por su nombre, en español o en inglés, y propone cuál es la máquina, el producto, la cantidad y el valor vendido. Si no acierta, la persona elige la columna de cada campo en una lista y vuelve a calcular.

## Verificación con septiembre de 2026

Con los archivos reales de septiembre, el programa cuadra al centavo con el total que cada lector trae en su propio reporte, y QuickBooks reporta las mismas ventas gravables que calcula la aplicación.

Queda una diferencia contra lo que declaró la empresa, 3,970.79 dólares. Viene de dos cosas. La primera es el agua y los productos comprados por fuera, que el gerente filtró a mano y no coinciden con lo que sale de los datos. La segunda son las devoluciones: él descontó un 3 % estimado, unos 1,883 dólares, mientras que los cupones devueltos a clientes en septiembre fueron 90. Las dos hay que confirmarlas con él.

Los archivos reales de la empresa no se publican en este repositorio. La carpeta datos_prueba tiene archivos con el mismo formato, pero con máquinas y ventas inventadas, y se generan con scripts/generar_datos_prueba.py.

## Publicarla en internet

La aplicación está publicada en Render, en https://ezsnack-impuestos.onrender.com. Para publicarla de nuevo se entra a render.com con la cuenta de GitHub, se crea un Blueprint con este repositorio y se completan el Client ID, el Client Secret y la dirección de regreso de la aplicación de Intuit, que es la dirección que asigna Render seguida de /auth/callback. Esa misma dirección se agrega en developer.intuit.com, en Settings, Redirect URIs. Sin esos valores la página funciona igual, solo que sin el envío a QuickBooks.

## Correrla en un computador

Se necesita Python 3.11 o superior. Dentro de la carpeta del proyecto se copia el archivo .env.example con el nombre .env, se completan sus valores si se quiere conectar QuickBooks y se ejecuta:

```
pip install -r requirements.txt
uvicorn web.main:app --port 8000
```

La página queda en http://localhost:8000.

## Organización del código

La carpeta ezsnack contiene la lógica. lectores.py reconoce y lee los reportes de cada lector, maquinas.py lee el vendor list, productos.py reconoce el agua y cruza la lista de compras, cierre.py aplica las fórmulas del resumen, libro.py arma el Excel, contabilidad.py crea las tasas y envía los recibos a QuickBooks, sandbox.py prepara la empresa de prueba y qbo.py maneja la conexión con Intuit. Las reglas están en config/reglas.json. La carpeta web tiene el servidor y la página. Las pruebas automáticas están en tests y se ejecutan con python -m pytest.

## Lo que falta confirmar con la empresa

Falta que el gerente confirme qué productos contó como agua y como compras por fuera en septiembre, y si además de los cupones hay devoluciones en efectivo que haya que descontar.
