# EzSnack Impuestos

Prototipo para EzSnack Texas, una empresa de máquinas expendedoras en Houston. Cada mes el gerente declara y paga el impuesto a las ventas ante el Texas Comptroller. Para hacerlo descarga los reportes de cuatro lectores de tarjeta distintos (Nayax, AV360, XMAI y Qingo), le pide a ChatGPT que los una, revisa duplicados, y en Excel le resta las devoluciones, el agua, que no paga impuesto, y los productos que compró por fuera con el impuesto ya pagado. Después filtra a mano las máquinas de Houston y las de Bellaire, Katy y Spring para calcular los impuestos locales. Este proceso le toma alrededor de una hora cada mes y depende de que ChatGPT sume bien. El prototipo hace todo el cálculo a partir de los mismos archivos y deja un Excel de respaldo para una auditoría del estado.

## Cómo funciona

La página está en español y tiene tres pasos. Los reportes de los lectores se suben tal como salen, en inglés.

En el primero se suben el vendor list, los reportes de ventas y un Excel con la columna Product con lo que se compró ese mes pagando impuesto. El programa reconoce cada reporte por sus columnas, descarta las transacciones rechazadas de Nayax y une todo por lector, máquina y producto. La ciudad de cada máquina sale del vendor list, por el número que aparece en su nombre.

En el segundo se confirman el agua, que es exenta, y los productos comprados con impuesto pagado. Si la lista dice el tamaño, por ejemplo Sunkist 16 oz, solo se marcan los productos de ese tamaño.

En el tercero aparece el resumen del mes con las mismas fórmulas del Excel de la empresa: ventas en efectivo y tarjeta, menos el tres por ciento de devoluciones, menos el agua y menos las compras con impuesto pagado. También salen las ventas de las máquinas de Houston y las de Bellaire, Katy y Spring, que son los valores que se digitan en la página del Comptroller. El estado y los impuestos locales se pagan juntos, en un solo pago al Comptroller. Desde ahí se descarga el Excel integrado, con las mismas hojas y fórmulas del que hoy se arma a mano, y se envían las ventas a QuickBooks.

## Qué hace la aplicación y qué hace QuickBooks

La regla es usar lo que ya existe y construir solo lo que falta. QuickBooks Online, que es el sistema contable de la empresa, ya tiene un módulo de Sales Tax que calcula el impuesto del estado, la ciudad y el MTA según la dirección de cada venta, lleva el impuesto por pagar y registra el pago. Lo que QuickBooks no hace es leer los reportes de los cuatro lectores, unirlos y separar el agua y las compras con impuesto pagado. Eso es lo único que hace esta aplicación.

Por eso la aplicación no calcula el impuesto oficial. Envía a QuickBooks, por su API, un recibo de venta por máquina con la dirección de la máquina y tres renglones: ventas gravables, agua y productos comprados con impuesto pagado. QuickBooks calcula el impuesto y la página muestra el resultado por jurisdicción. Si el mes se envía dos veces, los recibos se actualizan y no se duplican.

El mantenimiento queda acotado. Las tasas y las reglas de impuestos las mantiene Intuit dentro de QuickBooks. En la aplicación solo hay que ajustar el archivo ezsnack/lectores.py si un lector cambia el formato de su reporte, y config/reglas.json si cambian las ciudades o el porcentaje de devoluciones.

## Verificación con septiembre de 2026

Con los archivos reales de septiembre, el programa cuadra al centavo con el total que cada lector trae en su propio reporte, y las ventas de las máquinas de Bellaire, Katy y Spring dan igual que en el Excel del gerente. Las diferencias que quedan vienen de valores que él sacó filtrando a mano: el agua, los productos comprados con impuesto pagado y la lista de máquinas de Houston.

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

La carpeta ezsnack contiene la lógica. lectores.py reconoce y lee los reportes de cada lector, maquinas.py lee el vendor list, productos.py reconoce el agua y cruza la lista de compras, cierre.py aplica las fórmulas del resumen, libro.py arma el Excel integrado, contabilidad.py envía las ventas a QuickBooks y qbo.py maneja la conexión con Intuit. Las reglas están en config/reglas.json. La carpeta web tiene el servidor y la página. Las pruebas automáticas están en tests y se ejecutan con python -m pytest.

## Lo que falta confirmar con la empresa

Falta que el gerente confirme qué productos contó como agua y como compras por fuera en septiembre. También conviene revisar con el contador que QuickBooks aplica el 1 % del MTA a las máquinas de Houston, porque Houston queda dentro del MTA, mientras que hoy al MTA solo se le declaran las máquinas de Bellaire, Katy y Spring.
