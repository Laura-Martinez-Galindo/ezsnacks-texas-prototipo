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

En Configuración se cambia todo lo que depende del negocio, sin tocar el código, y queda guardado en la base de datos de la empresa con quién lo cambió y desde qué mes aplica. La sección Configuración y datos lo detalla.

Si llega un reporte de otro sistema, o un lector cambia el formato del suyo, la página reconoce las columnas por su nombre, en español o en inglés, y propone cuál es la máquina, el producto, la cantidad y el valor vendido. Si no acierta, la persona elige la columna de cada campo en una lista y vuelve a calcular.

## Que QuickBooks dé lo mismo que la aplicación

Todo se calcula primero por máquina y al centavo: lo vendido, las devoluciones, el agua, lo comprado con impuesto pagado y la venta gravable. El resumen de la página, la hoja Machines del Excel y los recibos de QuickBooks son esa misma tabla, así que no pueden dar bases distintas. La base de HOUSTON-CITY y la de HOUSTON MTA son las ventas gravables de las máquinas de esas ciudades, que es sobre lo que QuickBooks cobra el 1 %.

Al conectar QuickBooks, la aplicación deja la empresa configurada sin que nadie entre a Sales Tax: crea la agencia, las tres tasas propias, los tres productos con su marca de gravable o no, el cliente y la cuenta de ingresos. Si en las reglas cambia un porcentaje, crea un código de impuesto nuevo, porque QuickBooks no deja editar una tasa por la API.

Después de enviar el mes, la página muestra tasa por tasa la base y el impuesto de la aplicación al lado de los que devolvió QuickBooks, y marca si son iguales. QuickBooks redondea el impuesto recibo por recibo; el Comptroller redondea las bases a dólares enteros. Por eso el valor del Comptroller puede diferir en centavos, y la página muestra los dos.

## Las reglas dentro de QuickBooks

Las reglas no quedan solo en la aplicación: se migran a cualquier QuickBooks que se conecte, en el momento de conectarlo y sin esperar al primer envío. La aplicación crea en esa empresa un tax code por jurisdicción con la tasa del estado y la local, y un item por cada producto del catálogo con su marca de gravable; el agua queda como no gravable en QuickBooks mismo. También crea los items de devoluciones y de cupones vendidos a empresas, el cliente y la cuenta de ingresos. No toca transacciones existentes y, si se conecta otra vez, no duplica nada. Cuando se guardan reglas nuevas en Configuración, se vuelven a migrar.

Cada recibo trae un renglón por producto; los comprados con impuesto ya pagado van ese mes con el código NON, las devoluciones (los cupones de reembolso del mes) son un renglón negativo y los cupones que compran las empresas un renglón gravable. Así QuickBooks decide con sus propios items y códigos qué es gravable y cuánto impuesto cobra, y si alguien registra una venta a mano en QuickBooks, el agua ya sale sin impuesto.

## Si QuickBooks ya tenía los productos

Antes de crear un item, la aplicación busca si la empresa ya lo tiene, sea de inventario, de servicio o no inventariable: por el nombre, por los otros nombres con que lo traen los sistemas y por un nombre que sea el mismo producto escrito distinto. Si lo encuentra, usa ese item y solo le corrige la marca de gravable; no crea otro. Al terminar dice cuántos ya existían y cuáles se reconocieron por un nombre parecido.

## El mismo producto con nombres distintos

Cada sistema de ventas escribe los productos a su manera: "12oz - Coke Classic Can" en Nayax y "Coke Classic - 12 oz. can" en otro. En Configuración, Productos, la aplicación propone los pares que parecen el mismo producto: las palabras que distinguen un producto, como Zero o Diet, tienen que estar en los dos nombres, y el tamaño tiene que ser el mismo. La persona une o descarta cada par. Los nombres unidos cuentan como un solo producto en el catálogo, en el Excel y en QuickBooks, y lo que se marque con cualquiera de los dos nombres vale para el producto. Unir nombres no cambia el impuesto.

## Devoluciones a clientes

Es una regla que se cambia en Configuración. Con cupones se restan los cupones de reembolso que trae el reporte y se suman como venta los que compran las empresas para sus empleados. Con porcentaje fijo se resta un porcentaje de lo vendido en efectivo y tarjeta, como en el Excel hecho a mano, que usa el 3 %. Las devoluciones que se hacen desde Nayax llegan en negativo en su reporte y siempre restan. Por defecto las devoluciones son los cupones de reembolso del mes, y agua es todo producto cuyo nombre diga water, también el endulzado, como lo filtra el gerente. Las dos cosas se cambian en Configuración.

## Comparar con el Excel hecho a mano

Es una herramienta del equipo y no aparece en la página normal: se abre agregando ?interno=1 al final de la dirección. En el paso 3 se sube el Excel integrado que el gerente armó para el mismo mes. La aplicación lee su tabla y su resumen, compara renglón por renglón y busca la causa de cada diferencia en los datos: una máquina que está en el reporte del lector y no en el Excel, un porcentaje fijo en lugar de los cupones, una cifra digitada que no sale de la tabla del mismo archivo, o una máquina que se quedó por fuera al filtrar a mano las de Houston. Sirve para correr un mes en paralelo antes de dejar el proceso manual.

## Registrar otro sistema de ventas

Nayax, AV360, XMAI y Qingo vienen reconocidos. Cuando llega el reporte de otro sistema, la página propone cuál columna es la máquina, el producto, la cantidad y el valor. La persona corrige lo que haga falta, le pone un nombre al sistema y lo registra. Desde ese momento sus reportes se reconocen solos y aparecen con ese nombre. Los sistemas registrados se ven y se quitan en Configuración, y quedan guardados en la base de datos de la empresa.

## Configuración y datos

Lo que cambia con el negocio se maneja desde la página, en Configuración, y queda en la base de datos:

| Sección | Qué se configura |
|---|---|
| Impuestos y jurisdicciones | La tasa del estado, el descuento por pagar a tiempo y una tabla de jurisdicciones locales: nombre, código del Comptroller, tasa y ciudades. Una ciudad nueva con impuesto local es una fila más |
| Devoluciones, cupones y agua | El método de devoluciones, las máquinas donde una empresa compra cupones y las palabras que marcan un producto como agua |
| Contabilidad | A dónde se envían las ventas (QuickBooks o solo Excel) y los nombres de la cuenta y del cliente |
| Productos | La clasificación que ya se decidió para cada producto. Lo que se marca en el paso 2 queda guardado y se propone solo el mes siguiente |
| Máquinas | El vendor list guardado y editable. No hay que subirlo cada mes |
| Sistemas de ventas | Los formatos de reporte registrados |
| Usuarios | Quién entra y con qué rol |
| Cambios | Quién cambió qué y cuándo |

Las reglas se guardan por versiones. Cada versión dice desde qué mes aplica, así que un cambio de tasa en noviembre no altera el cierre de septiembre. Cuando cambia una tasa o aparece una jurisdicción, la aplicación crea el código de impuesto correspondiente en QuickBooks.

Hay tres roles. Consulta ve el historial y la configuración. Operador hace el cierre, clasifica productos, edita máquinas y envía a contabilidad. Administrador además cambia las reglas, conecta QuickBooks y maneja los usuarios. Mientras no exista ningún usuario la página está abierta; al crear el primer administrador empieza a pedir usuario y clave. Las claves se guardan cifradas con PBKDF2.

Cada cierre se puede guardar en el Historial, con las reglas que tenía y el detalle por máquina, y se guarda solo al enviarlo a contabilidad. Un cierre marcado como declarado no se reemplaza sin reabrirlo.

El modelo de datos está en ezsnack/almacen.py: empresas, usuarios, reglas, maquinas, productos, formatos, cierres, cierre_maquinas y bitacora. Con la variable DATABASE_URL usa PostgreSQL. Sin ella usa un archivo SQLite en la carpeta datos, que sirve en un computador pero en Render se pierde cuando el servicio se reinicia. Los archivos de ventas que se suben cada mes no se guardan: solo el resultado del cierre.

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
